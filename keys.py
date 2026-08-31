#!/usr/bin/env python3
"""Authorize any ordinary SSH public key offered to the rack gateway."""

import base64
import binascii
import re
import sys


KEY_RE = re.compile(
    r"(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)|"
    r"sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)"
    r"(?:-cert-v01@openssh\.com)?$"
)


def main() -> int:
    if len(sys.argv) != 3 or not KEY_RE.fullmatch(sys.argv[1]):
        return 1
    try:
        decoded = base64.b64decode(sys.argv[2], validate=True)
    except (binascii.Error, ValueError):
        return 1
    if not 32 <= len(decoded) <= 16384:
        return 1
    print(f"{sys.argv[1]} {sys.argv[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
