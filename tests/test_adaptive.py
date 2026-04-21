import numpy as np
import pytest
from PIL import Image

from steganographer import adaptive, analyze, core


def flip_random_lsbs(pixels, count, seed):
    rng = np.random.default_rng(seed)
    flat = pixels.reshape(-1)
    idx = rng.choice(len(flat), count, replace=False)
    flat[idx] = (flat[idx] & 0b11111100) | rng.integers(0, 4, count, dtype=np.uint8)


@pytest.fixture
def natural_pixels():
    rng = np.random.default_rng(1)
    return rng.integers(0, 256, (100, 100, 3), dtype=np.uint8)


# --- the one invariant everything else depends on --------------------------


def test_tier_assignment_survives_lsb_changes(natural_pixels):
    before = adaptive._tier_assignment(natural_pixels, adaptive.TIERS)

    after = natural_pixels.copy()
    flip_random_lsbs(after, 10000, seed=2)

    assert np.array_equal(before, adaptive._tier_assignment(after, adaptive.TIERS))


def test_adaptive_order_positions_survive_lsb_changes(natural_pixels):
    after = natural_pixels.copy()
    flip_random_lsbs(after, 10000, seed=3)

    before_chunks = list(adaptive.AdaptiveOrder("pw", natural_pixels).chunks(2000))
    after_chunks = list(adaptive.AdaptiveOrder("pw", after).chunks(2000))

    assert len(before_chunks) == len(after_chunks)
    for (s1, e1, p1), (s2, e2, p2) in zip(before_chunks, after_chunks, strict=True):
        assert (s1, e1) == (s2, e2)
        assert np.array_equal(p1, p2)


def test_complexity_map_is_integer_only(natural_pixels):
    # a regression guard: floating point isn't guaranteed bit-identical
    # across numpy versions or platforms the way integer math is (see
    # scatter.py and adaptive.py's module docstring for why this matters)
    assert np.issubdtype(adaptive.complexity_map(natural_pixels).dtype, np.integer)


# --- tiering behaves sensibly -----------------------------------------------


def test_tiers_are_roughly_equal_sized(natural_pixels):
    assignment = adaptive._tier_assignment(natural_pixels, 8)
    counts = np.bincount(assignment, minlength=8)
    assert counts.min() >= counts.max() - 8  # rounding only, no lopsided tiers


def test_flat_region_ranks_below_busy_region():
    pixels = np.zeros((40, 80, 3), dtype=np.uint8)
    pixels[:, :40] = 128
    rng = np.random.default_rng(4)
    pixels[:, 40:] = rng.integers(60, 196, (40, 40, 3), dtype=np.uint8)

    assignment = adaptive._tier_assignment(pixels, 8)
    left_tiers = assignment.reshape(40, 80, 3)[:, :40].reshape(-1)
    right_tiers = assignment.reshape(40, 80, 3)[:, 40:].reshape(-1)

    # lower tier number = busier = written first, and the busy half should
    # occupy the low tiers almost entirely
    assert right_tiers.mean() < left_tiers.mean()
    assert (right_tiers < 4).mean() > 0.95


