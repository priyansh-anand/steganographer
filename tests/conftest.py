import random

import pytest
from PIL import Image


@pytest.fixture
def cover(tmp_path):
    """A 64x48 image filled with noise, like a real photo would be."""
    rng = random.Random(1)
    path = tmp_path / "cover.png"
    Image.frombytes("RGB", (64, 48), bytes(rng.randrange(256) for _ in range(64 * 48 * 3))).save(path)
    return path


@pytest.fixture
def secret():
    return bytes(range(256)) * 4
