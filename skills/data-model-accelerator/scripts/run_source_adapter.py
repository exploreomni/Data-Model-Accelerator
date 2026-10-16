#!/usr/bin/env python3
"""Parse an approved local snapshot without executing source or contacting APIs.

Outputs sensitive source expressions: store outside the input repository in its
approved retention boundary. Does not perform agent disclosure authorization.
Exit 0: declared subset parsed; 2: explicit gaps; 1: invalid input/output.
"""
import argparse
import json
import os
from pathlib import Path
import stat
import sys

from source_adapters.base import MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_DEPTH
from source_adapters.filesystem import new_json_output
from source_adapters.registry import SOURCES, capability, parse
from plan_specialists import IGNORED_DIRS, is_secret


def collect(root):
    root = Path(root).absolute()
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise ValueError('source.unsafe_root')
    files, omissions, total, entries = {}, [], 0, 0
    dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    # Open every ancestor without following links; all subsequent access is
    # relative to retained directory descriptors, not replaceable path strings.
    fd = os.open('/', dir_flags)
    try:
        for component in root.parts[1:]:
            child = os.open(component, dir_flags, dir_fd=fd)
            os.close(fd)
            fd = child
        def walk(directory_fd, prefix='', depth=0):
            nonlocal total, entries
            if depth >= MAX_DEPTH:
                raise ValueError('source.path_depth_limit')
            with os.scandir(directory_fd) as iterator:
                names = []
                for entry in iterator:
                    entries += 1
                    if entries > MAX_FILES * 4:
                        raise ValueError('source.entry_limit')
                    names.append(entry.name)
            for name in sorted(names):
                rel = prefix + name
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    omissions.append({'path': rel, 'reason': 'symlink_not_read'})
                    continue
                if stat.S_ISDIR(info.st_mode):
                    if name in IGNORED_DIRS or name.startswith('.'):
                        omissions.append({'path': rel, 'reason': 'excluded_directory'})
                    else:
                        child = os.open(name, dir_flags, dir_fd=directory_fd)
                        try:
                            walk(child, rel + '/', depth + 1)
                        finally:
                            os.close(child)
                    continue
                if is_secret(Path(name)):
                    omissions.append({'path': rel, 'reason': 'credential_path_not_read'})
                    continue
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                with os.fdopen(os.open(name, flags, dir_fd=directory_fd), 'rb') as stream:
                    before = os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode):
                        raise ValueError('source.non_regular_file')
                    if before.st_size > MAX_FILE_BYTES:
                        raise ValueError('source.byte_limit')
                    raw = stream.read(MAX_FILE_BYTES + 1)
                    after = os.fstat(stream.fileno())
                if before.st_mtime_ns != after.st_mtime_ns or before.st_size != len(raw) or len(raw) > MAX_FILE_BYTES:
                    raise ValueError('source.changed_or_oversized_file')
                total += len(raw)
                if total > MAX_TOTAL_BYTES or len(files) >= MAX_FILES:
                    raise ValueError('source.snapshot_limit')
                try:
                    content = raw.decode('utf-8')
                    if '\x00' in content:
                        raise ValueError('binary')
                except (UnicodeError, ValueError):
                    omissions.append({'path': rel, 'reason': 'binary_or_non_utf8_requires_separate_export'})
                    continue
                files[rel] = content
        walk(fd)
    finally:
        os.close(fd)
    return files, omissions


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path, nargs='?')
    p.add_argument('--source', choices=SOURCES, required=True)
    p.add_argument('--output', type=Path)
    p.add_argument('--capabilities', action='store_true')
    a = p.parse_args(argv)
    try:
        if a.capabilities:
            print(json.dumps(capability(a.source), indent=2))
            return 0
        if a.root is None or a.output is None:
            raise ValueError('source.root_and_output_required')
        output = a.output.absolute()
        try:
            output.relative_to(a.root.resolve())
            raise ValueError('source.output_inside_input')
        except ValueError as exc:
            if str(exc) == 'source.output_inside_input':
                raise
        with new_json_output(output) as write:
            files, omissions = collect(a.root)
            result = parse(a.source, files)
            result['acquisition'] = {'mode': 'supplied_snapshot', 'omissions': omissions,
                                     'completeness': 'not_established', 'network_calls': 0}
            write(result)
            partial = bool(omissions or result['gaps'] or not files or any(f['status'] != 'parsed' for f in result['source_files']))
        print(json.dumps({'status': 'partial' if partial else 'subset_parsed',
                          'files': len(files), 'objects': len(result['objects']),
                          'gaps': len(result['gaps']), 'omissions': len(omissions),
                          'native_validation': 'not_run'}))
        return 2 if partial else 0
    except (ValueError, OSError, ImportError):
        print('Source parsing failed: invalid input, output, or missing pinned dependency. No source content is printed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
