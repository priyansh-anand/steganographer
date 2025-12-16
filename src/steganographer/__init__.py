"""
Steganographer - hide files inside images.

    >>> import steganographer
    >>> steganographer.hide("cat.png", b"secret", "cat_steg0.png", mode="lsb", password="hunter2")
    PosixPath('cat_steg0.png')
    >>> steganographer.reveal("cat_steg0.png", password="hunter2")
    b'secret'

Written by Priyansh Anand - https://github.com/priyansh-anand/steganographer
"""

__version__ = "4.0.0"

from .core import HiddenFile, Revealed, capacity, hide, inspect, reveal, reveal_file  # noqa: E402
from .deniable import hide_deniable, reveal_decoy  # noqa: E402
from .errors import (  # noqa: E402
    CapacityError,
    DecryptionError,
    NoHiddenDataError,
    SignatureError,
    SteganographerError,
)

__all__ = [
    "CapacityError",
    "DecryptionError",
    "HiddenFile",
    "NoHiddenDataError",
    "Revealed",
    "SignatureError",
    "SteganographerError",
    "capacity",
    "hide",
    "hide_deniable",
    "inspect",
    "reveal",
    "reveal_decoy",
    "reveal_file",
]
