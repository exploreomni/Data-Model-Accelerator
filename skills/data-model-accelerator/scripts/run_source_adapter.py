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
from source_adapters.errors import SourceAdapterError
from source_adapters.filesystem import new_json_output
from source_adapters.registry import SOURCES, capability, parse
from plan_specialists import IGNORED_DIRS, is_secret


# All public diagnostic text is static. Never include str(exc), filenames,
# parser messages, supplied gap messages or dependency names from exceptions.
_HINTS = {
    'source.invalid_arguments': 'Check the documented arguments and --source choices with --help.',
    'source.root_and_output_required': 'Supply both a local snapshot directory and a new output file outside that directory.',
    'source.input_missing': 'Check that the approved snapshot directory exists and is mounted before retrying.',
    'source.unsafe_root': 'Use an existing canonical directory without symlinks or redirected ancestors.',
    'source.input_unavailable': 'A snapshot entry disappeared or became inaccessible. Investigate and pin a stable snapshot before retrying.',
    'source.input_permission_denied': 'Check read and directory traversal access to the approved snapshot; do not broaden scope automatically.',
    'source.input_io_error': 'Investigate snapshot access, changed entries or unsupported filesystem objects before retrying.',
    'source.non_regular_file': 'Provide regular UTF-8 export files; devices, pipes and sockets are not source snapshots.',
    'source.changed_or_oversized_file': 'The file changed during reading or exceeded its byte bound. Pin a stable bounded snapshot before retrying.',
    'source.output_inside_input': 'Choose a new private output outside the source directory; source files must remain read-only.',
    'source.output_exists': 'Preserve the existing output. Reuse it only after verifying its pinned input and component hashes; otherwise choose a new output file.',
    'source.output_parent_missing': 'Create the approved private destination directory outside the source before retrying.',
    'source.output_parent_invalid': 'Choose an existing canonical output directory without redirected ancestors.',
    'source.output_permission_denied': 'Check write access to the approved private destination; do not write into the source.',
    'source.redirected_output': 'Choose a canonical private output directory without symlinks or redirected ancestors.',
    'source.output_parent_changed': 'The output directory changed during extraction. Investigate the destination before retrying with a new file.',
    'source.output_replaced': 'The output entry was replaced during extraction. Preserve the replacement and investigate before retrying.',
    'source.output_io_error': 'Investigate destination access, capacity or concurrent changes. Do not overwrite an existing result.',
    'source.path_depth_limit': 'Split the approved snapshot into coherent scopes within the documented path-depth limit; retain the full inventory denominator.',
    'source.entry_limit': 'Split the approved snapshot into coherent scopes within the directory-entry bound; do not repeatedly scan the same oversized scope.',
    'source.byte_limit': 'Split the approved snapshot within the documented per-file and total byte bounds; do not silently truncate evidence.',
    'source.snapshot_limit': 'Split the approved snapshot within the documented file and byte bounds; retain cross-scope dependencies and omissions.',
    'source.file_limit': 'Supply a bounded file mapping within the documented file-count limit.',
    'source.structure_limit': 'The parsed structure exceeds safe bounds. Investigate a smaller coherent export; do not raise limits or truncate blindly.',
    'source.unsafe_path': 'Use normalized relative snapshot paths without traversal, control characters or ambiguous separators.',
    'source.path_collision': 'Resolve case or Unicode path collisions in a separate approved snapshot; preserve original source identifiers.',
    'source.file_directory_collision': 'Resolve file/directory path collisions in a separate approved snapshot before parsing.',
    'source.dependency_missing': 'Install the pinned optional dependencies from scripts/requirements-source-adapters.txt in the selected interpreter, then verify that environment before retrying.',
    'source.dependency_unavailable': 'Check the selected interpreter against scripts/requirements-source-adapters.txt; a required parser import failed. Do not repeatedly retry the same environment.',
    'source.import_failed': 'Check the adapter installation and selected interpreter. An import failed; its cause was not classified as a missing optional dependency.',
    'source.parser_io_error': 'Check locally installed parser/schema resources and snapshot availability. No missing manifest or dependency was inferred from this I/O failure.',
    'source.invalid_input': 'Inspect the approved input against the selected adapter format and retained local evidence. The cause is not specific enough for automatic retry.',
    'source.empty_snapshot': 'No readable text files were collected. Check the approved scope and retained omissions before supplying a supported export.',
    'source.unsupported_input': 'Some supplied files are outside the selected adapter contract. Check --capabilities and provide a supported export without relabeling incomplete evidence.',
    'source.manifest_missing': 'No usable dbt manifest was extracted for authored code. Supply a matching supported manifest snapshot explicitly; generated directories may be excluded. Do not run dbt or source code implicitly.',
    'source.manifest_unsupported': 'The supplied dbt manifest schema is unsupported. Check --source dbt --capabilities and retain the original export; do not relabel its schema.',
    'source.manifest_binding_unresolved': 'A supplied dbt manifest does not establish all authored bindings. Verify project paths, revision and resource IDs; preserve unresolved evidence.',
    'source.schema_unavailable': 'Check the adapter reference for explicit pinned schema setup/checksum verification. Parsing does not download schemas.',
    'source.partial_evidence': 'Inspect the retained private result gaps and omissions. Partial evidence can support scoped provisional work; repeated parsing of unchanged inputs will not resolve semantic gaps.',
}
_DEPENDENCY_MODULES = {'yaml', 'sqlglot', 'lkml', 'jsonschema', 'referencing', 'lxml'}
_DEPENDENCY_GAPS = {'sql.parser_dependency_missing', 'looker.parser_dependency_missing',
                    'hex.missing_dependency', 'dbt.yaml_dependency_missing',
                    'coalesce.parser_dependency_missing', 'fabric.parser_dependency_missing'}


