"""Small working scene adapter to extend with each episode's original direction.

Use the frame/cover interface and drawing primitives; do not turn every topic
into this desk illustration. Product scenes may use captured UI, interactive prototypes or original UI animation; describe the actual form accurately.
"""
from PIL import Image, ImageDraw, ImageFont
import paper_art as art


def frame(segment, local_seconds, duration, events, context):
    """Draw a caption-free frame. Event times are measured local seconds."""
    im = art.background((1080, 1920)).copy()
    canvas = art.C(im)
    visual = segment.get('visual', {})
    kind = visual.get('kind')
    if kind != 'desk-example':
        raise ValueError(f'Author the scene for visual.kind={kind!r} in scenes.py.')
    # A working demonstration: a paper is gently set down beside a cup.
    # Select this example explicitly; add topic-specific functions for real episodes.
    event = events.get('place_paper', 0.0)
    progress = art.ease((local_seconds - event) / 0.65)
    art.desk(canvas, local_seconds)
    art.mug(canvas, 745, 790, 0.85, steam=True)
    art.paper(canvas, 340, 740 - 70 * (1 - progress), 245, 310, title=None, lines=5)
    art.plant(canvas, 195, 635, 0.8)
    return im


def title_lines(text, font_path, max_width, initial_size):
    draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    for size in range(initial_size, 31, -2):
        font = ImageFont.truetype(str(font_path), size)
        if draw.textlength(text, font=font) <= max_width:
            return [text], font
        candidates = [(text[:i], text[i:]) for i in range(1, len(text))]
        fits = [pair for pair in candidates if max(draw.textlength(s, font=font) for s in pair) <= max_width]
        if fits:
            pair = min(fits, key=lambda pair: abs(draw.textlength(pair[0], font=font) - draw.textlength(pair[1], font=font)))
            return list(pair), font
    raise ValueError('Shorten cover_title so the cover remains readable.')


def cover(size, episode, context):
    """Independent landscape/portrait composition, to adapt with the episode's main prop."""
    w, h = size
    im = art.background(size).copy()
    draw = ImageDraw.Draw(im)
    landscape = w > h
    regular, bold = context['font_regular'], context['font_bold']
    label_font = ImageFont.truetype(str(regular), 28)
    draw.text((w * 0.12, h * 0.12), '纸间日常 · Paper Days', font=label_font, fill=art.SOFT)
    lines, heading_font = title_lines(episode.get('cover_title', episode['title']), bold, w * 0.76, 74 if landscape else 72)
    y = h * 0.23
    for line in lines:
        draw.text((w / 2, y), line, font=heading_font, fill=art.INK, anchor='mt')
        y += heading_font.size * 1.35
    subtitle = episode.get('cover_subtitle', '')
    if subtitle:
        if draw.textlength(subtitle, font=label_font) > w * 0.76:
            raise ValueError('Shorten cover_subtitle to fit the safe region.')
        draw.text((w / 2, y + 12), subtitle, font=label_font, fill=art.SOFT, anchor='mt')
    c = art.C(im, scale=1.0 if landscape else 1.12, ox=w * 0.35, oy=h * 0.58)
    art.paper(c, 0, 0, 235, 270, title=None, lines=5)
    art.mug(c, 260, 125, 0.8, steam=True)
    return im
