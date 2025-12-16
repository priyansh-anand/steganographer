import random

import pytest

from steganographer import fec


@pytest.mark.parametrize("size", [0, 1, 50, 191, 192, 500, 5000])
def test_roundtrip(size):
    data = bytes(random.Random(size).randrange(256) for _ in range(size))
    assert fec.decode(fec.encode(data)) == data


@pytest.mark.parametrize("size", [1, 500, 5000])
def test_encoded_size_matches_actual_output(size):
    data = bytes(size)
    assert len(fec.encode(data)) == fec.encoded_size(size)


def test_survives_corruption_within_the_bound():
    data = bytes(random.Random(1).randrange(256) for _ in range(1000))
    encoded = bytearray(fec.encode(data))

    # corrupt up to PARITY_SIZE//2 bytes in every block, spread across the whole thing
    rng = random.Random(2)
    for block_start in range(0, len(encoded), fec.BLOCK_SIZE):
        block = range(block_start, min(block_start + fec.BLOCK_SIZE, len(encoded)))
        for i in rng.sample(list(block), min(fec.PARITY_SIZE // 2, len(block))):
            encoded[i] ^= 0xFF

    assert fec.decode(bytes(encoded)) == data


def test_raises_past_the_correction_bound():
    data = bytes(random.Random(3).randrange(256) for _ in range(200))
    encoded = bytearray(fec.encode(data))

    rng = random.Random(4)
    for i in rng.sample(range(fec.BLOCK_SIZE), fec.PARITY_SIZE // 2 + 1):
        encoded[i] ^= 0xFF

    with pytest.raises(fec.FecError):
        fec.decode(bytes(encoded))


def test_wrong_length_is_not_safe_on_its_own():
    # decode() needs to be given the *exact* number of bytes encode() produced.
    # Extra trailing bytes aren't reliably rejected, they can silently come back
    # as extra garbage appended to otherwise-correct data -- this is why
    # deniable stores the exact blob length in its own separate, redundant
    # marker instead of trusting anything derived from the encoded bytes
    # themselves.
    message = b"the real message"
    encoded = fec.encode(message)
    assert fec.decode(encoded + b"\x00" * 5) != message
