"""
Hide two files in the same lsb image under two different passwords: a
decoy you can hand over under pressure, and a real file that only shows
up for someone who has the real password. Works the same way a VeraCrypt
hidden volume does.

The decoy is written first, the real file second. Both use the normal
password-derived scatter order (see ``scatter``), and since the two
orders are independent, they land on some of the same pixels -- the real
file always wins those, because nothing is written after it. The decoy
is protected with Reed-Solomon parity (see ``fec``) so it survives that
damage as long as it stays under the correction bound.

Nothing here is probabilistic by the time you have the image: both
layers are read back and checked before anything is written to disk. If
the decoy wouldn't survive, ``hide_deniable`` raises instead of quietly
producing a file that might fail later, see the docstring on that
function for what to do about it.

The real layer is written with the ordinary ``core.hide``, so it is byte
for byte what a normal encrypted lsb hide produces -- there is nothing
that marks the image as carrying a second, deniable layer. The decoy
layer needs its own tiny on-disk format, since it has to describe its
own length without trusting anything that isn't itself protected:

    (magic (4) || blob length (4)) * MARKER_REPEATS || fec.encode(ciphertext)

The marker is read back byte by byte, majority vote across all
``MARKER_REPEATS`` copies, before anything else is trusted.
"""

import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from . import core, crypto, fec
from .errors import CapacityError, DecryptionError, SteganographerError

MARKER_MAGIC = 0x5DEC0940
MARKER_FIELD_SIZE = 8  # 4 byte magic + 4 byte blob length
MARKER_REPEATS = 15
MARKER_SIZE = MARKER_FIELD_SIZE * MARKER_REPEATS


def _build_marker(blob_length: int) -> bytes:
    if blob_length >= 2**32:
        raise CapacityError("the decoy file is too large for deniable hiding")
    field = MARKER_MAGIC.to_bytes(4, "big") + blob_length.to_bytes(4, "big")
    return field * MARKER_REPEATS


def _read_marker(marker: bytes) -> int | None:
    """Majority-votes each byte across the repeated copies. Returns the blob length, or None."""
    copies = [marker[i : i + MARKER_FIELD_SIZE] for i in range(0, len(marker), MARKER_FIELD_SIZE)]
    field = bytes(max(range(256), key=lambda b: sum(c[pos] == b for c in copies)) for pos in range(MARKER_FIELD_SIZE))
    if int.from_bytes(field[:4], "big") != MARKER_MAGIC:
        return None
    return int.from_bytes(field[4:], "big")


def _write_decoy(channels: np.ndarray, password: str, data: bytes, filename: str | None) -> None:
    packed = core._pack(core.safe_name(filename) if filename else None, data)
    blob = fec.encode(crypto.encrypt(packed, password))
    stream = _build_marker(len(blob)) + blob

    room = len(channels) // 4
    if len(stream) > room:
        raise CapacityError(
            f"the decoy needs {len(stream)} bytes but the image only has room for {room}, use a bigger image"
        )
    core._write_crumbs(channels, core._split(stream), core._order(password, channels))


def reveal_decoy(image_path: core.PathLike, password: str) -> tuple[str | None, bytes] | None:
    """
    Return ``(name, data)`` for the decoy layer of a deniable image, or
    None if this password doesn't open a decoy layer in it.
    """
    image = core._load(image_path)
    channels = core._color_channels(np.asarray(image))
    order = core._order(password, channels)
    room = len(channels) // 4

    marker_crumbs = MARKER_SIZE * 4
    if marker_crumbs > len(channels):
        return None
    blob_length = _read_marker(core._join(core._read_crumbs(channels, marker_crumbs, order)))
    if blob_length is None or MARKER_SIZE + blob_length > room:
        return None

    total_crumbs = (MARKER_SIZE + blob_length) * 4
    blob = core._join(core._read_crumbs(channels, total_crumbs, order)[marker_crumbs:])

    try:
        packed = crypto.decrypt(fec.decode(blob), password)
        name, data, _ = core._unpack(packed)
    except (fec.FecError, DecryptionError, IndexError):
        return None
    return name, data


def hide_deniable(
    image_path: core.PathLike,
    decoy_data: bytes,
    decoy_password: str,
    real_data: bytes,
    real_password: str,
    output_path: core.PathLike | None = None,
    *,
    decoy_filename: str | None = None,
    real_filename: str | None = None,
) -> Path:
    """
    Hide ``decoy_data`` and ``real_data`` in the same image, under
    ``decoy_password`` and ``real_password``. Extraction needs no special
    handling: ``reveal_decoy`` with the decoy password gets the decoy,
    and the ordinary ``core.reveal_file``/``reveal`` with the real
    password gets the real file, exactly like any other encrypted lsb
    image.

    Raises ``CapacityError`` if the decoy would not survive having the
    real file written on top of it -- try a bigger cover image, a
    smaller decoy or real file, or hide less data overall. This is
    checked before anything is written to disk, so a returned path is
    always fully readable with both passwords.
    """
    if decoy_password == real_password:
        raise ValueError("the decoy and real passwords must be different")

    output_path = Path(output_path) if output_path else core.default_output_path(image_path, "lsb")
    if output_path.suffix.lower() not in core.LOSSLESS_SUFFIXES:
        raise ValueError(
            f"lsb mode needs a lossless output format ({', '.join(sorted(core.LOSSLESS_SUFFIXES))}),"
            f" got {output_path.name}"
        )

    image = core._load(image_path)
    pixels = np.array(image)
    channels = core._color_channels(pixels)
    _write_decoy(channels, decoy_password, decoy_data, decoy_filename)

    pixels[..., :3] = channels.reshape(pixels.shape[:2] + (3,))
    # everything happens in a temp directory until both layers are confirmed
    # readable -- output_path is only ever touched by the final copy below,
    # so a refusal never leaves a broken (or partially written) file behind
    with tempfile.TemporaryDirectory() as tmp:
        decoy_only = Path(tmp) / f"decoy{output_path.suffix}"
        Image.fromarray(pixels).save(decoy_only)

        # this should always succeed, nothing has overwritten the decoy yet -- if
        # it doesn't, it's a bug here, not a matter of the two layers colliding
        if reveal_decoy(decoy_only, decoy_password) != (
            core.safe_name(decoy_filename) if decoy_filename else None,
            decoy_data,
        ):
            raise SteganographerError("internal error: could not read back the decoy layer right after writing it")

        both_layers = Path(tmp) / f"both{output_path.suffix}"
        core.hide(decoy_only, real_data, both_layers, password=real_password, mode="lsb", filename=real_filename)

        revealed = reveal_decoy(both_layers, decoy_password)
        if revealed is None or revealed[1] != decoy_data:
            raise CapacityError(
                "the decoy did not survive being written under the real file -- use a bigger cover image, "
                "a smaller decoy or real file, or hide less data overall"
            )

        output_path.write_bytes(both_layers.read_bytes())
    return output_path
