# CLI reference

```
steganographer -i IMAGE -h FILE [-o OUTPUT] [-m {lsb,endian,robust}] [-p PASSWORD | -P] [--sign KEY] [--adaptive]
steganographer -i IMAGE -h FILE -p PASSWORD --decoy FILE [--decoy-password PASSWORD] [--decoy-name NAME]
steganographer -e -i IMAGE [-h OUTPUT] [-p PASSWORD | -P] [--verify PUBKEY]
steganographer --info -i IMAGE [-p PASSWORD | -P]
steganographer --analyze -i IMAGE
steganographer --keygen FILE
steganographer --menu
```

> [!NOTE]
> `-h` means **hidden file**, not help, a convention kept from earlier versions. Use `--help` for help.

## Contents

- [Commands](#commands)
- [Options](#options)
- [Behaviour](#behaviour)
- [Recipes](#recipes)
- [Exit codes](#exit-codes)

## Commands

| Command | Does |
| --- | --- |
| `-i IMAGE -h FILE` | Hide `FILE` in `IMAGE` |
| `-e -i IMAGE` | Extract whatever is hidden in `IMAGE` |
| `--info -i IMAGE` | Print the `lsb` capacity and whether something is hidden |
| `--analyze -i IMAGE` | Run steganalysis and print a verdict |
| `--keygen FILE` | Create an Ed25519 key pair for signing |
| `--menu` | Interactive prompts for basic hide and extract |

## Options

### Input and output

| Option | Description |
| --- | --- |
| `-i IMAGE` | Cover image when hiding, stego image when extracting. Any format Pillow can open. |
| `-h FILE` | When hiding: the file to hide. With `-e`: where to save it (default: the stored original name). |
| `-o OUTPUT` | Output image. Default: `<name>_steg0.png` for `lsb` and `robust`, `<name>_steg0.<ext>` for `endian`. |
| `-e` | Extract instead of hide. |

### Mode

| Option | Description |
| --- | --- |
| `-m lsb` | Embed in the two lowest bits of each R, G and B value. Output must be PNG, BMP or TIFF. |
| `-m endian` | Append after the image data. Any output format. **Default.** |
| `-m robust` | Embed in DCT coefficients so the data survives JPEG recompression. Small capacity. |
| `--adaptive` | Fill the most textured regions first. Needs `-m lsb` and a password. |

See [Choosing a mode](../README.md#choosing-a-mode) for a comparison.

### Encryption

| Option | Description |
| --- | --- |
| `-p PASSWORD` | Encrypt when hiding, decrypt when extracting. |
| `-P` | Prompt for the password instead. When hiding, you're asked to type it twice. |

Prefer `-P`: a password passed with `-p` ends up in your shell history and is visible to other users in the
process list.

### Signing

| Option | Description |
| --- | --- |
| `--sign KEY` | Sign with an Ed25519 private key (OpenSSH or PEM). Prompts for its passphrase if it has one. |
| `--verify PUBKEY` | Only save the extracted file if it's signed by this key. Accepts a `.pub` file, a GitHub `.keys` file (the first `ssh-ed25519` line is used) or a PEM file. |
| `--keygen FILE` | Write a new key pair to `FILE` and `FILE.pub`, in the same format as `ssh-keygen`. Optional passphrase. |

Signing isn't available in `robust` mode yet.

### Deniable hiding

| Option | Description |
| --- | --- |
| `--decoy FILE` | Also hide `FILE` as a decoy under a second password. `lsb` only, so `-m` can be left out. |
| `--decoy-password PASSWORD` | Password for the decoy. Prompted for if omitted. Must differ from the real password. |
| `--decoy-name NAME` | File name to store for the decoy (default: the decoy's own name). |

### Other

| Option | Description |
| --- | --- |
| `--info` | Capacity and detection. Add `-p` or `-P` to find password-protected `lsb` data. |
| `--analyze` | Chi-square and RS steganalysis. See [How it works](how-it-works.md#steganalysis). |
| `--menu` | Interactive mode. Supports `lsb` and `endian` only. |
| `--version` | Print the version. |
| `--help` | Print usage and examples. |

## Behaviour

**Mode detection.** `-e` never needs `-m`. It checks, in order: an `endian` trailer, sequential `lsb`,
scattered `lsb` (with the password), adaptive `lsb` (with the password), a deniable decoy layer (with the
password), and finally `robust`.

**Passwords are asked for when needed.** If an encrypted file is found and you didn't give a password, you're
prompted for one. Scattered `lsb` data is the exception: it can't be found at all without the password, so
pass `-p` or `-P` up front.

**File names.** The original file name is stored inside the image (encrypted, if a password is used) and used
when extracting. Any directory components are stripped, so a crafted image can't write outside the current
directory. Extraction refuses to overwrite an existing file. Pass `-h` to choose another path.

**Unprotected `endian`.** Hiding in `endian` mode without a password prints a warning, because anyone can read
the data with a hex editor.

**Signatures are always checked.** If an extracted file is signed, the signature is verified and the signer's
fingerprint is printed (`SHA256:...`, the same format as `ssh-keygen -l`). `--verify` additionally requires a
specific signer.

## Recipes

Hide with a password, then extract:

```sh
steganographer -i cat.png -h notes.txt -m lsb -P
steganographer -e -i cat_steg0.png -P
```

Extract to a specific path:

```sh
steganographer -e -i cat_steg0.png -P -h ~/Desktop/recovered.txt
```

Check capacity before hiding:

```sh
steganographer --info -i cat.png
# [*] Capacity in lsb mode: 196593 bytes
# [*] No hidden file found
```

Sign with a new key and verify:

```sh
steganographer --keygen mykey                                    # creates mykey and mykey.pub
steganographer -i cat.png -h plan.txt -m lsb -P --sign mykey
steganographer -e -i cat_steg0.png -P --verify mykey.pub
```

Verify against someone's GitHub keys:

```sh
curl -s https://github.com/<username>.keys > sender.pub
steganographer -e -i cat_steg0.png -P --verify sender.pub
```

Deniable hide:

```sh
steganographer -i cat.png -h real.txt -P --decoy holiday.txt    # prompts for both passwords
```

A message that survives being shared as a JPEG:

```sh
steganographer -i photo.jpg -h note.txt -m robust -P -o photo_share.jpg
```

Keep a JPEG a JPEG (`endian`, not recompression-safe):

```sh
steganographer -i photo.jpg -h archive.zip -m endian -P    # -> photo_steg0.jpg
```

Adaptive placement, then check detectability:

```sh
steganographer -i forest.png -h notes.txt -m lsb -P --adaptive
steganographer --analyze -i forest_steg0.png
```

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | Error: nothing hidden, wrong password, file too large, bad signature, unreadable file, and so on. The message goes to stderr. |
| `2` | Invalid arguments. Usage is printed. |
| `130` | Interrupted with Ctrl-C |
