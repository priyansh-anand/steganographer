"""
Hide files inside images, and get them back out.

Two modes are supported:

lsb
    The payload is written into the 2 least significant bits of the R, G
    and B channels. Each pixel carries 6 bits. The alpha channel of
    transparent images is left untouched. The image has to be saved
    losslessly (PNG, BMP or TIFF), otherwise the hidden bits are destroyed.

    Without a password the channels are filled in order starting from the
    top left pixel. With a password the header and the data are spread over
    the whole image in an order that depends on the password (see
    ``scatter``), so the image doesn't show that anything is hidden unless
    you have the password.

endian
    The payload is appended after the end of the image file. Image
    viewers stop reading at the end of the image data and ignore it, so it
    works with any format, including JPEG, but it is trivial to spot with
    a hex editor. Always use a password with this mode.

Layout of the hidden data::

    lsb     magic (4) || length (8) || payload
    endian  <original image> || payload || length (8) || magic (4)

    payload = name length (2) || file name (utf-8) || file contents

The payload is encrypted as a whole when a password is used, so the file
name is only visible with the password. Images made by v3 and older store
just the file contents.

All integers are big endian. The magic number says which mode and which
encryption scheme was used, see ``Format``.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image

from . import crypto, scatter
from .errors import CapacityError, NoHiddenDataError

type PathLike = str | Path

MAGIC_SIZE = 4
LENGTH_SIZE = 8
HEADER_SIZE = MAGIC_SIZE + LENGTH_SIZE
NAME_LENGTH_SIZE = 2

LOSSLESS_SUFFIXES = {".png", ".bmp", ".tif", ".tiff"}


@dataclass(frozen=True)
class Format:
    magic: int
    mode: str
    encrypted: bool
    # made by v3 or older: no file name, and md5 as the encryption key
    legacy: bool = False

    @property
    def scattered(self) -> bool:
        return self.mode == "lsb" and self.encrypted and not self.legacy


FORMATS = [
    Format(0xDEADBEEF, "lsb", encrypted=False),
    Format(0x1337BEEF, "lsb", encrypted=True),
    Format(0x5AFEBEEF, "endian", encrypted=False),
    Format(0xBABEBEEF, "endian", encrypted=True),
    Format(0xDEADC0DE, "lsb", encrypted=False, legacy=True),
    Format(0x1337C0DE, "lsb", encrypted=True, legacy=True),
    Format(0x5AFEC0DE, "endian", encrypted=False, legacy=True),
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


class Revealed(NamedTuple):
    """A file taken out of an image. ``name`` is None if the image doesn't store one."""

    name: str | None
    data: bytes


def _pack(name: str | None, data: bytes) -> bytes:
    encoded = (name or "").encode()
    if len(encoded) >= 2 ** (8 * NAME_LENGTH_SIZE):
        raise ValueError("file name is too long")
    return len(encoded).to_bytes(NAME_LENGTH_SIZE, "big") + encoded + data


def _unpack(payload: bytes) -> Revealed:
    length = int.from_bytes(payload[:NAME_LENGTH_SIZE], "big")
    name = payload[NAME_LENGTH_SIZE : NAME_LENGTH_SIZE + length].decode(errors="replace")
    return Revealed(safe_name(name), payload[NAME_LENGTH_SIZE + length :])


def safe_name(name: str) -> str | None:
    """
    Strip any directories from a stored file name, so a crafted image can't
    make us write outside the current directory. Returns None if nothing
    usable is left.
    """
    name = name.replace("\\", "/").rsplit("/", 1)[-1].replace("\0", "").strip()
    if name in ("", ".", ".."):
        return None
    return name


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


def _order(password: str, channels: np.ndarray) -> scatter.Permutation:
    return scatter.Permutation(crypto.order_key(password, scatter.KEY_SIZE), len(channels))


def _write_crumbs(channels: np.ndarray, crumbs: np.ndarray, order: scatter.Permutation | None) -> None:
    if order is None:
        channels[: len(crumbs)] = channels[: len(crumbs)] & 0b11111100 | crumbs
        return
    for start, stop, positions in order.chunks(len(crumbs)):
        channels[positions] = channels[positions] & 0b11111100 | crumbs[start:stop]


def _read_crumbs(channels: np.ndarray, count: int, order: scatter.Permutation | None) -> np.ndarray:
    if order is None:
        return channels[:count] & 3
    out = np.empty(count, dtype=np.uint8)
    for start, stop, positions in order.chunks(count):
        out[start:stop] = channels[positions] & 3
    return out


