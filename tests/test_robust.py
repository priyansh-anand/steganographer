import io

import numpy as np
import pytest
from PIL import Image

from steganographer import robust
from steganographer.errors import CapacityError, DecryptionError


def natural_image(seed, h=384, w=384):
    """A smooth, photo-like cover with real mid-frequency DCT energy to modulate."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    img = np.zeros((h, w, 3))
    for c in range(3):
        val = np.zeros((h, w))
        for _ in range(5):
            fx, fy = rng.uniform(0.01, 0.15, 2)
            phase = rng.uniform(0, 6.28, 2)
            amp = rng.uniform(20, 60)
            val += amp * np.sin(fx * xx + phase[0]) * np.cos(fy * yy + phase[1])
        val += 128 + rng.normal(0, 4, (h, w))
        img[:, :, c] = val
    return np.clip(np.round(img), 0, 255).astype(np.uint8)


@pytest.fixture
def cover(tmp_path):
    path = tmp_path / "cover.png"
    Image.fromarray(natural_image(3)).save(path)
    return path


def jpeg_recompress(path, quality, subsampling=2):
    """Re-encode as JPEG (default 4:2:0 chroma, like phones and social apps)."""
    with Image.open(path) as image:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=quality, subsampling=subsampling)
    buf.seek(0)
    out = path.parent / f"{path.stem}_q{quality}.png"
    Image.open(buf).save(out)
    return out


# --- the transform ---------------------------------------------------------


def test_dct_is_its_own_inverse():
    block = np.random.default_rng(1).uniform(0, 255, (8, 8))
    assert np.allclose(robust._idct2(robust._dct2(block)), block)


def test_dct_is_orthonormal():
    # M @ M.T == I, so the transform preserves energy (Parseval)
    assert np.allclose(robust._M @ robust._M.T, np.eye(8))


# --- roundtrip, no recompression -------------------------------------------


def test_plain_roundtrip(cover, tmp_path):
    out = robust.hide_robust(cover, b"a short message", tmp_path / "out.png", filename="note.txt")
    revealed = robust.reveal_robust(out)
    assert revealed.name == "note.txt"
    assert revealed.data == b"a short message"


def test_encrypted_roundtrip(cover, tmp_path):
    out = robust.hide_robust(cover, b"secret payload", tmp_path / "out.png", password="pw", filename="s.txt")
    assert robust.reveal_robust(out, password="pw").data == b"secret payload"


def test_wrong_password(cover, tmp_path):
    out = robust.hide_robust(cover, b"secret", tmp_path / "out.png", password="right")
    with pytest.raises(DecryptionError):
        robust.reveal_robust(out, password="wrong")


def test_nothing_hidden_returns_none(cover):
    assert robust.reveal_robust(cover) is None


def test_too_big_is_refused(cover):
    with pytest.raises(CapacityError):
        robust.hide_robust(cover, b"x" * 100000, cover.parent / "big.png")


def test_capacity_is_honest(cover, tmp_path):
    # a file right at the reported capacity should fit
    room = robust.robust_capacity(*Image.open(cover).size)
    assert room > 0
    out = robust.hide_robust(cover, b"x" * room, tmp_path / "out.png")
    assert robust.reveal_robust(out).data == b"x" * room


# --- the point of the whole mode: surviving recompression ------------------


@pytest.mark.parametrize("quality", [40, 60, 75, 90])
def test_survives_single_jpeg_recompression(cover, tmp_path, quality):
    out = robust.hide_robust(cover, b"survive me", tmp_path / "out.png", filename="m.txt")
    recompressed = jpeg_recompress(out, quality)
    revealed = robust.reveal_robust(recompressed)
    assert revealed is not None and revealed.data == b"survive me"


def test_survives_repeated_recompression(cover, tmp_path):
    # sharing a photo around re-compresses it several times over
    out = robust.hide_robust(cover, b"still here", tmp_path / "out.png")
    current = out
    for _ in range(5):
        current = jpeg_recompress(current, 60)
    assert robust.reveal_robust(current).data == b"still here"


def test_lsb_would_not_survive_but_robust_does(cover, tmp_path):
    # contrast: the same recompression that robust mode shrugs off destroys
    # an ordinary lsb hide, which is the whole reason this mode exists
    from steganographer import core

    lsb_out = core.hide(cover, b"fragile", tmp_path / "lsb.png", mode="lsb")
    assert core.reveal(lsb_out) == b"fragile"  # fine before recompression
    recompressed = jpeg_recompress(lsb_out, 75)
    assert core.inspect(recompressed) is None  # gone after

    robust_out = robust.hide_robust(cover, b"durable", tmp_path / "rob.png")
    assert robust.reveal_robust(jpeg_recompress(robust_out, 75)).data == b"durable"


def test_imperceptible(cover, tmp_path):
    out = robust.hide_robust(cover, b"invisible change", tmp_path / "out.png")
    before = np.asarray(Image.open(cover).convert("RGB")).astype(np.float64)
    after = np.asarray(Image.open(out).convert("RGB")).astype(np.float64)
    mse = np.mean((before - after) ** 2)
    psnr = 10 * np.log10(255**2 / mse)
    assert psnr > 38  # comfortably imperceptible
