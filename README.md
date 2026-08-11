# Steganographer

[![CI](https://github.com/priyansh-anand/steganographer/actions/workflows/ci.yml/badge.svg)](https://github.com/priyansh-anand/steganographer/actions/workflows/ci.yml)

Hide any file inside an image, optionally encrypted with a password, and get it back out later.

| Original image | Same image with 100k words hidden inside |
| --- | --- |
| ![Original Image](https://i.ibb.co/gPgs2YZ/original-image.png) | ![Modified Image](https://i.imgur.com/T2iifFr.png) |

Can you spot the difference? The image on the right has a text file with 100,000 words hidden in its pixels.

**[Try it in your browser](https://priyansh-anand.github.io/steganographer/)** &mdash; the real package,
including signing, deniable hiding, adaptive placement and `--analyze`, runs entirely client-side via
[Pyodide](https://pyodide.org). Nothing you pick ever leaves the tab, see [`web/`](web/).

## Install

Needs Python 3.12 or newer.

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

Extract it again, it is saved under its original name (`notes.txt`):

```sh
steganographer -e -i cat_steg0.png
```

| Option | |
| --- | --- |
| `-i IMAGE` | input image |
| `-h FILE` | file to hide, or where to save the extracted file when using `-e` (default: its original name) |
| `-o OUTPUT` | output image, defaults to `<image>_steg0.png` next to the input |
| `-e` | extract instead of hide |
| `-m lsb\|endian` | hiding mode, see below (default: `endian`) |
| `-p PASSWORD` | encrypt with this password |
| `-P` | ask for the password instead, so it doesn't end up in your shell history |
| `--info` | show how much fits in an image, and whether it already has something hidden (add `-p`/`-P` for images hidden with a password in lsb mode) |
| `--menu` | interactive menu |

When extracting you don't need to pass the mode. Steganographer figures out how the file was hidden, and asks
for the password if it is encrypted.

### Modes

**`lsb`** hides the file inside the pixels themselves (see [how it works](#how-it-works)). The image looks
the same to the eye. The output has to be a lossless format (PNG, BMP or TIFF), because
JPEG compression would destroy the hidden bits. The input can be anything Pillow can open, including JPEG.

With a password, lsb mode also spreads the data over the whole image in an order that depends on the password,
instead of filling the pixels from the top. Without the password there is no way to even tell that the image
has something hidden in it, `--info` and `-e` only find it when given the password.

**`endian`** appends the file after the end of the image data. Image viewers ignore anything after the end of
the image, so it still opens normally. It works with any format and any file size, but anyone who opens the
image in a hex editor will see it, so always use a password with this mode.

**`robust`** survives the image being re-saved as JPEG, unlike the other two. Small capacity, its own section
below.

## Signing

A password keeps the file secret, but it doesn't tell the person extracting it who hid it, or whether someone
changed it on the way. For that you can sign it with an Ed25519 key. Your existing SSH key works:

```sh
steganographer -i cat.png -h plan.txt -m lsb -P --sign ~/.ssh/id_ed25519
```

The other side checks the signature against your public key. GitHub publishes everyone's public keys, so they
don't even need to ask you for it:

```sh
curl -s https://github.com/<your-username>.keys > you.pub
steganographer -e -i cat_steg0.png -P --verify you.pub
```

With `--verify`, the file is only saved if it was signed by that key and wasn't modified. Without it, a signed
file is still checked and the signer's fingerprint is printed, in the same format as `ssh-keygen -l`.

No SSH key? `steganographer --keygen mykey` creates `mykey` and `mykey.pub`, in the same format ssh-keygen
uses. Only Ed25519 keys are supported, RSA keys are not.

The signature covers the file name and the contents. When a password is used, the signature is encrypted
along with the file, so nobody without the password can see who signed it.

## Deniable hiding

`--decoy` hides two files in the same image under two different passwords: a decoy you can hand over if you're
ever pressured to reveal what's hidden, and a real file that stays invisible without its own password. This
works the same way a [VeraCrypt hidden volume](https://veracrypt.eu) does.

```sh
steganographer -i cat.png -h plan.txt -p realpw --decoy vacation.txt --decoy-password decoypw
```

Extraction needs nothing special, the same `-e` command finds whichever file matches the password you give it:

```sh
steganographer -e -i cat_steg0.png -p decoypw   # gets vacation.txt
steganographer -e -i cat_steg0.png -p realpw    # gets plan.txt
```

The decoy is written first, and the real file is written on top of it in lsb mode's normal scattered order (see
[Encryption](#encryption)). Since the two passwords give independent, unrelated layouts, they land on some of
the same pixels, and the real file always wins there since nothing is written after it. The decoy carries
[Reed-Solomon](https://en.wikipedia.org/wiki/Reed%E2%80%93Solomon_error_correction) parity so it survives that
damage, the same kind of error correction CDs and QR codes use.

This only works up to a point: **keep the real file under about 2-3% of the image's `--info` capacity** for the
decoy to reliably survive being written on top of. Both files are always read back and checked before anything
is written to disk, so `--decoy` never produces an image with an unknown chance of losing the decoy later --
past that point it refuses outright and tells you to use a bigger image or smaller files, rather than silently
gambling on it. There's no way to tune around this: it comes from the same 2 bits per channel that keeps lsb
mode's changes invisible in the first place, see [`fec.py`](src/steganographer/fec.py) for the actual numbers.

Nothing marks the image as carrying a decoy. The real layer, byte for byte, is exactly what you'd get from an
ordinary `steganographer -i ... -h ... -p realpw` with no `--decoy` at all.

## Checking how detectable your image is

`--analyze` runs two classic steganalysis tests against an image and tells you how exposed it looks, instead of
just taking the [Limitations](#limitations) section's word for it:

```sh
steganographer --analyze -i cat_steg0.png
```

```
[*] Chi-square (whole image): 0.000
[*] Chi-square (most suspicious window): 1.000
[*] RS discriminant: -0.0009 (estimated 3% of capacity used)
[!] Verdict: likely contains hidden data
```

- **Chi-square** ([Westfeld & Pfitzmann](https://doi.org/10.1007/10719724_5)) checks whether adjacent byte
  values look suspiciously close to equally common, which is what lsb replacement does to them. It's run over
  20 windows across the image as well as the whole thing, so a file hidden without a password (filled in from
  the top, see [Modes](#modes)) shows up as a spike in the early windows even when the whole-image number stays
  quiet, exactly what "most suspicious window" above is showing for a small, unscattered hide.
- **RS analysis** ([Fridrich, Goljan & Du](https://doi.org/10.1145/1232454.1232466)) flips groups of pixels two
  opposite ways and compares how that changes local smoothness. It doesn't need the chi-square test's kind of
  byte-value imbalance to work, so it's the one that can also say roughly how much of the image's capacity
  looks used, calibrated against synthetic test data (see
  [`analyze.py`](src/steganographer/analyze.py) for exactly how, and its limits).

Neither test is reliable alone, which is why there are two and why both matter to the verdict. Both are more
exact on real photographs, which have natural sensor and compression bias these tests were designed around;
smoother or already-noisy images can read as more suspicious than they really are. Nothing here replaces a
dedicated steganalysis tool, it's meant to answer "would a scattered, password-protected hide actually be
harder to find than a plain one" for this project's own output, not to catch someone else's.

## Adaptive placement

`--adaptive` fills the visually busiest parts of the image first (fine texture, foliage, noisy areas) instead
of spreading the data perfectly uniformly, so a file that only needs part of the capacity never touches the
smooth, flat parts of the image where a couple of flipped low bits would be the most out of place:

```sh
steganographer -i cat.png -h notes.txt -m lsb -P --adaptive
```

On a test image that's half flat and half textured, hiding the same small file with `--adaptive` left the flat
half's `analyze.py` RS statistics completely unchanged, while a normal scattered hide of the same size shifted
them by 0.40 (see `test_adaptive_disturbs_the_flat_half_far_less_than_uniform_scattering` in
[`tests/test_adaptive.py`](tests/test_adaptive.py), which checks this is still true, not just once measured by
hand). A file too big to fit in the busy regions alone spills into the flat ones the same way capacity has
always worked, it doesn't refuse or fail differently.

Extraction is the normal `-e` with the same password, nothing extra to pass. Needs `-m lsb` and a password.

This isn't free: the complexity of a pixel only depends on bits the image already shows, not on the password,
so anyone can recompute the same busy/flat map from the stego image alone and narrow down *where* data is
likely to be, even without the password -- a real, known trade-off of adaptive steganography in general, not a
bug specific to this implementation. It doesn't reveal whether anything is hidden at all or let anyone read it,
and a busy region is still a large area to search, but it's a weaker guarantee than plain scattering's "no
information without the password" at all. See [`adaptive.py`](src/steganographer/adaptive.py) for the details
and how the busy/flat map is computed so it survives being written to reliably.

## Surviving JPEG recompression

`lsb` and `endian` both die the moment an image is re-saved as JPEG, which is what every chat app and social
network does to whatever you send it. `-m robust` survives that:

```sh
steganographer -i photo.jpg -h note.txt -m robust
steganographer -e -i photo_steg0.png          # even after it's been re-compressed and shared around
```

Instead of touching the pixels' low bits (the first thing JPEG throws away), it nudges one mid-frequency DCT
coefficient of each 8×8 luma block onto an even or odd multiple of a step — the same value JPEG's own quantiser
rounds to and keeps. Measured through five rounds of JPEG recompression at quality 40–90 with 4:2:0 chroma
subsampling, it comes back at under 1% bit error, invisibly (PSNR ~41 dB), and [`fec`](src/steganographer/fec.py)'s
Reed-Solomon mops up that last bit. See [`robust.py`](src/steganographer/robust.py) and
[`tests/test_robust.py`](tests/test_robust.py), which check it against real recompression rather than asserting it.

The trade-off is **capacity**: one bit per 8×8 block, so roughly 70 bytes for a 256×256 image, ~400 for
512×512, a few KB for a large photo (a password's encryption overhead eats ~90 bytes of that). This is a mode
for a short message, a URL, a key fingerprint or a signature — not a general file. It also **only survives
re-compression, not resizing, cropping or rotation**, which shift the 8×8 grid it's aligned to. `hide`/`reveal`
via `-e` and the Python API work the same as any other mode.

## Using it from Python

```python
import steganographer

steganographer.hide("cat.png", b"meet at noon", "cat_steg0.png", mode="lsb", password="hunter2")

found = steganographer.inspect("cat_steg0.png")
found.mode, found.encrypted
# ('lsb', True)

steganographer.reveal("cat_steg0.png", password="hunter2")
# b'meet at noon'

# pass filename= to hide() to store a name, and get it back with reveal_file()
steganographer.hide("cat.png", b"meet at noon", "cat_steg0.png", mode="lsb", filename="plan.txt")
steganographer.reveal_file("cat_steg0.png")
# Revealed(name='plan.txt', data=b'meet at noon')

steganographer.capacity("cat.png")  # max bytes that fit with lsb mode

# signing
from steganographer import signing

key = signing.load_private_key("/home/me/.ssh/id_ed25519", passphrase="...")
steganographer.hide("cat.png", b"meet at noon", "cat_steg0.png", mode="lsb", sign_with=key)
steganographer.reveal_file("cat_steg0.png", signed_by=signing.load_public_key("friend.pub"))

# deniable hiding
steganographer.hide_deniable(
    "cat.png",
    b"holiday photos",
    "decoypw",
    b"the real plan",
    "realpw",
    "cat_steg0.png",
)
steganographer.reveal_decoy("cat_steg0.png", "decoypw")  # (None, b'holiday photos')
steganographer.reveal("cat_steg0.png", password="realpw")  # b'the real plan'

# steganalysis
from steganographer import analyze

report = analyze.analyze("cat_steg0.png")
report.chi_square, report.peak_chi_square, report.estimated_fraction, report.verdict
# (0.0, 1.0, 0.03, 'likely contains hidden data')

# adaptive placement
steganographer.hide("cat.png", b"meet at noon", "cat_steg0.png", mode="lsb", password="hunter2", adaptive=True)

# robust mode (survives JPEG recompression)
steganographer.hide_robust("photo.jpg", b"a durable note", "photo_steg0.png", filename="note.txt")
steganographer.reveal_robust("photo_steg0.png")  # Revealed(name='note.txt', data=b'a durable note', ...)
steganographer.robust_capacity(512, 512)  # ~400 bytes
```

`inspect` returns `None` if the image has nothing hidden in it. For lsb mode with a password, pass `password=` to
`inspect` as well, otherwise it can't find anything. Errors are raised as `CapacityError`,
`NoHiddenDataError`, `DecryptionError` and `SignatureError`, all subclasses of `SteganographerError`.

## How it works

It is based on a simple principle: if we change the LSBs (least significant bits) of every pixel, the change
is so small that it can't be noticed by eye.

Each pixel of an RGB image has 3 channels, red, green and blue, each with a value from 0 to 255:

```python
a_pixel = (17, 32, 11)  # (RED, GREEN, BLUE)
```

Steganographer takes 2 bits of the file to hide and puts them in place of the last 2 bits of a channel, then
moves to the next channel. Let's hide `0b100111` in `a_pixel`:

```python
a_pixel = (0b10001, 0b100000, 0b1011)  # binary representation of a_pixel

# RED:   0b10001  -> 0b10010   last 2 bits replaced with 10
# GREEN: 0b100000 -> 0b100001  last 2 bits replaced with 01
# BLUE:  0b1011   -> 0b1011    last 2 bits are already 11, nothing changes

a_pixel = (17, 32, 11)
a_pixel_with_data = (18, 33, 11)
```

A channel changes by at most 3 out of 255, which is invisible. Every pixel holds 6 bits, so the largest file
that fits is:

```python
max_file_size = width * height * 6 // 8 - 15 - len(file_name)  # bytes
```

The 15 bytes are a small header in front of the hidden file: a 4 byte magic number that says which mode and
encryption were used, the 8 byte length of the data, 1 byte of flags and the 2 byte length of the file name. The name is stored
so the file can be extracted without having to remember what it was called. When a password is used, the name
is encrypted along with the contents. `steganographer --info -i image.png` prints the exact
number for an image. Encrypted files take more room: the encrypted data is base64 encoded, so it is about a third
bigger than the original, plus around 100 bytes.

Transparent images keep their alpha channel, data is only hidden in the R, G and B values.

### Encryption

With a password, the file is encrypted with [Fernet](https://cryptography.io/en/latest/fernet/)
(AES-128-CBC with HMAC-SHA256) before it is hidden. The key is derived from the password with scrypt and a
random salt, so the same file and password give different output every time.

In lsb mode the password also picks where the data goes. Bit pair `i` of the hidden data is written to channel
`P(i)`, where `P` is a pseudo random permutation of all the channels in the image, keyed by the password (a
Feistel network, see [`scatter.py`](src/steganographer/scatter.py)). This means small files don't leave all
their changes in the first few rows, and the header that says "something is hidden here" can't be found without
the password.

Versions before 4.0 used the md5 of the password as the key. Images made with them can still be read, but it
is a good idea to hide those files again with the current version.

### Limitations

- Changing the lowest bits adds a bit of noise. Anyone who has the original image, or runs steganalysis tools,
  can tell the image was modified (`--analyze` runs two of the classic ones, see
  [Checking how detectable your image is](#checking-how-detectable-your-image-is)). Never share the original
  image.
- Spreading the data out with a password helps most for small files. The more of the image's capacity you use,
  the more its statistics change, wherever the bits go. Use an image much bigger than the file. `--adaptive`
  (see [Adaptive placement](#adaptive-placement)) concentrates that change where it's least visible instead of
  spreading it uniformly, but the same rule applies once you use enough of the image's capacity that it has to
  spread into flatter areas too.
- Anything that recompresses or resizes the image destroys data hidden with `lsb` mode. Most chat apps and
  social networks do this to uploaded images, so either send the image as a file/document, or use
  [`-m robust`](#surviving-jpeg-recompression), which is built to survive recompression (at a big cost in
  capacity, and still not resizing/cropping).

## Development

```sh
uv run pytest
uv run ruff check .
```

See [CHANGELOG.md](CHANGELOG.md) for what changed between versions.

## License

MIT

**Free Software, Hell Yeah!**
