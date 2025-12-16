from pathlib import Path

import pytest

from steganographer import inspect
from steganographer.cli import main


@pytest.fixture
def secret_file(tmp_path, secret):
    path = tmp_path / "secret.bin"
    path.write_bytes(secret)
    return path


def test_hide_and_extract(cover, secret_file, tmp_path):
    out = tmp_path / "out.png"
    extracted = tmp_path / "extracted.bin"

    assert main(["-i", str(cover), "-h", str(secret_file), "-o", str(out), "-m", "lsb", "-p", "pw"]) == 0
    assert main(["-e", "-i", str(out), "-h", str(extracted), "-p", "pw"]) == 0
    assert extracted.read_bytes() == secret_file.read_bytes()


def test_default_output_next_to_input(cover, secret_file):
    assert main(["-i", str(cover), "-h", str(secret_file), "-m", "lsb"]) == 0
    assert (cover.parent / "cover_steg0.png").exists()


def test_prompts_for_password_when_extracting(cover, secret_file, tmp_path, monkeypatch):
    out = tmp_path / "out.png"
    main(["-i", str(cover), "-h", str(secret_file), "-o", str(out), "-p", "pw"])

    monkeypatch.setattr("steganographer.cli.getpass", lambda prompt: "pw")
    assert main(["-e", "-i", str(out), "-h", str(tmp_path / "x.bin")]) == 0


def test_mismatched_password_confirmation(cover, secret_file, monkeypatch):
    answers = iter(["one", "two"])
    monkeypatch.setattr("steganographer.cli.getpass", lambda prompt: next(answers))
    assert main(["-i", str(cover), "-h", str(secret_file), "-P"]) == 1


def test_wrong_password_exit_code(cover, secret_file, tmp_path, capsys):
    out = tmp_path / "out.png"
    main(["-i", str(cover), "-h", str(secret_file), "-o", str(out), "-p", "right"])

    assert main(["-e", "-i", str(out), "-h", str(tmp_path / "x.bin"), "-p", "wrong"]) == 1
    assert "wrong password" in capsys.readouterr().err


def test_info(cover, capsys):
    assert main(["--info", "-i", str(cover)]) == 0
    assert "No hidden file" in capsys.readouterr().out


def test_usage_without_arguments(capsys):
    assert main([]) == 2
    assert "usage" in capsys.readouterr().out


def test_menu_lsb_option(cover, secret_file, tmp_path, monkeypatch):
    out = tmp_path / "menu.png"
    answers = iter(["1", str(cover), str(secret_file), str(out), "1"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr("steganographer.cli.getpass", lambda prompt: "")

    assert main(["--menu"]) == 0
    assert inspect(out).mode == "lsb"


def test_extract_uses_original_file_name(cover, secret_file, tmp_path, monkeypatch):
    out = tmp_path / "out.png"
    main(["-i", str(cover), "-h", str(secret_file), "-o", str(out), "-m", "lsb"])

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert main(["-e", "-i", str(out)]) == 0
    assert (elsewhere / "secret.bin").read_bytes() == secret_file.read_bytes()

    # don't overwrite a file that is already there
    assert main(["-e", "-i", str(out)]) == 1


def test_extract_legacy_image_needs_a_path(capsys):
    legacy = Path(__file__).parent / "fixtures" / "legacy_lsb.png"
    assert main(["-e", "-i", str(legacy)]) == 1
    assert "pass -h" in capsys.readouterr().err


@pytest.fixture
def big_cover(tmp_path):
    import random

    from PIL import Image

    rng = random.Random(9)
    path = tmp_path / "big_cover.png"
    Image.frombytes("RGB", (300, 300), bytes(rng.randrange(256) for _ in range(300 * 300 * 3))).save(path)
    return path


def test_deniable_hide_and_extract_both_layers(big_cover, tmp_path):
    decoy_file = tmp_path / "vacation.txt"
    decoy_file.write_bytes(b"holiday snaps, nothing interesting here")
    real_file = tmp_path / "plan.txt"
    real_file.write_bytes(b"the actual plan")
    out = tmp_path / "out.png"

    assert (
        main(
            [
                "-i",
                str(big_cover),
                "-h",
                str(real_file),
                "-p",
                "realpw",
                "--decoy",
                str(decoy_file),
                "--decoy-password",
                "decoypw",
                "-o",
                str(out),
            ]
        )
        == 0
    )

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    import os

    old = os.getcwd()
    try:
        os.chdir(elsewhere)
        assert main(["-e", "-i", str(out), "-p", "decoypw"]) == 0
        assert (elsewhere / "vacation.txt").read_bytes() == decoy_file.read_bytes()

        assert main(["-e", "-i", str(out), "-p", "realpw"]) == 0
        assert (elsewhere / "plan.txt").read_bytes() == real_file.read_bytes()
    finally:
        os.chdir(old)


def test_deniable_needs_lsb_mode(big_cover, tmp_path):
    decoy_file = tmp_path / "decoy.txt"
    decoy_file.write_bytes(b"decoy")
    real_file = tmp_path / "real.txt"
    real_file.write_bytes(b"real")

    assert (
        main(
            [
                "-i",
                str(big_cover),
                "-h",
                str(real_file),
                "-p",
                "realpw",
                "--decoy",
                str(decoy_file),
                "--decoy-password",
                "decoypw",
                "-m",
                "endian",
            ]
        )
        == 1
    )


def test_deniable_refuses_when_decoy_would_not_survive(big_cover, tmp_path, capsys):
    decoy_file = tmp_path / "decoy.txt"
    decoy_file.write_bytes(b"small decoy")
    real_file = tmp_path / "real.txt"
    real_file.write_bytes(b"r" * 40000)  # far past the safe fraction of big_cover's capacity
    out = tmp_path / "out.png"

    assert (
        main(
            [
                "-i",
                str(big_cover),
                "-h",
                str(real_file),
                "-p",
                "realpw",
                "--decoy",
                str(decoy_file),
                "--decoy-password",
                "decoypw",
                "-o",
                str(out),
            ]
        )
        == 1
    )
    assert not out.exists()
    assert "survive" in capsys.readouterr().err
