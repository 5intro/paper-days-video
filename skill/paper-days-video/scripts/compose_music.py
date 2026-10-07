#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create a seeded, sample-free light instrumental bed using NumPy and SciPy."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

SR = 48000


def hz(midi: int) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def add_note(out: np.ndarray, start: float, length: float, midi: int,
             gain: float, pan: float, kind: str, rng: np.random.Generator) -> None:
    first = max(0, round(start * SR))
    count = min(round(length * SR), len(out) - first)
    if count <= 1:
        return
    t = np.arange(count, dtype=np.float64) / SR
    phase = 2.0 * np.pi * hz(midi) * t
    if kind == 'pad':
        wave = (np.sin(phase) + .19 * np.sin(phase * 2.0 + .3) +
                .10 * np.sin(phase * 3.0 + .5)) / 1.29
        env = (1.0 - np.exp(-t / .34)) * np.exp(-t / max(length * .9, .2))
        release = min(.8, length * .3)
    elif kind == 'bass':
        wave = (np.sin(phase) + .13 * np.sin(phase * 2.0)) / 1.13
        env = (1.0 - np.exp(-t / .035)) * np.exp(-t / .9)
        release = min(.2, length * .3)
    else:
        # Damped harmonic oscillators, not a recording or a borrowed motif.
        wave = (np.sin(phase) * np.exp(-t / 1.45) +
                .26 * np.sin(2.0 * phase + .2) * np.exp(-t / .5) +
                .07 * np.sin(3.0 * phase + .35) * np.exp(-t / .22)) / 1.33
        env = 1.0 - np.exp(-t / .008)
        release = min(.22, length * .3)
    remaining = (count - 1) / SR - t
    tail = np.sin(np.clip(remaining / max(release, 1.0 / SR), 0, 1) * np.pi / 2) ** 2
    signal = (wave * env * tail * gain).astype(np.float32)
    angle = (float(np.clip(pan, -1, 1)) + 1) * np.pi / 4
    out[first:first + count, 0] += signal * np.cos(angle)
    out[first:first + count, 1] += signal * np.sin(angle)
    # Sparse soft echoes are generated from the same note, never sampled assets.
    if kind == 'keys':
        for delay, amplitude in ((.17, .075), (.31, .04)):
            a = first + round(delay * SR)
            k = min(count, len(out) - a)
            if k > 0:
                out[a:a + k, 0] += signal[:k] * amplitude * np.sin(angle)
                out[a:a + k, 1] += signal[:k] * amplitude * np.cos(angle)


