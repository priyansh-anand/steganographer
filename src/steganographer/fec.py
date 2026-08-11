"""
Reed-Solomon forward error correction, used by ``deniable`` (to let a decoy
layer survive being partly overwritten) and by ``robust`` (to mop up the
handful of bit errors JPEG recompression leaves behind).

``reedsolo`` already splits long messages into 255 byte blocks and puts
them back together, so this module is a thin wrapper: it turns the
library's exceptions into ``FecError`` and lets the caller pick a parity
size, since the two users need very different amounts of it.

Decoding needs the *exact* length of the encoded bytes, not a prefix of
them or extra trailing bytes -- both callers store that length themselves
(``deniable`` in its redundant marker, ``robust`` in its header), since
the whole point of this module is that nothing else can be trusted intact.
"""

import reedsolo

BLOCK_SIZE = 255

# ``deniable`` corrupts bytes in groups of 4: a byte is written as 4 separate
# 2 bit crumbs, scattered independently, so a p% chance of a crumb collision
# is roughly a 4p% chance of corrupting the byte it belongs to. That needs a
# lot of parity -- 128 of every 255 bytes, correcting up to 64 per block
# (~25%), far more than a typical Reed-Solomon use (CDs and QR codes ~12%).
DENIABLE_PARITY = 128

# ``robust`` sees a much gentler channel: DCT-domain QIM leaves under ~1% of
# bits wrong after JPEG recompression, so a byte is wrong ~8% of the time at
# worst. 32 of every 255 bytes corrects up to 16 per block (~6%), with room
# to spare -- calibrated in tests/test_robust.py, not derived.
ROBUST_PARITY = 32

_codecs: dict[int, reedsolo.RSCodec] = {}


def _codec(parity: int) -> reedsolo.RSCodec:
    if parity not in _codecs:
        _codecs[parity] = reedsolo.RSCodec(parity)
    return _codecs[parity]


class FecError(Exception):
    """More bytes were corrupted than the parity can correct."""


def encode(data: bytes, parity: int = DENIABLE_PARITY) -> bytes:
    return bytes(_codec(parity).encode(data))


def decode(data: bytes, parity: int = DENIABLE_PARITY) -> bytes:
    try:
        decoded, _, _ = _codec(parity).decode(data)
    except reedsolo.ReedSolomonError as e:
        raise FecError(str(e)) from e
    return bytes(decoded)


def encoded_size(data_size: int, parity: int = DENIABLE_PARITY) -> int:
    """Exact size of ``encode(data)`` for data of ``data_size`` bytes, without encoding it."""
    chunk = BLOCK_SIZE - parity
    full, remainder = divmod(data_size, chunk)
    return full * BLOCK_SIZE + (remainder + parity if remainder else 0)
