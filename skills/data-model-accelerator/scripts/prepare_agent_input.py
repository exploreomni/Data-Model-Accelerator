"""Stage only declared-approved, scanned low-sensitivity inputs for a specialist.

This helper does not sandbox the agent host. Never give a specialist access to
original protected inputs; no protected-host execution is qualified by this CLI.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat

from ae_common import load_json, require, write_json, _path, hash_json
from plan_specialists import is_secret
from privacy_contract import evaluate_disclosure
from sensitive_data import scan_bytes, MAX_BYTES, MAX_TOTAL_BYTES


def prepare(root, request, output):
    root, output = _path(root), _path(output, must_exist=False)
    require(root.is_dir() and output.parent.is_dir() and not output.exists(), 'New output outside the source is required')
    require(root != output and root not in output.parents, 'Output must be outside source')
    require(type(request) is dict and type(request.get('schema_version')) is int
            and request['schema_version'] == 1 and request.get('kind') == 'agent_input_request', 'Unsupported input request')
    entries = request.get('files')
    require(type(entries) is list and 0 < len(entries) <= 200, 'Explicit bounded input inventory required')
    captured, names, total = [], set(), 0
    for item in entries:
        require(type(item) is dict and type(item.get('path')) is str, 'Invalid input entry')
        path = PurePosixPath(item['path'])
        require(not path.is_absolute() and path.as_posix() == item['path'] and '..' not in path.parts
                and '\\' not in item['path'] and ':' not in item['path'] and '\x00' not in item['path']
                and path.parts and not any(is_secret(Path(p)) for p in path.parts), 'Input path is not permitted')
        require(item['path'].casefold() not in names, 'Duplicate input path')
        names.add(item['path'].casefold())
        require(scan_bytes(item['path'].encode(), 'path.txt')['status'] == 'clear', 'Input path needs sanitization')
        source = _path(root / item['path'])
        require(root in source.parents, 'Input path escapes source')
        fd = os.open(str(source), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, 'Input file outside supported bounds')
            content = stream.read(MAX_BYTES + 1)
            after = os.fstat(stream.fileno())
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(identity(before) == identity(after) and len(content) == after.st_size, 'Input changed during capture')
        total += len(content)
        require(total <= MAX_TOTAL_BYTES, 'Input inventory exceeds bounded projection size')
        digest = hashlib.sha256(content).hexdigest()
        require(digest == item.get('sha256'), 'Input content differs from reviewed inventory')
        scan = scan_bytes(content, item['path'])
        result = evaluate_disclosure(item.get('classification'), request.get('policy'), 'agent_input', scan)
        require(result['allowed'], 'Agent input denied; review classification, destination and scan coverage')
        captured.append((item['path'], content, digest))
    output.mkdir(mode=0o700)
    try:
        for name, content, _ in captured:
            destination = output / name
            # New run-owned directories only; originals are never changed.
            for parent in reversed(destination.parents):
                if output == parent or output in parent.parents:
                    parent.mkdir(mode=0o700, exist_ok=True)
            fd = os.open(str(destination), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
        manifest = {'schema_version': 1, 'kind': 'agent_input_projection',
                    'request_sha256': hash_json(request), 'host_isolation_verified': False,
                    'protected_inputs_allowed': False,
                    'files': [{'path': name, 'sha256': digest} for name, _, digest in captured],
                    'assurance': 'Scanned pre-sanitized projection under declared policy; does not sandbox a host.'}
        require(not (output/'AGENT_INPUT_MANIFEST.json').exists(), 'Reserved output name collision')
        write_json(output/'AGENT_INPUT_MANIFEST.json', manifest)
        os.chmod(output/'AGENT_INPUT_MANIFEST.json', 0o600)
        return manifest
    except BaseException:
        shutil.rmtree(output)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = prepare(args.root, load_json(args.request), args.output)
    except (ValueError, OSError, UnicodeError):
        parser.exit(2, 'Agent input preparation blocked; inspect policy and value-free scans locally.\n')
    print(json.dumps({'files': len(result['files']), 'host_isolation_verified': False}))


if __name__ == '__main__':
    main()