def diagnostic(code, stage, status='error'):
    """Emit a stable safe JSON line, separate from the successful stdout contract."""
    if code not in _HINTS:
        code = 'source.invalid_input'
    print(json.dumps({'kind': 'source_adapter_diagnostic', 'schema_version': 1,
                      'status': status, 'code': code, 'stage': stage,
                      'hint': _HINTS[code], 'retry': 'investigate_before_retry'}), file=sys.stderr)


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error includes arbitrary command-line values.
        diagnostic('source.invalid_arguments', 'arguments')
        raise SystemExit(2)


def _failure_code(exc, stage):
    if isinstance(exc, SourceAdapterError):
        return exc.code
    if isinstance(exc, ImportError):
        if (exc.name or '').split('.')[0] in _DEPENDENCY_MODULES:
            return 'source.dependency_missing' if isinstance(exc, ModuleNotFoundError) else 'source.dependency_unavailable'
        return 'source.import_failed'
    if isinstance(exc, OSError):
        if stage in ('output_validation', 'output_write'):
            if isinstance(exc, FileExistsError):
                return 'source.output_exists'
            if isinstance(exc, PermissionError):
                return 'source.output_permission_denied'
            if stage == 'output_validation' and isinstance(exc, FileNotFoundError):
                return 'source.output_parent_missing'
            if isinstance(exc, NotADirectoryError):
                return 'source.output_parent_invalid'
            return 'source.output_io_error'
        if stage == 'input_scan':
            if isinstance(exc, FileNotFoundError):
                return 'source.input_unavailable'
            if isinstance(exc, PermissionError):
                return 'source.input_permission_denied'
            return 'source.input_io_error'
        return 'source.parser_io_error'
    return 'source.invalid_input'


