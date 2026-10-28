#!/usr/bin/env python3
"""Audit complete CI locks, including hashed direct wheels that pip-audit skips.

This only creates advisory-query input. It never downloads or executes a wheel.
update_locks.py verifies the wheel metadata and records the reviewed provenance.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename

ROOT = Path(__file__).resolve().parents[2]
LOCKS = ROOT / '.github' / 'requirements'
ALLOWED_HOSTS = {'github.com', 'public.cdn.getdbt.com', 'files.pythonhosted.org'}
HASH = re.compile(r'\s+--hash=sha256:[0-9a-f]{64}(?=\s|$)')


def audit_inventory(text: str) -> list[str]:
    """Fail closed on unlocked, ambiguous or unauditable dependency entries."""
    versions: dict[str, str] = {}
    for raw in text.replace('\\\n', ' ').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if not HASH.search(line):
            raise ValueError(f'No reviewed SHA-256 for requirement: {line[:100]}')
        requirement = Requirement(HASH.sub('', line).strip())
        if requirement.marker:
            # Locks target one Linux/Python runtime. Do not silently drop markers
            # by evaluating them on the developer's different operating system.
            raise ValueError('CI audit requires fully resolved, marker-free locks')
        name = canonicalize_name(requirement.name)
        if requirement.url:
            url = urlsplit(requirement.url)
            if (url.scheme != 'https' or url.hostname not in ALLOWED_HOSTS
                    or url.username or url.password or url.port not in (None, 443)
                    or url.query):
                raise ValueError(f'Unreviewed direct-wheel origin for {name}')
            if url.fragment and not (url.fragment.startswith('sha256=')
                    and '--hash=' + url.fragment.replace('=', ':', 1) in line):
                raise ValueError(f'Wheel fragment/hash mismatch for {name}')
            wheel_name, version, _, _ = parse_wheel_filename(unquote(url.path.rsplit('/', 1)[-1]))
            if canonicalize_name(wheel_name) != name:
                raise ValueError(f'Wheel identity mismatch for {name}')
            version = str(version)
        else:
            specifiers = list(requirement.specifier)
            if len(specifiers) != 1 or specifiers[0].operator != '==' or '*' in specifiers[0].version:
                raise ValueError(f'Non-exact dependency pin for {name}')
            version = specifiers[0].version
        if name in versions and versions[name] != version:
            raise ValueError(f'Conflicting versions of {name}')
        versions[name] = version
    if not versions:
        raise ValueError('The dependency lock is empty')
    return [f'{name}=={version}' for name, version in sorted(versions.items())]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('locks', nargs='*', help='Lock basenames; defaults to every CI lock')
    args = parser.parse_args()
    paths = [LOCKS / (name + '.txt') for name in args.locks] if args.locks else sorted(LOCKS.glob('*.txt'))
    if not paths or any(path.resolve().parent != LOCKS.resolve() for path in paths):
        parser.error('Select existing CI lock basenames only')
    subprocess.run([sys.executable, str(ROOT / '.github/scripts/update_locks.py'), '--check'], check=True)
    failed = False
    with tempfile.TemporaryDirectory(prefix='dma-advisory-input-') as directory:
        for path in paths:
            inventory = audit_inventory(path.read_text())
            target = Path(directory) / path.name
            target.write_text('\n'.join(inventory) + '\n')
            print(f'Auditing {path.name}: {len(inventory)} exact package versions (direct wheels included)', flush=True)
            result = subprocess.run([
                sys.executable, '-m', 'pip_audit', '--disable-pip', '--no-deps',
                '--strict', '-r', str(target), '--progress-spinner', 'off',
            ], check=False)
            failed |= result.returncode != 0
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
