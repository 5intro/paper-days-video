#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Speech-first 48 kHz mix with bounded BGM dynamics and objective audit."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

import numpy as np
from scipy.io import wavfile
from scipy.ndimage import gaussian_filter1d

from audit_media import measure_loudness, probe_media, run, sha256

SR = 48000
STEP = .01
PARAMS = {
    'sample_rate': SR, 'control_step_seconds': STEP,
    'music_eq': 'highpass=f=65,equalizer=f=1700:t=q:w=0.65:g=-3,'
                'equalizer=f=3300:t=q:w=0.8:g=-2,lowpass=f=11000',
    'music_dynamic_ratio': 1.8, 'music_dynamic_max_boost_db': 2.5,
    'music_dynamic_max_cut_db': -3.5, 'music_dynamic_smoothing_seconds': .8,
    'music_dynamic_max_slew_db_per_second': 1.0,
    'music_dynamic_no_boost_below_lufs': -38.0,
    'music_dynamic_full_boost_above_lufs': -26.0,
    'music_standalone_target_lufs': -16.0, 'music_standalone_peak_ceiling_dbtp': -3.0,
    'music_base_voice_advantage_lu': 10.0, 'music_bed_peak_ceiling_dbtp': -10.0,
    'speech_duck_db': -1.5, 'total_adaptive_duck_limit_db': 4.0,
    'stable_window_voice_advantage_db': 10.0,
    'speech_attack_seconds': .14, 'speech_hold_seconds': .30,
    'speech_release_seconds': 1.15, 'gap_recovery_maximum_db': 2.0,
    'high_energy_extra_duck_db': -1.5, 'opening_fade_seconds': .65,
    'ending_fade_seconds': 1.2, 'target_lufs': -16.0,
    'true_peak_ceiling_dbtp': -1.8, 'decoded_aac_peak_ceiling_dbtp': -1.8,
    'voice_speed_change': False, 'music_speed_change': False,
}


def db(value: float) -> float:
    return 20.0 * math.log10(max(float(value), 1e-12))


def rms(values: np.ndarray) -> float:
    return math.sqrt(float(np.mean(np.square(values, dtype=np.float64)))) if values.size else 0.0


def number(value: object, field: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f'{field} must be finite')
    return result


def project_path(project: Path, value: str, exists: bool = True) -> Path:
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError('Paths must be relative to --project.')
    path = (project / relative).resolve(strict=exists)
    if not path.is_relative_to(project):
        raise ValueError('Path escapes --project.')
    if exists and not path.is_file():
        raise ValueError(f'Expected a file: {relative}')
    return path


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def write_audio(path: Path, audio: np.ndarray) -> None:
    if not np.isfinite(audio).all():
        raise ValueError('Audio contains non-finite samples.')
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(path, SR, audio.astype(np.float32, copy=False))


