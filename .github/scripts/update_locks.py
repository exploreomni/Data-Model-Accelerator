"""Resolve wheel-only CPython 3.12 / Ubuntu 24.04 x86_64 CI requirements.

Run with Python 3.12 and uv 0.12.5. Review changed package versions and hashes
before committing. --check is offline and detects changed inputs or lockfiles;
it does not replace pip's dependency, wheel-compatibility or hash verification.

Native dbt packages use the official wheel URLs and SHA-256 values embedded in
their PyPI source archives, recorded in native-wheels.json. These constraints
avoid executing the packages' download-at-install source build backends.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
LOCKS = ROOT / '.github/requirements'
SCRIPTS = 'skills/data-model-accelerator/scripts/'
UV_VERSION = '0.12.5'
PYTHON_VERSION = '3.12'
PLATFORM = 'x86_64-manylinux_2_39'
LANES = {
    'bootstrap': ['.github/requirements/bootstrap.in'],
    'development': ['requirements-dev.txt'],
    'hex': [SCRIPTS + 'requirements-hex-e2e.txt'],
    'deployment': [SCRIPTS + 'requirements-deployment.txt'],
    'source-adapters': [SCRIPTS + 'requirements-source-adapters.txt'],
    'lint': [SCRIPTS + 'requirements-lint.txt', SCRIPTS + 'requirements-deployment.txt'],
    'tableau': [SCRIPTS + 'requirements-tableau-e2e.txt'],
    'powerbi': [SCRIPTS + 'requirements-powerbi-e2e.txt'],
    'dbt-v2': [SCRIPTS + 'requirements-dbt-v2.txt'],
    'dbt-oss': [SCRIPTS + 'requirements-dbt-oss.txt'],
    'dbt-metadata': [SCRIPTS + 'requirements-dbt-metadata.txt'],
    'security': ['.github/requirements/security.in'],
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_hashes():
    paths = {Path(__file__).resolve(), LOCKS / 'native-wheels.json'}

    def visit(path):
        path = path.resolve()
        path.relative_to(ROOT)
        if path in paths:
            return
        paths.add(path)
        for line in path.read_text().splitlines():
            if line.strip().startswith('-r '):
                visit(path.parent / line.strip()[3:].strip())

    for sources in LANES.values():
        for source in sources:
            visit(ROOT / source)
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(paths)}


def check():
    metadata = json.loads((LOCKS / 'lock-metadata.json').read_text())
    if metadata['inputs'] != input_hashes():
        raise ValueError('CI dependency inputs changed; regenerate and review lockfiles')
    if set(metadata['locks']) != {name + '.txt' for name in LANES}:
        raise ValueError('CI lockfile inventory differs from the configured environments')
    for name, expected in metadata['locks'].items():
        if digest(LOCKS / name) != expected:
            raise ValueError('CI lockfile changed without regeneration: ' + name)
    print('Verified all CI lock inputs and generated file digests (offline)')


def native_constraints():
    manifest = json.loads((LOCKS / 'native-wheels.json').read_text())
    lines = []
    for package in manifest['packages']:
        url, checksum = package['wheel_url'], package['wheel_sha256']
        if not re.fullmatch('[0-9a-f]{64}', checksum):
            raise ValueError('Invalid native wheel SHA-256')
        if not url.startswith(('https://public.cdn.getdbt.com/fs/wheels/',
                               'https://github.com/dbt-labs/dbt/releases/download/')):
            raise ValueError('Native wheel must use a reviewed official publisher URL')
        if not url.endswith('-manylinux_2_28_x86_64.whl'):
            raise ValueError('Native wheel is not the selected Linux x86_64 target')
        lines.append(package['name'] + ' @ ' + url + '#sha256=' + checksum)
    return '\n'.join(lines) + '\n'


def verify_native_wheels(directory):
    """Verify publisher provenance and wheel identity without executing packages."""
    manifest = json.loads((LOCKS / 'native-wheels.json').read_text())

    def fetch(url, checksum, limit):
        path = directory / checksum
        if not path.exists() or digest(path) != checksum:
            request = urllib.request.Request(url, headers={'User-Agent': 'dma-ci-locks'})
            with urllib.request.urlopen(request, timeout=60) as response:
                if not response.url.startswith('https://'):
                    raise ValueError('Native package download redirected outside HTTPS')
                with path.open('wb') as stream:
                    size = 0
                    while block := response.read(1024 * 1024):
                        size += len(block)
                        if size > limit:
                            raise ValueError('Oversized publisher package')
                        stream.write(block)
        if digest(path) != checksum:
            raise ValueError('Publisher package SHA-256 mismatch')
        return path

    for package in manifest['packages']:
        if not package['source_url'].startswith('https://files.pythonhosted.org/packages/'):
            raise ValueError('Native source archive must be published by PyPI')
        source = fetch(package['source_url'], package['source_sha256'], 2 * 1024 * 1024)
        with tarfile.open(source) as archive:
            member = archive.getmember(package['source_manifest'])
            if not member.isfile() or member.size > 100_000:
                raise ValueError('Invalid publisher wheel manifest')
            embedded = json.load(archive.extractfile(member))
        wheel = embedded['wheels'][manifest['platform']]
        if (embedded['name'] != package['name'] or embedded['version'] != package['version']
                or embedded['base_url'].rstrip('/') + '/' + wheel['filename'] != package['wheel_url']
                or wheel['sha256'] != package['wheel_sha256']):
            raise ValueError('Native wheel differs from the pinned publisher archive')
        path = fetch(package['wheel_url'], package['wheel_sha256'], 200 * 1024 * 1024)
        with zipfile.ZipFile(path) as archive:
            members = [item for item in archive.infolist() if item.filename.endswith('.dist-info/METADATA')]
            if len(members) != 1 or members[0].file_size > 1024 * 1024:
                raise ValueError('Invalid native wheel metadata')
            metadata = Parser().parsestr(archive.read(members[0]).decode('utf-8'))
        canonical = lambda value: re.sub(r'[-_.]+', '-', value).lower()
        if (metadata.get_all('Name') is None or len(metadata.get_all('Name')) != 1
                or canonical(metadata['Name']) != canonical(package['name'])
                or metadata.get_all('Version') != [package['version']]):
            raise ValueError('Native wheel metadata differs from the selected distribution/version')
        print('Verified publisher archive, wheel SHA-256 and metadata: ' + package['name'])


def generate(uv, cache_dir):
    if sys.version_info[:2] != (3, 12):
        raise ValueError('Generate locks with Python 3.12')
    executable = shutil.which(uv)
    if not executable:
        raise ValueError('Install uv ' + UV_VERSION + ' before generating locks')
    version = subprocess.check_output([executable, '--version'], text=True).split()[1]
    if version != UV_VERSION:
        raise ValueError('Expected uv ' + UV_VERSION + ', found ' + version)
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('UV_', 'PIP_'))}
    with tempfile.TemporaryDirectory(prefix='dma-ci-locks-') as directory:
        temporary = Path(directory)
        constraints = temporary / 'native-wheels.txt'
        constraints.write_text(native_constraints())
        native_cache = cache_dir / 'verified-native' if cache_dir else temporary / 'verified-native'
        native_cache.mkdir(parents=True, exist_ok=True)
        verify_native_wheels(native_cache)

        def compile_lane(item):
            name, sources = item
            output = temporary / (name + '.txt')
            command = [executable, 'pip', 'compile', *sources,
                       '--constraint', str(constraints), '--generate-hashes',
                       '--only-binary', ':all:', '--python-platform', PLATFORM,
                       '--python-version', PYTHON_VERSION, '--python', sys.executable,
                       '--default-index', 'https://pypi.org/simple', '--no-config',
                       '--no-sources', '--no-python-downloads', '--no-annotate',
                       '--no-header', '--quiet', '--output-file', str(output)]
            if cache_dir:
                command.extend(['--cache-dir', str(cache_dir)])
            subprocess.run(command, cwd=ROOT, env=environment, check=True, timeout=600)
            body = output.read_text()
            header = ('# Generated by python .github/scripts/update_locks.py; do not edit.\n'
                      '# Target: CPython 3.12, Ubuntu 24.04 x86_64; uv ' + UV_VERSION + '.\n'
                      '# Install with --require-hashes --only-binary=:all:.\n'
                      '# Native wheel provenance: native-wheels.json.\n\n')
            output.write_text(header + body)
            return name, output

        with ThreadPoolExecutor(max_workers=4) as executor:
            outputs = dict(executor.map(compile_lane, LANES.items()))
        metadata = {'schema_version': 1, 'python': PYTHON_VERSION, 'platform': PLATFORM,
                    'uv': UV_VERSION, 'inputs': input_hashes(),
                    'locks': {name + '.txt': digest(outputs[name]) for name in sorted(outputs)}}
        for name, path in outputs.items():
            (LOCKS / (name + '.txt')).write_bytes(path.read_bytes())
        (LOCKS / 'lock-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    check()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check input/output digests offline')
    parser.add_argument('--uv', default='uv', help='Path to uv ' + UV_VERSION)
    parser.add_argument('--cache-dir', type=Path)
    args = parser.parse_args()
    try:
        check() if args.check else generate(args.uv, args.cache_dir)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