def compose(duration: float, seed: int, bpm: float) -> tuple[np.ndarray, dict]:
    rng = np.random.default_rng(seed)
    out = np.zeros((round(duration * SR), 2), dtype=np.float32)
    beat = 60.0 / bpm
    bar = beat * 4
    phrase = bar * 4
    # Common harmonic building blocks; all note selection is procedural.
    palette = ((48, 52, 55, 59), (45, 48, 52, 55),
               (41, 45, 48, 52), (43, 47, 50, 55))
    order = (0, 1, 2, 3) if rng.random() < .5 else (0, 2, 1, 3)
    ending = min(4.5, duration * .23)
    outro = duration - ending
    motif = rng.choice([0, 1, 2, 3, 4, 5, 6], 8, replace=True)
    scale = [60, 62, 64, 67, 69, 72, 74]
    for index in range(math.ceil(outro / bar)):
        start = index * bar
        chord = palette[order[index % 4]]
        breathing = .88 + .12 * np.sin(index * .53 + .4)
        for j, note in enumerate(chord):
            add_note(out, start + j * .015, min(bar + .6, duration - start),
                     note + 12, .023 * breathing, (j - 1.5) / 3, 'pad', rng)
        for position in (0.0, 2.0):
            at = start + position * beat
            if at < outro:
                add_note(out, at, 1.65 * beat, chord[0] - 12, .055, 0, 'bass', rng)
        for j, position in enumerate((0.5, 1.5, 2.5, 3.25)):
            at = start + position * beat + rng.uniform(-.012, .012)
            if at >= outro or rng.random() < .20:
                continue
            # A restrained recurring contour with per-phrase deterministic variation.
            slot = int(motif[(index * 2 + j) % len(motif)])
            midi = scale[slot]
            if index % 4 == 3 and j >= 2:
                midi = 67 if j == 2 else 64
            add_note(out, at, min(1.9, duration - at), midi,
                     .065 * rng.uniform(.78, 1.10), rng.uniform(-.4, .4), 'keys', rng)
    # Resolve deliberately before the last fade, rather than slicing a loop at EOF.
    for j, midi in enumerate((48, 55, 60, 64, 67)):
        add_note(out, outro + j * .055, duration - outro - j * .055,
                 midi, .035 if j < 2 else .055, (j - 2) / 5, 'keys', rng)
    out = sosfilt(butter(2, 11000, fs=SR, btype='lowpass', output='sos'),
                  out, axis=0).astype(np.float32)
    attack = min(.65, duration * .12)
    release = min(1.25, duration * .20)
    t = np.arange(len(out)) / SR
    fade = np.sin(np.clip(t / attack, 0, 1) * np.pi / 2) ** 2
    fade *= np.sin(np.clip((duration - 1 / SR - t) / release, 0, 1) * np.pi / 2) ** 2
    out *= fade.astype(np.float32)[:, None]
    active = out[int(attack * SR):max(int(attack * SR) + 1, len(out) - int(release * SR))]
    level = math.sqrt(float(np.mean(active.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(out)))
    scale_gain = min(10 ** (-21 / 20) / max(level, 1e-12),
                     10 ** (-4.2 / 20) / max(peak, 1e-12))
    out *= scale_gain
    boundaries = [round(float(x), 6) for x in np.arange(0, outro, phrase)]
    report = {'schema_version': 1, 'generator': 'paper-days procedural instrumental v1',
              'seed': seed, 'duration_seconds': len(out) / SR, 'sample_rate': SR,
              'bpm': bpm, 'beats_per_bar': 4, 'bars_per_phrase': 4,
              'phrase_boundaries_s': boundaries, 'outro_start_s': round(outro, 6),
              'crossfade_seconds': min(2.0, phrase / 4),
              'source_type': 'procedural_synthesis', 'external_samples': [],
              'composition': 'Seeded original oscillator-based arrangement; no supplied melody '
                             'or third-party recording is used.',
              'speed_change': False, 'sample_peak_dbfs': 20 * math.log10(max(float(np.max(np.abs(out))), 1e-12)),
              'measurement_scope': 'Synthesis metadata and sample peak; no listening or true-peak approval.'}
    return out, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, required=True, help='Seconds, at least 3.')
    parser.add_argument('--seed', type=int, default=17)
    parser.add_argument('--bpm', type=float, default=82.0)
    parser.add_argument('--out', '--output', dest='out', type=Path, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.duration) or not 3 <= args.duration <= 1800:
        parser.error('--duration must be finite and between 3 and 1800 seconds')
    if not math.isfinite(args.bpm) or not 55 <= args.bpm <= 120:
        parser.error('--bpm must be between 55 and 120')
    if args.out.suffix.lower() != '.wav':
        parser.error('--out must have a .wav extension')
    metadata_path = args.out.with_suffix('.music.json')
    if args.out.exists() or metadata_path.exists():
        parser.error('Output or metadata already exists; use a new output filename.')
    audio, report = compose(args.duration, args.seed, args.bpm)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(args.out, SR, audio)
    report['file'] = args.out.name
    metadata_path.write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                        allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'music': args.out.name, 'metadata': metadata_path.name,
                      'duration_seconds': report['duration_seconds'], 'seed': args.seed}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        print(f'Music composition error: {error}', file=sys.stderr)
        raise SystemExit(2)