def _partial_diagnostics(result, files, omissions):
    codes = {gap['code'] for gap in result['gaps']}
    selected = set()
    if codes & _DEPENDENCY_GAPS:
        selected.add('source.dependency_unavailable')
    if 'hex.schema_unavailable' in codes:
        selected.add('source.schema_unavailable')
    if 'dbt.unsupported_manifest_version' in codes:
        selected.add('source.manifest_unsupported')
    elif 'dbt.authored_binding_unverified' in codes or 'dbt.ambiguous_manifest_binding' in codes:
        has_manifest = any(o['kind'] == 'dbt_manifest' for o in result['objects'])
        selected.add('source.manifest_binding_unresolved' if has_manifest else 'source.manifest_missing')
    if any(f['status'] == 'unsupported' for f in result['source_files']) or any(
            o['reason'] == 'binary_or_non_utf8_requires_separate_export' for o in omissions):
        selected.add('source.unsupported_input')
    if not files:
        selected.add('source.empty_snapshot')
    for code in sorted(selected):
        diagnostic(code, 'result', 'partial')
    diagnostic('source.partial_evidence', 'result', 'partial')


def collect(root):
    root = Path(root).absolute()
    if not root.is_symlink() and not root.exists():
        raise SourceAdapterError('source.input_missing')
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise SourceAdapterError('source.unsafe_root')
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
                raise SourceAdapterError('source.path_depth_limit')
            with os.scandir(directory_fd) as iterator:
                names = []
                for entry in iterator:
                    entries += 1
                    if entries > MAX_FILES * 4:
                        raise SourceAdapterError('source.entry_limit')
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
                        raise SourceAdapterError('source.non_regular_file')
                    if before.st_size > MAX_FILE_BYTES:
                        raise SourceAdapterError('source.byte_limit')
                    raw = stream.read(MAX_FILE_BYTES + 1)
                    after = os.fstat(stream.fileno())
                if before.st_mtime_ns != after.st_mtime_ns or before.st_size != len(raw) or len(raw) > MAX_FILE_BYTES:
                    raise SourceAdapterError('source.changed_or_oversized_file')
                total += len(raw)
                if total > MAX_TOTAL_BYTES or len(files) >= MAX_FILES:
                    raise SourceAdapterError('source.snapshot_limit')
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
    p = _ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path, nargs='?')
    p.add_argument('--source', choices=SOURCES, required=True)
    p.add_argument('--output', type=Path)
    p.add_argument('--capabilities', action='store_true')
    a = p.parse_args(argv)
    stage = 'arguments'
    try:
        if a.capabilities:
            stage = 'capability'
            print(json.dumps(capability(a.source), indent=2))
            return 0
        if a.root is None or a.output is None:
            raise SourceAdapterError('source.root_and_output_required')
        output = a.output.absolute()
        try:
            source_root = a.root.resolve()
        except RuntimeError:  # pathlib on a symlink loop (Python < 3.13)
            raise SourceAdapterError('source.unsafe_root') from None
        try:
            output.relative_to(source_root)
        except ValueError:
            pass
        else:
            raise SourceAdapterError('source.output_inside_input')
        stage = 'output_validation'
        with new_json_output(output) as write:
            stage = 'input_scan'
            files, omissions = collect(a.root)
            stage = 'parse'
            result = parse(a.source, files)
            result['acquisition'] = {'mode': 'supplied_snapshot', 'omissions': omissions,
                                     'completeness': 'not_established', 'network_calls': 0}
            stage = 'output_write'
            write(result)
            partial = bool(omissions or result['gaps'] or not files or any(f['status'] != 'parsed' for f in result['source_files']))
        print(json.dumps({'status': 'partial' if partial else 'subset_parsed',
                          'files': len(files), 'objects': len(result['objects']),
                          'gaps': len(result['gaps']), 'omissions': len(omissions),
                          'native_validation': 'not_run'}))
        if partial:
            _partial_diagnostics(result, files, omissions)
        return 2 if partial else 0
    except (ValueError, OSError, ImportError) as exc:
        diagnostic(_failure_code(exc, stage), stage)
        return 1


if __name__ == '__main__':
    sys.exit(main())
