#!/usr/bin/env python3
"""Inventory and structurally verify a finished project's delivery files."""
import argparse
import json
import math
import os
from pathlib import Path
from PIL import Image
from audit_media import sha256, probe_media


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', required=True, type=Path)
    a = p.parse_args()
    root = a.project.resolve()
    delivery = root / 'delivery'
    cfg, episode = read(root / 'config.json'), read(root / 'episode.json')
    for name in ['main.mp4', 'cover-3x4.png', 'cover-4x3.png', 'subtitles.srt', 'description.txt']:
        path = delivery / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Missing or empty delivery file: {name}')
    if not (root / 'sources.md').is_file():
        raise ValueError('sources.md must record actual sources/material provenance, including a no-research-source explanation if applicable.')
    (delivery / 'sources.md').write_bytes((root / 'sources.md').read_bytes())
    probe = probe_media(delivery / 'main.mp4', os.environ.get('FFPROBE', cfg.get('ffprobe', 'ffprobe')))
    videos = [s for s in probe['streams'] if s['codec_type'] == 'video']
    audios = [s for s in probe['streams'] if s['codec_type'] == 'audio']
    if len(videos) != 1 or len(audios) != 1:
        raise ValueError('Delivery must have one video and one audio stream.')
    v, audio = videos[0], audios[0]
    if (v['width'], v['height'], v['codec_name'], v['pix_fmt']) != (1080, 1920, 'h264', 'yuv420p'):
        raise ValueError('Unexpected delivery video format.')
    ratio = v.get('avg_frame_rate', '0/1').split('/')
    if len(ratio) != 2 or abs(int(ratio[0]) / int(ratio[1]) - 24) > 0.001:
        raise ValueError('Delivery frame rate must be 24 fps.')
    if audio['codec_name'] != 'aac' or int(audio['sample_rate']) != 48000:
        raise ValueError('Delivery audio must be AAC / 48 kHz.')
    timeline = read(root / 'timeline.json')
    actual = float(probe['format']['duration'])
    expected = float(timeline[-1]['end'])
    if not math.isfinite(actual) or abs(actual - expected) > 0.1:
        raise ValueError('Delivery length does not match the current timeline.')
    for name, size in [('cover-3x4.png', (1080, 1440)), ('cover-4x3.png', (1440, 1080))]:
        with Image.open(delivery / name) as im:
            if im.size != size:
                raise ValueError(f'Cover size mismatch: {name}')
            im.verify()
    mux_receipt = read(root / 'qa' / 'mux.json')
    if mux_receipt.get('mp4_sha256') != sha256(delivery / 'main.mp4') or mux_receipt.get('timeline_sha256') != sha256(root / 'timeline.json'):
        raise ValueError('Final MP4 or current timeline does not match the mux receipt.')
    audio_audit = read(root / 'qa' / 'final-media.json')
    if audio_audit.get('sha256') != sha256(delivery / 'main.mp4'):
        raise ValueError('The objective audio audit must correspond to the actual final MP4.')
    review_path = root / 'qa' / 'review.json'
    review = read(review_path) if review_path.exists() else {'status': 'not_recorded'}
    manifest = {'title': episode['title'], 'mode': episode['mode'], 'duration_seconds': actual,
                'structural_checks': {'format': 'passed', 'duration': 'passed', 'cover_dimensions': 'passed'},
                'objective_audio': audio_audit, 'review': review,
                'voice_provenance': read(root / 'assets' / 'voice' / 'provenance.json'),
                'music_path': cfg.get('music_path'),
                'files': [{'path': item.name, 'bytes': item.stat().st_size, 'sha256': sha256(item)}
                          for item in sorted(delivery.iterdir()) if item.is_file() and item.name != 'manifest.json']}
    (delivery / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(f'Delivery inventory written: {delivery / "manifest.json"}')


if __name__ == '__main__':
    main()