def test_adaptive_order_fills_busy_positions_first():
    pixels = np.zeros((40, 80, 3), dtype=np.uint8)
    pixels[:, :40] = 128
    rng = np.random.default_rng(5)
    pixels[:, 40:] = rng.integers(60, 196, (40, 40, 3), dtype=np.uint8)

    order = adaptive.AdaptiveOrder("pw", pixels)
    _, _, first_positions = next(order.chunks(3000))

    # channel index // 3 // 80 gives the row-major pixel index; a position
    # is in the busy (right) half if its column is >= 40
    columns = (first_positions // 3) % 80
    assert (columns >= 40).mean() > 0.95


# --- through core.hide / reveal ---------------------------------------------


@pytest.fixture
def cover(tmp_path):
    rng = np.random.default_rng(6)
    path = tmp_path / "cover.png"
    Image.fromarray(rng.integers(0, 256, (150, 150, 3), dtype=np.uint8)).save(path)
    return path


def test_roundtrip(cover, tmp_path):
    data = b"adaptive placement roundtrip" * 20
    out = core.hide(cover, data, tmp_path / "out.png", mode="lsb", password="pw", adaptive=True, filename="x.txt")

    found = core.inspect(out, password="pw")
    assert found.format.adaptive
    assert core.reveal_file(out, password="pw") == ("x.txt", data, None)


def test_wrong_password_finds_nothing(cover, tmp_path):
    out = core.hide(cover, b"secret", tmp_path / "out.png", mode="lsb", password="pw", adaptive=True)
    assert core.inspect(out, password="wrong") is None


def test_needs_lsb_and_a_password(cover, tmp_path):
    with pytest.raises(ValueError, match="lsb mode and a password"):
        core.hide(cover, b"x", tmp_path / "out.png", mode="endian", password="pw", adaptive=True)
    with pytest.raises(ValueError, match="lsb mode and a password"):
        core.hide(cover, b"x", tmp_path / "out.png", mode="lsb", adaptive=True)


def test_adaptive_and_uniform_images_are_distinct_formats(cover, tmp_path):
    data = b"same payload"
    adaptive_out = core.hide(cover, data, tmp_path / "a.png", mode="lsb", password="pw", adaptive=True)
    uniform_out = core.hide(cover, data, tmp_path / "u.png", mode="lsb", password="pw")

    assert core.inspect(adaptive_out, password="pw").format.adaptive
    assert not core.inspect(uniform_out, password="pw").format.adaptive
    # reading one as the other finds nothing -- they really are different layouts
    assert core.inspect(adaptive_out, password="pw").format != core.inspect(uniform_out, password="pw").format


# --- the actual point: concentrates changes where they're least visible ----


@pytest.fixture
def half_flat_half_busy(tmp_path):
    rng = np.random.default_rng(7)
    h, w = 100, 200
    pixels = np.zeros((h, w, 3), dtype=np.uint8)
    pixels[:, : w // 2] = 128
    pixels[:, w // 2 :] = rng.integers(80, 176, (h, w // 2, 3), dtype=np.uint8)
    path = tmp_path / "mixed.png"
    Image.fromarray(pixels).save(path)
    return path


def _half_discriminants(path):
    pixels = np.asarray(Image.open(path).convert("RGB"))
    mid = pixels.shape[1] // 2
    return analyze.rs_stats(pixels[:, :mid].reshape(-1)).discriminant, analyze.rs_stats(
        pixels[:, mid:].reshape(-1)
    ).discriminant


def test_small_payload_never_touches_the_flat_half(half_flat_half_busy, tmp_path):
    room = core.capacity(half_flat_half_busy)
    rng = np.random.default_rng(0)
    payload = bytes(rng.integers(0, 256, int(room * 0.1), dtype=np.uint8))

    out = core.hide(half_flat_half_busy, payload, tmp_path / "out.png", mode="lsb", password="pw", adaptive=True)

    before_left, _ = _half_discriminants(half_flat_half_busy)
    after_left, _ = _half_discriminants(out)
    assert after_left == before_left


def test_large_payload_spills_into_the_flat_half(half_flat_half_busy, tmp_path):
    room = core.capacity(half_flat_half_busy)
    rng = np.random.default_rng(0)
    payload = bytes(rng.integers(0, 256, int(room * 0.7), dtype=np.uint8))

    out = core.hide(half_flat_half_busy, payload, tmp_path / "out.png", mode="lsb", password="pw", adaptive=True)

    before_left, _ = _half_discriminants(half_flat_half_busy)
    after_left, _ = _half_discriminants(out)
    assert after_left != before_left


def test_adaptive_disturbs_the_flat_half_far_less_than_uniform_scattering(half_flat_half_busy, tmp_path):
    room = core.capacity(half_flat_half_busy)
    rng = np.random.default_rng(0)
    payload = bytes(rng.integers(0, 256, int(room * 0.15), dtype=np.uint8))

    uniform_out = core.hide(half_flat_half_busy, payload, tmp_path / "u.png", mode="lsb", password="pw")
    adaptive_out = core.hide(half_flat_half_busy, payload, tmp_path / "a.png", mode="lsb", password="pw", adaptive=True)

    before_left, _ = _half_discriminants(half_flat_half_busy)
    uniform_left, _ = _half_discriminants(uniform_out)
    adaptive_left, _ = _half_discriminants(adaptive_out)

    uniform_shift = abs(uniform_left - before_left)
    adaptive_shift = abs(adaptive_left - before_left)
    assert adaptive_shift < uniform_shift / 5
