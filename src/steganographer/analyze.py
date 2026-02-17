"""
Steganalysis: check whether an image looks like it has data hidden in its
pixels with lsb mode, roughly how much, and whether it was likely written
sequentially from the top or spread out with a password.

Two classic, independent tests are combined:

Chi-square attack (Westfeld & Pfitzmann, 1999)
    LSB replacement makes adjacent byte values (2k, 2k+1) tend toward equal
    frequency, since a replaced LSB is as likely to be 0 as 1 regardless of
    what the original bit was. ``chi_square_profile`` runs this test in
    windows across the image, which is what localizes *where* the change
    is concentrated -- useful against unscattered lsb hides, which fill
    pixels in order from the top and leave the rest of the image alone.

    This test only has something to find if the *cover* image's own byte
    values were unevenly distributed to begin with (real photos usually
    are, because of sensor and compression artifacts a smooth synthetic
    image doesn't have) -- on a sufficiently smooth or already-noisy cover
    it reads close to 1 whether or not anything is hidden, since nothing
    round-trips through a camera or a codec to make one value more likely
    than its neighbor. tests/test_analyze.py's cover images are built to
    have this bias deliberately (posterized before adding fine noise) so
    the test is checking something real; a fully synthetic gradient does
    not reliably behave the same way, and this is a real limitation to
    keep in mind reading a report on real files, not just a test fixture
    detail.

Regular-Singular analysis (Fridrich, Goljan & Du, 2001)
    Groups of pixels are flipped in two opposite ways and classified as
    "regular" or "singular" by whether flipping increases or decreases
    local noise. Natural images are regular more often than singular;
    replacing LSBs with random data erodes that gap. ``rs_discriminant``
    is that gap, and unlike the chi-square attack it doesn't need the
    cover's byte values to already be unevenly distributed, only that
    neighboring pixels tend to be close in value, which holds for most
    synthetic gradients as well as real photos.

``estimate_embedded_fraction`` turns the RS discriminant into a rough
percentage by comparing it against a calibration curve built by actually
embedding known amounts into synthetic images and measuring where the
discriminant landed (see ``_CALIBRATION`` below and
tests/test_analyze.py) -- not a closed-form solve of the kind the
original paper describes. It is only meant to say "roughly how much",
not to recover an exact byte count, and the curve is specific to this
project's own scattered lsb mode, not tuned to match any published
implementation's numbers.

None of this is a substitute for a dedicated steganalysis tool, and
neither test is reliable on its own -- that's the reason there are two.
This exists so `steganographer --analyze` can tell you how exposed your
own output actually is, and to measure whether one hiding strategy is
harder to spot than another (see the "hide where the image is busy" idea
in the project's notes) instead of just asserting it.
"""

import math
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
from PIL import Image

from . import core

