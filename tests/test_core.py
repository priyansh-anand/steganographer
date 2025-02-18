from pathlib import Path

import pytest
from PIL import Image

import steganographer
from steganographer import core
from steganographer.errors import CapacityError, DecryptionError, NoHiddenDataError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("mode", ["lsb", "endian"])
@pytest.mark.parametrize("password", [None, "hunter2"])
def test_roundtrip(cover, tmp_path, secret, mode, password):
    out = steganographer.hide(cover, secret, tmp_path / "out.png", mode=mode, password=password)

    found = steganographer.inspect(out)
    assert found.mode == mode
    assert found.encrypted == bool(password)
    assert steganographer.reveal(out, password=password) == secret


@pytest.mark.parametrize("data", [b"", b"a", b"ab", b"abc", b"abcd"])
def test_lsb_small_payloads(cover, tmp_path, data):
    # payload sizes that don't line up with the 3 channels of a pixel
    out = steganographer.hide(cover, data, tmp_path / "out.png", mode="lsb")
    assert steganographer.reveal(out) == data


def test_lsb_only_touches_two_low_bits(cover, tmp_path, secret):
    out = steganographer.hide(cover, secret, tmp_path / "out.png", mode="lsb")

    before = Image.open(cover).tobytes()
    after = Image.open(out).tobytes()
    assert all(a >> 2 == b >> 2 for a, b in zip(before, after))


def test_lsb_fills_image_exactly(cover, tmp_path):
    data = b"x" * steganographer.capacity(cover)
    out = steganographer.hide(cover, data, tmp_path / "out.png", mode="lsb")
    assert steganographer.reveal(out) == data


def test_lsb_too_big(cover, tmp_path):
    data = b"x" * (steganographer.capacity(cover) + 1)
    with pytest.raises(CapacityError):
        steganographer.hide(cover, data, tmp_path / "out.png", mode="lsb")


def test_lsb_rejects_lossy_output(cover, tmp_path):
    with pytest.raises(ValueError, match="lossless"):
        steganographer.hide(cover, b"data", tmp_path / "out.jpg", mode="lsb")


def test_endian_keeps_the_image_readable(cover, tmp_path, secret):
    out = steganographer.hide(cover, secret, tmp_path / "out.png", mode="endian")
    assert out.read_bytes().startswith(cover.read_bytes())
    assert Image.open(out).tobytes() == Image.open(cover).tobytes()


def test_endian_works_with_jpeg(tmp_path, secret):
    jpeg = tmp_path / "photo.jpg"
    Image.new("RGB", (16, 16), "teal").save(jpeg)

    out = steganographer.hide(jpeg, secret, mode="endian", password="pw")
    assert out == tmp_path / "photo_steg0.jpg"
    assert steganographer.reveal(out, password="pw") == secret


def test_wrong_password(cover, tmp_path, secret):
    out = steganographer.hide(cover, secret, tmp_path / "out.png", mode="lsb", password="right")
    with pytest.raises(DecryptionError):
        steganographer.reveal(out, password="wrong")
    with pytest.raises(DecryptionError):
        steganographer.reveal(out)


def test_same_password_gives_different_ciphertext(cover, tmp_path, secret):
    a = steganographer.hide(cover, secret, tmp_path / "a.png", mode="endian", password="pw")
    b = steganographer.hide(cover, secret, tmp_path / "b.png", mode="endian", password="pw")
    assert a.read_bytes() != b.read_bytes()


def test_nothing_hidden(cover):
    assert steganographer.inspect(cover) is None
    with pytest.raises(NoHiddenDataError):
        steganographer.reveal(cover)


def test_not_an_image(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    assert steganographer.inspect(path) is None


def test_default_output_path_keeps_directory(tmp_path):
    # used to turn "./photo.png" into "/photo_steg0.png"
    image = tmp_path / "some.dir" / "photo.v2.png"
    assert core.default_output_path(image, "lsb") == tmp_path / "some.dir" / "photo.v2_steg0.png"


def test_split_join_roundtrip():
    data = bytes(range(256))
    assert core._join(core._split(data)) == data


@pytest.mark.parametrize(
    "name, mode, encrypted",
    [
        ("legacy_lsb.png", "lsb", False),
        ("legacy_lsb_encrypted.png", "lsb", True),
        ("legacy_endian.png", "endian", False),
        ("legacy_endian_encrypted.png", "endian", True),
    ],
)
def test_reads_images_made_by_v3(name, mode, encrypted):
    # these fixtures were made with the original v3 script, password "hunter2"
    path = FIXTURES / name
    found = steganographer.inspect(path)
    assert (found.mode, found.encrypted, found.format.legacy) == (mode, encrypted, encrypted)
    assert steganographer.reveal(path, password="hunter2") == (FIXTURES / "legacy_secret.txt").read_bytes()


@pytest.mark.parametrize("password", [None, "pw"])
def test_lsb_keeps_transparency(tmp_path, secret, password):
    cover = tmp_path / "logo.png"
    image = Image.new("RGBA", (64, 64), (200, 30, 30, 0))
    image.paste((10, 120, 250, 255), (16, 16, 48, 48))
    image.save(cover)

    out = steganographer.hide(cover, secret, tmp_path / "out.png", mode="lsb", password=password)
    result = Image.open(out)
    assert result.mode == "RGBA"
    assert result.getchannel("A").tobytes() == image.getchannel("A").tobytes()
    assert steganographer.reveal(out, password=password) == secret


def test_lsb_palette_image_with_transparency(tmp_path):
    cover = tmp_path / "icon.png"
    image = Image.new("P", (32, 32), 0)
    image.putpalette([0, 0, 0, 255, 255, 255] + [0] * 762)
    image.info["transparency"] = 0
    image.save(cover, transparency=0)

    out = steganographer.hide(cover, b"hello", tmp_path / "out.png", mode="lsb")
    assert Image.open(out).mode == "RGBA"
    assert steganographer.reveal(out) == b"hello"
