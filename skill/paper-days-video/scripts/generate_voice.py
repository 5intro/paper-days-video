#!/usr/bin/env python3
"""Resident Qwen voice generation, content-addressed resume and bounded supervision."""
from __future__ import annotations

import argparse
import contextlib
import gc
import importlib.metadata
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone

from voice_common import (GENERATION_DEFAULTS, PIPELINE_VERSION, atomic_json,
                          file_digest, json_digest, load_config, load_episode,
                          model_identity, project_relative, resolve_path)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def log(event, **values):
    print(json.dumps({"event": event, "utc": utc_now(), **values}, ensure_ascii=False), flush=True)


@contextlib.contextmanager
def project_lock(path):
    """OS-owned advisory lock; exits and signals release it without stale PID guesses."""
    with Path(path).open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another voice run is using this output directory.") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def audio_measure(path, threshold):
    import numpy as np
    import soundfile as sf
    audio, rate = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim != 1 or len(audio) == 0 or not np.isfinite(audio).all():
        raise ValueError(f"Invalid mono waveform: {path.name}")
    active = np.flatnonzero(np.abs(audio) > threshold)
    if not len(active):
        raise ValueError(f"No waveform activity: {path.name}")
    return {"duration": len(audio) / rate, "sample_rate": int(rate), "frames": len(audio),
            "first_activity_s": int(active[0]) / rate,
            "last_activity_s": (int(active[-1]) + 1) / rate,
            "peak": float(np.abs(audio).max()),
            "sha256": file_digest(path)}


