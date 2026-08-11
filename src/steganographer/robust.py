"""
Hide a short message so it survives the image being re-saved as JPEG, the
way chat apps and social networks re-compress everything they're sent.

lsb and endian mode both die the moment an image is recompressed: JPEG
throws away exactly the low-order detail they hide in. This mode instead
nudges a single mid-frequency DCT coefficient of each 8x8 luma block to an
even or odd multiple of a step (quantization index modulation), the same
value JPEG's own quantiser rounds to and preserves. The bit is read back
by looking at which multiple the coefficient landed on.

The trade-off is capacity: one bit per 8x8 block, so a 512x512 image
carries about 500 bytes before error correction, a few KB for a large
photo. This is a low-capacity, high-durability mode for a short message,
a URL, a key fingerprint or a signature -- not a general file, and not a
replacement for lsb mode.

Measured (see tests/test_robust.py): at step 16 it comes through five
rounds of JPEG recompression at quality 40-90 with 4:2:0 chroma
subsampling at under 1% bit error, invisibly (PSNR ~41 dB). Reed-Solomon
(see ``fec``) mops up that <1%. It does NOT survive resizing, cropping or
rotation -- those move the 8x8 grid it's aligned to -- so it's for
re-compression at the same dimensions, which is what sharing a photo
around usually does to it.

Layout, as a stream of bits in block raster order (one bit per block):

    fec(magic (4) || blob length (4))        -- fixed size, the header
    fec(flags/name/data, maybe encrypted)    -- the blob, header gives length

The header is a fixed-size Reed-Solomon block so the reader knows how many
blocks to take for the blob without trusting anything unprotected.
"""

from pathlib import Path

import numpy as np
from PIL import Image

from . import core, crypto, fec
from .errors import CapacityError, SteganographerError

BLOCK = 8
COEF = (2, 2)  # mid-frequency: survives quantisation, still imperceptible
STEP = 16  # QIM step; 16 clears JPEG quality 40+ with room to spare
PARITY = fec.ROBUST_PARITY

MAGIC_PLAIN = 0x304A5047  # "0JPG"
MAGIC_ENCRYPTED = 0x314A5047  # "1JPG"
_MAGICS = {MAGIC_PLAIN: False, MAGIC_ENCRYPTED: True}
MAGIC_SIZE = 4
LENGTH_SIZE = 4
HEADER_SIZE = MAGIC_SIZE + LENGTH_SIZE

# orthonormal 8x8 DCT-II basis; the 2D transform is M @ block @ M.T
_k = np.arange(BLOCK)
_M = np.sqrt(2.0 / BLOCK) * np.cos(np.pi * (2 * _k[None, :] + 1) * _k[:, None] / (2 * BLOCK))
_M[0, :] /= np.sqrt(2)


def _dct2(block: np.ndarray) -> np.ndarray:
    return _M @ block @ _M.T


def _idct2(coeffs: np.ndarray) -> np.ndarray:
    return _M.T @ coeffs @ _M


def _luma(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("YCbCr")).astype(np.float64)


