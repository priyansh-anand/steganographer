"""
Places hidden data in the visually busiest parts of the cover image first,
instead of spreading it perfectly uniformly the way ``scatter.Permutation``
does. A small file then only touches high-detail regions (texture, foliage,
noise) where a couple of flipped low bits are least visible and hardest for
tests like the ones in ``analyze.py`` to pick out; a file big enough to need
it still spills into flatter regions the same way capacity has always
worked -- see ``AdaptiveOrder``.

The complexity of a pixel is computed only from its upper 6 bits, the 2
lowest bits are the only ones hiding ever touches, so recomputing it on the
stego image gives exactly the same answer as computing it on the cover
image before anything was written. This is the one thing that has to hold
exactly, or reveal would look for data in the wrong order and never find
it, so the arithmetic here is integer only -- no floating point, whose
rounding isn't guaranteed identical across numpy versions or platforms,
the same reason ``scatter.py`` avoids it. tests/test_adaptive.py checks
this directly, and it's the first thing to check if this stops working
after any change here.

Pixels are bucketed into ``TIERS`` equal-sized groups by that complexity
score, busiest first, and each group gets its own password-keyed
``scatter.Permutation``. Anyone can recompute the bucket boundaries from
the stego image alone, without the password -- the complexity map only
depends on bits the image already shows. What the password still protects
is the exact position within a bucket, and, as always, the contents. This
is a real, known trade-off of adaptive steganography in general, not a bug
here specifically: a busy region is still a big haystack, and knowing the
haystack doesn't say whether anything is hidden in it at all, but it's a
weaker guarantee than uniform scattering's "no information without the
password" -- see the README.
"""

import numpy as np

from . import crypto, scatter

TIERS = 8
_NEIGHBOR_SHIFTS = ((0, 1), (0, -1), (1, 0), (-1, 0))


def complexity_map(pixels: np.ndarray) -> np.ndarray:
    """
    A (height, width) roughness score, higher where the image is busier.
    Built only from bits hiding never changes, integer arithmetic only.
    """
    stable = (pixels[..., :3].astype(np.int32) >> 2).sum(axis=-1) // 3
    score = np.zeros(stable.shape, dtype=np.int32)
    for dy, dx in _NEIGHBOR_SHIFTS:
        score += np.abs(stable - np.roll(np.roll(stable, dy, axis=0), dx, axis=1))
    return score


def _tier_assignment(pixels: np.ndarray, tiers: int) -> np.ndarray:
    """Channel index -> tier number (0 = busiest), matching core._color_channels' flattening."""
    score = complexity_map(pixels)
    channel_score = np.repeat(score.reshape(-1), 3).astype(np.int64)
    n = len(channel_score)

    # rank based, ties broken by index, so tier boundaries are exact and
    # reproducible regardless of how many distinct scores there are. The
    # index is folded into the sort key itself, rather than using a stable
    # sort, so the result doesn't depend on which sorting algorithm numpy
    # happens to use -- unlike a stable sort's tie order, which isn't
    # guaranteed to stay the same across numpy versions, this is: with no
    # ties left in the key, every correct sort gives the same answer.
    key = -channel_score * n + np.arange(n, dtype=np.int64)
    busiest_first = np.argsort(key)
    tier_of_rank = (np.arange(n, dtype=np.intp) * tiers) // n

    tier = np.empty(n, dtype=np.intp)
    tier[busiest_first] = tier_of_rank
    return tier


class AdaptiveOrder:
    """
    Same interface as ``scatter.Permutation`` (a ``chunks(count)`` that
    yields channel positions), so it plugs into ``core._write_crumbs`` and
    ``core._read_crumbs`` unchanged. Reading it back needs the exact same
    ``pixels`` array construction ``hide`` used to write it -- built from
    ``core._load``, matching ``core._color_channels``' flattening.
    """

    def __init__(self, password: str, pixels: np.ndarray, tiers: int = TIERS):
        assignment = _tier_assignment(pixels, tiers)
        # one scrypt call instead of `tiers` separate ones, scrypt is
        # deliberately slow and there's no benefit to paying its cost per tier
        keys = crypto.order_key(password, scatter.KEY_SIZE * tiers)

        self._groups = []
        for t in range(tiers):
            indices = np.flatnonzero(assignment == t)
            key = keys[t * scatter.KEY_SIZE : (t + 1) * scatter.KEY_SIZE]
            self._groups.append((indices, scatter.Permutation(key, len(indices))))
        self.size = sum(len(indices) for indices, _ in self._groups)

    def chunks(self, count: int):
        remaining, offset = count, 0
        for indices, permutation in self._groups:
            if remaining <= 0:
                break
            take = min(len(indices), remaining)
            for start, stop, local_positions in permutation.chunks(take):
                yield offset + start, offset + stop, indices[local_positions]
            offset += take
            remaining -= take