def runtime_versions():
    result = {}
    for name in ("qwen-tts", "torch", "transformers", "accelerate", "numpy", "soundfile",
                 "tokenizers", "safetensors", "librosa"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = "missing"
    return result


def worker(args):
    config_path, root, config = load_config(args.config)
    for key, value in {
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1", "ORT_DISABLE_TELEMETRY": "1", "TOKENIZERS_PARALLELISM": "false",
        "HF_ENABLE_PARALLEL_LOADING": "FALSE", "OMP_NUM_THREADS": str(config["cpu_threads"]),
        "MKL_NUM_THREADS": str(config["cpu_threads"]), "PYTHONDONTWRITEBYTECODE": "1",
    }.items():
        os.environ[key] = value
    log("preparing")
    import numpy as np
    import soundfile as sf
    import torch
    try:
        import onnxruntime
        onnxruntime.disable_telemetry_events()
    except ImportError:
        pass
    from qwen_tts import Qwen3TTSModel
    from qwen_tts.inference.qwen3_tts_model import VoiceClonePromptItem

    segments = load_episode(args.episode)
    output = resolve_path(root, config["output_dir"])
    for name in ("raw", "trimmed", "segments", "checkpoints"):
        (output / name).mkdir(parents=True, exist_ok=True)
    reference = resolve_path(root, config["voice_reference"])
    transcript_path = resolve_path(root, config["voice_transcript"])
    transcript = transcript_path.read_text(encoding="utf-8").strip()
    if not transcript:
        raise ValueError("The reference transcript is empty.")
    reference_info = audio_measure(reference, config["trim_threshold"])
    prompt_path = resolve_path(root, config["voice_prompt"]) if config["voice_prompt"] else None
    if prompt_path is not None and not prompt_path.is_file():
        raise FileNotFoundError(f"Configured voice_prompt does not exist: {config['voice_prompt']}")
    model_path = resolve_path(root, config["model_path"])
    log("fingerprinting_model")
    model_info = model_identity(model_path)
    packages = runtime_versions()
    if packages["qwen-tts"] != "0.1.1":
        raise ValueError("This pipeline requires qwen-tts==0.1.1.")
    # Include effective synthesis settings rather than unrelated render settings or machine paths.
    synthesis_keys = ("device", "dtype", "seed", "cpu_threads", "speed", "max_new_tokens",
                      "trim_threshold", "boundary_padding_seconds")
    settings = {key: config[key] for key in synthesis_keys}
    ffmpeg = shutil.which(os.environ.get("FFMPEG", str(config["ffmpeg"])))
    if ffmpeg is None:
        raise FileNotFoundError("FFmpeg is required; install it and put ffmpeg on PATH.")
    ffmpeg_version = subprocess.check_output([ffmpeg, "-version"], text=True).splitlines()[0]
    identity = {
        "pipeline_version": PIPELINE_VERSION,
        "implementation_sha256": json_digest({p.name: file_digest(p) for p in
            (Path(__file__), Path(__file__).with_name("voice_common.py"))}),
        "config_sha256": json_digest({**settings, "generation": GENERATION_DEFAULTS}),
        "settings": settings, "generation": GENERATION_DEFAULTS,
        "reference_sha256": reference_info["sha256"],
        "reference_transcript_sha256": file_digest(transcript_path),
        "voice_prompt_sha256": file_digest(prompt_path) if prompt_path else None,
        "model_files_sha256": model_info["files_sha256"],
        "model_repo": model_info["requested_repo"], "model_revision": model_info["requested_revision"],
        "runtime_packages": packages, "ffmpeg_version": ffmpeg_version,
    }
    atomic_json(output / "model-identity.json", model_info)
    completed = {}

    def key_for(segment):
        return json_digest({"source_text_sha256": json_digest(segment), "identity": identity})

    def write_manifest(status):
        entries, cursor = [], 0.0
        for segment in segments:
            entry = completed.get(segment["id"])
            if entry is None:
                continue
            entry = dict(entry)
            # Sum real speech durations; the renderer owns gaps and end holds.
            cursor += entry["duration"]
            entries.append(entry)
        atomic_json(output / "manifest.json", {
            "schema_version": 1, "status": status, "updated_utc": utc_now(),
            "path_base": "config_directory", "identity": identity,
            "episode_sha256": json_digest(segments), "completed": len(entries), "total": len(segments),
            "duration": cursor, "segments": entries,
        })

    for segment in segments:
        sid = segment["id"]
        checkpoint = output / "checkpoints" / (sid + ".json")
        if not checkpoint.exists():
            continue
        try:
            entry = json.loads(checkpoint.read_text(encoding="utf-8"))
            if entry["resume_key"] != key_for(segment):
                raise ValueError("source text, configuration, reference or runtime changed")
            for field, subdir in (("path", "segments"), ("raw_path", "raw"), ("trimmed_path", "trimmed")):
                expected = output / subdir / (sid + ".wav")
                if entry[field] != project_relative(root, expected):
                    raise ValueError("output path changed")
                sha_field = "sha256" if field == "path" else field.replace("_path", "_sha256")
                if file_digest(expected) != entry[sha_field]:
                    raise ValueError("audio bytes do not match the checkpoint")
            measured = audio_measure(output / "segments" / (sid + ".wav"), config["trim_threshold"])
            for field in ("duration", "sample_rate", "frames", "first_activity_s", "last_activity_s"):
                if measured[field] != entry[field]:
                    raise ValueError("checkpoint measurements do not match audio")
            completed[sid] = entry
            log("resume_verified", id=sid)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log("checkpoint_invalidated", id=sid, reason=str(exc))
    write_manifest("complete" if len(completed) == len(segments) else "generating")
    if len(completed) == len(segments):
        log("complete", completed=len(completed), reused=len(completed))
        return

    torch.set_num_threads(config["cpu_threads"])
    torch.manual_seed(config["seed"])
    device = torch.device(config["device"])
    if device.type == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is unavailable; choose cpu explicitly.")
        if device.index is None:
            device = torch.device("cuda", torch.cuda.current_device())
        with torch.cuda.device(device):
            if not torch.cuda.is_bf16_supported():
                raise RuntimeError("The selected CUDA device does not support BF16.")
        torch.cuda.manual_seed_all(config["seed"])
    log("loading_model", device=str(device), dtype="bfloat16")
    model = Qwen3TTSModel.from_pretrained(
        str(model_path), device_map=str(device), dtype=torch.bfloat16,
        attn_implementation="sdpa", use_safetensors=True, local_files_only=True,
    )
    modules = {"model": model.model, "codec": model.model.speech_tokenizer.model}
    for name, module in modules.items():
        for parameter in module.parameters():
            if parameter.device != device:
                raise RuntimeError(f"{name} is not fully resident on {device}; offload is disallowed.")
        if module.dtype != torch.bfloat16:
            raise RuntimeError(f"{name} is not BF16.")
    log("loaded", device=str(device))
    log("building_prompt")
    prompt_source = "reference_wav"
    prompt = None
    if prompt_path:
        try:
            saved = torch.load(prompt_path, map_location=str(device), weights_only=True)
            if not isinstance(saved, list) or len(saved) != 1 or not isinstance(saved[0], dict):
                raise ValueError("The fixed prompt must contain one dictionary.")
            prompt = [VoiceClonePromptItem(**saved[0])]
            if prompt[0].ref_text != transcript:
                raise ValueError("The prompt transcript differs from voice_transcript.")
            prompt_source = "approved_tensor"
        except Exception as exc:
            prompt = None
            # Never deserialize unrestricted pickle or allowlist unknown globals.
            log("prompt_rebuild", reason=type(exc).__name__, source="reference_wav")
    if prompt is None:
        prompt = model.create_voice_clone_prompt(ref_audio=str(reference), ref_text=transcript,
                                                 x_vector_only_mode=False)
    log("prompt_ready", source=prompt_source)

    try:
        for segment in segments:
            sid = segment["id"]
            if sid in completed:
                continue
            count = [0]

            def trace(_module, _inputs, _output):
                count[0] += 1
                # Each forward is evidence of progress; this is not a fabricated heartbeat.
                log("forward", id=sid, count=count[0])

            hook = model.model.talker.register_forward_hook(trace)
            torch.manual_seed(config["seed"])
            if device.type == "cuda":
                torch.cuda.manual_seed_all(config["seed"])
            started = time.monotonic()
            log("generating", id=sid)
            try:
                with torch.inference_mode():
                    wavs, rate = model.generate_voice_clone(
                        text=segment["tts_text"], language="Chinese", voice_clone_prompt=prompt,
                        max_new_tokens=config["max_new_tokens"], **GENERATION_DEFAULTS,
                    )
            finally:
                hook.remove()
            log("generated", id=sid, forward_count=count[0])
            raw = np.asarray(wavs[0], dtype=np.float32)
            if raw.ndim != 1 or not len(raw) or not np.isfinite(raw).all():
                raise ValueError(f"{sid}: invalid waveform.")
            if np.any(np.abs(raw) >= 1):
                raise ValueError(f"{sid}: clipped raw waveform; checkpoint not committed.")
            if count[0] >= config["max_new_tokens"] - 2:
                raise ValueError(f"{sid}: near token limit; split this paragraph before retrying.")
            active = np.flatnonzero(np.abs(raw) > config["trim_threshold"])
            if not len(active):
                raise ValueError(f"{sid}: no waveform activity.")
            pad = round(config["boundary_padding_seconds"] * rate)
            lo, hi = max(0, int(active[0]) - pad), min(len(raw), int(active[-1]) + pad + 1)
            trimmed = raw[lo:hi]
            paths = {name: output / name / (sid + ".wav") for name in ("raw", "trimmed", "segments")}
            temporary = {name: path.with_name(f".{sid}.{os.getpid()}.tmp.wav") for name, path in paths.items()}
            try:
                sf.write(temporary["raw"], raw, rate, subtype="PCM_16")
                sf.write(temporary["trimmed"], trimmed, rate, subtype="PCM_16")
                # Read the unsped trim only. A final/previous output is never sped a second time.
                subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                                "-i", str(temporary["trimmed"]), "-af", "atempo=1.1",
                                "-c:a", "pcm_s16le", str(temporary["segments"])], check=True)
                measured = audio_measure(temporary["segments"], config["trim_threshold"])
                entry = {
                    **segment, **measured, "resume_key": key_for(segment),
                    "source_text_sha256": json_digest(segment), "identity": identity,
                    "path": project_relative(root, paths["segments"]),
                    "raw_path": project_relative(root, paths["raw"]),
                    "trimmed_path": project_relative(root, paths["trimmed"]),
                    "raw_sha256": file_digest(temporary["raw"]),
                    "trimmed_sha256": file_digest(temporary["trimmed"]),
                    "raw_duration": len(raw) / rate, "trimmed_duration": len(trimmed) / rate,
                    "raw_frames": len(raw), "trimmed_frames": len(trimmed),
                    "trim_start_s": lo / rate, "trim_end_s": (len(raw) - hi) / rate,
                    "tempo_passes": 1, "atempo": 1.1, "forward_count": count[0],
                    "generation_seconds": time.monotonic() - started, "prompt_source": prompt_source,
                    "completed_utc": utc_now(), "content_review": "pending",
                }
                for name, path in paths.items():
                    os.replace(temporary[name], path)
                # Commit only after all three validated files are in place.
                atomic_json(output / "checkpoints" / (sid + ".json"), entry)
                completed[sid] = entry
                write_manifest("generating")
                log("segment_complete", id=sid, duration=entry["duration"])
            finally:
                for path in temporary.values():
                    path.unlink(missing_ok=True)
            del raw, trimmed, wavs, active
            gc.collect()
    finally:
        del model, prompt
        gc.collect()
    write_manifest("complete")
    log("complete", completed=len(completed))


