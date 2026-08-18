from PIL import Image, ImageDraw
from random import choices


def _install_pillow_captcha_compat():
    """Restore the Pillow API expected by the legacy captcha package."""

    if hasattr(ImageDraw.ImageDraw, "textsize"):
        return

    def textsize(self, text, font=None, *args, **kwargs):
        left, top, right, bottom = self.textbbox(
            (0, 0),
            text,
            font=font,
            *args,
            **kwargs,
        )
        width = max(1, right - left)
        height = bottom - top
        if height <= 0 and font is not None:
            _, line_top, _, line_bottom = self.textbbox(
                (0, 0),
                "Ag",
                font=font,
                *args,
                **kwargs,
            )
            height = line_bottom - line_top
        return width, max(1, height)

    ImageDraw.ImageDraw.textsize = textsize


_install_pillow_captcha_compat()

from captcha.image import ImageCaptcha


def gen_captcha(content='2345689abcdefghijklmnpqrstuvwxyzABCDEFGHIJKLMNPQRSTUVWXYZ'):
    """ 生成验证码 """
    image = ImageCaptcha()
    # 获取字符串
    captcha_text = "".join(choices(content, k=4)).lower()
    # 生成图像
    captcha_image = Image.open(image.generate(captcha_text))
    return captcha_text, captcha_image
