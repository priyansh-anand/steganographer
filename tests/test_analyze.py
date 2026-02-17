import numpy as np
import pytest
from PIL import Image

from steganographer import analyze, core


def natural_channel(seed, h=150, w=150):
    """
    A smooth, locally-correlated synthetic channel -- like a real photo in
    that neighboring pixels tend to be close in value, which is all RS
    analysis needs. Its byte values are NOT unevenly distributed the way a
    real photo's usually are (see analyze.py's module docstring), so it is
    deliberately not used for chi-square tests.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    val = np.zeros((h, w))
    for _ in range(5):
        fx, fy = rng.uniform(0.01, 0.15, 2)
        phase = rng.uniform(0, 6.28, 2)
        amp = rng.uniform(20, 60)
        val += amp * np.sin(fx * xx + phase[0]) * np.cos(fy * yy + phase[1])
    val += 128 + rng.normal(0, 4, (h, w))
    return np.clip(np.round(val), 0, 255).astype(np.uint8).reshape(-1)


def posterized_channel(seed, h=150, w=150, step=6):
    """
    A synthetic channel with deliberately uneven byte-value frequencies --
    quantized to a coarse grid before a little fine noise is added back, the
    way a limited palette or heavy compression biases which exact values
    occur. This is what the chi-square attack actually needs to have
    something to find; see analyze.py's module docstring.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    val = 128 + 60 * np.sin(0.04 * xx + seed) + 40 * np.cos(0.05 * yy + seed)
    val = np.round(val / step) * step + rng.normal(0, 1.0, (h, w))
    return np.clip(np.round(val), 0, 255).astype(np.uint8).reshape(-1)


def posterized_image(seed, h=250, w=250, step=6):
    channels = [posterized_channel(seed + c, h, w, step).reshape(h, w) for c in range(3)]
    return np.stack(channels, axis=-1)


def flip_random_lsbs(values, fraction, seed):
    n = int(len(values) * fraction)
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(values), n, replace=False)
    out = values.copy()
    out[idx] = (out[idx] & 0b11111110) | rng.integers(0, 2, n).astype(np.uint8)
    return out


# --- flip functions -----------------------------------------------------


def test_flip1_is_lsb_flip():
    x = np.array([0, 1, 2, 3, 254, 255])
    assert analyze._flip1(x).tolist() == [1, 0, 3, 2, 255, 254]


def test_flip_neg1_pairs_and_fixed_points():
    x = np.array([0, 1, 2, 3, 4, 253, 254, 255])
    assert analyze._flip_neg1(x).tolist() == [0, 2, 1, 4, 3, 254, 253, 255]


def test_flip1_and_flip_neg1_are_involutions_except_at_fixed_points():
    x = np.arange(1, 255)
    assert (analyze._flip1(analyze._flip1(x)) == x).all()
    assert (analyze._flip_neg1(analyze._flip_neg1(x)) == x).all()


# --- chi-square -----------------------------------------------------------


def test_chi_square_low_on_a_biased_clean_image():
    assert analyze.chi_square_pvalue(posterized_channel(1)) < 0.05


def test_chi_square_rises_with_full_lsb_replacement():
    values = posterized_channel(2)
    assert analyze.chi_square_pvalue(flip_random_lsbs(values, 1.0, seed=1)) > 0.9


def test_chi_square_approximation_matches_scipy_shape():
    # regression check on the Wilson-Hilferty approximation itself: it should
    # at least be monotonically decreasing in the statistic for fixed df,
    # which is the only property the rest of this module actually depends on
    df = 40
    xs = [5, 20, 40, 60, 100, 200]
    ps = [analyze._chi_square_sf(x, df) for x in xs]
    assert ps == sorted(ps, reverse=True)


@pytest.mark.parametrize("windows", [1, 5, 37])
def test_chi_square_profile_length_and_range(windows):
    values = posterized_channel(3)
    profile = analyze.chi_square_profile(values, windows=windows)
    assert len(profile) == windows
    assert all(0.0 <= p <= 1.0 for p in profile)


def test_chi_square_profile_is_flat_on_a_clean_image():
    profile = analyze.chi_square_profile(posterized_channel(4), windows=20)
    assert max(profile) < 0.1


# --- RS analysis ------------------------------------------------------------


