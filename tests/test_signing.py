import shutil
import subprocess
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import steganographer
from steganographer import core, signing
from steganographer.cli import main
from steganographer.errors import SignatureError

needs_ssh_keygen = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen not installed")


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


@pytest.mark.parametrize("mode", ["lsb", "endian"])
@pytest.mark.parametrize("password", [None, "pw"])
def test_signed_roundtrip(cover, tmp_path, key, mode, password):
    out = steganographer.hide(cover, b"data", tmp_path / "out.png", mode=mode, password=password, sign_with=key)

    revealed = steganographer.reveal_file(out, password=password, signed_by=key.public_key())
    assert revealed.data == b"data"
    assert revealed.signer == signing.raw(key.public_key())


def test_unsigned_has_no_signer(cover, tmp_path):
    out = steganographer.hide(cover, b"data", tmp_path / "out.png")
    assert steganographer.reveal_file(out).signer is None


def test_signed_by_someone_else(cover, tmp_path, key):
    out = steganographer.hide(cover, b"data", tmp_path / "out.png", sign_with=key)
    with pytest.raises(SignatureError, match="different key"):
        steganographer.reveal_file(out, signed_by=Ed25519PrivateKey.generate().public_key())


def test_expected_signature_missing(cover, tmp_path, key):
    out = steganographer.hide(cover, b"data", tmp_path / "out.png")
    with pytest.raises(SignatureError, match="not signed"):
        steganographer.reveal_file(out, signed_by=key.public_key())


@pytest.mark.parametrize("where", ["name", "data"])
def test_tampering_is_detected(key, where):
    payload = bytearray(core._pack("notes.txt", b"pay alice 10", key))
    index = payload.index(b"notes") if where == "name" else payload.index(b"10")
    payload[index] ^= 1
    with pytest.raises(SignatureError):
        core._unpack(bytes(payload))


def test_signer_is_hidden_when_encrypted(cover, tmp_path, key):
    out = steganographer.hide(cover, b"data", tmp_path / "out.png", mode="endian", password="pw", sign_with=key)
    assert signing.raw(key.public_key()) not in out.read_bytes()


def test_generate_and_load(tmp_path):
    path = tmp_path / "id"
    key = signing.generate(path, "pp")

    assert (path.stat().st_mode & 0o777 == 0o600) or sys.platform == "win32"
    with pytest.raises(signing.PassphraseRequired):
        signing.load_private_key(path)
    with pytest.raises(signing.KeyFileError):
        signing.load_private_key(path, "wrong")
    assert signing.raw(signing.load_private_key(path, "pp").public_key()) == signing.raw(key.public_key())
    assert signing.raw(signing.load_public_key(tmp_path / "id.pub")) == signing.raw(key.public_key())

    with pytest.raises(signing.KeyFileError, match="exists"):
        signing.generate(path)


def test_public_key_from_a_list_of_keys(tmp_path, key):
    # what https://github.com/<user>.keys looks like when there are several keys
    rsa_line = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .public_key()
        .public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    )
    ed_line = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    keys = tmp_path / "user.keys"
    keys.write_bytes(rsa_line + b"\n" + ed_line + b"\n")

    assert signing.raw(signing.load_public_key(keys)) == signing.raw(key.public_key())


def test_rsa_keys_are_rejected(tmp_path):
    path = tmp_path / "id_rsa"
    path.write_bytes(
        rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()
        )
    )
    with pytest.raises(signing.KeyFileError, match="not an Ed25519"):
        signing.load_private_key(path)


@needs_ssh_keygen
def test_works_with_ssh_keygen_keys(tmp_path):
    path = tmp_path / "id_ed25519"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "secret", "-f", str(path)], check=True)

    key = signing.load_private_key(path, "secret")
    assert signing.raw(signing.load_public_key(f"{path}.pub")) == signing.raw(key.public_key())

    listed = subprocess.run(["ssh-keygen", "-lf", f"{path}.pub"], check=True, capture_output=True, text=True)
    assert signing.fingerprint(key.public_key()) == listed.stdout.split()[1]


def test_cli_sign_and_verify(cover, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("steganographer.cli.getpass", lambda prompt: "")
    secret = tmp_path / "plan.txt"
    secret.write_text("meet at noon")
    out = tmp_path / "out.png"

    assert main(["--keygen", str(tmp_path / "me")]) == 0
    assert main(["--keygen", str(tmp_path / "someone")]) == 0
    assert main(["-i", str(cover), "-h", str(secret), "-o", str(out), "-m", "lsb", "--sign", str(tmp_path / "me")]) == 0

    extracted = tmp_path / "extracted.txt"
    assert main(["-e", "-i", str(out), "-h", str(extracted), "--verify", str(tmp_path / "me.pub")]) == 0
    assert extracted.read_text() == "meet at noon"
    assert "matches the key you gave" in capsys.readouterr().out

    # a signature from the wrong person must not produce a file
    wrong = tmp_path / "wrong.txt"
    assert main(["-e", "-i", str(out), "-h", str(wrong), "--verify", str(tmp_path / "someone.pub")]) == 1
    assert not wrong.exists()
