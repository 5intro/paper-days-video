#!/usr/bin/env python3
"""Save raw ASR observations; do not replace locked text or claim subjective listening."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', required=True, type=Path)
    p.add_argument('--model', default='small', help='faster-whisper model name or local directory')
    p.add_argument('--segment', action='append', help='Process only this id (repeatable)')
    p.add_argument('--device', default='cpu', choices=['cpu', 'cuda'])
    a = p.parse_args()
    root = a.project.resolve()
    config = json.loads((root / 'config.json').read_text(encoding='utf-8'))
    manifest = json.loads((root / config.get('output_dir', 'voice') / 'manifest.json').read_text(encoding='utf-8'))
    out = root / 'qa' / 'asr'
    out.mkdir(parents=True, exist_ok=True)
    from faster_whisper import WhisperModel
    model = WhisperModel(a.model, device=a.device, compute_type='int8' if a.device == 'cpu' else 'float16', cpu_threads=4)
    for segment in manifest['segments']:
        sid = str(segment['id'])
        if a.segment and sid not in a.segment:
            continue
        audio = (root / segment['path']).resolve()
        if not audio.is_relative_to(root):
            raise ValueError('ASR audio must be in the project.')
        identity = {'audio_sha256': hashlib.sha256(audio.read_bytes()).hexdigest(), 'model': a.model,
                    'device': a.device, 'language': 'zh', 'word_timestamps': True, 'vad_filter': False}
        dest = out / f'{sid}-{Path(a.model).name}.json'
        if dest.exists() and json.loads(dest.read_text(encoding='utf-8')).get('identity') == identity:
            print(f'Reusing raw ASR {sid}', flush=True)
            continue
        observed, info = model.transcribe(str(audio), language='zh', beam_size=5,
                                          word_timestamps=True, vad_filter=False)
        rows = []
        for item in observed:
            rows.append({'start': item.start, 'end': item.end, 'text': item.text,
                         'avg_logprob': item.avg_logprob,
                         'words': [{'start': w.start, 'end': w.end, 'word': w.word, 'probability': w.probability}
                                   for w in item.words or []]})
        value = {'identity': identity, 'segment_id': sid, 'duration': info.duration,
                 'language_probability': info.language_probability, 'segments': rows,
                 'purpose': 'Raw observations only. Review homophones, omissions and timing against the locked script.'}
        tmp = dest.with_suffix('.tmp')
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        tmp.replace(dest)
        print(f'Observed {sid}', flush=True)


if __name__ == '__main__':
    main()
