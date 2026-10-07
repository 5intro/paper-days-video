#!/usr/bin/env python3
"""Shared paths, identities and JSON helpers for the portable voice pipeline."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path

MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
MODEL_REVISION = "fd4b254389122332181a7c3db7f27e918eec64e3"
PIPELINE_VERSION = 1
# Official snapshot file identities: Git blob SHA-1 for small files, SHA-256 for LFS weights.
PINNED_FILES = {
    "config.json": ("git_blob_sha1", "81b57e8e790c07e8fa7f82d8bdfd7574d485c396"),
    "generation_config.json": ("git_blob_sha1", "1872b16d4535564abf2db5d6debe6cddd82b7f2e"),
    "merges.txt": ("git_blob_sha1", "20024bfe7c83998e9aeaf98a0cd6a2ce6306c2f0"),
    "model.safetensors": ("sha256", "38fc7fc51c5e776e840414b6fd443962e9411b9654888fd7913e4da643cb857c"),
    "preprocessor_config.json": ("git_blob_sha1", "0525dd953bb9241912f7147666f0d535165d5d4f"),
    "speech_tokenizer/config.json": ("git_blob_sha1", "06cc8dc4c5ec8a1929086b71b98c313020d9268b"),
    "speech_tokenizer/configuration.json": ("git_blob_sha1", "ab58e2eaf53cd14a1a2a7527d9261ceea93a24cd"),
    "speech_tokenizer/model.safetensors": ("sha256", "836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258"),
    "speech_tokenizer/preprocessor_config.json": ("git_blob_sha1", "ba40914f4f49ab98a8ca545d4892ef7291a39592"),
    "tokenizer_config.json": ("git_blob_sha1", "6ff9fd60cc623bb54bbd603cbd418c97a11528d7"),
    "vocab.json": ("git_blob_sha1", "4783fe10ac3adce15ac8f358ef5462739852c569"),
}
DEFAULTS = {
    "voice_reference": "assets/voice/reference.wav",
    "voice_transcript": "assets/voice/reference.txt",
    "voice_prompt": None,
    "model_path": "models/Qwen3-TTS-12Hz-1.7B-Base",
    "device": "cpu",
    "dtype": "bfloat16",
    "seed": 21,
    "cpu_threads": 4,
    "speed": 1.1,
    "max_new_tokens": 500,
    "trim_threshold": 0.001,
    "boundary_padding_seconds": 0.1,
    "timeout_seconds": 900,
    "no_progress_timeout_seconds": 60,
    "output_dir": "voice",
    "ffmpeg": "ffmpeg",
}
GENERATION_DEFAULTS = {
    "do_sample": True,
    "temperature": 0.9,
    "top_p": 1.0,
    "top_k": 50,
    "repetition_penalty": 1.05,
    "subtalker_dosample": True,
    "subtalker_temperature": 0.9,
    "subtalker_top_p": 1.0,
    "subtalker_top_k": 50,
}


def json_digest(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def resolve_path(root, value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def project_relative(root, path):
    """Use portable project-root-relative paths in every generated manifest."""
    return Path(os.path.relpath(Path(path).resolve(), root)).as_posix()


def load_config(path):
    path = Path(path).expanduser().resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("The config must be a JSON object.")
    config = {**DEFAULTS, **raw}
    if config["dtype"] != "bfloat16":
        raise ValueError("This fixed-voice pipeline requires dtype=bfloat16.")
    if not re.fullmatch(r"cpu|cuda(?::[0-9]+)?", str(config["device"])):
        raise ValueError("device must be cpu or cuda[:index]; offload is not supported.")
    if float(config["speed"]) != 1.1:
        raise ValueError("The fixed-voice pipeline applies exactly one atempo=1.1 pass.")
    for key in ("cpu_threads", "max_new_tokens"):
        if isinstance(config[key], bool) or int(config[key]) != config[key] or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer.")
        config[key] = int(config[key])
    if config["max_new_tokens"] < 4:
        raise ValueError("max_new_tokens must be at least 4.")
    if isinstance(config["seed"], bool) or int(config["seed"]) != config["seed"]:
        raise ValueError("seed must be an integer.")
    config["seed"] = int(config["seed"])
    for key in ("timeout_seconds", "no_progress_timeout_seconds", "trim_threshold"):
        config[key] = float(config[key])
        if not math.isfinite(config[key]) or config[key] <= 0:
            raise ValueError(f"{key} must be finite and greater than zero.")
    for key in ("boundary_padding_seconds",):
        config[key] = float(config[key])
        if not math.isfinite(config[key]) or config[key] < 0:
            raise ValueError(f"{key} must be finite and nonnegative.")
    root = path.parent
    output = resolve_path(root, config["output_dir"])
    if output == root or root not in output.parents:
        raise ValueError("output_dir must be a subdirectory of the config/project directory.")
    return path, root, config


def load_episode(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    segments = data.get("segments") if isinstance(data, dict) else None
    if not isinstance(segments, list) or not segments:
        raise ValueError("episode.json must contain a nonempty segments array.")
    result, seen = [], set()
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("Every segment must be an object.")
        sid = segment.get("id")
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", sid):
            raise ValueError("Segment IDs must be 1-80 safe letters, digits, underscores or hyphens.")
        if sid.casefold() in seen:
            raise ValueError(f"Duplicate segment ID (case-insensitive): {sid}")
        seen.add(sid.casefold())
        for field in ("zh", "en"):
            if not isinstance(segment.get(field), str) or not segment[field].strip():
                raise ValueError(f"{sid}: {field} must be a nonempty string.")
        tts_text = segment.get("tts_text", segment["zh"])
        if not isinstance(tts_text, str) or not tts_text.strip():
            raise ValueError(f"{sid}: tts_text must be a nonempty string.")
        result.append({"id": sid, "zh": segment["zh"], "en": segment["en"], "tts_text": tts_text})
    return result


def model_identity(directory):
    """Hash local weights and configuration, including explicitly supplied snapshots."""
    directory = Path(directory)
    if not (directory / "config.json").is_file():
        raise FileNotFoundError("Local model missing. Run setup_model.py or set model_path to its snapshot.")
    suffixes = {".safetensors", ".json", ".txt", ".model", ".tiktoken"}
    files = [p for p in sorted(directory.rglob("*"))
             if p.is_file() and p.suffix in suffixes
             and not any(part.startswith(".") for part in p.relative_to(directory).parts)
             and p.name != "paper-days-model-lock.json"]
    if not any(p.suffix == ".safetensors" for p in files):
        raise ValueError("The model directory contains no safetensors weights.")
    inventory = [{"path": p.relative_to(directory).as_posix(), "size": p.stat().st_size,
                  "sha256": file_digest(p)} for p in files]
    by_name = {entry["path"]: entry for entry in inventory}
    for name, (algorithm, expected) in PINNED_FILES.items():
        entry = by_name.get(name)
        if entry is None:
            raise ValueError(f"Incomplete pinned model snapshot: missing {name}")
        if algorithm == "sha256":
            observed = entry["sha256"]
        else:
            data = (directory / name).read_bytes()
            observed = hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()
        if observed != expected:
            raise ValueError(f"Model file does not match the fixed revision: {name}")
    return {"requested_repo": MODEL_ID, "requested_revision": MODEL_REVISION,
            "verified_revision": MODEL_REVISION,
            "files": inventory, "files_sha256": json_digest(inventory)}
