# Security model

Steganography hides the *existence* of a message. Encryption hides its *contents*. Steganographer does both,
but each has limits. This page explains what you can rely on.

## What it protects

| Property | How | Caveat |
| --- | --- | --- |
| **Confidentiality** | Fernet (AES-128-CBC + HMAC-SHA256), scrypt-derived key | Only as strong as your password |
| **Integrity** | Fernet's HMAC rejects any modified ciphertext | Needs a password. Unencrypted data has no integrity check unless it's signed. |
| **Authenticity** | Optional Ed25519 signature over the file name and contents | Trust comes from how you got the signer's public key |
| **Concealment** | `lsb` with a password scatters data and header across the whole image | Statistical tests can still flag heavy use, see below. `endian` and `robust` don't conceal. |
| **Deniability** | `--decoy` stores a second file that nothing points to | Limited to a small real file, see below |

## What it doesn't protect against

**Access to the original image.** Comparing the stego image with its cover reveals every changed pixel
instantly. Don't use a photo that exists elsewhere, such as online, in a cloud backup or on someone else's
phone. Delete the cover after hiding, or take a fresh photo for each use.

**Statistical steganalysis.** Replacing low bits changes an image's statistics, and the more capacity you use,
the more detectable it becomes. The README demo fills 83% of its image's capacity, which works as a
demonstration but is poor practice. For real use:

- Keep the payload to a **small fraction of capacity**. Under 10% is a sensible rule of thumb.
- Use **textured, noisy photos** (foliage, gravel, crowds) rather than smooth ones (sky, studio shots,
  graphics).
- Consider `--adaptive`, and check the result with `--analyze`.

**Recompression and resizing.** Messaging apps and social networks re-encode images. `lsb` and `endian` data
does not survive that. `robust` survives recompression but not resizing, cropping or rotation.

**Endian mode inspection.** Appended data is visible to anyone who looks at the file's bytes. It gives no
concealment, only encryption (if you set a password).

**Weak passwords.** scrypt slows down brute-forcing, but a short or common password can still be guessed.
Use a long passphrase.

**Metadata.** `lsb` and `robust` write a freshly encoded image with no EXIF data. `endian` copies the original
file byte for byte, so its EXIF data, **including any GPS location**, is kept. Strip metadata first if that
matters.

## Mode by mode

| | Existence hidden? | Contents hidden? |
| --- | --- | --- |
| `lsb` without a password | Weakly: the header is readable at a known position | No |
| `lsb` with a password | Yes, subject to statistical analysis | Yes |
| `lsb --adaptive` | Yes, but likely regions can be estimated | Yes |
| `endian` without a password | No | No |
| `endian` with a password | No | Yes |
| `robust` without a password | No: the header sits at a fixed position | No |
| `robust` with a password | No: anyone can detect the payload, only you can read it | Yes |

### Adaptive placement

Adaptive placement ranks regions using only bits that hiding never changes, so anyone can compute the same
ranking from the stego image. That lets an attacker narrow down *where* data would be. It reveals nothing
about whether data is present or what it says, but it's a weaker guarantee than uniform scattering's "no
information without the password". This is inherent to adaptive steganography in general.

### Deniable hiding

The real layer is identical to an ordinary encrypted hide, and the decoy is a separate, fully functional
encrypted file. Deniability is only as good as your decoy's credibility, though. An empty or implausible decoy
invites further questions. The real file must stay under about 2–3% of the image's capacity for the decoy to
survive, and Steganographer refuses to write an image where it wouldn't.

## Safe extraction

- Stored file names are reduced to their last path component, so a malicious image can't write to
  `../../.bashrc` or any other path outside the current directory.
- Extraction never overwrites an existing file.
- A signed file is always verified. With `--verify`, a missing or mismatched signature means nothing is written.

## Recommended practice

```sh
# fresh, textured photo; small payload; prompted password; signed
steganographer -i IMG_2231.jpg -h message.txt -m lsb -P --adaptive --sign ~/.ssh/id_ed25519
steganographer --analyze -i IMG_2231_steg0.png
```

Send the result as a **file attachment**, not an inline photo, so it isn't recompressed. If it must go through
a platform that recompresses images, use `-m robust` for a short message instead.
