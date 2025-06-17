"""
Password dependent order for spreading hidden data over the whole image.

Without a password, lsb mode fills the channels in order from the top left
corner. A small file then only changes the first few rows, which is easy to
see in the statistics of the image, and anyone can read the header to find
out that something is hidden and how big it is.

With a password, bit pair ``i`` goes to channel ``P(i)`` instead, where ``P``
is a keyed pseudo random permutation of ``range(size)``. ``P`` is a 4 round
Feistel network over the smallest power of 4 that is ``>= size``, with cycle
walking to stay inside the range. It only needs integer math, so any
position can be computed directly without building a shuffled list of every
channel in the image, and it gives the same result on every platform and
numpy version.
"""

import numpy as np

ROUNDS = 4
KEY_SIZE = 8 * ROUNDS

# splitmix64 finalizer, used as the Feistel round function
_M1 = np.uint64(0xBF58476D1CE4E5B9)
_M2 = np.uint64(0x94D049BB133111EB)
_S1, _S2, _S3 = np.uint64(30), np.uint64(27), np.uint64(31)

CHUNK = 1 << 20


def _mix(x: np.ndarray) -> np.ndarray:
    x = (x ^ (x >> _S1)) * _M1
    x = (x ^ (x >> _S2)) * _M2
    return x ^ (x >> _S3)


class Permutation:
    def __init__(self, key: bytes, size: int):
        if len(key) != KEY_SIZE:
            raise ValueError(f"key must be {KEY_SIZE} bytes")
        self.size = size
        bits = max((size - 1).bit_length(), 2)
        self.half = np.uint64((bits + 1) // 2)
        self.mask = np.uint64((1 << int(self.half)) - 1)
        self.keys = [np.uint64(int.from_bytes(key[i : i + 8], "big")) for i in range(0, KEY_SIZE, 8)]

    def _feistel(self, x: np.ndarray) -> np.ndarray:
        left, right = x >> self.half, x & self.mask
        for key in self.keys:
            left, right = right, left ^ (_mix(right ^ key) & self.mask)
        return (left << self.half) | right

    def positions(self, start: int, stop: int) -> np.ndarray:
        """``P(i)`` for every ``i`` in ``range(start, stop)``."""
        out = self._feistel(np.arange(start, stop, dtype=np.uint64))
        outside = out >= self.size
        while outside.any():
            out[outside] = self._feistel(out[outside])
            outside = out >= self.size
        return out.astype(np.intp)

    def chunks(self, count: int):
        """Yield ``(start, stop, positions)`` covering ``range(count)`` a chunk at a time."""
        for start in range(0, count, CHUNK):
            stop = min(start + CHUNK, count)
            yield start, stop, self.positions(start, stop)
