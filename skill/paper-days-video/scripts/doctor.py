#!/usr/bin/env python3
"""Inspect local prerequisites without installing packages or downloading models."""
import argparse
import importlib.util
import json
import os
import platform
import shutil
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, required=True)
    a = p.parse_args()
    root = a.project.resolve()
    cfg = json.loads((root / 'config.json').read_text(encoding='utf-8'))
    deps = ['numpy', 'scipy', 'PIL', 'soundfile', 'psutil', 'torch', 'qwen_tts', 'faster_whisper']
    report = {'python': sys.version, 'platform': platform.platform(),
              'python_supported': (3, 11) <= sys.version_info[:2] <= (3, 12),
              'packages': {x: importlib.util.find_spec(x) is not None for x in deps},
              'executables': {x: shutil.which(os.environ.get(x.upper(), cfg.get(x, x))) for x in ['ffmpeg', 'ffprobe']},
              'assets': {key: (root / cfg[key]).is_file() for key in ['voice_reference', 'voice_transcript', 'font_regular', 'font_bold', 'music_path']}}
    if report['packages']['psutil']:
        import psutil
        report['available_memory_gib'] = round(psutil.virtual_memory().available / 2**30, 2)
        report['recommended_available_memory_gib'] = 8
    if report['packages']['torch']:
        import torch
        report['torch'] = torch.__version__
        report['cuda_available'] = torch.cuda.is_available()
        if report['cuda_available']:
            report['cuda_device'] = torch.cuda.get_device_name(0)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
