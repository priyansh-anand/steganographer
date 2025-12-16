import argparse
import sys
from getpass import getpass
from pathlib import Path

from . import __version__, core, deniable, signing
from .errors import SteganographerError

USAGE = """\
steganographer -i IMAGE -h FILE [-o OUTPUT] [-m {lsb,endian}] [-p PASSWORD | -P] [--sign KEY]
       steganographer -i IMAGE -h FILE -p PASSWORD --decoy FILE [--decoy-password PASSWORD]
       steganographer -e -i IMAGE [-h OUTPUT] [-p PASSWORD | -P] [--verify PUBKEY]
       steganographer --info -i IMAGE [-p PASSWORD | -P]
       steganographer --keygen FILE
       steganographer --menu"""

EPILOG = """\
modes:
  lsb     hide the file inside the pixels (output must be PNG, BMP or TIFF)
  endian  append the file after the end of the image (works with any format)

examples:
  steganographer -i cat.png -h notes.txt -m lsb -P
  steganographer -e -i cat_steg0.png

  steganographer -i cat.png -h notes.txt -m lsb -P --sign ~/.ssh/id_ed25519
  curl -s https://github.com/<user>.keys > friend.pub
  steganographer -e -i cat_steg0.png -P --verify friend.pub

  steganographer -i cat.png -h plan.txt -p realpw --decoy vacation.txt --decoy-password decoypw
  steganographer -e -i cat_steg0.png -p decoypw    # gets vacation.txt back
  steganographer -e -i cat_steg0.png -p realpw     # gets plan.txt back
"""


def build_parser() -> argparse.ArgumentParser:
    # -h has always meant "hidden file" here, so the automatic help flag is
    # replaced with --help only.
    parser = argparse.ArgumentParser(
        prog="steganographer",
        usage=USAGE,
        description="Hide files inside images.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-i", dest="image", metavar="IMAGE", help="input image")
    parser.add_argument(
        "-h",
        dest="file",
        metavar="FILE",
        help="file to hide, or where to save the extracted file (default: its original name)",
    )
    parser.add_argument("-o", dest="output", metavar="OUTPUT", help="output image (default: <image>_steg0.png)")
    parser.add_argument("-e", dest="extract", action="store_true", help="extract a hidden file instead of hiding one")
    parser.add_argument("-m", dest="mode", choices=["lsb", "endian"], default=None, help="default: endian")

    password = parser.add_mutually_exclusive_group()
    password.add_argument("-p", dest="password", metavar="PASSWORD", help="encrypt/decrypt with this password")
    password.add_argument("-P", dest="ask_password", action="store_true", help="prompt for the password")

    parser.add_argument(
        "--decoy",
        metavar="FILE",
        help="hide this file too, under --decoy-password, as a deniable decoy (lsb mode only)",
    )
    parser.add_argument("--decoy-password", metavar="PASSWORD", help="password for --decoy (default: prompt)")
    parser.add_argument("--decoy-name", metavar="NAME", help="name to store for --decoy (default: its own name)")
    parser.add_argument("--sign", metavar="KEY", help="sign the hidden file with this Ed25519 private key")
    parser.add_argument("--verify", metavar="PUBKEY", help="only extract if the file is signed with this public key")
    parser.add_argument("--keygen", metavar="FILE", help="create an Ed25519 key pair in FILE and FILE.pub")
    parser.add_argument("--info", action="store_true", help="show capacity and whether IMAGE has a hidden file")
    parser.add_argument("--menu", action="store_true", help="interactive menu")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--help", action="help", help="show this help and exit")
    return parser


def ask_password(confirm: bool) -> str:
    password = getpass("[?] Password: ")
    if confirm and getpass("[?] Repeat password: ") != password:
        raise SteganographerError("passwords do not match")
    return password


def load_signing_key(path: str):
    try:
        return signing.load_private_key(path)
    except signing.PassphraseRequired:
        return signing.load_private_key(path, getpass(f"[?] Passphrase for {path}: "))


def keygen(path: str) -> None:
    passphrase = getpass("[?] Passphrase for the new key [optional]: ")
    if passphrase and getpass("[?] Repeat passphrase: ") != passphrase:
        raise SteganographerError("passphrases do not match")

    key = signing.generate(path, passphrase or None)
    print(f"[+] Private key saved to {path}, keep it to yourself")
    print(f"[+] Public key saved to {path}.pub, give it to whoever should check your signature")
    print(f"[*] Fingerprint: {signing.fingerprint(key.public_key())}")


def hide(
    image: str, file: str, output: str | None, mode: str, password: str | None, sign_key: str | None = None
) -> None:
    data = Path(file).read_bytes()
    print(f"[*] {file} file size: {len(data)} bytes")
    if mode == "endian" and not password:
        print("[!] Warning: endian mode is easy to detect, consider using a password")

    key = load_signing_key(sign_key) if sign_key else None
    written = core.hide(image, data, output, password=password, mode=mode, filename=Path(file).name, sign_with=key)
    if key:
        print(f"[*] Signed with {signing.fingerprint(key.public_key())}")
    print(f"[+] Hidden file saved in {written}")


