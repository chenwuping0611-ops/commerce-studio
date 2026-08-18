import os
from random import choices, randint

from PIL import Image, ImageDraw, ImageFont


CAPTCHA_WIDTH = 160
CAPTCHA_HEIGHT = 60
CAPTCHA_FONT_SIZE = 36


def _load_captcha_font():
    """Load a readable font on both Windows and CentOS deployments."""

    candidates = [
        os.getenv("STUDIO_CAPTCHA_FONT"),
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, CAPTCHA_FONT_SIZE)

    try:
        return ImageFont.load_default(size=CAPTCHA_FONT_SIZE)
    except TypeError:
        return ImageFont.load_default()


def gen_captcha(content='2345689abcdefghijklmnpqrstuvwxyzABCDEFGHIJKLMNPQRSTUVWXYZ'):
    """Generate a readable four-character CAPTCHA image."""

    captcha_text = "".join(choices(content, k=4)).lower()
    image = Image.new("RGB", (CAPTCHA_WIDTH, CAPTCHA_HEIGHT), (248, 250, 252))
    draw = ImageDraw.Draw(image)

    # Keep interference light and draw it before the characters for readability.
    for _ in range(24):
        x = randint(0, CAPTCHA_WIDTH - 1)
        y = randint(0, CAPTCHA_HEIGHT - 1)
        draw.ellipse((x, y, x + 1, y + 1), fill=(177, 215, 202))
    for _ in range(2):
        points = [
            (randint(0, CAPTCHA_WIDTH // 3), randint(8, CAPTCHA_HEIGHT - 8)),
            (randint(CAPTCHA_WIDTH // 2, CAPTCHA_WIDTH), randint(8, CAPTCHA_HEIGHT - 8)),
        ]
        draw.line(points, fill=(166, 205, 191), width=1)

    font = _load_captcha_font()
    cell_width = CAPTCHA_WIDTH // len(captcha_text)
    text_color = (28, 126, 91)
    for index, character in enumerate(captcha_text):
        left, top, right, bottom = draw.textbbox((0, 0), character, font=font)
        glyph_width = right - left
        glyph_height = bottom - top
        x = index * cell_width + (cell_width - glyph_width) // 2 - left
        y = (CAPTCHA_HEIGHT - glyph_height) // 2 - top + randint(-2, 2)
        draw.text((x, y), character, font=font, fill=text_color)

    return captcha_text, image