def decode(path: Path, output: Path, channels: int, ffmpeg: str, eq: str | None = None) -> np.ndarray:
    command = [ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', str(path), '-map', '0:a:0', '-vn']
    if eq:
        command += ['-af', eq]
    command += ['-ar', str(SR), '-ac', str(channels), '-c:a', 'pcm_f32le', str(output)]
    run(command)
    rate, result = wavfile.read(output)
    if rate != SR or len(result) == 0 or not np.isfinite(result).all():
        raise ValueError(f'Invalid decoded audio: {path.name}')
    return result.astype(np.float32, copy=False)


def loudness_frames(path: Path, ffmpeg: str) -> np.ndarray:
    result = run([ffmpeg, '-hide_banner', '-loglevel', 'verbose', '-nostdin',
                  '-i', str(path), '-map', '0:a:0', '-vn', '-af',
                  'ebur128=framelog=verbose', '-f', 'null', '-'])
    rows = re.findall(r' t:\s*([\d.]+)\s+TARGET:.*?M:\s*([-\d.]+)\s+S:\s*([-\d.]+)', result.stderr)
    return np.array([[float(x) for x in row] for row in rows], dtype=float).reshape(-1, 3)


def valid_measurement(measurement: dict, label: str) -> None:
    if measurement['integrated_lufs'] is None or measurement['true_peak_dbtp'] is None:
        raise ValueError(f'{label} has no measurable non-silent audio.')


def constant_gain(measurement: dict, target: float, ceiling: float) -> float:
    valid_measurement(measurement, 'Input')
    return min(target - measurement['integrated_lufs'], ceiling - measurement['true_peak_dbtp'])


def apply_grid(audio: np.ndarray, grid: np.ndarray, gain_db: np.ndarray) -> None:
    for a in range(0, len(audio), SR):
        b = min(a + SR, len(audio))
        gain = 10 ** (np.interp(np.arange(a, b) / SR, grid, gain_db) / 20)
        audio[a:b] *= gain.astype(np.float32)[:, None] if audio.ndim == 2 else gain


def prepare_music(source: Path, work: Path, ffmpeg: str) -> tuple[np.ndarray, dict]:
    eq_path = work / 'music_eq.wav'
    audio = decode(source, eq_path, 2, ffmpeg, PARAMS['music_eq'])
    before = measure_loudness(eq_path, ffmpeg)
    valid_measurement(before, 'Music')
    rows = loudness_frames(eq_path, ffmpeg)
    valid = rows[(rows[:, 0] >= 3) & (rows[:, 2] > -60)]
    grid = np.arange(math.ceil(len(audio) / SR / .1) + 1) * .1
    if len(valid):
        levels = np.interp(grid, valid[:, 0] - 1.5, valid[:, 2])
        center = float(np.median(valid[:, 2]))
        method = 'Centered three-second EBU R128 short-term loudness.'
    else:
        # Very short sources have no complete three-second R128 window.
        levels = np.array([db(rms(audio[max(0, round((t - .2) * SR)):
                                             min(len(audio), round((t + .2) * SR))])) for t in grid])
        center = float(np.median(levels[levels > -60])) if np.any(levels > -60) else -60.0
        method = 'Centered 400 ms RMS fallback for a source shorter than three seconds.'
    gains = np.clip((center - levels) * (1 - 1 / PARAMS['music_dynamic_ratio']), -3.5, 2.5)
    gate = np.clip((levels + 38) / 12, 0, 1)
    gains = np.where(gains > 0, gains * gate, gains)
    gains = gaussian_filter1d(gains, .8 / .1, mode='nearest')
    # Keep quiet fades unboosted without violating the 1 dB/s slew limit.
    gains = np.minimum(gains, 2.5 * gate)
    for i in range(1, len(gains)):
        gains[i] = min(gains[i], gains[i - 1] + .1)
    for i in range(len(gains) - 2, -1, -1):
        gains[i] = min(gains[i], gains[i + 1] + .1)
    apply_grid(audio, grid, gains)
    dynamic = work / 'music_dynamic.wav'
    write_audio(dynamic, audio)
    unscaled = measure_loudness(dynamic, ffmpeg)
    gain = constant_gain(unscaled, -16, -3)
    audio *= 10 ** (gain / 20)
    write_audio(dynamic, audio)
    after = measure_loudness(dynamic, ffmpeg)
    return audio, {'before': before, 'after': after, 'constant_gain_db': gain,
                   'dynamic_gain_min_db': float(gains.min()), 'dynamic_gain_max_db': float(gains.max()),
                   'analysis': method, 'ratio': 1.8, 'max_boost_db': 2.5, 'max_cut_db': -3.5,
                   'maximum_gain_slew_db_per_second': float(np.max(np.abs(np.diff(gains))) / .1)
                       if len(gains) > 1 else 0.0,
                   'processing': 'Slow bounded music loudness automation; no hard limiting.'}


def fit_music(audio: np.ndarray, samples: int, cues: dict | None,
              policy: str) -> tuple[np.ndarray, dict]:
    available = len(audio)
    if samples <= available:
        return audio[:samples].copy(), {'method': 'trim_to_timeline', 'speed_change': False,
                                       'original_ending_preserved': samples == available}
    if policy == 'error':
        raise ValueError('Music is shorter than the timeline. Supply phrase cues and use '
                         '--music-end-policy crossfade_extend, or compose music for the required duration.')
    if not cues:
        raise ValueError('Phrase-aware extension requires --music-cues or a sibling .music.json. '
                         'Do not label an envelope-only match as a verified musical phrase.')
    outro = number(cues['outro_start_s'], 'outro_start_s')
    fade_s = number(cues.get('crossfade_seconds', 2.0), 'crossfade_seconds')
    if not 0 < outro < available / SR or not .1 <= fade_s <= 8:
        raise ValueError('Invalid outro or crossfade cue.')
    fade = round(fade_s * SR)
    boundaries = sorted(set(round(number(t, 'phrase boundary') * SR)
                            for t in cues['phrase_boundaries_s']))
    if any(t < 0 or t >= available for t in boundaries):
        raise ValueError('Phrase boundary is outside the music source.')
    candidates = []
    for a in boundaries:
        if a + fade > round(outro * SR):
            continue
        for b in boundaries:
            span = a - b
            if span < max(2 * fade, 2 * SR):
                continue
            # Envelope similarity ranks caller-confirmed phrase boundaries only.
            hop = max(1, round(.1 * SR))
            left, right = audio[a:a + fade], audio[b:b + fade]
            score = float(np.mean([abs(db(rms(left[j:j + hop])) - db(rms(right[j:j + hop])))
                                   for j in range(0, fade, hop)]))
            candidates.append((score, -span, a, b))
    if not candidates:
        raise ValueError('No suitable pair of phrase cues before the protected outro.')
    score, _, a, b = min(candidates)
    span = a - b
    repeats = math.ceil((samples - available) / span)
    weights = (.5 - .5 * np.cos(np.linspace(0, np.pi, fade))).astype(np.float32)[:, None]
    result = audio
    for _ in range(repeats):
        blend = result[a:a + fade] * (1 - weights) + result[b:b + fade] * weights
        result = np.concatenate([result[:a], blend, result[b + fade:]], axis=0)
    leading_trim = len(result) - samples
    result = result[leading_trim:].copy()
    if len(result) != samples:
        raise ValueError('Internal music edit length mismatch.')
    return result, {'method': 'whole_phrase_backward_crossfade_then_leading_trim',
                    'speed_change': False, 'pitch_change': False, 'original_ending_preserved': True,
                    'outro_start_source_s': outro, 'source_phrase_outgoing_s': a / SR,
                    'source_phrase_incoming_s': b / SR, 'whole_phrase_repeats': repeats,
                    'crossfade_seconds': fade / SR, 'leading_trim_seconds': leading_trim / SR,
                    'extension_seconds': (samples - available) / SR,
                    'candidate_envelope_mismatch_db': score,
                    'review': 'Phrase cues are caller-supplied; audition the seam and the changed opening.'}


def merge(intervals: list, gap: float = 0.0) -> list:
    result = []
    for a, b in sorted(intervals):
        if result and a <= result[-1][1] + gap:
            result[-1][1] = max(b, result[-1][1])
        else:
            result.append([float(a), float(b)])
    return result


def detect_activity(voice: np.ndarray, timeline: list) -> tuple[list, np.ndarray, float]:
    hop = round(.02 * SR)
    framed = np.pad(voice, (0, (-len(voice)) % hop)).reshape(-1, hop)
    levels = 20 * np.log10(np.sqrt(np.mean(framed.astype(np.float64) ** 2, axis=1)) + 1e-12)
    threshold = max(-48.0, float(np.percentile(levels, 95)) - 28)
    activity = levels >= threshold
    intervals = merge([[i * hop / SR, min((i + 1) * hop / SR, len(voice) / SR)]
                       for i in np.flatnonzero(activity)])
    phrases = []
    for segment in timeline:
        start = segment['start'] + segment.get('first_activity_s', 0.0)
        end = segment['start'] + segment.get('last_activity_s', segment['voice_end'] - segment['start'])
        local = merge([[max(a, start), min(b, end)] for a, b in intervals if b > start and a < end], .28)
        for a, b in local:
            if b - a >= .06:
                phrases.append({'segment_id': segment['segment_id'], 'start': max(start, a - .06),
                                'end': min(end, b + .10)})
    return phrases, np.repeat(activity, hop)[:len(voice)], threshold


def dip(grid: np.ndarray, start: float, end: float, depth: float,
        attack: float, hold: float, release: float) -> np.ndarray:
    result = np.zeros(len(grid))
    a = (grid >= start - attack) & (grid < start)
    result[a] = depth * (.5 - .5 * np.cos(np.pi * (grid[a] - start + attack) / attack))
    result[(grid >= start) & (grid <= end + hold)] = depth
    b = (grid > end + hold) & (grid < end + hold + release)
    result[b] = depth * (.5 + .5 * np.cos(np.pi * (grid[b] - end - hold) / release))
    return result


def window_audit(voice: np.ndarray, music: np.ndarray, active: np.ndarray,
                 width: float = .4, stride: float = .1) -> list:
    size, hop = round(width * SR), round(stride * SR)
    rows = []
    for a in range(0, len(voice) - size + 1, hop):
        fraction = float(active[a:a + size].mean())
        v = db(rms(voice[a:a + size]))
        if fraction >= .5 and v >= -40:
            m = db(rms(music[a:a + size]))
            rows.append({'start': a / SR, 'end': (a + size) / SR,
                         'voice_rms_dbfs': v, 'music_rms_dbfs': m,
                         'voice_advantage_db': v - m, 'active_fraction': fraction})
    return rows


def summarize(rows: list) -> dict:
    values = [row['voice_advantage_db'] for row in rows]
    return {'windows': len(rows), 'minimum_db': min(values) if values else None,
            'p05_db': float(np.percentile(values, 5)) if values else None,
            'median_db': float(np.median(values)) if values else None,
            'maximum_db': max(values) if values else None}


def load_voice(project: Path, timeline_path: Path, work: Path,
               ffmpeg: str) -> tuple[np.ndarray, list, list]:
    incoming = json.loads(timeline_path.read_text(encoding='utf-8'))
    if isinstance(incoming, dict):
        incoming = incoming.get('segments', incoming.get('timeline'))
    if not isinstance(incoming, list) or not incoming:
        raise ValueError('Timeline must be a nonempty list of segments.')
    timeline, inputs, clips = [], [], []
    previous_end, ids = 0.0, set()
    for i, raw in enumerate(incoming):
        sid = str(raw['segment_id'])
        start, voice_end, end = [number(raw[k], k) for k in ('start', 'voice_end', 'end')]
        if sid in ids or start < previous_end - 1 / SR or voice_end <= start or end < voice_end:
            raise ValueError(f'Invalid, overlapping or unordered timeline segment: {sid}')
        ids.add(sid)
        source = project_path(project, str(raw['audio_path']))
        before = sha256(source)
        clip = decode(source, work / f'voice_{i:04d}.wav', 1, ffmpeg)
        if abs((voice_end - start) - len(clip) / SR) > .001 + 2 / SR:
            raise ValueError(f'voice_end does not match decoded audio duration: {sid}')
        first = number(raw.get('first_activity_s', 0.0), 'first_activity_s')
        last = number(raw.get('last_activity_s', len(clip) / SR), 'last_activity_s')
        if not 0 <= first <= last <= len(clip) / SR + 2 / SR:
            raise ValueError(f'Activity offsets must lie inside the source clip: {sid}')
        timeline.append({'segment_id': sid, 'start': start, 'voice_end': voice_end, 'end': end,
                         'audio_path': source.relative_to(project).as_posix(),
                         'first_activity_s': first, 'last_activity_s': last})
        inputs.append({'path': source, 'sha256': before})
        clips.append((round(start * SR), clip))
        previous_end = end
    voice = np.zeros(round(previous_end * SR), dtype=np.float32)
    for a, clip in clips:
        if a + len(clip) > len(voice):
            raise ValueError('Decoded voice exceeds the final timeline; correct its duration metadata.')
        voice[a:a + len(clip)] += clip
    return voice, timeline, inputs


def load_sfx(project: Path, spec: Path | None, count: int, work: Path,
             ffmpeg: str) -> tuple[np.ndarray, list, list]:
    effects = np.zeros(count, dtype=np.float32)
    if spec is None:
        return effects, [], []
    if spec.suffix.lower() == '.json':
        placements = json.loads(spec.read_text(encoding='utf-8'))
        if not isinstance(placements, list):
            raise ValueError('SFX JSON must be a list of {audio_path,start,gain_db?}.')
    else:
        placements = [{'audio_path': spec.relative_to(project).as_posix(), 'start': 0.0, 'gain_db': 0.0}]
    rows, inputs = [], []
    for i, item in enumerate(placements):
        path = project_path(project, str(item['audio_path']))
        start = number(item['start'], 'SFX start')
        gain = number(item.get('gain_db', 0), 'SFX gain_db')
        if start < 0 or not -80 <= gain <= 24:
            raise ValueError('Invalid SFX start or gain.')
        before = sha256(path)
        audio = decode(path, work / f'sfx_{i:04d}.wav', 1, ffmpeg)
        a, b = round(start * SR), round(start * SR) + len(audio)
        if b > count:
            raise ValueError('SFX extends beyond the timeline; edit its placement explicitly.')
        effects[a:b] += audio * 10 ** (gain / 20)
        rows.append({'start': start, 'end': b / SR, 'audio_path': path.relative_to(project).as_posix(), 'gain_db': gain})
        inputs.append({'path': path, 'sha256': before})
    # A full aligned stem should only duck BGM near real SFX activity.
    if spec.suffix.lower() != '.json':
        hop = round(.02 * SR)
        level = [rms(effects[a:a + hop]) for a in range(0, count, hop)]
        intervals = merge([[i * hop / SR, min((i + 1) * hop / SR, count / SR)]
                           for i, x in enumerate(level) if db(x) > -55], .08)
        rows = [{'start': a, 'end': b, 'audio_path': spec.relative_to(project).as_posix(), 'gain_db': 0.0}
                for a, b in intervals]
    return effects, rows, inputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--timeline', default='timeline.json')
    parser.add_argument('--music', required=True)
    parser.add_argument('--sfx', help='Aligned audio stem, or event-list JSON.')
    parser.add_argument('--out', default='mix.wav')
    parser.add_argument('--bed-below-voice-db', type=float, default=10.0,
                        help='Integrated voice advantage over the base bed; default 10 dB.')
    parser.add_argument('--duck-db', type=float, default=1.5,
                        help='Nonnegative shallow speech-duck amount; default 1.5 dB.')
    parser.add_argument('--duck-limit-db', type=float, default=4.0,
                        help='Nonnegative cap on total adaptive ducking; default 4 dB.')
    parser.add_argument('--music-end-policy', choices=['error', 'crossfade_extend'], default='error')
    parser.add_argument('--music-cues', help='Project-relative phrase/outro JSON; inferred sibling .music.json otherwise.')
    parser.add_argument('--ffmpeg', default=os.environ.get('FFMPEG', 'ffmpeg'))
    parser.add_argument('--ffprobe', default=os.environ.get('FFPROBE', 'ffprobe'))
    parser.add_argument('--skip-aac-check', action='store_true', help='Omit codec-preview measurement; report marks it unverified.')
    args = parser.parse_args()
    for name in ('bed_below_voice_db', 'duck_db', 'duck_limit_db'):
        value = getattr(args, name)
        if not math.isfinite(value) or not 0 <= value <= 30:
            parser.error(f'--{name.replace("_", "-")} must be between 0 and 30 dB')
    if args.duck_db > args.duck_limit_db:
        parser.error('--duck-db cannot exceed --duck-limit-db')
    params = dict(PARAMS)
    params.update(music_base_voice_advantage_lu=args.bed_below_voice_db,
                  stable_window_voice_advantage_db=args.bed_below_voice_db,
                  speech_duck_db=-args.duck_db,
                  total_adaptive_duck_limit_db=args.duck_limit_db)
    project = args.project.expanduser().resolve(strict=True)
    if not project.is_dir():
        parser.error('--project must be a directory')
    timeline_path = project_path(project, args.timeline)
    music_path = project_path(project, args.music)
    sfx_path = project_path(project, args.sfx) if args.sfx else None
    output = project_path(project, args.out, exists=False)
    if output.suffix.lower() != '.wav':
        parser.error('--out must have a .wav extension')
    report_path = output.with_suffix('.report.json')
    stem_dir = output.with_name(output.stem + '_stems')
    if output.exists() or report_path.exists() or stem_dir.exists():
        parser.error('Mix, report or stem directory already exists; use a new --out filename.')
    cues_path = project_path(project, args.music_cues) if args.music_cues else music_path.with_suffix('.music.json')
    if not cues_path.resolve().is_relative_to(project):
        raise ValueError('Music cues escape the project.')
    cues = json.loads(cues_path.read_text(encoding='utf-8')) if cues_path.exists() else None
    inputs = [{'path': music_path, 'sha256': sha256(music_path)},
              {'path': timeline_path, 'sha256': sha256(timeline_path)}]
    if cues_path.exists():
        inputs.append({'path': cues_path, 'sha256': sha256(cues_path)})
    if sfx_path:
        inputs.append({'path': sfx_path, 'sha256': sha256(sfx_path)})
    # Fail before preparation if either required executable is unavailable.
    run([args.ffmpeg, '-version'])
    run([args.ffprobe, '-version'])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.audio-work-', dir=output.parent) as temporary:
        work = Path(temporary)
        voice, timeline, voice_inputs = load_voice(project, timeline_path, work, args.ffmpeg)
        inputs.extend(voice_inputs)
        samples, duration = len(voice), len(voice) / SR
        voice_path = work / 'voice_timeline.wav'
        write_audio(voice_path, np.column_stack([voice, voice]))
        voice_measure = measure_loudness(voice_path, args.ffmpeg)
        valid_measurement(voice_measure, 'Narration')
        music, dynamics = prepare_music(music_path, work, args.ffmpeg)
        music, edit = fit_music(music, samples, cues, args.music_end_policy)
        fitted_path = work / 'music_fitted.wav'
        write_audio(fitted_path, music)
        fitted_measure = measure_loudness(fitted_path, args.ffmpeg)
        base = constant_gain(fitted_measure, voice_measure['integrated_lufs'] - args.bed_below_voice_db, -10)
        music *= 10 ** (base / 20)
        effects, sfx_rows, sfx_inputs = load_sfx(project, sfx_path, samples, work, args.ffmpeg)
        inputs.extend(sfx_inputs)
        phrases, active, threshold = detect_activity(voice, timeline)
        raw = window_audit(voice, music, active)
        grid = np.arange(math.ceil(duration / STEP) + 1) * STEP
        speech, energy, sfx_env = [np.zeros(len(grid)) for _ in range(3)]
        for phrase in phrases:
            rows = [r for r in raw if r['end'] > phrase['start'] and r['start'] < phrase['end']]
            # One robust gain per phrase; exclude weak tails and sparsely voiced windows.
            robust = [r['voice_advantage_db'] for r in rows
                      if r['active_fraction'] >= .8 and r['voice_rms_dbfs'] >= -30]
            depth = (max(-args.duck_limit_db, min(-args.duck_db,
                         float(np.percentile(robust, 10)) - args.bed_below_voice_db))
                     if robust else -args.duck_db)
            phrase['duck_db'] = depth
            speech = np.minimum(speech, dip(grid, phrase['start'], phrase['end'], depth, .14, .30, 1.15))
        for previous, following in zip(phrases, phrases[1:]):
            if following['start'] > previous['end']:
                depth = min(0, min(previous['duck_db'], following['duck_db']) + 2)
                speech = np.minimum(speech, dip(grid, previous['end'], following['start'], depth, .25, 0, 1.15))
        frames = loudness_frames(fitted_path, args.ffmpeg)
        valid = frames[(frames[:, 0] >= 3) & (frames[:, 2] > -60)]
        high_intervals = []
        if len(valid):
            cutoff = float(np.percentile(valid[:, 2], 80))
            high_intervals = merge([[max(0, t - 3), min(duration, t)]
                                    for t, _, loudness in valid if loudness >= cutoff], .7)
            for a, b in high_intervals:
                energy = np.minimum(energy, dip(grid, a, b, -1.5, .45, .2, 1.70))
        for row in sfx_rows:
            a, b = round(row['start'] * SR), min(samples, round(row['end'] * SR))
            advantages = [db(rms(effects[j:min(j + round(.1 * SR), b)])) -
                          db(rms(music[j:min(j + round(.1 * SR), b)])) - 3
                          for j in range(a, b, round(.05 * SR))
                          if db(rms(effects[j:min(j + round(.1 * SR), b)])) > -55]
            depth = max(-2, min([0.0] + advantages))
            row['music_duck_db'] = depth
            sfx_env = np.minimum(sfx_env, dip(grid, row['start'], row['end'], depth, .1, .12, .6))
        combined = np.maximum(-args.duck_limit_db, np.minimum(speech, sfx_env) + energy)
        apply_grid(music, grid, combined)
        for a in range(0, samples, SR):
            b = min(a + SR, samples)
            t = np.arange(a, b) / SR
            fade = np.sin(np.clip(t / .65, 0, 1) * np.pi / 2) ** 2
            fade *= np.sin(np.clip((duration - 1 / SR - t) / 1.2, 0, 1) * np.pi / 2) ** 2
            music[a:b] *= fade.astype(np.float32)[:, None]
        music_final_path = work / 'music_ducked.wav'
        write_audio(music_final_path, music)
        music_measure = measure_loudness(music_final_path, args.ffmpeg)
        premaster = music.copy()
        premaster += (voice + effects)[:, None]
        premaster_path = work / 'premaster.wav'
        write_audio(premaster_path, premaster)
        premaster_measure = measure_loudness(premaster_path, args.ffmpeg)
        gain = constant_gain(premaster_measure, -16, -1.8)
        candidate = work / 'candidate.wav'
        aac = None
        for attempt in range(4):
            write_audio(candidate, premaster * 10 ** (gain / 20))
            final = measure_loudness(candidate, args.ffmpeg)
            correction = max(0.0, final['true_peak_dbtp'] + 1.8)
            if not args.skip_aac_check:
                encoded = work / 'candidate.m4a'
                run([args.ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', str(candidate),
                     '-c:a', 'aac', '-b:a', '192k', str(encoded)])
                aac = measure_loudness(encoded, args.ffmpeg)
                valid_measurement(aac, 'AAC preview')
                correction = max(correction, aac['true_peak_dbtp'] + 1.8)
            if correction <= .01:
                break
            gain -= correction + .15
        else:
            raise RuntimeError('Peak headroom could not be verified; no final output was committed.')
        windows = {f'{width:g}s': window_audit(voice, music, active, width) for width in (.4, 1, 3)}
        summaries = {key: summarize(rows) for key, rows in windows.items()}
        unchanged = all(sha256(item['path']) == item['sha256'] for item in inputs)
        if not unchanged:
            raise RuntimeError('An input changed during mixing; no final output was committed.')
        warnings = []
        if summaries['0.4s']['windows'] == 0:
            warnings.append('No qualifying 400 ms speech windows; inspect narration and activity metadata.')
        else:
            if summaries['0.4s']['p05_db'] < 5 or summaries['0.4s']['median_db'] < 9:
                warnings.append('Speech/music objective margin is low; listen and revise the balance.')
        if final['integrated_lufs'] < -18:
            warnings.append('Peak-limited constant gain leaves loudness below -18 LUFS; '
                            'no master overcompression was used to force -16.')
        if args.skip_aac_check:
            warnings.append('AAC codec headroom was not measured.')
        output_probe = probe_media(candidate, args.ffprobe)
        stem_dir.mkdir(parents=True, exist_ok=False)
        write_audio(stem_dir / 'voice_timeline.wav', np.column_stack([voice, voice]))
        write_audio(stem_dir / 'music_ducked.wav', music)
        write_audio(stem_dir / 'sfx_timeline.wav', np.column_stack([effects, effects]))
        save_json(stem_dir / 'timeline.json', timeline)
        save_json(stem_dir / 'automation_10ms.json', [
            {'t': float(t), 'speech_db': float(s), 'high_energy_db': float(e),
             'sfx_db': float(f), 'total_db': float(c)}
            for t, s, e, f, c in zip(grid, speech, energy, sfx_env, combined)])
        for key, rows in windows.items():
            save_json(stem_dir / f'windows_{key}.json', rows)
        candidate.replace(output)
        report = {'schema_version': 1, 'output': output.relative_to(project).as_posix(),
                  'duration_seconds': duration, 'segments': len(timeline), 'parameters': params,
                  'inputs': [{'path': item['path'].relative_to(project).as_posix(), 'sha256': item['sha256']}
                             for item in inputs],
                  'inputs_unchanged': unchanged, 'voice_measurement': voice_measure,
                  'music_dynamics': dynamics, 'music_edit': edit,
                  'base_music_gain_db': base, 'music_after_duck_measurement': music_measure,
                  'voice_minus_music_integrated_lu': voice_measure['integrated_lufs'] - music_measure['integrated_lufs']
                      if music_measure['integrated_lufs'] is not None else None,
                  'speech_detector_threshold_dbfs': threshold, 'phrases': phrases,
                  'high_energy_intervals': high_intervals, 'sfx': sfx_rows,
                  'relative_level_audit': summaries, 'premaster': premaster_measure,
                  'master_constant_gain_db': gain, 'final_pcm': final, 'aac_192k_preview': aac,
                  'output_probe': output_probe, 'output_sha256': sha256(output),
                  'stem_levels': 'Pre-master; apply master_constant_gain_db for final-equivalent playback.',
                  'voice_processing': 'Sample-rate conversion to 48 kHz and centered mono placement; '
                                      'only common constant gain in final mix. No time stretch, '
                                      'speed change, denoise, voice compression or source overwrite.',
                  'review_required': warnings + ['Listen to the entire rendered final video, including the '
                                                 'opening, quiet speech, music edit seams and ending.'],
                  'measurement_scope': 'Objective loudness, true peak, RMS windows, timing and hashes; '
                                       'not a subjective listening or intelligibility approval.',
                  'music_provenance': 'Use only the authorized bundled music or caller-owned/authorized sources.'}
        save_json(report_path, report)
        print(json.dumps({'mix': output.relative_to(project).as_posix(),
                          'report': report_path.relative_to(project).as_posix(),
                          'stems': stem_dir.relative_to(project).as_posix(),
                          'integrated_lufs': final['integrated_lufs'],
                          'true_peak_dbtp': final['true_peak_dbtp'], 'review_required': warnings}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (KeyError, TypeError, ValueError, OSError, RuntimeError) as error:
        print(f'Audio mix error: {error}', file=sys.stderr)
        raise SystemExit(2)