def hide_deniable(
    image: str,
    file: str,
    password: str,
    decoy_file: str,
    decoy_password: str,
    decoy_name: str | None,
    output: str | None,
) -> None:
    real_data = Path(file).read_bytes()
    decoy_data = Path(decoy_file).read_bytes()
    print(
        f"[*] {file} file size: {len(real_data)} bytes (real), {decoy_file} file size: {len(decoy_data)} bytes (decoy)"
    )

    written = deniable.hide_deniable(
        image,
        decoy_data,
        decoy_password,
        real_data,
        password,
        output,
        decoy_filename=Path(decoy_file).name if decoy_name is None else decoy_name,
        real_filename=Path(file).name,
    )
    print(f"[+] Hidden file saved in {written}")
    print("[*] Extract either file with the normal -e command, using the matching password")


def extract(image: str, output: str | None, password: str | None, verify_key: str | None = None) -> None:
    found = core.inspect(image, password=password)
    if found is None:
        if password:
            revealed = deniable.reveal_decoy(image, password)
            if revealed is not None:
                _save_extracted(*revealed, output)
                print("[*] This is a deniable image, found the decoy layer for this password")
                return
        hint = "" if password else ", if it was hidden with a password pass -p or -P"
        raise SteganographerError(f"no hidden file found in {image}{hint}")

    print(f"[+] Hidden file found in image ({found.mode} mode, {found.size} bytes)")
    if found.encrypted:
        print("[*] Hidden file is encrypted")
        if password is None:
            password = ask_password(confirm=False)

    expected = signing.load_public_key(verify_key) if verify_key else None
    name, data, signer = core.reveal_file(image, password=password, signed_by=expected)
    if signer:
        verified = " (matches the key you gave)" if expected else ""
        print(f"[+] Signed by {signing.fingerprint(signer)}{verified}")
    else:
        print("[*] Not signed")

    _save_extracted(name, data, output)


def _save_extracted(name: str | None, data: bytes, output: str | None) -> None:
    if output is None:
        if name is None:
            raise SteganographerError("this image doesn't store the file name, pass -h to say where to save it")
        if Path(name).exists():
            raise SteganographerError(f"{name} already exists, pass -h to choose where to save it")
        output = name

    Path(output).write_bytes(data)
    print(f"[+] Saved hidden file to {output} ({len(data)} bytes)")


def info(image: str, password: str | None) -> None:
    print(f"[*] Capacity in lsb mode: {core.capacity(image)} bytes")
    found = core.inspect(image, password=password)
    if found is None:
        print("[*] No hidden file found")
    else:
        encrypted = "encrypted" if found.encrypted else "not encrypted"
        print(f"[+] Hidden file found: {found.mode} mode, {found.size} bytes, {encrypted}")


def menu() -> None:
    print("[*] Steganographer - Hide files in images")
    print("[#] Menu:")
    print("\t[1] Hide file in image")
    print("\t[2] Unhide file from image")

    choice = input("[?] Choose an option: ").strip()
    if choice == "1":
        image = input("[?] Enter the input image path: ")
        file = input("[?] Enter the path of file to hide: ")
        output = input("[?] Enter the output image path [optional]: ") or None

        print("[#] Hiding modes:")
        print("\t[1] LSB Mode   : Hide file in the pixels of image")
        print("\t[2] Endian Mode: Append hidden file at the end of image")
        mode = "lsb" if input("[?] Choose an option [default: endian]: ").strip() in ("1", "lsb") else "endian"
        password = getpass("[?] Enter password [optional]: ") or None

        hide(image, file, output, mode, password)
    elif choice == "2":
        image = input("[?] Enter the input image path: ")
        output = input("[?] Enter the path for extracted file [default: original name]: ") or None
        extract(image, output, None)
    else:
        print("[!] Wrong choice")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.menu:
            menu()
        elif args.keygen:
            keygen(args.keygen)
        elif args.decoy and not (args.image and args.file):
            raise SteganographerError("--decoy needs -i and -h for the real file too")
        elif args.decoy:
            if args.mode not in (None, "lsb"):
                raise SteganographerError("--decoy only works with -m lsb")
            password = args.password or ask_password(confirm=True)
            decoy_password = args.decoy_password or getpass("[?] Decoy password: ")
            hide_deniable(args.image, args.file, password, args.decoy, decoy_password, args.decoy_name, args.output)
        elif args.image and (args.file or args.extract or args.info):
            password = args.password
            if args.ask_password:
                password = ask_password(confirm=not (args.extract or args.info))
            if args.info:
                info(args.image, password)
            elif args.extract:
                extract(args.image, args.file, password, args.verify)
            else:
                hide(args.image, args.file, args.output, args.mode or "endian", password, args.sign)
        else:
            parser.print_usage()
            print("\nRun with --help to see all options.")
            return 2
    except (SteganographerError, ValueError, OSError) as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0
