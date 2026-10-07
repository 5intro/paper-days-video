#!/usr/bin/env python3
"""Download the exact complete OFL fonts from their official pinned source."""
import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, required=True)
    a = p.parse_args()
    root = a.project.resolve()
    folder = root / 'assets' / 'fonts'
    manifest = json.loads((folder / 'downloads.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        out = folder / item['filename']
        if out.exists() and out.stat().st_size == item['size_bytes'] and sha(out) == item['sha256']:
            print(f'Present: {item["filename"]}')
            continue
        tmp = out.with_suffix(out.suffix + '.part')
        try:
            req = urllib.request.Request(item['url'], headers={'User-Agent': 'paper-days-video/1.0'})
            with urllib.request.urlopen(req, timeout=90) as r, tmp.open('wb') as f:
                while chunk := r.read(1024 * 1024):
                    f.write(chunk)
            if tmp.stat().st_size != item['size_bytes'] or sha(tmp) != item['sha256']:
                raise ValueError(f'Font checksum mismatch: {item["filename"]}; keep pinned manifest unchanged and inspect upstream.')
            tmp.replace(out)
            print(f'Ready: {item["filename"]}')
        finally:
            if tmp.exists():
                tmp.unlink()


if __name__ == '__main__':
    main()
