"""Explicitly acquire Hex's public schema; analysis itself never downloads it."""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

URL = 'https://static.hex.site/hex-file-schema.json'
SHA256 = 'e0a8d6f4261983194de2230821bcd86604d817301dc054a42665df4eb421bde0'
DESTINATION = Path(__file__).with_name('schemas') / 'hex-file-schema.v3.json'
MAX_BYTES = 2_000_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Schema acquisition does not follow redirects')


def verify(content):
    if len(content) > MAX_BYTES or hashlib.sha256(content).hexdigest() != SHA256:
        raise ValueError('Hex schema checksum mismatch; review a new publisher version before updating the pin')
    json.loads(content)
    return content


def acquire(source=None):
    if source is not None:
        with Path(source).open('rb') as stream:
            return verify(stream.read(MAX_BYTES + 1))
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(URL, timeout=30) as response:
        return verify(response.read(MAX_BYTES + 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Use a locally obtained, checksum-matching schema for offline setup')
    args = parser.parse_args()
    if DESTINATION.is_symlink():
        raise ValueError('Refusing a symlink schema destination')
    if DESTINATION.exists() and hashlib.sha256(DESTINATION.read_bytes()).hexdigest() == SHA256:
        print('Pinned Hex schema already installed')
        return
    content = acquire(args.source)
    DESTINATION.write_bytes(content)
    print('Verified Hex schema installed locally; excluded from Git and the MIT license')


if __name__ == '__main__':
    main()
