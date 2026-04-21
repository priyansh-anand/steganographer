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

    payload = flags (1) || name length (2) || file name (utf-8)
              || [signer public key (32) || signature (64)] || file contents

The signer's key and signature are only there if the ``signed`` flag is
set. The signature covers the name and the contents, see ``signing``.

The payload is encrypted as a whole when a password is used, so the file
name and the signer are only visible with the password. Images made by v3
and older store just the file contents.

All integers are big endian. The magic number says which mode and which
encryption scheme was used, see ``Format``.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import numpy as np
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from PIL import Image

from . import crypto, scatter, signing
from .adaptive import AdaptiveOrder
from .errors import CapacityError, NoHiddenDataError, SignatureError, SteganographerError

type PathLike = str | Path

MAGIC_SIZE = 4
LENGTH_SIZE = 8
HEADER_SIZE = MAGIC_SIZE + LENGTH_SIZE
FLAGS_SIZE = 1
NAME_LENGTH_SIZE = 2
SIGNED = 0b1

LOSSLESS_SUFFIXES = {".png", ".bmp", ".tif", ".tiff"}


@dataclass(frozen=True)
class Format:
    magic: int
    mode: str
    encrypted: bool
    # made by v3 or older: no file name, and md5 as the encryption key
    legacy: bool = False
    # busiest-region-first order instead of a uniform scatter, see adaptive.py
    adaptive: bool = False

    @property
    def scattered(self) -> bool:
        return self.mode == "lsb" and self.encrypted and not self.legacy


FORMATS = [
    Format(0xDEADBEEF, "lsb", encrypted=False),
    Format(0x1337BEEF, "lsb", encrypted=True),
    Format(0xADA97EED, "lsb", encrypted=True, adaptive=True),
    Format(0x5AFEBEEF, "endian", encrypted=False),
    Format(0xBABEBEEF, "endian", encrypted=True),
    Format(0xDEADC0DE, "lsb", encrypted=False, legacy=True),
    Format(0x1337C0DE, "lsb", encrypted=True, legacy=True),
    Format(0x5AFEC0DE, "endian", encrypted=False, legacy=True),
    Format(0xBABEC0DE, "endian", encrypted=True, legacy=True),
]
_BY_MAGIC = {f.magic: f for f in FORMATS}


def _format_for(mode: str, encrypted: bool, adaptive: bool = False) -> Format:
    for f in FORMATS:
        if f.mode == mode and f.encrypted == encrypted and f.adaptive == adaptive and not f.legacy:
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
    """
    A file taken out of an image. ``name`` is None if the image doesn't
    store one. ``signer`` is the raw public key of whoever signed it, the
    signature has already been checked.
    """

    name: str | None
    data: bytes
    signer: bytes | None = None


def _pack(name: str | None, data: bytes, sign_with: Ed25519PrivateKey | None = None) -> bytes:
    encoded = (name or "").encode()
    if len(encoded) >= 2 ** (8 * NAME_LENGTH_SIZE):
        raise ValueError("file name is too long")
    named = len(encoded).to_bytes(NAME_LENGTH_SIZE, "big") + encoded

    if sign_with is None:
        return bytes([0]) + named + data
    return bytes([SIGNED]) + named + signing.sign(sign_with, named + data) + data


def _unpack(payload: bytes) -> Revealed:
    flags, rest = payload[0], payload[FLAGS_SIZE:]
    length = int.from_bytes(rest[:NAME_LENGTH_SIZE], "big")
    named, rest = rest[: NAME_LENGTH_SIZE + length], rest[NAME_LENGTH_SIZE + length :]
    name = safe_name(named[NAME_LENGTH_SIZE:].decode(errors="replace"))

    if not flags & SIGNED:
        return Revealed(name, rest)

    public_key = rest[: signing.PUBLIC_KEY_SIZE]
    signature = rest[signing.PUBLIC_KEY_SIZE : signing.PUBLIC_KEY_SIZE + signing.SIGNATURE_SIZE]
    data = rest[signing.PUBLIC_KEY_SIZE + signing.SIGNATURE_SIZE :]
    signing.verify(public_key, signature, named + data)
    return Revealed(name, data, public_key)


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
    return max(_lsb_room(width, height) - FLAGS_SIZE - NAME_LENGTH_SIZE, 0)


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
    sign_with: Ed25519PrivateKey | None = None,
    adaptive: bool = False,
) -> Path:
    """
    Hide ``data`` inside the image at ``image_path`` and write the result to
    ``output_path``. Returns the path that was written.

    ``filename`` is stored alongside the data, so ``reveal_file`` can give it
    back when extracting. Only the last part of the path is kept.

    ``sign_with`` signs the name and contents with an Ed25519 key (see
    ``signing.load_private_key``).

    ``adaptive`` (lsb mode with a password only) fills the visually busiest
    parts of the image first instead of scattering uniformly, see
    ``adaptive.py`` and its trade-offs.
    """
    if adaptive and (mode != "lsb" or not password):
        raise ValueError("adaptive placement needs lsb mode and a password")
    fmt = _format_for(mode, encrypted=bool(password), adaptive=adaptive)
    output_path = Path(output_path) if output_path else default_output_path(image_path, mode)

    data = _pack(safe_name(filename) if filename else None, data, sign_with)
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
        if fmt.adaptive:
            order = AdaptiveOrder(password, pixels)
        elif fmt.scattered:
            order = _order(password, channels)
        else:
            order = None
        _write_crumbs(channels, crumbs, order)
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
            pixels = np.asarray(image)
            channels = _color_channels(pixels)
            room = _lsb_room(*image.size)
            found = _read_lsb(channels, room, None)
            if found is None and password:
                found = _read_lsb(channels, room, _order(password, channels))
            if found is None and password:
                found = _read_lsb(channels, room, AdaptiveOrder(password, pixels))

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


def reveal_file(
    image_path: PathLike,
    *,
    password: str | None = None,
    signed_by: Ed25519PublicKey | None = None,
) -> Revealed:
    """
    Return the name and contents of the file hidden in the image at
    ``image_path``.

    If the file is signed the signature is always checked, and
    ``SignatureError`` is raised if it doesn't match. Pass ``signed_by`` to
    also require that it was signed with that key.
    """
    fmt, payload = _read(image_path, password)
    if fmt.encrypted:
        payload = crypto.decrypt(payload, password or "", legacy=fmt.legacy)
    if fmt.legacy:
        revealed = Revealed(None, payload)
    else:
        try:
            revealed = _unpack(payload)
        except IndexError:
            raise SteganographerError("the hidden data is corrupted") from None

    if signed_by is not None:
        if revealed.signer is None:
            raise SignatureError("the file is not signed")
        if revealed.signer != signing.raw(signed_by):
            raise SignatureError(f"the file is signed by a different key ({signing.fingerprint(revealed.signer)})")
    return revealed


def reveal(image_path: PathLike, *, password: str | None = None) -> bytes:
    """Return the contents of the file hidden in the image at ``image_path``."""
    return reveal_file(image_path, password=password).data
