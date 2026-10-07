#!/usr/bin/env python3
"""Copy this standalone skill into Codex's personal skill discovery directory."""
import argparse
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dest', type=Path, help='Exact new skill directory; default ~/.agents/skills/paper-days-video')
    args = parser.parse_args()
    source = Path(__file__).resolve().parent / 'skill' / 'paper-days-video'
    target = (args.dest or Path.home() / '.agents' / 'skills' / 'paper-days-video').expanduser().resolve()
    if target.exists():
        raise SystemExit(f'Destination already exists: {target}. Choose --dest or review the existing installation before replacing it.')
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
    print(f'Installed: {target}\nIn Codex, invoke $paper-days-video with a topic.')


if __name__ == '__main__':
    main()
