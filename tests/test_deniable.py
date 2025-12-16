import random

import pytest
from PIL import Image

import steganographer
from steganographer import core, deniable
from steganographer.errors import CapacityError


@pytest.fixture
def big_cover(tmp_path):
    """
    Deniable hiding needs real headroom: the decoy has to survive Reed-Solomon
    parity overhead on top of the real file's own footprint, see fec.py and
    deniable.py's module docstring for why. 400x400 gives ~120KB of lsb room.
    """
    rng = random.Random(1)
    path = tmp_path / "cover.png"
    Image.frombytes("RGB", (400, 400), bytes(rng.randrange(256) for _ in range(400 * 400 * 3))).save(path)
    return path


def test_roundtrip(big_cover, tmp_path):
    decoy = b"holiday photos, nothing interesting" * 10
    real = b"the real plan" * 20

    out = steganographer.hide_deniable(
        big_cover,
        decoy,
        "decoypw",
        real,
        "realpw",
        tmp_path / "out.png",
        decoy_filename="vacation.txt",
        real_filename="plan.txt",
    )

    assert steganographer.reveal_decoy(out, "decoypw") == ("vacation.txt", decoy)
    assert steganographer.reveal_file(out, password="realpw") == ("plan.txt", real, None)


def test_real_layer_is_an_ordinary_encrypted_lsb_hide(big_cover, tmp_path):
    real = b"just the real file, hidden normally for comparison"
    plain = steganographer.hide(
        big_cover, real, tmp_path / "plain.png", mode="lsb", password="realpw", filename="x.txt"
    )

    out = steganographer.hide_deniable(
        big_cover, b"decoy", "decoypw", real, "realpw", tmp_path / "out.png", real_filename="x.txt"
    )

    # inspect() on the real password sees exactly the same format it would for
    # a normal hide -- nothing marks the image as carrying a second layer
    assert core.inspect(out, password="realpw").format == core.inspect(plain, password="realpw").format


def test_wrong_password_finds_nothing(big_cover, tmp_path):
    out = steganographer.hide_deniable(big_cover, b"decoy", "decoypw", b"real", "realpw", tmp_path / "out.png")

    assert steganographer.reveal_decoy(out, "wrongpw") is None
    assert steganographer.reveal_decoy(out, "realpw") is None  # the real password isn't a decoy password
    assert core.inspect(out, password="wrongpw") is None
    assert core.inspect(out, password="decoypw") is None  # the decoy password doesn't open the real layer either


def test_passwords_must_differ(big_cover, tmp_path):
    with pytest.raises(ValueError, match="different"):
        steganographer.hide_deniable(big_cover, b"decoy", "samepw", b"real", "samepw", tmp_path / "out.png")


def test_refuses_rather_than_write_a_broken_decoy(big_cover, tmp_path):
    # a real file big enough relative to the image that the decoy statistically
    # can't survive it -- see fec.py's module comment for why the threshold is
    # so much lower than a typical Reed-Solomon use
    room = core.capacity(big_cover)
    huge_real = b"r" * int(room * 0.5)

    with pytest.raises(CapacityError):
        steganographer.hide_deniable(big_cover, b"small decoy", "decoypw", huge_real, "realpw", tmp_path / "out.png")
    assert not (tmp_path / "out.png").exists()


def test_keeps_transparency(tmp_path):
    cover = tmp_path / "logo.png"
    image = Image.new("RGBA", (200, 200), (200, 30, 30, 0))
    image.paste((10, 120, 250, 255), (40, 40, 160, 160))
    image.save(cover)

    out = steganographer.hide_deniable(cover, b"decoy data", "decoypw", b"real data", "realpw", tmp_path / "out.png")
    result = Image.open(out)
    assert result.mode == "RGBA"
    assert result.getchannel("A").tobytes() == image.getchannel("A").tobytes()
    assert steganographer.reveal_decoy(out, "decoypw") == (None, b"decoy data")


@pytest.mark.parametrize("real_fraction", [0.01, 0.02, 0.03])
def test_survives_at_recommended_sizes(big_cover, tmp_path, real_fraction):
    # empirically-checked safe range, see the module docstring in deniable.py
    room = core.capacity(big_cover)
    real = bytes(random.Random(42).randrange(256) for _ in range(int(room * real_fraction)))
    decoy = b"a modest decoy note"

    out = steganographer.hide_deniable(
        big_cover, decoy, "decoypw", real, "realpw", tmp_path / f"out_{real_fraction}.png"
    )
    assert steganographer.reveal_decoy(out, "decoypw") == (None, decoy)
    assert steganographer.reveal(out, password="realpw") == real


def test_reveal_decoy_on_a_plain_image_finds_nothing(big_cover):
    assert steganographer.reveal_decoy(big_cover, "anypw") is None


def test_marker_majority_vote():
    field = deniable.MARKER_MAGIC.to_bytes(4, "big") + (12345).to_bytes(4, "big")
    copies = [bytearray(field) for _ in range(deniable.MARKER_REPEATS)]
    # corrupt a minority of copies at various positions -- majority vote should still win
    for i, copy in enumerate(copies[: deniable.MARKER_REPEATS // 2]):
        copy[i % len(copy)] ^= 0xFF

    assert deniable._read_marker(b"".join(bytes(c) for c in copies)) == 12345


def test_marker_rejects_garbage():
    garbage = bytes(random.Random(7).randrange(256) for _ in range(deniable.MARKER_SIZE))
    assert deniable._read_marker(garbage) is None
