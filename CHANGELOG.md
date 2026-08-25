# Changelog

## 4.0.0

### Changed

- Needs Python 3.12 or newer.
- The code is now a package under `src/steganographer`, installable with pip or uv, with a `steganographer`
  command and a Python API (`hide`, `reveal`, `inspect`, `capacity`). `python3 steganographer.py` still works.
- Passwords are turned into keys with scrypt and a random salt instead of md5. Images made with older versions
  can still be decrypted.
- LSB mode is around 4-5x faster on large images.
- Transparent images keep their alpha channel in lsb mode instead of being flattened to RGB.
- The mode is detected automatically when extracting.
- Endian mode no longer requires a `.png` output, it works with any image format.
- lsb mode accepts BMP and TIFF output as well as PNG, and refuses lossy formats instead of silently
  writing an image the file can't be recovered from.
- Errors go to stderr and the command exits with a non-zero status.
- Because of the stored file name, images made with 4.0 can't be read by v3 or older. Images made with older
  versions can still be read by 4.0.

### Added

- `-m robust` hides a short message that survives the image being re-saved as JPEG, which destroys `lsb` and
  `endian` data (chat apps and social networks recompress everything). It modulates a mid-frequency DCT
  coefficient of each 8x8 luma block (QIM) rather than the pixels' low bits, and Reed-Solomon mops up the
  residual error. Low capacity (about one bit per 8x8 block) and same-dimensions only (not resize/crop). New
  `robust` module, `-m robust`, and `hide_robust`/`reveal_robust`/`robust_capacity` in the Python API. Measured
  against real repeated recompression in `tests/test_robust.py`.
- A browser demo at [priyansh-anand.github.io/steganographer](https://priyansh-anand.github.io/steganographer/),
  running the real package client-side via Pyodide, no server involved: hide/reveal in every mode (lsb, endian
  and robust), signing, deniable hiding, adaptive placement and `--analyze`, plus a Keys tab to generate an
  Ed25519 pair without the private key ever leaving the tab. New `web/` directory and
  `.github/workflows/pages.yml`, deploying on every push to `master`.
- `--adaptive` (lsb mode with a password) fills the visually busiest parts of the image first instead of
  scattering uniformly, so a file that fits in the busy regions alone never touches the flat, low-noise parts
  where a change would stand out the most. Verified with `--analyze`: on a half flat, half textured test image,
  a small adaptive hide left the flat half's RS statistics completely unchanged, where a uniform scattered hide
  of the same size shifted them by 0.40. New `adaptive` module, `hide(..., adaptive=True)` in the Python API.
  Anyone can recompute which regions are busy from the stego image alone, without the password -- see the
  README for what that trade-off actually means.
- `--analyze` runs a chi-square attack and RS analysis against an image and reports how likely it is to have
  something hidden in it, roughly how much, and (via a windowed chi-square profile) whether it's concentrated
  in one part of the image the way an unscattered hide would be. New `analyze` module, `analyze.analyze` in the
  Python API. See the README for what each test actually needs from a cover image to be meaningful.
- `--decoy FILE --decoy-password PASSWORD` hides a second, decoy file in the same lsb image, so you have
  something to hand over if you're ever pressured to reveal what's hidden while the real file stays invisible.
  Works the same way a VeraCrypt hidden volume does, see the README for how and its limits. New `fec` and
  `deniable` modules, `hide_deniable`/`reveal_decoy` in the Python API.
- `--sign KEY` signs the hidden file with an Ed25519 key (existing SSH keys work), and `--verify PUBKEY` only
  extracts it if the signature matches. `--keygen` creates a new key pair.
- With a password, lsb mode spreads the data over the whole image in an order derived from the password, so the
  image doesn't show that anything is hidden in it without the password.
- The name of the hidden file is stored in the image (encrypted, when using a password), so `-h` can be left out
  when extracting. Extraction never overwrites an existing file unless you pass `-h` yourself.
- `-P` to type the password at a prompt instead of passing it on the command line.
- `--info` to show how much an image can hold and whether something is hidden in it.
- `--version` and `--help`.
- Tests, and CI on Linux, macOS and Windows.

### Fixed

- The default output path dropped every `.` in the input path, so `./photo.png` was saved as
  `/photo_steg0.png`.
- Choosing `[1] LSB Mode` in the interactive menu used endian mode.
- The usage text was printed after leaving the interactive menu.

## 2021-01-27

- Added the interactive menu (`--menu`).

## 3.0.0 - 2020-10-13

- Added password encryption (`-p`).
- Added hiding modes. The new endian mode appends the file to the end of the image, so there is no size limit.

## 2.0.0 - 2020-10-11

- Rewrote the script as a command line tool (`-i`, `-h`, `-o`, `-e`).

## 1.0.0 - 2020-03-30

- First release, hides files in the 2 least significant bits of every pixel.
