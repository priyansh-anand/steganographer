# How it works

This page covers what Steganographer does to an image, byte by byte. Each section names the module it
describes, so you can read the source alongside it.

## Contents

- [LSB embedding](#lsb-embedding)
- [Capacity](#capacity)
- [Data layout](#data-layout)
- [Encryption](#encryption)
- [Scattering](#scattering)
- [Adaptive placement](#adaptive-placement)
- [Endian mode](#endian-mode)
- [Robust mode](#robust-mode)
- [Deniable hiding](#deniable-hiding)
- [Signatures](#signatures)
- [Steganalysis](#steganalysis)
- [Compatibility with older versions](#compatibility-with-older-versions)

## LSB embedding

*[`core.py`](../src/steganographer/core.py)*

Every pixel of an RGB image has three 8-bit channels. Replacing the lowest two bits of a channel changes its
value by at most 3 out of 255, which is too small to see.

Each byte of the payload is split into four 2-bit pieces, most significant first, and each piece replaces the
low bits of one channel. Hiding the six bits `10 01 11` in one pixel:

```
            before        after       value
red         0001 0001  -> 0001 0010    17 -> 18
green       0010 0000  -> 0010 0001    32 -> 33
blue        0000 1011  -> 0000 1011    11 -> 11   (already 11)
```

The alpha channel of a transparent image is never touched. Only R, G and B carry data.

## Capacity

Each pixel carries 6 bits, so an image holds `width × height × 6 / 8` bytes. The header and metadata take a
little of that:

```
max file size = width × height × 6 // 8 − 15 − len(file name)      bytes, unencrypted
```

With a password, the payload is a base64 Fernet token, so it grows by about a third, plus around 100 bytes.
The 607,606-byte book in the README demo is 810,268 bytes once encrypted. `steganographer --info` prints the
exact capacity of an image.

| Image | `lsb` capacity |
| --- | --- |
| 512 × 512 | 192 KB |
| 1024 × 768 | 576 KB |
| 1920 × 1080 | 1.5 MB |
| 4000 × 3000 | 8.6 MB |

## Data layout

All integers are big-endian.

```
lsb      magic (4) ‖ length (8) ‖ payload
endian   original image ‖ payload ‖ length (8) ‖ magic (4)

payload  = flags (1) ‖ name length (2) ‖ name (UTF-8)
           ‖ [signer public key (32) ‖ signature (64)]      only if flags & 1
           ‖ file contents
```

With a password, the whole payload is encrypted, so the file name and the signer's identity are hidden too.

The magic number identifies the mode and the encryption scheme:

| Magic | Mode | Encrypted | Notes |
| --- | --- | --- | --- |
| `0xDEADBEEF` | lsb | No | Sequential, from the top-left pixel |
| `0x1337BEEF` | lsb | Yes | Scattered by password |
| `0xADA97EED` | lsb | Yes | Adaptive placement |
| `0x5AFEBEEF` | endian | No | |
| `0xBABEBEEF` | endian | Yes | |
| `0x…C0DE` | any | any | Written by v3 and older, read only |

## Encryption

*[`crypto.py`](../src/steganographer/crypto.py)*

The payload is encrypted with [Fernet](https://cryptography.io/en/latest/fernet/): AES-128-CBC with an
HMAC-SHA256 tag, so tampering or a wrong password is detected rather than producing garbage. The key comes from
scrypt (N = 2¹⁵, r = 8, p = 1) with a random 16-byte salt:

```
encrypted payload = salt (16) ‖ Fernet token
```

A fresh salt means the same file and password produce different output every time.

## Scattering

*[`scatter.py`](../src/steganographer/scatter.py)*

Without a password, `lsb` data fills channels in order from the top-left pixel. A small file then only changes
the first few rows, which shows up in the image's statistics, and anyone can read the header.

With a password, 2-bit piece `i` goes to channel `P(i)`, where `P` is a pseudorandom permutation of every
channel in the image, keyed by the password. `P` is a 4-round Feistel network over the smallest power of 4 that
covers the channel count, with cycle-walking to stay in range. Any position can be computed directly, with no
shuffled list of millions of indices, and the integer-only arithmetic gives identical results on every platform.

The header is scattered too, so without the password there's nothing to find. The permutation key is derived
from the password with a fixed salt. It can't use a random one, because the salt would have to be stored in
the image, and you'd need the key to find it.

The difference image at the top of the [README](../README.md) shows the result: the changes are spread evenly
across the whole frame.

## Adaptive placement

*[`adaptive.py`](../src/steganographer/adaptive.py)*

`--adaptive` ranks pixels by local complexity, meaning how much they differ from their four neighbours. It
then splits them into 8 equal tiers, busiest first, and gives each tier its own password-keyed permutation.
Data fills the busiest tier first and only spills into flatter tiers when it has to.

Complexity is computed from the upper 6 bits of each channel only, the bits embedding never touches. The stego
image therefore produces exactly the same ranking as the cover did, which is what lets extraction find the
data again. All of this uses integer arithmetic, so it's exact across platforms.

On a test image that's half flat and half textured, a small adaptive hide left the flat half's RS statistics
completely unchanged, while a uniformly scattered hide shifted them by 0.40
([`test_adaptive.py`](../tests/test_adaptive.py)).

The trade-off: since the ranking depends only on visible bits, anyone can compute which regions are likely to
carry data. The password still protects the exact positions and the contents, and nobody can tell whether
anything is hidden at all. See the [security model](security.md#adaptive-placement).

## Endian mode

The payload and a 12-byte trailer are appended after the image's own data. Decoders stop at the image's end
marker, so the file still opens normally in any viewer, in any format. Extraction reads the trailer from the
last 12 bytes.

This is easy to detect: the file is larger than its pixels justify, and the trailer is plainly visible in a hex
editor. Any re-encoding drops the appended bytes. Always use a password.

## Robust mode

*[`robust.py`](../src/steganographer/robust.py), [`fec.py`](../src/steganographer/fec.py)*

JPEG compression throws away the low-order detail that `lsb` hides in. Robust mode works with the codec
instead:

1. The image is converted to YCbCr and the luma channel is split into 8×8 blocks, the same grid JPEG uses.
2. Each block gets a DCT, and one mid-frequency coefficient, `(2, 2)`, is rounded to a multiple of 16.
   An even multiple encodes a 0 and an odd multiple a 1. This is quantisation index modulation (QIM).
3. JPEG's quantiser rounds coefficients to multiples of its own step. A step of 16 is coarse enough that
   recompression at quality 40 or above leaves the parity intact.
4. The data is protected by Reed-Solomon codes (32 parity bytes per 255-byte block), which correct the few
   bits that still flip.

```
robust  RS(magic (4) ‖ blob length (4)) ‖ RS(payload, maybe encrypted)       one bit per 8×8 block
```

Measured in [`test_robust.py`](../tests/test_robust.py): after five rounds of recompression at quality 40–90
with 4:2:0 chroma subsampling, fewer than 1% of bits flip before error correction. Image quality stays high
(PSNR about 41 dB).

Resizing, cropping and rotation move the 8×8 grid, so they destroy the data. Capacity is one bit per block,
before error correction.

## Deniable hiding

*[`deniable.py`](../src/steganographer/deniable.py)*

A deniable image carries two independent `lsb` layers:

1. **The decoy** is written first, scattered by its own password and protected by heavy Reed-Solomon parity
   (128 bytes per 255-byte block). A small marker describing its length is repeated 15 times and read back by
   majority vote.
2. **The real file** is written on top with an ordinary encrypted `lsb` hide. The two permutations are
   unrelated, so the real file overwrites some of the decoy's channels, and the decoy's parity repairs them.

Before the output is written, both layers are read back in a temporary directory. If the decoy wouldn't
survive, the call fails with `CapacityError` and nothing is written. In practice, the real file must stay under
about 2–3% of the image's capacity.

The real layer is byte-for-byte what a normal `-p` hide produces, so nothing indicates that a second layer
exists.

## Signatures

*[`signing.py`](../src/steganographer/signing.py)*

Signatures are Ed25519 over `context ‖ name length ‖ name ‖ contents`, with a fixed domain-separation context
string. The signer's 32-byte public key and the 64-byte signature are stored in the payload. When a password is
used, they're encrypted along with everything else, so the signer's identity stays private.

Keys are standard OpenSSH or PEM files, so an existing `~/.ssh/id_ed25519` works. Fingerprints use the same
`SHA256:` format as `ssh-keygen -l`.

## Steganalysis

*[`analyze.py`](../src/steganographer/analyze.py)*

`--analyze` combines two classic, independent tests.

**Chi-square attack** ([Westfeld & Pfitzmann, 1999](https://doi.org/10.1007/10719724_5)). Replacing low bits
with random data pushes each pair of byte values (2k, 2k+1) toward equal frequency. The test measures how close
the pairs are, over the whole image and over 20 consecutive windows. The windows catch sequential hides that
only touch the top of an image. It only has something to find if the cover image was unevenly distributed to
begin with, which is usually true of real photographs.

**RS analysis** ([Fridrich, Goljan & Du, 2001](https://doi.org/10.1145/1232454.1232466)). This test flips pixel
groups two opposite ways and counts how often local noise rises ("regular") or falls ("singular"). Natural
images show a consistent gap between the two, and LSB replacement erodes it. The size of the gap is mapped to a
rough "fraction of capacity used" through a calibration curve built from synthetic embeddings.

| Verdict | Condition |
| --- | --- |
| likely contains hidden data | a chi-square value > 0.9, or estimated fraction > 50% |
| suspicious | a chi-square value > 0.5, or estimated fraction > 15% |
| no strong signal of hidden data | otherwise |

Both tests are heuristics. Smooth, heavily processed or previously compressed images can read as suspicious with
nothing hidden, so compare against the cover image rather than trusting a single verdict. The tool is meant to
compare hiding strategies on your own output, not to replace forensic tools.

## Compatibility with older versions

Version 4.0 reads images made by v3 and older, including their MD5-derived encryption keys. Those images store
no file name, so pass `-h` when extracting. New images always use scrypt, and v3 can't read them. Re-hide old
files with the current version.
