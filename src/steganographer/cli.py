import argparse
import sys
from getpass import getpass
from pathlib import Path

from . import __version__, core
from .errors import SteganographerError

USAGE = """\
steganographer -i IMAGE -h FILE [-o OUTPUT] [-m {lsb,endian}] [-p PASSWORD | -P]
       steganographer -e -i IMAGE [-h OUTPUT] [-p PASSWORD | -P]
       steganographer --info -i IMAGE [-p PASSWORD | -P]
       steganographer --menu"""

EPILOG = """\
modes:
  lsb     hide the file inside the pixels (output must be PNG, BMP or TIFF)
  endian  append the file after the end of the image (works with any format)

examples:
  steganographer -i cat.png -h notes.txt -m lsb -P
  steganographer -e -i cat_steg0.png
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
    parser.add_argument("-m", dest="mode", choices=["lsb", "endian"], default="endian", help="default: endian")

    password = parser.add_mutually_exclusive_group()
    password.add_argument("-p", dest="password", metavar="PASSWORD", help="encrypt/decrypt with this password")
    password.add_argument("-P", dest="ask_password", action="store_true", help="prompt for the password")

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


def hide(image: str, file: str, output: str | None, mode: str, password: str | None) -> None:
    data = Path(file).read_bytes()
    print(f"[*] {file} file size: {len(data)} bytes")
    if mode == "endian" and not password:
        print("[!] Warning: endian mode is easy to detect, consider using a password")

    written = core.hide(image, data, output, password=password, mode=mode, filename=Path(file).name)
    print(f"[+] Hidden file saved in {written}")


def extract(image: str, output: str | None, password: str | None) -> None:
    found = core.inspect(image, password=password)
    if found is None:
        hint = "" if password else ", if it was hidden with a password pass -p or -P"
        raise SteganographerError(f"no hidden file found in {image}{hint}")

    print(f"[+] Hidden file found in image ({found.mode} mode, {found.size} bytes)")
    if found.encrypted:
        print("[*] Hidden file is encrypted")
        if password is None:
            password = ask_password(confirm=False)

    name, data = core.reveal_file(image, password=password)
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
        elif args.image and (args.file or args.extract or args.info):
            password = args.password
            if args.ask_password:
                password = ask_password(confirm=not (args.extract or args.info))
            if args.info:
                info(args.image, password)
            elif args.extract:
                extract(args.image, args.file, password)
            else:
                hide(args.image, args.file, args.output, args.mode, password)
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