def test_rs_stats_are_fractions():
    stats = analyze.rs_stats(natural_channel(1))
    for value in stats:
        assert 0.0 <= value <= 1.0


def test_rs_discriminant_decreases_monotonically_with_embedding():
    values = natural_channel(5)
    discriminants = [
        analyze.rs_stats(flip_random_lsbs(values, frac, seed=1)).discriminant for frac in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    ]
    # not strictly monotonic on one image (see test_analyze's module note on
    # the ~0.025 std observed across images at a fixed fraction), but the
    # overall trend across this wide a spread should be
    assert discriminants[0] > discriminants[-1]
    assert sum(a >= b for a, b in zip(discriminants[:-1], discriminants[1:], strict=True)) >= 4


def test_rs_discriminant_trends_down_across_many_images():
    # the property the calibration table in analyze.py relies on: averaged
    # over enough images, higher embedded fraction means lower discriminant
    low_frac, high_frac = [], []
    for seed in range(15):
        values = natural_channel(seed * 3 + 1)
        low_frac.append(analyze.rs_stats(flip_random_lsbs(values, 0.1, seed)).discriminant)
        high_frac.append(analyze.rs_stats(flip_random_lsbs(values, 0.8, seed)).discriminant)
    assert np.median(low_frac) > np.median(high_frac)


# --- calibration --------------------------------------------------------


def test_calibration_table_is_sorted_and_monotonic():
    discriminants = [d for d, _ in analyze._CALIBRATION]
    fractions = [f for _, f in analyze._CALIBRATION]
    assert discriminants == sorted(discriminants, reverse=True)
    assert fractions == sorted(fractions)


def test_estimate_embedded_fraction_is_monotonic_and_clamped():
    xs = [0.05, 0.002, -0.005, -0.02, -0.05, -0.1, -0.15, -0.3]
    ys = [analyze.estimate_embedded_fraction(x) for x in xs]
    assert ys == sorted(ys)
    assert ys[0] == 0.0
    assert ys[-1] == 1.0


def test_estimate_is_reasonably_close_on_held_out_images():
    # different seeds than the ones the _CALIBRATION table itself was built
    # from (see analyze.py's comment on it) -- checks the curve generalizes
    # rather than only fitting its own training images
    for frac in [0.1, 0.3, 0.6, 0.9]:
        discs = [
            analyze.rs_stats(flip_random_lsbs(natural_channel(seed * 101 + 5), frac, seed)).discriminant
            for seed in range(10)
        ]
        estimated = analyze.estimate_embedded_fraction(float(np.median(discs)))
        assert abs(estimated - frac) < 0.2


# --- end to end, through real hide() output ------------------------------


@pytest.fixture
def big_posterized_cover(tmp_path):
    path = tmp_path / "cover.png"
    Image.fromarray(posterized_image(1)).save(path)
    return path


def test_clean_image_reads_as_clean(big_posterized_cover):
    report = analyze.analyze(big_posterized_cover)
    assert report.verdict == "no strong signal of hidden data"


def test_unscattered_hide_is_localized_and_flagged(big_posterized_cover, tmp_path):
    room = core.capacity(big_posterized_cover)
    payload = bytes(np.random.default_rng(0).integers(0, 256, int(room * 0.25), dtype=np.uint8))

    out = core.hide(big_posterized_cover, payload, tmp_path / "seq.png", mode="lsb")
    report = analyze.analyze(out)

    assert report.verdict == "likely contains hidden data"
    # front-loaded: the first windows are flagged, the later ones aren't
    assert report.chi_square_profile[0] > 0.9
    assert report.chi_square_profile[-1] < 0.1


def test_scattered_hide_of_the_same_size_is_not_localized(big_posterized_cover, tmp_path):
    room = core.capacity(big_posterized_cover)
    payload = bytes(np.random.default_rng(0).integers(0, 256, int(room * 0.25), dtype=np.uint8))

    out = core.hide(big_posterized_cover, payload, tmp_path / "scat.png", mode="lsb", password="pw")
    report = analyze.analyze(out)

    # this is the actual claim the README makes about password-scattered lsb
    # mode -- checking it here means it's verified, not just asserted
    assert report.verdict == "no strong signal of hidden data"
    assert report.peak_chi_square < 0.1
