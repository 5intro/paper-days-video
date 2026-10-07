#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Objective ffprobe/loudness audit; never claims that a person heard the result."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Executable not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        # Keep the last useful diagnostic; no shell interpretation is used.
        raise RuntimeError(f"{Path(command[0]).name} failed: {exc.stderr[-3000:]}") from exc


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def finite(value: object) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def measure_loudness(path: Path, ffmpeg: str = 'ffmpeg') -> dict:
    """Read loudnorm's input statistics, discarding its processed output."""
    result = run([ffmpeg, '-hide_banner', '-nostdin', '-i', str(path),
                  '-map', '0:a:0', '-vn', '-af',
                  'loudnorm=I=-16:TP=-1.8:LRA=11:print_format=json',
                  '-f', 'null', '-'])
    matches = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', result.stderr)
    if not matches:
        raise RuntimeError('FFmpeg did not return loudness input measurements.')
    raw = json.loads(matches[-1])
    return {'integrated_lufs': finite(raw.get('input_i')),
            'true_peak_dbtp': finite(raw.get('input_tp')),
            'loudness_range_lu': finite(raw.get('input_lra')),
            'gate_threshold_lufs': finite(raw.get('input_thresh')),
            'method': 'FFmpeg loudnorm input measurement; processed output discarded.'}


def probe_media(path: Path, ffprobe: str = 'ffprobe') -> dict:
    raw = json.loads(run([ffprobe, '-v', 'error', '-show_streams',
                          '-show_format', '-of', 'json', str(path)]).stdout)
    # Do not copy source tags, local filesystem paths or arbitrary metadata.
    keys = ('index', 'codec_type', 'codec_name', 'sample_rate', 'channels',
            'channel_layout', 'width', 'height', 'pix_fmt', 'r_frame_rate',
            'avg_frame_rate', 'duration', 'nb_frames', 'bit_rate')
    return {'format': {k: raw.get('format', {}).get(k) for k in
                       ('format_name', 'duration', 'size', 'bit_rate')},
            'streams': [{k: s[k] for k in keys if k in s} for s in raw.get('streams', [])]}


def audit(path: Path, ffmpeg: str, ffprobe: str, ceiling: float) -> dict:
    metadata = probe_media(path, ffprobe)
    audio = [s for s in metadata['streams'] if s.get('codec_type') == 'audio']
    loudness = measure_loudness(path, ffmpeg) if audio else None
    tp = loudness['true_peak_dbtp'] if loudness else None
    return {'file': path.name, 'sha256': sha256(path), 'probe': metadata,
            'audio_stream_measured': audio[0]['index'] if audio else None,
            'loudness': loudness, 'true_peak_ceiling_dbtp': ceiling,
            'true_peak_within_ceiling': tp <= ceiling + .01 if tp is not None else None,
            'loudness_target_lufs': -16.0,
            'integrated_distance_from_target_lu':
                loudness['integrated_lufs'] + 16.0
                if loudness and loudness['integrated_lufs'] is not None else None,
            'review_required': ['Listen to the entire final export for speech intelligibility, '
                                'music balance, edit transitions, clicks and timing.',
                                'Inspect video frames and subtitle placement separately.'],
            'measurement_scope': 'Objective metadata and first-audio-stream loudness only; '
                                 'no listening, ASR, visual or subjective quality approval.'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('media', type=Path)
    parser.add_argument('--out', type=Path, help='Optional JSON report; otherwise print JSON.')
    parser.add_argument('--ffmpeg', default=os.environ.get('FFMPEG', 'ffmpeg'))
    parser.add_argument('--ffprobe', default=os.environ.get('FFPROBE', 'ffprobe'))
    parser.add_argument('--true-peak-ceiling', type=float, default=-1.8)
    args = parser.parse_args()
    path = args.media.expanduser().resolve(strict=True)
    if not math.isfinite(args.true_peak_ceiling):
        parser.error('--true-peak-ceiling must be finite')
    if args.out and args.out.expanduser().resolve() == path:
        parser.error('Report cannot overwrite the media input.')
    report = audit(path, args.ffmpeg, args.ffprobe, args.true_peak_ceiling)
    data = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(data, encoding='utf-8')
    print(data, end='')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        print(f'Audio audit error: {error}', file=sys.stderr)
        raise SystemExit(2)
