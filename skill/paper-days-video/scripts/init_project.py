#!/usr/bin/env python3
"""Create a self-contained editable production project; Codex authors its story."""
import argparse
import json
import shutil
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', required=True, type=Path)
    p.add_argument('--topic', required=True)
    p.add_argument('--mode', choices=['research', 'product'], default='research')
    a = p.parse_args()
    root = a.project.resolve()
    if root.exists() and any(root.iterdir()):
        raise SystemExit('Project directory is not empty; choose a new directory, or continue the existing project without reinitializing.')
    root.mkdir(parents=True, exist_ok=True)
    skill = Path(__file__).resolve().parent.parent
    shutil.copytree(skill / 'assets', root / 'assets', ignore=shutil.ignore_patterns('project'))
    for source in (skill / 'assets' / 'project').iterdir():
        if source.is_file():
            shutil.copy2(source, root / source.name)
    shutil.copytree(skill / 'scripts', root / 'tools', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('LICENSE', 'LICENSE-ASSETS.md', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(skill / name, root / name)
    for name in ('requirements.txt', 'requirements-voice.txt', 'requirements-asr.txt'):
        source = skill / name
        if source.exists():
            shutil.copy2(source, root / name)
    config = {
        'voice_reference': 'assets/voice/reference.wav',
        'voice_transcript': 'assets/voice/reference.txt',
        'voice_prompt': 'assets/voice/approved_voice_prompt.pt',
        'model_path': 'models/Qwen3-TTS-12Hz-1.7B-Base',
        'device': 'cpu', 'dtype': 'bfloat16', 'seed': 21, 'cpu_threads': 4,
        'speed': 1.1, 'timeout_seconds': 900, 'no_progress_timeout_seconds': 60,
        'output_dir': 'voice',
        'font_regular': 'assets/fonts/SourceHanSansSC-Regular.otf',
        'font_bold': 'assets/fonts/SourceHanSansSC-Bold.otf',
        'music_path': 'assets/music/observation-deck.mp3', 'mix_path': 'mix.wav',
        'ffmpeg': 'ffmpeg', 'ffprobe': 'ffprobe',
        'fps': 24, 'width': 1080, 'height': 1920, 'gap_seconds': 0.42, 'end_hold_seconds': 2.0,
    }
    episode = {'title': a.topic, 'topic': a.topic, 'mode': a.mode, 'cover_title': a.topic,
               'cover_subtitle': 'Paper Days', 'description': '', 'segments': []}
    for name, value in [('config.json', config), ('episode.json', episode)]:
        (root / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (root / '.gitignore').write_text('.venv/\nmodels/\nvoice/\nrendered/\nframes/\nqa/\n__pycache__/\n*.part\n', encoding='utf-8')
    print(f'Project ready: {root}\nCodex now writes sources.md, episode.json and the topic-specific scenes.py.')


if __name__ == '__main__':
    main()
