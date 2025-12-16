"""
Reed-Solomon forward error correction, used by ``deniable`` to let the
decoy layer of a deniable image survive having some of its bytes
overwritten by the real layer written on top of it.

``reedsolo`` already splits long messages into 255 byte blocks and puts
them back together, so this module is a thin wrapper: it just fixes the
parity size and turns the library's exceptions into ``FecError``.

Decoding needs the *exact* length of the encoded bytes, not a prefix of
them or extra trailing bytes -- ``deniable`` stores that length itself,
in its own redundant marker, since the whole point of this module is
that nothing else here can be trusted to survive intact.
"""

import reedsolo

# out of every 255 bytes, 128 are parity and 127 are data, correcting up to
# 64 corrupted bytes per block (about 25%). This is much higher than a
# typical Reed-Solomon use (CDs and QR codes use ~12%) because
# ``deniable`` corrupts bytes in groups of 4: a byte is written as 4
# separate 2 bit crumbs, scattered independently, so it only takes one of
# those 4 crumbs landing on a position the real layer also uses to corrupt
# the whole byte. A p% chance of a crumb collision is roughly a 4p% chance
# of the byte it belongs to being corrupted, for small p.
BLOCK_SIZE = 255
PARITY_SIZE = 128
MAX_CORRUPTED_RATIO = (PARITY_SIZE // 2) / BLOCK_SIZE

_codec = reedsolo.RSCodec(PARITY_SIZE)


class FecError(Exception):
    """More bytes were corrupted than the parity can correct."""


def encode(data: bytes) -> bytes:
    return bytes(_codec.encode(data))


def decode(data: bytes) -> bytes:
    try:
        decoded, _, _ = _codec.decode(data)
    except reedsolo.ReedSolomonError as e:
        raise FecError(str(e)) from e
    return bytes(decoded)


def encoded_size(data_size: int) -> int:
    """Exact size of ``encode(data)`` for data of ``data_size`` bytes, without encoding it."""
    chunk = BLOCK_SIZE - PARITY_SIZE
    full, remainder = divmod(data_size, chunk)
    return full * BLOCK_SIZE + (remainder + PARITY_SIZE if remainder else 0)
