"""
Password based encryption for hidden payloads.

Payloads are encrypted with Fernet (AES-128-CBC + HMAC-SHA256). The key is
derived from the password with scrypt and a random 16 byte salt, which is
stored in front of the Fernet token:

    salt (16 bytes) || fernet token

Images made by v3 and older used md5(password) as the key with no salt.
Those can still be decrypted with ``legacy=True``, but nothing new is ever
written that way.
"""

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .errors import DecryptionError

SALT_SIZE = 16

# ~32 MiB of memory and well under a second on a laptop
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1


def derive_key(password: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def order_key(password: str, size: int) -> bytes:
    """
    Key for the order in which lsb mode spreads data over the image. It
    can't use a random salt, since the salt would have to be stored in the
    image and we'd need the key to find it, so the salt is fixed and the
    key only depends on the password.
    """
    kdf = Scrypt(salt=b"steganographer lsb order", length=size, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return kdf.derive(password.encode())


def legacy_key(password: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.md5(password.encode()).hexdigest().encode())


def encrypt(data: bytes, password: str) -> bytes:
    salt = os.urandom(SALT_SIZE)
    return salt + Fernet(derive_key(password, salt)).encrypt(data)


def decrypt(data: bytes, password: str, legacy: bool = False) -> bytes:
    if legacy:
        key, token = legacy_key(password), data
    else:
        salt, token = data[:SALT_SIZE], data[SALT_SIZE:]
        key = derive_key(password, salt)

    try:
        return Fernet(key).decrypt(token)
    except InvalidToken:
        raise DecryptionError("wrong password or corrupted data") from None
