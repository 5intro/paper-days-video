#!/usr/bin/env python3
"""Render an authored Paper Days project from measured voice and reviewed cue timings."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def inside(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f'Project path escapes its directory: {value}')
    return path


def timestamp(seconds):
    n = round(seconds * 1000)
    return f'{n // 3600000:02}:{n // 60000 % 60:02}:{n // 1000 % 60:02},{n % 1000:03}'


def wrap(text, font_path, language):
    """Fit one or two readable lines. Fail instead of shrinking unreadably."""
    draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    text = text.strip()
    sizes = [44, 42, 40] if language == 'zh' else [29, 28, 27]
    for size in sizes:
        font = ImageFont.truetype(str(font_path), size)
        width = lambda s: draw.textlength(s, font=font)
        if width(text) <= 880:
            return [text], size
        if language == 'zh':
            candidates = [(text[:i], text[i:]) for i in range(2, len(text) - 1)]
        else:
            words = text.split()
            candidates = [(' '.join(words[:i]), ' '.join(words[i:])) for i in range(1, len(words))]
        candidates = [pair for pair in candidates if all(width(x) <= 880 for x in pair)]
        if candidates:
            return list(min(candidates, key=lambda pair: abs(width(pair[0]) - width(pair[1])))), size
    raise ValueError(f'Split this {language} cue semantically into smaller timed cues: {text}')


def prepare(root, episode, config):
    fps = config.get('fps', 24)
    if (config.get('width', 1080), config.get('height', 1920), fps) != (1080, 1920, 24):
        raise ValueError('This Paper Days render profile is 1080x1920 at 24 fps.')
    segments = episode['segments']
    if not segments:
        raise ValueError('Codex must write the researched bilingual episode before rendering.')
    ids = [str(s['id']) for s in segments]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r'[A-Za-z0-9_-]+', x) for x in ids):
        raise ValueError('Each segment requires a unique safe id (letters, digits, underscore, hyphen).')
    voice_manifest = read(root / config.get('output_dir', 'voice') / 'manifest.json')
    if voice_manifest.get('status') != 'complete':
        raise ValueError('Complete all voice segments before building the final timeline.')
    voice = voice_manifest['segments']
    by_id = {str(v['id']): v for v in voice}
    alignment = read(root / 'alignment.json')['segments']
    regular = inside(root, config['font_regular'])
    timeline, cues, cursor = [], [], 0.0
    for index, segment in enumerate(segments):
        sid = str(segment['id'])
        v = by_id[sid]
        path = inside(root, v['path'])
        if v['zh'] != segment['zh'] or sha(path) != v['sha256']:
            raise ValueError(f'Voice/text identity mismatch in segment {sid}; regenerate affected voice.')
        duration = float(v['duration'])
        first = float(v['first_activity_s'])
        last = float(v['last_activity_s'])
        if not 0 <= first <= last <= duration + 0.001:
            raise ValueError(f'Invalid voice activity bounds: {sid}')
        is_last = index == len(segments) - 1
        gap_target = config.get('end_hold_seconds', 2.0) if is_last else config.get('gap_seconds', 0.42)
        next_head = 0 if is_last else float(by_id[str(segments[index + 1]['id'])]['first_activity_s'])
        added = max(0.0, gap_target - (duration - last) - next_head)
        frames = math.ceil((duration + added) * fps - 1e-8)
        end = cursor + frames / fps
        row = {'segment_id': sid, 'start': cursor, 'voice_end': cursor + duration,
               'end': end, 'duration': frames / fps, 'frames': frames,
               'audio_path': str(path.relative_to(root)).replace(os.sep, '/'),
               'first_activity_s': first, 'last_activity_s': last}
        timeline.append(row)
        observed = alignment[sid]
        local_cues = observed['cues']
        compact = lambda text: ''.join(text.split())
        if compact(''.join(c['zh'] for c in local_cues)) != compact(segment['zh']):
            raise ValueError(f'Captions must preserve locked Chinese text including punctuation: {sid}')
        previous_end = 0.0
        for number, cue in enumerate(local_cues):
            start, finish = float(cue['start']), float(cue['end'])
            if not (0 <= start < finish <= duration + 0.001) or start < previous_end - 0.001:
                raise ValueError(f'Invalid/overlapping cue boundaries: {sid}:{number}')
            if not cue.get('evidence'):
                raise ValueError(f'Record the real timing evidence for cue: {sid}:{number}')
            zh_lines, zh_size = wrap(cue['zh'], regular, 'zh')
            en_lines, en_size = wrap(cue['en'], regular, 'en')
            cues.append({'segment_id': sid, 'start': cursor + start, 'end': cursor + finish,
                         'local_start': start, 'local_end': finish, 'zh': cue['zh'], 'en': cue['en'],
                         'zh_lines': zh_lines, 'en_lines': en_lines, 'zh_size': zh_size,
                         'en_size': en_size, 'evidence': cue['evidence']})
            previous_end = finish
        for name, event in observed.get('events', {}).items():
            if not isinstance(event, dict) or not event.get('evidence') or not 0 <= float(event['time']) <= duration:
                raise ValueError(f'Animation event needs a measured local time and evidence: {sid}/{name}')
        cursor = end
    write(root / 'timeline.json', timeline)
    write(root / 'caption_timing.json', cues)
    delivery = root / 'delivery'
    delivery.mkdir(exist_ok=True)
    lines = []
    for i, cue in enumerate(cues, 1):
        lines.append(f'{i}\n{timestamp(cue["start"])} --> {timestamp(cue["end"])}\n' + '\n'.join(cue['zh_lines'] + cue['en_lines']))
    (delivery / 'subtitles.srt').write_text('\n\n'.join(lines) + '\n', encoding='utf-8')
    (delivery / 'description.txt').write_text(episode.get('description', '').strip() + '\n', encoding='utf-8')
    if (root / 'sources.md').exists():
        (delivery / 'sources.md').write_bytes((root / 'sources.md').read_bytes())
    return timeline, cues, alignment


def load_scenes(root, config):
    sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location('episode_scenes', root / 'scenes.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, 'art') and hasattr(module.art, 'configure_fonts'):
        module.art.configure_fonts(inside(root, config['font_regular']), inside(root, config['font_bold']))
    return module


def make_frame(module, segment, row, local, cues, alignment, ctx):
    events = {key: float(value['time']) for key, value in alignment[str(segment['id'])].get('events', {}).items()}
    im = module.frame(segment, local, row['duration'], events, ctx)
    if not isinstance(im, Image.Image) or im.size != (1080, 1920):
        raise ValueError('scenes.frame must return a 1080x1920 PIL image.')
    im = im.convert('RGB')
    cue = next((c for c in cues if c['segment_id'] == str(segment['id']) and c['local_start'] <= local < c['local_end']), None)
    if cue:
        draw = ImageDraw.Draw(im)
        y = 1420
        for key, size_key, colour, spacing in [('zh_lines', 'zh_size', '#243E35', 54), ('en_lines', 'en_size', '#4F6359', 38)]:
            font = ImageFont.truetype(str(ctx['font_regular']), cue[size_key])
            for line in cue[key]:
                bbox = draw.textbbox((540, y), line, font=font, anchor='mt')
                if bbox[0] < 75 or bbox[2] > 1005 or bbox[3] > 1660:
                    raise ValueError(f'Caption outside safe band: {line}')
                draw.text((540, y), line, font=font, fill=colour, anchor='mt')
                y += spacing
            y += 8
    return im


def source_key(root, episode, config, timeline, cues, alignment):
    files = {}
    for p in sorted(root.rglob('*.py')):
        if not any(part in {'.venv', 'models', '__pycache__'} for part in p.relative_to(root).parts):
            files[p.relative_to(root).as_posix()] = sha(p)
    for p in sorted((root / 'assets').rglob('*')):
        if p.is_file():
            files[p.relative_to(root).as_posix()] = sha(p)
    data = [episode, config, timeline, cues, alignment, files]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def render(root, module, episode, config, timeline, cues, alignment, ctx, samples=False):
    outdir = root / ('frames' if samples else 'rendered')
    outdir.mkdir(exist_ok=True)
    key = source_key(root, episode, config, timeline, cues, alignment)
    ffmpeg = os.environ.get('FFMPEG', config.get('ffmpeg', 'ffmpeg'))
    for segment, row in zip(episode['segments'], timeline):
        sid = str(segment['id'])
        if samples:
            for j, t in enumerate([0.0, row['duration'] * 0.3, row['duration'] * 0.65, max(0, row['duration'] - 0.1)]):
                make_frame(module, segment, row, t, cues, alignment, ctx).save(outdir / f'{sid}-{j}.png')
            continue
        target = outdir / f'{sid}.mp4'
        receipt = outdir / f'{sid}.json'
        if target.exists() and receipt.exists():
            previous = read(receipt)
            if previous.get('source_key') == key and previous.get('sha256') == sha(target):
                print(f'Reusing scene {sid}', flush=True)
                continue
        temp = outdir / f'{sid}.partial.mp4'
        command = [ffmpeg, '-nostdin', '-y', '-v', 'warning', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                   '-s', '1080x1920', '-r', '24', '-i', '-', '-an', '-c:v', 'libx264',
                   '-preset', 'veryfast', '-threads', '2', '-crf', '18', '-pix_fmt', 'yuv420p',
                   '-movflags', '+faststart', str(temp)]
        process = subprocess.Popen(command, stdin=subprocess.PIPE)
        try:
            for index in range(row['frames']):
                image = make_frame(module, segment, row, index / 24, cues, alignment, ctx)
                process.stdin.write(image.tobytes())
            process.stdin.close()
            if process.wait() != 0:
                raise RuntimeError(f'FFmpeg rendering failed: {sid}')
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if temp.exists():
                temp.unlink()
            raise
        temp.replace(target)
        write(receipt, {'source_key': key, 'sha256': sha(target), 'frames': row['frames']})
        print(f'Rendered {sid}: {row["frames"]} frames', flush=True)


def covers(root, module, episode, ctx):
    for name, size in [('cover-3x4.png', (1080, 1440)), ('cover-4x3.png', (1440, 1080))]:
        image = module.cover(size, episode, ctx)
        if not isinstance(image, Image.Image) or image.size != size:
            raise ValueError(f'Cover size mismatch: {name}')
        image.convert('RGB').save(root / 'delivery' / name)


def mux(root, config, timeline, source_identity):
    ffmpeg = os.environ.get('FFMPEG', config.get('ffmpeg', 'ffmpeg'))
    rendered = root / 'rendered'
    for row in timeline:
        clip = rendered / f"{row['segment_id']}.mp4"
        receipt = read(rendered / f"{row['segment_id']}.json")
        if receipt.get('source_key') != source_identity or receipt.get('sha256') != sha(clip):
            raise ValueError('A rendered scene is stale or altered; run the render stage again.')
    # Relative safe segment ids avoid platform-specific quoting in concat lists.
    listing = rendered / 'concat.txt'
    listing.write_text(''.join(f"file '{r['segment_id']}.mp4'\n" for r in timeline), encoding='utf-8')
    picture = rendered / 'picture.mp4'
    subprocess.run([ffmpeg, '-nostdin', '-y', '-v', 'warning', '-f', 'concat', '-safe', '1',
                    '-i', str(listing), '-c', 'copy', str(picture)], check=True)
    audio = inside(root, config.get('mix_path', 'mix.wav'))
    if not audio.is_file():
        raise FileNotFoundError('Run mix_audio.py before mux; config mix_path must point to the current mix.')
    report = read(audio.with_suffix('.report.json'))
    if report.get('output_sha256') != sha(audio):
        raise ValueError('Mix output does not match its report.')
    for item in report['inputs']:
        if sha(inside(root, item['path'])) != item['sha256']:
            raise ValueError('Mix source changed; generate a new mix before mux.')
    if not any(item['path'] == 'timeline.json' for item in report['inputs']):
        raise ValueError('Mix report must identify the current project timeline.')
    target = root / 'delivery' / 'main.mp4'
    subprocess.run([ffmpeg, '-nostdin', '-y', '-v', 'warning', '-i', str(picture), '-i', str(audio),
                    '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                    '-ar', '48000', '-movflags', '+faststart', '-t', str(timeline[-1]['end']), str(target)], check=True)
    write(root / 'qa' / 'mux.json', {'source_key': source_identity, 'mp4_sha256': sha(target),
                                    'mix_sha256': sha(audio), 'timeline_sha256': sha(root / 'timeline.json')})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('stage', choices=['prepare', 'samples', 'render', 'covers', 'mux'])
    a = p.parse_args()
    root = a.project.resolve()
    episode, config = read(root / 'episode.json'), read(root / 'config.json')
    timeline, cues, alignment = prepare(root, episode, config)
    if a.stage == 'prepare':
        return
    if a.stage == 'mux':
        mux(root, config, timeline, source_key(root, episode, config, timeline, cues, alignment))
        return
    module = load_scenes(root, config)
    ctx = {'project': root, 'config': config, 'font_regular': inside(root, config['font_regular']),
           'font_bold': inside(root, config['font_bold'])}
    if a.stage == 'covers':
        covers(root, module, episode, ctx)
    else:
        render(root, module, episode, config, timeline, cues, alignment, ctx, samples=a.stage == 'samples')


if __name__ == '__main__':
    main()
