"""The customer PDF's logo (S26 decision 1): a PNG or a JPEG, told by its bytes and opened, never an SVG."""

import io

import pytest
from PIL import Image

from konboro.services import document_template as dt


def image(fmt: str, size: tuple[int, int] = (120, 40)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 60, 40)).save(out, fmt)
    return out.getvalue()


def test_a_png_or_a_jpeg_is_a_logo() -> None:
    assert dt.logo_kind(image("PNG")) == ("image/png", "png")
    assert dt.logo_kind(image("JPEG")) == ("image/jpeg", "jpg")


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "logo_type"),
        (image("GIF"), "logo_type"),
        (b"\x89PNG\r\n\x1a\n" + b"not really a png", "logo_type"),  # the magic alone is not enough
        (b"\xff\xd8\xff" + b"\0" * (dt.LOGO_MAX_BYTES + 1), "logo_too_large"),
        (image("PNG", (dt.LOGO_MAX_PX + 1, 10)), "logo_too_large"),
    ],
    ids=["svg", "gif", "fake-png", "over-1mb", "over-4000px"],
)
def test_anything_else_is_refused(data: bytes, code: str) -> None:
    with pytest.raises(dt.LogoError) as e:
        dt.logo_kind(data)
    assert e.value.code == code
