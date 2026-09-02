# Python API

```python
import steganographer
```

Every function takes paths as `str` or `pathlib.Path`, and hidden data as `bytes`.

## Contents

- [Hiding and revealing](#hiding-and-revealing)
- [Inspecting and capacity](#inspecting-and-capacity)
- [Signing](#signing)
- [Deniable hiding](#deniable-hiding)
- [Robust mode](#robust-mode)
- [Steganalysis](#steganalysis)
- [Types](#types)
- [Exceptions](#exceptions)

## Hiding and revealing

### `hide`

```python
hide(
    image_path, data, output_path=None, *,
    password=None, mode="endian", filename=None, sign_with=None, adaptive=False,
) -> Path
```

Hides `data` in `image_path`, writes the result to `output_path`, and returns the path it wrote.

| Parameter | Description |
| --- | --- |
| `mode` | `"lsb"` or `"endian"`. For robust mode, use [`hide_robust`](#hide_robust). |
| `password` | Encrypt the data. With `lsb`, the password also scatters it across the image. |
| `filename` | Name stored alongside the data and returned by `reveal_file`. Directory components are stripped. |
| `sign_with` | An `Ed25519PrivateKey` (see [`signing`](#signing)). |
| `adaptive` | Fill textured regions first. Requires `mode="lsb"` and a password. |
| `output_path` | Default: `<stem>_steg0.png` for `lsb`, the input's extension for `endian`. `lsb` needs `.png`, `.bmp`, `.tif` or `.tiff`. |

Raises `CapacityError` if the data doesn't fit, and `ValueError` for an invalid combination of options or a
lossy `lsb` output path.

### `reveal_file`

```python
reveal_file(image_path, *, password=None, signed_by=None) -> Revealed
```

Returns the hidden file's name, contents and signer. A signed file's signature is always checked. Pass an
`Ed25519PublicKey` as `signed_by` to also require a particular signer.

Raises `NoHiddenDataError`, `DecryptionError` or `SignatureError`.

### `reveal`

```python
reveal(image_path, *, password=None) -> bytes
```

Shorthand for `reveal_file(...).data`.

```python
steganographer.hide("cat.png", b"meet at noon", "out.png", mode="lsb", password="hunter2", filename="plan.txt")

steganographer.reveal("out.png", password="hunter2")
# b'meet at noon'

steganographer.reveal_file("out.png", password="hunter2")
# Revealed(name='plan.txt', data=b'meet at noon', signer=None)
```

## Inspecting and capacity

### `inspect`

```python
inspect(image_path, *, password=None) -> HiddenFile | None
```

Describes what's hidden without decrypting it, or returns `None`. Password-protected `lsb` data can only be
found with the password.

```python
found = steganographer.inspect("out.png", password="hunter2")
found.mode, found.encrypted, found.size
# ('lsb', True, 136)
```

`size` is the stored payload size, which includes encryption and header overhead.

### `capacity`

```python
capacity(image_path) -> int
```

The largest unencrypted file, in bytes, that fits in the image in `lsb` mode. A stored file name takes up room
too. Encryption adds about a third plus roughly 100 bytes, see
[How it works](how-it-works.md#capacity).

## Signing

```python
from pathlib import Path
from steganographer import signing
```

| Function | Description |
| --- | --- |
| `signing.load_private_key(path, passphrase=None)` | Load an OpenSSH or PEM Ed25519 private key. Raises `signing.PassphraseRequired` if the key is encrypted and no passphrase was given. |
| `signing.load_public_key(path)` | Load a `.pub` file, an `authorized_keys` style list such as a GitHub `.keys` file (the first `ssh-ed25519` line is used), or PEM. |
| `signing.generate(path, passphrase=None, comment="steganographer")` | Write a new key pair to `path` and `path.pub`. Returns the private key. |
| `signing.fingerprint(key)` | `SHA256:...`, the same format as `ssh-keygen -l`. Accepts a public key or raw bytes, such as `Revealed.signer`. |

```python
key = signing.load_private_key(Path.home() / ".ssh/id_ed25519", passphrase="...")
steganographer.hide("cat.png", b"meet at noon", "out.png", mode="lsb", sign_with=key)

revealed = steganographer.reveal_file("out.png", signed_by=signing.load_public_key("friend.pub"))
signing.fingerprint(revealed.signer)
# 'SHA256:...'
```

A key that can't be read, or isn't Ed25519, raises `signing.KeyFileError`, a subclass of
`SteganographerError`.

## Deniable hiding

### `hide_deniable`

```python
hide_deniable(
    image_path, decoy_data, decoy_password, real_data, real_password, output_path=None, *,
    decoy_filename=None, real_filename=None,
) -> Path
```

Hides two files in one `lsb` image under two different passwords. Both layers are read back and verified
before anything is written. If the decoy wouldn't survive, it raises `CapacityError` and writes nothing. Keep
the real file under about 2–3% of the image's capacity.

### `reveal_decoy`

```python
reveal_decoy(image_path, password) -> tuple[str | None, bytes] | None
```

Returns `(name, data)` for the decoy layer, or `None`. The real file is read with the ordinary `reveal` or
`reveal_file`.

```python
steganographer.hide_deniable("cat.png", b"holiday photos", "decoy-pw", b"the real plan", "real-pw", "out.png")

steganographer.reveal_decoy("out.png", "decoy-pw")  # (None, b'holiday photos')
steganographer.reveal("out.png", password="real-pw")  # b'the real plan'
```

## Robust mode

### `hide_robust`

```python
hide_robust(image_path, data, output_path=None, *, password=None, filename=None) -> Path
```

Hides a short message so it survives JPEG recompression. The output format follows `output_path`'s extension,
and saving straight to `.jpg` works. Raises `CapacityError` if the message is too long. Signing isn't supported
in this mode.

### `reveal_robust`

```python
reveal_robust(image_path, *, password=None) -> Revealed | None
```

Returns `None` if there's no robust payload, and raises `DecryptionError` for a wrong password.

### `robust_capacity`

```python
robust_capacity(width, height) -> int
```

A conservative estimate of the largest unencrypted message for those dimensions.

| Size | `robust_capacity` |
| --- | --- |
| 512 × 512 | 409 bytes |
| 1024 × 768 | 1,305 bytes |
| 1920 × 1080 | 3,503 bytes |
| 4000 × 3000 | 20,457 bytes |

```python
steganographer.hide_robust("photo.jpg", b"a durable note", "share.jpg", filename="note.txt")
steganographer.reveal_robust("share.jpg")
# Revealed(name='note.txt', data=b'a durable note', signer=None)
```

## Steganalysis

```python
from steganographer import analyze

report = analyze.analyze("out.png")
```

`AnalysisReport` fields:

| Field | Description |
| --- | --- |
| `chi_square` | Chi-square p-value over the whole image. Near 1 suggests LSB replacement. |
| `chi_square_profile` | The same test over 20 consecutive windows. |
| `peak_chi_square` | Highest value in the profile, which catches sequential hides in part of the image. |
| `rs` | `RSStats(r_m, s_m, r_neg_m, s_neg_m)`, with a `.discriminant` property. |
| `estimated_fraction` | Rough fraction of `lsb` capacity that looks used, from 0 to 1. |
| `verdict` | `"likely contains hidden data"`, `"suspicious"` or `"no strong signal of hidden data"`. |

This is a rough indicator, not a forensic tool. See [How it works](how-it-works.md#steganalysis).

## Types

### `HiddenFile`

Returned by `inspect`. Has `mode` (`"lsb"` or `"endian"`), `encrypted` (bool) and `size` (payload bytes).

### `Revealed`

A `NamedTuple` of `(name, data, signer)`. `name` is `None` if the image stores no name (made by v3 or older).
`signer` is the signer's raw 32-byte public key, already verified, or `None` if the file is unsigned.

## Exceptions

All of them inherit from `SteganographerError`.

| Exception | Raised when |
| --- | --- |
| `CapacityError` | The data doesn't fit, or a decoy wouldn't survive |
| `NoHiddenDataError` | Nothing readable is hidden in the image (or the password is needed to find it) |
| `DecryptionError` | Wrong password, or the data is corrupted |
| `SignatureError` | Invalid signature, unsigned when `signed_by` was given, or signed by a different key |
| `signing.KeyFileError` | A key file can't be read or isn't Ed25519 |

```python
from steganographer import DecryptionError, NoHiddenDataError

try:
    data = steganographer.reveal("out.png", password=attempt)
except NoHiddenDataError:
    ...
except DecryptionError:
    ...
```
