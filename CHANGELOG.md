# Changelog

## 4.0.0

### Changed

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

### Added

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