def stop_process_group(process, psutil, known_descendants=()):
    """Terminate the whole launched group, including FFmpeg, and reap the child."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        # Retain observed Process objects so children can be reaped even if their parent exits.
        processes = {item.pid: item for item in known_descendants}
        try:
            parent = psutil.Process(process.pid)
            processes[parent.pid] = parent
            processes.update({item.pid: item for item in parent.children(recursive=True)})
        except psutil.NoSuchProcess:
            pass
        for item in processes.values():
            try:
                item.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(list(processes.values()), timeout=5)
        for item in alive:
            try:
                item.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(alive, timeout=5)
    process.wait()


def supervise(args):
    import psutil
    _, root, config = load_config(args.config)
    load_episode(args.episode)
    output = resolve_path(root, config["output_dir"])
    output.mkdir(parents=True, exist_ok=True)
    with project_lock(output / ".generation.lock"):
        return supervise_locked(args, root, config, output, psutil)


def supervise_locked(args, root, config, output, psutil):
    run = output / "runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}")
    run.mkdir(parents=True)
    atomic_json(output / "manifest.json", {"schema_version": 1, "status": "preparing", "segments": []})
    command = [sys.executable, "-u", str(Path(__file__).resolve()), "--worker",
               "--config", str(Path(args.config).resolve()), "--episode", str(Path(args.episode).resolve())]
    options = {"start_new_session": True} if os.name == "posix" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", bufsize=1,
                               env=env, **options)
    lines = queue.Queue()

    def reader():
        for line in process.stdout:
            lines.put((time.monotonic(), line))
        lines.put((time.monotonic(), None))

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    start = phase_start = time.monotonic()
    last_forward, segment_start = None, None
    reason, received_signal = None, None
    peak_rss, phase = 0, "startup"
    previous_handlers = {}
    known_descendants = {}

    def interrupted(number, _frame):
        nonlocal received_signal
        received_signal = number

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, interrupted)
    try:
        with (run / "worker.jsonl").open("w", encoding="utf-8") as worker_log, \
                (run / "resources.jsonl").open("w", encoding="utf-8") as resources:
            eof = False
            while True:
                while True:
                    try:
                        observed, line = lines.get_nowait()
                    except queue.Empty:
                        break
                    if line is None:
                        eof = True
                        continue
                    worker_log.write(line)
                    worker_log.flush()
                    print(line, end="", flush=True)
                    try:
                        event = json.loads(line).get("event")
                    except (ValueError, AttributeError):
                        continue
                    if event in ("preparing", "fingerprinting_model", "loading_model", "loaded",
                                 "building_prompt", "prompt_ready", "segment_complete", "complete"):
                        phase, phase_start = event, observed
                        if event in ("segment_complete", "complete"):
                            segment_start, last_forward = None, None
                    elif event == "generating":
                        phase, phase_start = event, observed
                        segment_start = last_forward = observed
                    elif event == "forward":
                        last_forward = observed
                    elif event == "generated":
                        phase = "postprocessing"
                        # Segment wall guard remains active; the forward-idle guard ends here.
                        last_forward = None
                now = time.monotonic()
                if process.poll() is not None and eof:
                    break
                if received_signal is not None:
                    reason = f"cancelled_by_signal_{received_signal}"
                    break
                if segment_start is not None and now - segment_start > config["timeout_seconds"]:
                    reason = "segment_wall_timeout"
                    break
                if segment_start is None and now - phase_start > config["timeout_seconds"]:
                    reason = "phase_wall_timeout"
                    break
                if last_forward is not None and now - last_forward > config["no_progress_timeout_seconds"]:
                    reason = "forward_progress_timeout"
                    break
                sample = {"utc": utc_now(), "elapsed_seconds": now - start, "phase": phase,
                          "pid": process.pid, "rss_bytes": None, "process_count": 0}
                try:
                    parent = psutil.Process(process.pid)
                    children = parent.children(recursive=True)
                    known_descendants.update({item.pid: item for item in children})
                    processes = [parent, *children]
                    rss = 0
                    for item in processes:
                        try:
                            rss += item.memory_info().rss
                            sample["process_count"] += 1
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    sample["rss_bytes"] = rss
                    peak_rss = max(peak_rss, rss)
                    sample["available_memory_bytes"] = psutil.virtual_memory().available
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                resources.write(json.dumps(sample) + "\n")
                resources.flush()
                time.sleep(0.25)
    except BaseException:
        reason = reason or "supervisor_error"
        raise
    finally:
        # Cleanup runs after success, errors, timeouts and user cancellation alike.
        stop_process_group(process, psutil, known_descendants.values())
        thread.join(timeout=2)
        process.stdout.close()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        result = {"returncode": process.returncode, "termination_reason": reason,
                  "elapsed_seconds": time.monotonic() - start, "peak_rss_bytes": peak_rss,
                  "run_dir": project_relative(root, run), "finished_utc": utc_now()}
        if process.returncode in (-9, 137):
            result["exit_detail"] = "Forced termination observed; its cause is not established by the exit code."
        atomic_json(run / "result.json", result)
        if process.returncode != 0 or reason:
            try:
                manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                manifest = {"schema_version": 1, "segments": []}
            manifest.update(status="interrupted" if reason else "failed", last_run=result)
            atomic_json(output / "manifest.json", manifest)
        log("supervisor_finished", **result)
    return 0 if process.returncode == 0 and reason is None else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", required=True, help="Episode JSON containing segments.")
    parser.add_argument("--config", required=True, help="Project config; relative paths use its directory.")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return 0
    return supervise(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log("error", error=type(exc).__name__, message=str(exc))
        traceback.print_exc()
        raise SystemExit(1)
