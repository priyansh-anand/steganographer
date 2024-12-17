# Steganographer

[![CI](https://github.com/priyansh-anand/steganographer/actions/workflows/ci.yml/badge.svg)](https://github.com/priyansh-anand/steganographer/actions/workflows/ci.yml)

Hide any file inside an image, optionally encrypted with a password, and get it back out later.

| Original image | Same image with 100k words hidden inside |
| --- | --- |
| ![Original Image](https://i.ibb.co/gPgs2YZ/original-image.png) | ![Modified Image](https://i.imgur.com/T2iifFr.png) |

Can you spot the difference? The image on the right has a text file with 100,000 words hidden in its pixels.

## Install

With [uv](https://docs.astral.sh/uv/):

```sh
uv tool install git+https://github.com/priyansh-anand/steganographer
```

or with pip:

```sh
pip install git+https://github.com/priyansh-anand/steganographer
```

Either one gives you a `steganographer` command. To try it without installing anything:

```sh
uvx --from git+https://github.com/priyansh-anand/steganographer steganographer --help
```

Running it from a clone with `python3 steganographer.py` still works too, after
`pip install -r requirements.txt`.

## Usage

Hide a file:

```sh
steganographer -i cat.png -h notes.txt -m lsb -P
```

Extract it again:

```sh
steganographer -e -i cat_steg0.png -h notes.txt
```

| Option | |
| --- | --- |
| `-i IMAGE` | input image |
| `-h FILE` | file to hide, or where to save the extracted file when using `-e` |
| `-o OUTPUT` | output image, defaults to `<image>_steg0.png` next to the input |
| `-e` | extract instead of hide |
| `-m lsb\|endian` | hiding mode, see below (default: `endian`) |
| `-p PASSWORD` | encrypt with this password |
| `-P` | ask for the password instead, so it doesn't end up in your shell history |
| `--info` | show how much fits in an image, and whether it already has something hidden |
| `--menu` | interactive menu |

When extracting you don't need to pass the mode. Steganographer figures out how the file was hidden, and asks
for the password if it is encrypted.

### Modes

**`lsb`** hides the file inside the pixels themselves (see [how it works](#how-it-works)). The image looks
the same to the eye. The output has to be a lossless format (PNG, BMP or TIFF), because
JPEG compression would destroy the hidden bits. The input can be anything Pillow can open, including JPEG.

**`endian`** appends the file after the end of the image data. Image viewers ignore anything after the end of
the image, so it still opens normally. It works with any format and any file size, but anyone who opens the
image in a hex editor will see it, so always use a password with this mode.

## Using it from Python

```python
import steganographer

steganographer.hide("cat.png", b"meet at noon", "cat_steg0.png", mode="lsb", password="hunter2")

found = steganographer.inspect("cat_steg0.png")
found.mode, found.encrypted, found.size
# ('lsb', True, 116)

steganographer.reveal("cat_steg0.png", password="hunter2")
# b'meet at noon'

steganographer.capacity("cat.png")  # max bytes that fit with lsb mode
```

`inspect` returns `None` if the image has nothing hidden in it. Errors are raised as `CapacityError`,
`NoHiddenDataError` and `DecryptionError`, all subclasses of `SteganographerError`.

## How it works

It is based on a simple principle: if we change the LSBs (least significant bits) of every pixel, the change
is so small that it can't be noticed by eye.

Each pixel of an RGB image has 3 channels, red, green and blue, each with a value from 0 to 255:

```python
a_pixel = (17, 32, 11)     # (RED, GREEN, BLUE)
```

Steganographer takes 2 bits of the file to hide and puts them in place of the last 2 bits of a channel, then
moves to the next channel. Let's hide `0b100111` in `a_pixel`:

```python
a_pixel = (0b10001, 0b100000, 0b1011)   # binary representation of a_pixel

# RED:   0b10001  -> 0b10010   last 2 bits replaced with 10
# GREEN: 0b100000 -> 0b100001  last 2 bits replaced with 01
# BLUE:  0b1011   -> 0b1011    last 2 bits are already 11, nothing changes

a_pixel           = (17, 32, 11)
a_pixel_with_data = (18, 33, 11)
```

A channel changes by at most 3 out of 255, which is invisible. Every pixel holds 6 bits, so the largest file
that fits is:

```python
max_file_size = width * height * 6 // 8 - 12   # bytes
```

The 12 bytes are a small header in front of the hidden file: a 4 byte magic number that says which mode and
encryption were used, and the 8 byte length of the file. `steganographer --info -i image.png` prints the exact
number for an image. Encrypted files take more room: the encrypted data is base64 encoded, so it is about a third
bigger than the original, plus around 100 bytes.

Images with transparency are converted to RGB, so the alpha channel is dropped.

### Encryption

With a password, the file is encrypted with [Fernet](https://cryptography.io/en/latest/fernet/)
(AES-128-CBC with HMAC-SHA256) before it is hidden. The key is derived from the password with scrypt and a
random salt, so the same file and password give different output every time.

Versions before 4.0 used the md5 of the password as the key. Images made with them can still be read, but it
is a good idea to hide those files again with the current version.

### Limitations

- Changing the lowest bits adds a bit of noise. Anyone who has the original image, or runs steganalysis tools,
  can tell the image was modified. Never share the original image.
- Anything that recompresses or resizes the image destroys data hidden with `lsb` mode. Most chat apps and
  social networks do this to uploaded images, so send the image as a file/document instead.

## Development

```sh
uv run pytest
uv run ruff check .
```

See [CHANGELOG.md](CHANGELOG.md) for what changed between versions.

## License

MIT

**Free Software, Hell Yeah!**
