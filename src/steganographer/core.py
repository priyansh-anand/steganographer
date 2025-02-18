"""
Hide files inside images, and get them back out.

Two modes are supported:

lsb
    The payload is written into the 2 least significant bits of every
    R, G and B channel, starting from the top left pixel and going row by
    row. Each pixel carries 6 bits. The alpha channel of transparent images
    is left untouched. The image has to be saved losslessly (PNG, BMP or
    TIFF), otherwise the hidden bits are destroyed.

endian
    The payload is appended after the end of the image file. Image
    viewers stop reading at the end of the image data and ignore it, so it
    works with any format, including JPEG, but it is trivial to spot with
    a hex editor. Always use a password with this mode.

Layout of the hidden data::

    lsb     magic (4) || length (8) || payload
    endian  <original image> || payload || length (8) || magic (4)

All integers are big endian. The magic number says which mode and which
encryption scheme was used, see ``Format``.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import numpy as np
from PIL import Image

from . import crypto
from .errors import CapacityError, NoHiddenDataError

PathLike = Union[str, Path]

MAGIC_SIZE = 4
LENGTH_SIZE = 8
HEADER_SIZE = MAGIC_SIZE + LENGTH_SIZE

LOSSLESS_SUFFIXES = {".png", ".bmp", ".tif", ".tiff"}


@dataclass(frozen=True)
class Format:
    magic: int
    mode: str
    encrypted: bool
    legacy: bool = False


FORMATS = [
    Format(0xDEADC0DE, "lsb", encrypted=False),
    Format(0x1337BEEF, "lsb", encrypted=True),
    Format(0x1337C0DE, "lsb", encrypted=True, legacy=True),
    Format(0x5AFEC0DE, "endian", encrypted=False),
    Format(0xBABEBEEF, "endian", encrypted=True),
    Format(0xBABEC0DE, "endian", encrypted=True, legacy=True),
]
_BY_MAGIC = {f.magic: f for f in FORMATS}


def _format_for(mode: str, encrypted: bool) -> Format:
    for f in FORMATS:
        if f.mode == mode and f.encrypted == encrypted and not f.legacy:
            return f
    raise ValueError(f"unknown hiding mode: {mode!r}")


@dataclass(frozen=True)
class HiddenFile:
    """What ``inspect`` found inside an image."""

    format: Format
    size: int

    @property
    def mode(self) -> str:
        return self.format.mode

    @property
    def encrypted(self) -> bool:
        return self.format.encrypted


def _split(data: bytes) -> np.ndarray:
    """Split every byte into four 2 bit values, most significant first."""
    d = np.frombuffer(data, dtype=np.uint8)
    return np.stack([(d >> 6) & 3, (d >> 4) & 3, (d >> 2) & 3, d & 3], axis=1).reshape(-1)


def _join(crumbs: np.ndarray) -> bytes:
    """Inverse of ``_split``."""
    c = crumbs[: len(crumbs) - len(crumbs) % 4].reshape(-1, 4)
    return (c[:, 0] << 6 | c[:, 1] << 4 | c[:, 2] << 2 | c[:, 3]).astype(np.uint8).tobytes()


def _load(path: PathLike) -> Image.Image:
    """Open an image as RGB, or as RGBA if it has any kind of transparency."""
    with Image.open(path) as image:
        transparent = "A" in image.getbands() or "transparency" in image.info
        return image.convert("RGBA" if transparent else "RGB")


def _color_channels(pixels: np.ndarray) -> np.ndarray:
    """The R, G and B values of every pixel, row by row. Alpha is never touched."""
    return pixels[..., :3].reshape(-1)


def lsb_capacity(width: int, height: int) -> int:
    """Largest payload (in bytes) that fits in a ``width`` x ``height`` image."""
    return max(width * height * 6 // 8 - HEADER_SIZE, 0)


def capacity(image_path: PathLike) -> int:
    """Largest payload (in bytes) that can be hidden in this image with lsb mode."""
    with Image.open(image_path) as image:
        return lsb_capacity(*image.size)


def default_output_path(image_path: PathLike, mode: str) -> Path:
    image_path = Path(image_path)
    suffix = ".png" if mode == "lsb" else image_path.suffix
    return image_path.with_name(f"{image_path.stem}_steg0{suffix}")


def hide(
    image_path: PathLike,
    data: bytes,
    output_path: Optional[PathLike] = None,
    *,
    password: Optional[str] = None,
    mode: str = "endian",
) -> Path:
    """
    Hide ``data`` inside the image at ``image_path`` and write the result to
    ``output_path``. Returns the path that was written.
    """
    fmt = _format_for(mode, encrypted=bool(password))
    output_path = Path(output_path) if output_path else default_output_path(image_path, mode)

    if password:
        data = crypto.encrypt(data, password)

    if mode == "lsb":
        if output_path.suffix.lower() not in LOSSLESS_SUFFIXES:
            raise ValueError(
                f"lsb mode needs a lossless output format ({', '.join(sorted(LOSSLESS_SUFFIXES))}),"
                f" got {output_path.name}"
            )

        image = _load(image_path)
        available = lsb_capacity(*image.size)
        if len(data) > available:
            raise CapacityError(
                f"{len(data)} bytes do not fit in a {image.size[0]}x{image.size[1]} image,"
                f" the maximum is {available} bytes"
            )

        header = fmt.magic.to_bytes(MAGIC_SIZE, "big") + len(data).to_bytes(LENGTH_SIZE, "big")
        crumbs = _split(header + data)

        pixels = np.array(image)
        channels = _color_channels(pixels)
        channels[: len(crumbs)] = channels[: len(crumbs)] & 0b11111100 | crumbs
        pixels[..., :3] = channels.reshape(pixels.shape[:2] + (3,))
        Image.fromarray(pixels).save(output_path)
    else:
        cover = Path(image_path).read_bytes()
        trailer = len(data).to_bytes(LENGTH_SIZE, "big") + fmt.magic.to_bytes(MAGIC_SIZE, "big")
        output_path.write_bytes(cover + data + trailer)

    return output_path


def _read_endian(raw: bytes) -> Optional[tuple]:
    if len(raw) < HEADER_SIZE:
        return None
    fmt = _BY_MAGIC.get(int.from_bytes(raw[-MAGIC_SIZE:], "big"))
    if fmt is None or fmt.mode != "endian":
        return None
    size = int.from_bytes(raw[-HEADER_SIZE:-MAGIC_SIZE], "big")
    if size > len(raw) - HEADER_SIZE:
        return None
    return fmt, raw[-HEADER_SIZE - size : -HEADER_SIZE]


def _read_lsb(image_path: PathLike) -> Optional[tuple]:
    try:
        image = _load(image_path)
    except OSError:
        return None

    channels = _color_channels(np.asarray(image))
    header = _join(channels[: HEADER_SIZE * 4] & 3)
    if len(header) < HEADER_SIZE:
        return None
    fmt = _BY_MAGIC.get(int.from_bytes(header[:MAGIC_SIZE], "big"))
    if fmt is None or fmt.mode != "lsb":
        return None
    size = int.from_bytes(header[MAGIC_SIZE:], "big")
    if size > lsb_capacity(*image.size):
        return None

    end = (HEADER_SIZE + size) * 4
    return fmt, _join(channels[HEADER_SIZE * 4 : end] & 3)


def _read(image_path: PathLike) -> tuple:
    found = _read_endian(Path(image_path).read_bytes()) or _read_lsb(image_path)
    if found is None:
        raise NoHiddenDataError(f"no hidden file found in {image_path}")
    return found


def inspect(image_path: PathLike) -> Optional[HiddenFile]:
    """Describe what is hidden in the image, or return None if nothing is."""
    try:
        fmt, payload = _read(image_path)
    except NoHiddenDataError:
        return None
    return HiddenFile(fmt, len(payload))


def reveal(image_path: PathLike, *, password: Optional[str] = None) -> bytes:
    """Return the file hidden inside the image at ``image_path``."""
    fmt, payload = _read(image_path)
    if fmt.encrypted:
        payload = crypto.decrypt(payload, password or "", legacy=fmt.legacy)
    return payload