def _block_count(width: int, height: int) -> int:
    return (height // BLOCK) * (width // BLOCK)


def robust_capacity(width: int, height: int) -> int:
    """
    Rough largest unencrypted file (bytes, not counting its name) this image
    can carry in robust mode. A password and a stored filename both eat into
    it. Conservative -- ``hide_robust`` raises ``CapacityError`` for the
    exact limit.
    """
    blocks = _block_count(width, height)
    header_blocks = fec.encoded_size(HEADER_SIZE, PARITY) * 8
    blob_bytes = max((blocks - header_blocks) // 8, 0)
    body = blob_bytes * (fec.BLOCK_SIZE - PARITY) // fec.BLOCK_SIZE  # undo parity overhead
    return max(body - core.FLAGS_SIZE - core.NAME_LENGTH_SIZE, 0)


def _to_bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def _from_bits(bits: np.ndarray) -> bytes:
    return np.packbits(bits).tobytes()


def _write_bits(luma: np.ndarray, bits: np.ndarray, start_block: int) -> None:
    h, w = luma.shape
    per_row = w // BLOCK
    for i, bit in enumerate(bits):
        b = start_block + i
        by, bx = (b // per_row) * BLOCK, (b % per_row) * BLOCK
        block = luma[by : by + BLOCK, bx : bx + BLOCK]
        coeffs = _dct2(block)
        q = round(coeffs[COEF] / STEP)
        if q % 2 != bit:
            q += 1
        coeffs[COEF] = q * STEP
        luma[by : by + BLOCK, bx : bx + BLOCK] = _idct2(coeffs)


def _read_bits(luma: np.ndarray, count: int, start_block: int) -> np.ndarray:
    h, w = luma.shape
    per_row = w // BLOCK
    out = np.empty(count, dtype=np.uint8)
    for i in range(count):
        b = start_block + i
        by, bx = (b // per_row) * BLOCK, (b % per_row) * BLOCK
        coeffs = _dct2(luma[by : by + BLOCK, bx : bx + BLOCK])
        out[i] = int(round(coeffs[COEF] / STEP)) % 2
    return out


def hide_robust(
    image_path: core.PathLike,
    data: bytes,
    output_path: core.PathLike | None = None,
    *,
    password: str | None = None,
    filename: str | None = None,
) -> Path:
    """
    Hide ``data`` in ``image_path`` so it survives JPEG recompression, and
    write the result (a lossless PNG carrying the pattern) to ``output_path``.
    Raises ``CapacityError`` if the file is too big for the image.
    """
    output_path = Path(output_path) if output_path else core.default_output_path(image_path, "lsb")

    body = core._pack(core.safe_name(filename) if filename else None, data)
    magic = MAGIC_PLAIN
    if password:
        body = crypto.encrypt(body, password)
        magic = MAGIC_ENCRYPTED

    blob = fec.encode(body, PARITY)
    header = fec.encode(magic.to_bytes(MAGIC_SIZE, "big") + len(blob).to_bytes(LENGTH_SIZE, "big"), PARITY)

    with Image.open(image_path) as image:
        ycc = _luma(image)
    blocks = _block_count(ycc.shape[1], ycc.shape[0])
    needed = (len(header) + len(blob)) * 8
    if needed > blocks:
        raise CapacityError(
            f"robust mode needs {needed} blocks but this image only has {blocks}, use a bigger image or a smaller file"
        )

    luma = ycc[:, :, 0]
    _write_bits(luma, _to_bits(header), 0)
    _write_bits(luma, _to_bits(blob), len(header) * 8)
    ycc[:, :, 0] = np.clip(np.round(luma), 0, 255)

    rgb = np.asarray(Image.fromarray(ycc.astype(np.uint8), "YCbCr").convert("RGB"))
    Image.fromarray(rgb).save(output_path)
    return output_path


def reveal_robust(image_path: core.PathLike, *, password: str | None = None) -> core.Revealed | None:
    """
    Return the file hidden in ``image_path`` with robust mode, or None if
    there isn't one. Raises ``DecryptionError`` for a wrong password on an
    encrypted one.
    """
    with Image.open(image_path) as image:
        luma = _luma(image)[:, :, 0]
    blocks = _block_count(luma.shape[1], luma.shape[0])

    header_bytes = fec.encoded_size(HEADER_SIZE, PARITY)
    if header_bytes * 8 > blocks:
        return None
    try:
        header = fec.decode(_from_bits(_read_bits(luma, header_bytes * 8, 0)), PARITY)
    except fec.FecError:
        return None

    magic = int.from_bytes(header[:MAGIC_SIZE], "big")
    if magic not in _MAGICS:
        return None
    blob_len = int.from_bytes(header[MAGIC_SIZE:HEADER_SIZE], "big")
    if (header_bytes + blob_len) * 8 > blocks:
        return None

    try:
        blob = _from_bits(_read_bits(luma, blob_len * 8, header_bytes * 8))
        body = fec.decode(blob, PARITY)
    except fec.FecError:
        return None

    if _MAGICS[magic]:
        body = crypto.decrypt(body, password or "")
    try:
        return core._unpack(body)
    except IndexError:
        raise SteganographerError("the hidden data is corrupted") from None