GROUP_SIZE = 4
_MASK = np.array([1, 0] * (GROUP_SIZE // 2), dtype=np.int16)


def _load_channels(image_path: core.PathLike) -> np.ndarray:
    with Image.open(image_path) as image:
        pixels = np.asarray(image.convert("RGB"))
    return pixels.reshape(-1)


def _chi_square_sf(x: float, df: int) -> float:
    """
    P(a chi-square variable with ``df`` degrees of freedom is >= x), via the
    Wilson-Hilferty approximation. Accurate to within ~0.002 even at df as
    low as 5, and to within floating point noise for the df this module
    actually uses (tens to low hundreds) -- checked against scipy.stats.chi2
    during development, not shipped as a dependency for it.
    """
    if df <= 0 or x <= 0:
        return 1.0
    z = ((x / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
    return 0.5 * math.erfc(z / math.sqrt(2))


def chi_square_pvalue(values: np.ndarray) -> float:
    """
    Pairs-of-values chi-square statistic for one stretch of bytes, as a
    p-value: close to 1 means the byte value pairs (2k, 2k+1) are about as
    equally frequent as full lsb replacement would make them, close to 0
    means they look like an ordinary, untouched image.
    """
    hist = np.bincount(values, minlength=256).astype(np.float64)
    even, odd = hist[0::2], hist[1::2]
    expected = (even + odd) / 2
    used = expected > 0
    if used.sum() < 2:
        return 0.0
    statistic = float(np.sum((even[used] - expected[used]) ** 2 / expected[used]))
    return _chi_square_sf(statistic, df=int(used.sum()) - 1)


def chi_square_profile(values: np.ndarray, windows: int = 20) -> list[float]:
    """
    ``chi_square_pvalue`` computed separately over ``windows`` equal,
    consecutive slices of ``values``. A hide that fills pixels in order
    from the top shows up as a block of high p-values followed by a drop;
    a scattered, password-protected hide is closer to flat.
    """
    edges = np.linspace(0, len(values), windows + 1, dtype=np.intp)
    return [chi_square_pvalue(values[edges[i] : edges[i + 1]]) for i in range(windows)]


def _flip1(x: np.ndarray) -> np.ndarray:
    return x ^ 1


def _flip_neg1(x: np.ndarray) -> np.ndarray:
    """Pairs (1,2), (3,4), ..., (253,254); 0 and 255 have nowhere to go and are left alone."""
    shifted = ((x - 1) ^ 1) + 1
    return np.where((x == 0) | (x == 255), x, shifted)


def _roughness(groups: np.ndarray) -> np.ndarray:
    return np.abs(np.diff(groups, axis=1)).sum(axis=1)


def _apply_mask(groups: np.ndarray, mask: np.ndarray) -> np.ndarray:
    out = groups.copy()
    for column, m in enumerate(mask):
        if m == 1:
            out[:, column] = _flip1(groups[:, column])
        elif m == -1:
            out[:, column] = _flip_neg1(groups[:, column])
    return out


def _regular_singular(groups: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    before, after = _roughness(groups), _roughness(_apply_mask(groups, mask))
    total = len(groups) or 1
    return float(np.sum(after > before)) / total, float(np.sum(after < before)) / total


class RSStats(NamedTuple):
    """
    Regular/singular fractions for a mask and its opposite. ``r_m > s_m``
    and ``r_neg_m > s_neg_m`` with the two gaps close together is typical
    of an unmodified image; the gaps closing (``discriminant`` near 0) or
    crossing (negative) is typical of heavy lsb replacement.
    """

    r_m: float
    s_m: float
    r_neg_m: float
    s_neg_m: float

    @property
    def discriminant(self) -> float:
        return (self.r_m - self.s_m) - (self.r_neg_m - self.s_neg_m)


def rs_stats(values: np.ndarray, group_size: int = GROUP_SIZE) -> RSStats:
    values = values.astype(np.int16)
    usable = len(values) - len(values) % group_size
    groups = values[:usable].reshape(-1, group_size)
    mask = np.resize([1, 0], group_size)

    r_m, s_m = _regular_singular(groups, mask)
    r_neg_m, s_neg_m = _regular_singular(groups, -mask)
    return RSStats(r_m, s_m, r_neg_m, s_neg_m)


# discriminant -> embedded fraction, the median discriminant over 40 synthetic
# cover images (see tests/test_analyze.py's natural_channel fixture) at each
# fraction, embedding random-bit lsb replacement directly rather than going
# through hide(), so the numbers reflect the underlying statistics and not
# this project's specific header/scatter overhead. Not derived from a
# formula -- tests/test_analyze.py::test_calibration_is_monotonic_and_close
# regenerates a version of this and checks it's still in the same shape.
_CALIBRATION = [
    (0.00204, 0.00),
    (-0.00373, 0.05),
    (-0.01653, 0.10),
    (-0.02044, 0.15),
    (-0.02987, 0.20),
    (-0.05449, 0.30),
    (-0.07644, 0.40),
    (-0.08773, 0.50),
    (-0.10044, 0.60),
    (-0.11929, 0.70),
    (-0.14533, 0.85),
    (-0.16569, 1.00),
]


def estimate_embedded_fraction(discriminant: float) -> float:
    """
    Rough fraction of the image's lsb capacity that looks used, from
    ``RSStats.discriminant``. Clamped to [0, 1]; a cover image's own
    discriminant varies enough between images that this is a rough
    indicator, not a byte count -- ``size`` in ``--info`` is exact,
    this isn't.
    """
    xs, ys = zip(*_CALIBRATION, strict=True)  # xs descending
    if discriminant >= xs[0]:
        return ys[0]
    if discriminant <= xs[-1]:
        return ys[-1]
    return float(np.interp(discriminant, xs[::-1], ys[::-1]))


@dataclass(frozen=True)
class AnalysisReport:
    chi_square: float
    chi_square_profile: list[float]
    rs: RSStats
    estimated_fraction: float

    @property
    def peak_chi_square(self) -> float:
        """
        The highest p-value in ``chi_square_profile``. Data hidden
        unscattered in a small part of a big image can be invisible in
        ``chi_square`` (diluted by the rest of the image) but still show
        up clearly here, so the verdict looks at both.
        """
        return max(self.chi_square_profile, default=0.0)

    @property
    def verdict(self) -> str:
        chi_square = max(self.chi_square, self.peak_chi_square)
        if chi_square > 0.9 or self.estimated_fraction > 0.5:
            return "likely contains hidden data"
        if chi_square > 0.5 or self.estimated_fraction > 0.15:
            return "suspicious"
        return "no strong signal of hidden data"


def analyze(image_path: core.PathLike) -> AnalysisReport:
    """Run both tests against ``image_path`` and summarize the result."""
    values = _load_channels(image_path)
    stats = rs_stats(values)
    return AnalysisReport(
        chi_square=chi_square_pvalue(values),
        chi_square_profile=chi_square_profile(values),
        rs=stats,
        estimated_fraction=estimate_embedded_fraction(stats.discriminant),
    )
