"""
Ed25519 signatures, so whoever extracts a file can check who hid it and that
it wasn't changed on the way.

Keys are regular OpenSSH keys, so an existing ~/.ssh/id_ed25519 works, and
anyone's public key can be taken from https://github.com/<user>.keys. PEM
keys work as well.
"""

import base64
import hashlib
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .errors import SignatureError, SteganographerError

PUBLIC_KEY_SIZE = 32
SIGNATURE_SIZE = 64

# prefixed to everything we sign, so a signature made here can't be passed
# off as a signature over something else made with the same key
CONTEXT = b"steganographer signature v1\0"


class KeyFileError(SteganographerError):
    """A key file can't be read, or isn't an Ed25519 key."""


class PassphraseRequired(KeyFileError):
    """The private key is encrypted and no passphrase was given."""


def load_private_key(path: str | Path, passphrase: str | None = None) -> Ed25519PrivateKey:
    data = Path(path).read_bytes()
    secret = passphrase.encode() if passphrase else None
    try:
        if b"OPENSSH PRIVATE KEY" in data:
            key = serialization.load_ssh_private_key(data, secret)
        else:
            key = serialization.load_pem_private_key(data, secret)
    except TypeError as e:
        # raised both for "needs a password" and "doesn't need one"
        if secret is None:
            raise PassphraseRequired(f"{path} is protected with a passphrase") from e
        raise KeyFileError(f"{path}: {e}") from e
    except ValueError as e:
        raise KeyFileError(f"can't read {path}, wrong passphrase or not a private key") from e
    except UnsupportedAlgorithm as e:
        raise KeyFileError(f"can't read {path}: {e}") from e

    if not isinstance(key, Ed25519PrivateKey):
        raise KeyFileError(f"{path} is not an Ed25519 key (make one with ssh-keygen -t ed25519)")
    return key


def load_public_key(path: str | Path) -> Ed25519PublicKey:
    """
    Read a public key from a .pub file, an authorized_keys style list (the
    first ssh-ed25519 line is used) or a PEM file.
    """
    data = Path(path).read_bytes()
    try:
        if b"BEGIN PUBLIC KEY" in data:
            key = serialization.load_pem_public_key(data)
        else:
            line = next((line for line in data.splitlines() if line.startswith(b"ssh-ed25519 ")), None)
            if line is None:
                raise KeyFileError(f"no ssh-ed25519 key found in {path}")
            key = serialization.load_ssh_public_key(line)
    except (ValueError, UnsupportedAlgorithm) as e:
        raise KeyFileError(f"can't read {path}: {e}") from e

    if not isinstance(key, Ed25519PublicKey):
        raise KeyFileError(f"{path} is not an Ed25519 key")
    return key


def raw(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def fingerprint(key: Ed25519PublicKey | bytes) -> str:
    """Same format as ``ssh-keygen -l`` prints, ``SHA256:`` followed by unpadded base64."""
    if isinstance(key, bytes):
        key = Ed25519PublicKey.from_public_bytes(key)
    blob = key.public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).split()[1]
    digest = hashlib.sha256(base64.b64decode(blob)).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


def generate(path: str | Path, passphrase: str | None = None, comment: str = "steganographer") -> Ed25519PrivateKey:
    """Write a new key pair to ``path`` and ``path.pub``, the same way ssh-keygen does."""
    path = Path(path)
    if path.exists() or path.with_name(path.name + ".pub").exists():
        raise KeyFileError(f"{path} already exists")

    key = Ed25519PrivateKey.generate()
    encryption = (
        serialization.BestAvailableEncryption(passphrase.encode()) if passphrase else serialization.NoEncryption()
    )
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, encryption)
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)

    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(private)
    path.with_name(path.name + ".pub").write_bytes(public + b" " + comment.encode() + b"\n")
    return key


def sign(key: Ed25519PrivateKey, message: bytes) -> bytes:
    """Returns the signer's public key followed by the signature."""
    return raw(key.public_key()) + key.sign(CONTEXT + message)


def verify(public_key: bytes, signature: bytes, message: bytes) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, CONTEXT + message)
    except (InvalidSignature, ValueError):
        raise SignatureError("the signature doesn't match, the file was changed or the signature is fake") from None
