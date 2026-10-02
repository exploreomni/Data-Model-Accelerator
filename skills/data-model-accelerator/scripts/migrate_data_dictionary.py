"""Migrate a dictionary to a new file; never overwrite the original or a destination."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

from data_dictionary_v2 import migrate_dictionary


MAX_INPUT_BYTES = 10 * 1024 * 1024


def _path(value):
    path = Path(value).expanduser().absolute()
    if '..' in path.parts or any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError('Symlink or traversal paths are not allowed')
    return path


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key in input')
        value[key] = item
    return value


def _constant(value):
    raise ValueError('Nonfinite JSON number in input')


def migrate_file(source, destination):
    """Read bounded stable input and create a private, exclusive destination copy."""
    source, destination = _path(source), _path(destination)
    if source == destination or destination.exists():
        raise ValueError('Output must be a new destination; in-place migration and overwrite are refused')
    if not destination.parent.is_dir():
        raise ValueError('Output parent directory must already exist')
    fd = os.open(str(source), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_INPUT_BYTES:
            raise ValueError('Input must be a regular JSON file of at most 10 MiB')
        raw = stream.read(MAX_INPUT_BYTES + 1)
        after = os.fstat(stream.fileno())
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    if identity(before) != identity(after) or len(raw) != after.st_size or len(raw) > MAX_INPUT_BYTES:
        raise ValueError('Input changed during the read or exceeded the bound')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
    result = migrate_dictionary(value)
    if value['schema_version'] == 1:
        result['migration']['source_file_sha256'] = hashlib.sha256(raw).hexdigest()
    data = (json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False) + '\n').encode('utf-8')
    _path(destination)
    # O_EXCL is the final no-overwrite check even if another process wins a race.
    fd = os.open(str(destination), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    created = os.fstat(fd)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        current = destination.lstat()
        if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
            destination.unlink()
        raise
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = migrate_file(args.input, args.output)
    except (OSError, ValueError, TypeError, RecursionError) as error:
        print('Dictionary migration refused: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps({'output': str(args.output.absolute()), 'schema_version': 2,
                      'unresolved': len(result.get('migration', {}).get('unresolved', [])),
                      'authority': 'Migrated documentation only; no review approval or deployment authority.'}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
