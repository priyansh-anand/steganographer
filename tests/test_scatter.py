import numpy as np
import pytest

from steganographer import scatter

KEY = bytes(range(scatter.KEY_SIZE))


@pytest.mark.parametrize("size", [1, 2, 3, 4, 5, 17, 1000, 4096, 12345])
def test_is_a_permutation(size):
    positions = scatter.Permutation(KEY, size).positions(0, size)
    assert sorted(positions.tolist()) == list(range(size))


def test_chunks_match_one_call(monkeypatch):
    monkeypatch.setattr(scatter, "CHUNK", 7)
    order = scatter.Permutation(KEY, 1000)
    chunked = np.concatenate([p for _, _, p in order.chunks(100)])
    assert (chunked == order.positions(0, 100)).all()


def test_depends_on_key():
    a = scatter.Permutation(KEY, 10000).positions(0, 100)
    b = scatter.Permutation(bytes(scatter.KEY_SIZE), 10000).positions(0, 100)
    assert (a != b).any()


def test_stable_across_versions():
    # images hidden with a password must stay readable forever, so the order
    # must never change. If this fails, something broke compatibility.
    positions = scatter.Permutation(KEY, 1_000_000).positions(0, 8)
    assert positions.tolist() == [300675, 467987, 608615, 247293, 488379, 439524, 368847, 710373]
