class SteganographerError(Exception):
    """Base class for every error raised by steganographer."""


class CapacityError(SteganographerError):
    """The file does not fit inside the cover image."""


class NoHiddenDataError(SteganographerError):
    """The image does not carry anything steganographer can read."""


class DecryptionError(SteganographerError):
    """Wrong password, or the hidden data is corrupted."""


class SignatureError(SteganographerError):
    """The file is signed but the signature is invalid, or it isn't signed by the expected key."""
