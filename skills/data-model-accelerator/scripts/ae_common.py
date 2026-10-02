"""Small, read-only evidence helpers for the analytics-engineering workflow."""
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import stat

from verify_dbt_evidence import snapshot_project

MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_FILE_BYTES = 100 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _path(path, must_exist=True):
    path = Path(path).absolute()
    require(not any(part in ('.', '..') for part in path.parts), 'Noncanonical path')
    require(not any(p.is_symlink() for p in (path,) + tuple(path.parents)), 'Symlink path is not allowed')
    if must_exist:
        require(path.exists(), 'Missing file or directory: ' + str(path))
    return path


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _float(value):
    number = float(value)
    require(math.isfinite(number), 'Nonfinite JSON number')
    return number


def _nonfinite(value):
    raise ValueError('Nonfinite JSON value: ' + value)


def load_json(path, max_bytes=MAX_JSON_BYTES):
    require(type(max_bytes) is int and max_bytes > 0, 'Invalid JSON byte limit')
    path = _path(path)
    require(stat.S_ISREG(path.stat().st_mode), 'JSON input must be a regular file')
    require(path.stat().st_size <= max_bytes, 'JSON byte limit exceeded')
    with path.open('rb') as stream:
        content = stream.read(max_bytes + 1)
    require(len(content) <= max_bytes, 'JSON byte limit exceeded')
    return json.loads(content.decode('utf-8'), object_pairs_hook=_pairs,
                      parse_float=_float, parse_constant=_nonfinite)


def _json_value(value):
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        require(math.isfinite(value), 'Nonfinite JSON number')
        return
    if type(value) is list:
        for item in value:
            _json_value(item)
        return
    require(type(value) is dict and all(type(key) is str for key in value), 'Value must use JSON types and string object keys')
    for item in value.values():
        _json_value(item)


def _json_bytes(value):
    _json_value(value)
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('utf-8')


def hash_json(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def hash_file(path):
    path = _path(path)
    require(stat.S_ISREG(path.stat().st_mode), 'Hash input must be a regular file')
    require(path.stat().st_size <= MAX_FILE_BYTES, 'File byte limit exceeded')
    digest, count = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            count += len(chunk)
            require(count <= MAX_FILE_BYTES, 'File byte limit exceeded')
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    content = _json_bytes(value) + b'\n'
    path = _path(path, must_exist=False)
    require(path.parent.is_dir(), 'Output parent directory must exist')
    with path.open('xb') as stream:
        stream.write(content)


def safe_relative(value):
    require(type(value) is str and value and value == value.strip(), 'Path must be a nonempty relative string')
    require(not any(ord(char) < 32 or ord(char) == 127 for char in value), 'Control characters are not allowed in paths')
    require(not any(char in value for char in '\\:*?[]'), 'Path must be exact, not a drive, glob or backslash path')
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(part not in ('', '.', '..') for part in value.split('/'))
            and path.as_posix() == value, 'Path must remain within its declared root')
    return value


def snapshot(project):
    """Deterministic byte inventory; capture is not proof of execution or approval."""
    files = snapshot_project(project)['files']
    return {'files': files, 'sha256': hash_json(files)}