def _lsb_room(width: int, height: int) -> int:
    """Bytes available for the payload in a ``width`` x ``height`` image."""
    return max(width * height * 6 // 8 - HEADER_SIZE, 0)


def lsb_capacity(width: int, height: int) -> int:
    """Largest unencrypted file (in bytes) that fits in a ``width`` x ``height`` image, not counting its name."""
    return max(_lsb_room(width, height) - NAME_LENGTH_SIZE, 0)


def capacity(image_path: PathLike) -> int:
    """
    Largest unencrypted file (in bytes) that can be hidden in this image with
    lsb mode. The file name, if stored, takes up room as well.
    """
    with Image.open(image_path) as image:
        return lsb_capacity(*image.size)


def default_output_path(image_path: PathLike, mode: str) -> Path:
    image_path = Path(image_path)
    suffix = ".png" if mode == "lsb" else image_path.suffix
    return image_path.with_name(f"{image_path.stem}_steg0{suffix}")


def hide(
    image_path: PathLike,
    data: bytes,
    output_path: PathLike | None = None,
    *,
    password: str | None = None,
    mode: str = "endian",
    filename: str | None = None,
) -> Path:
    """
    Hide ``data`` inside the image at ``image_path`` and write the result to
    ``output_path``. Returns the path that was written.

    ``filename`` is stored alongside the data, so ``reveal_file`` can give it
    back when extracting. Only the last part of the path is kept.
    """
    fmt = _format_for(mode, encrypted=bool(password))
    output_path = Path(output_path) if output_path else default_output_path(image_path, mode)

    data = _pack(safe_name(filename) if filename else None, data)
    if password:
        data = crypto.encrypt(data, password)

    if mode == "lsb":
        if output_path.suffix.lower() not in LOSSLESS_SUFFIXES:
            raise ValueError(
                f"lsb mode needs a lossless output format ({', '.join(sorted(LOSSLESS_SUFFIXES))}),"
                f" got {output_path.name}"
            )

        image = _load(image_path)
        available = _lsb_room(*image.size)
        if len(data) > available:
            raise CapacityError(
                f"the file needs {len(data)} bytes but a {image.size[0]}x{image.size[1]} image only has room"
                f" for {available}, use a bigger image"
            )

        header = fmt.magic.to_bytes(MAGIC_SIZE, "big") + len(data).to_bytes(LENGTH_SIZE, "big")
        crumbs = _split(header + data)

        pixels = np.array(image)
        channels = _color_channels(pixels)
        _write_crumbs(channels, crumbs, _order(password, channels) if fmt.scattered else None)
        pixels[..., :3] = channels.reshape(pixels.shape[:2] + (3,))
        Image.fromarray(pixels).save(output_path)
    else:
        cover = Path(image_path).read_bytes()
        trailer = len(data).to_bytes(LENGTH_SIZE, "big") + fmt.magic.to_bytes(MAGIC_SIZE, "big")
        output_path.write_bytes(cover + data + trailer)

    return output_path


def _read_endian(raw: bytes) -> tuple | None:
    if len(raw) < HEADER_SIZE:
        return None
    fmt = _BY_MAGIC.get(int.from_bytes(raw[-MAGIC_SIZE:], "big"))
    if fmt is None or fmt.mode != "endian":
        return None
    size = int.from_bytes(raw[-HEADER_SIZE:-MAGIC_SIZE], "big")
    if size > len(raw) - HEADER_SIZE:
        return None
    return fmt, raw[-HEADER_SIZE - size : -HEADER_SIZE]


def _read_lsb(channels: np.ndarray, room: int, order: scatter.Permutation | None) -> tuple | None:
    if len(channels) < HEADER_SIZE * 4:
        return None
    header = _join(_read_crumbs(channels, HEADER_SIZE * 4, order))
    fmt = _BY_MAGIC.get(int.from_bytes(header[:MAGIC_SIZE], "big"))
    if fmt is None or fmt.mode != "lsb" or fmt.scattered != (order is not None):
        return None
    size = int.from_bytes(header[MAGIC_SIZE:], "big")
    if size > room:
        return None

    crumbs = _read_crumbs(channels, (HEADER_SIZE + size) * 4, order)
    return fmt, _join(crumbs[HEADER_SIZE * 4 :])


def _read(image_path: PathLike, password: str | None) -> tuple:
    found = _read_endian(Path(image_path).read_bytes())
    if found is None:
        try:
            image = _load(image_path)
        except OSError:
            image = None
        if image is not None:
            channels = _color_channels(np.asarray(image))
            room = _lsb_room(*image.size)
            found = _read_lsb(channels, room, None)
            if found is None and password:
                found = _read_lsb(channels, room, _order(password, channels))

    if found is None:
        raise NoHiddenDataError(f"no hidden file found in {image_path}")
    return found


def inspect(image_path: PathLike, *, password: str | None = None) -> HiddenFile | None:
    """
    Describe what is hidden in the image, or return None if nothing is.

    Files hidden with lsb mode and a password can only be found with the
    right password.
    """
    try:
        fmt, payload = _read(image_path, password)
    except NoHiddenDataError:
        return None
    return HiddenFile(fmt, len(payload))


def reveal_file(image_path: PathLike, *, password: str | None = None) -> Revealed:
    """Return the name and contents of the file hidden in the image at ``image_path``."""
    fmt, payload = _read(image_path, password)
    if fmt.encrypted:
        payload = crypto.decrypt(payload, password or "", legacy=fmt.legacy)
    if fmt.legacy:
        return Revealed(None, payload)
    return _unpack(payload)


def reveal(image_path: PathLike, *, password: str | None = None) -> bytes:
    """Return the contents of the file hidden in the image at ``image_path``."""
    return reveal_file(image_path, password=password).data
