"""Bounded, offline projection of a dbt Information Schema v1 snapshot.

No dbt command, Jinja, source SQL, package, views.sql, or extension is executed.
DuckDB reads only private copies of bounded local bytes with external access
disabled. Install requirements-dbt-metadata.txt explicitly to enable this reader.

Contract: https://docs.getdbt.com/reference/info-schema
Stages: https://docs.getdbt.com/docs/build/dbt-information-schema
Public v1 column/lineage names were also observed in an isolated dbt 2.0.8 export.
Native aliases/runtime/lineage fields are additionally based on dbt-labs/dbt-fusion
9977b6cbb1b761065536300037560d8e3c037011,
crates/dbt-index-core/src/parquet.rs. That source is not a release certification.
"""
import argparse
from contextlib import contextmanager
from datetime import date, datetime
import hashlib
import importlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import sys
import tempfile

from sensitive_data import scan_bytes
from source_adapters.filesystem import _open_directory, new_json_output, read_assigned

DUCKDB_VERSION = '1.5.5'
MAX_FILES = 64
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_FOOTER_BYTES = 1024 * 1024
MAX_ROWS = 20000
MAX_TOTAL_ROWS = 50000
MAX_COLUMNS = 256
MAX_METADATA_ROWS = 4096
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_PROJECTED_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_VALUE_BYTES = 16384
MAX_LIST_ITEMS = 128
STAGES = ('unknown', 'parse', 'compile', 'run', 'build')
# Public diagnostics are exact fixed codes. Callers may project these without
# copying native decoder messages, paths, or untrusted source values.
ERROR_CODES = frozenset('dbt_info_schema.' + code for code in (
    'byte_limit column_limit_or_duplicate column_limit_or_invalid '
    'conflicting_column_node_id conflicting_declared_type conflicting_lineage_identity '
    'conflicting_resource_identity conflicting_resource_type '
    'dependency_missing_install_requirements_dbt_metadata duplicate_column duplicate_identity '
    'expanded_byte_limit file_limit footer_limit_or_invalid invalid_column_type invalid_field_type '
    'invalid_list_or_limit invalid_number invalid_parquet invalid_parquet_schema invalid_string '
    'metadata_limit missing_required_column missing_required_value no_supported_tables '
    'output_byte_limit output_inside_source_or_unsafe parquet_decode_failed '
    'parse_invocation_has_compiled_metadata parse_invocation_has_run_results path_collision '
    'projected_byte_limit row_count_mismatch row_limit sensitive_or_unscannable_metadata '
    'snapshot_outside_source unsafe_directory unsafe_file unsafe_metadata_path '
    'unsafe_or_malformed_snapshot unsafe_or_oversized_file unsafe_path unsupported_duckdb_version '
    'unsupported_schema_version unsupported_stage unsupported_version_directory value_limit'
).split())


class InformationSchemaError(ValueError):
    """Safe fixed code, never native decoder messages or source values."""


def _fail(code):
    message = 'dbt_info_schema.' + code
    if message not in ERROR_CODES:
        message = 'dbt_info_schema.unsafe_or_malformed_snapshot'
    raise InformationSchemaError(message) from None


def _fields(text, kind='string'):
    return dict.fromkeys(text.split(), kind)


MODEL_FIELDS = dict(
    _fields('unique_id name resource_type package_name original_file_path alias '
            'description node_language database_name schema_name relation_name '
            'identifier materialized access group access_level group_name '
            'properties_yml_file_path source_name source_description'),
    **_fields('enabled contract_enforced', 'bool'),
    **_fields('fqn tags primary_key', 'strings'),
    **_fields('ingested_at', 'timestamp'),
)
COLUMN_FIELDS = dict(
    _fields('node_unique_id unique_id column_name data_type_declared declared_type '
            'data_type_inferred data_type_actual inferred_type catalog_type data_type description'),
    **_fields('column_index', 'integer'), **_fields('tags', 'strings'),
    **_fields('ingested_at', 'timestamp'),
)
COMPILED_FIELDS = {'data_type_inferred', 'data_type_actual', 'inferred_type', 'catalog_type', 'data_type'}
LINEAGE_ALIASES = {
    'from_node_unique_id': 'parent_node_unique_id', 'from_column_name': 'parent_column_name',
    'to_node_unique_id': 'child_node_unique_id', 'to_column_name': 'child_column_name',
}
TABLES = {
    'dbt.project': ('projects', dict(_fields('project_name dbt_version adapter_type git_sha'),
                                   **_fields('schema_version', 'integer')), ('project_name',)),
    'dbt.models': ('models', MODEL_FIELDS, ('unique_id', 'name')),
    'dbt.sources': ('sources', MODEL_FIELDS, ('unique_id', 'name')),
    'dbt.seeds': ('seeds', MODEL_FIELDS, ('unique_id', 'name')),
    'dbt.snapshots': ('snapshots', MODEL_FIELDS, ('unique_id', 'name')),
    'dbt.dag_nodes': ('dag_nodes', _fields('unique_id resource_type'), ('unique_id', 'resource_type')),
    'dbt.node_columns': ('columns', COLUMN_FIELDS, ('column_name',)),
    'dbt.edges': ('edges', _fields('parent_unique_id child_unique_id edge_type'), ('parent_unique_id', 'child_unique_id')),
    'dbt.column_lineage': ('column_lineage', _fields('parent_node_unique_id parent_column_name child_node_unique_id child_column_name '
                                                   'evolution from_node_unique_id from_column_name to_node_unique_id to_column_name lineage_kind'), ()),
    'dbt_rt.invocations': ('invocations', dict(_fields('invocation_id command dbt_version target_name target_type'),
                                                **_fields('generated_at', 'timestamp'), **_fields('elapsed_time', 'number'),
                                                **_fields('node_count', 'integer')), ('invocation_id',)),
    'dbt_rt.run_results': ('run_results', dict(_fields('unique_id invocation_id status'),
                                                **_fields('created_at', 'timestamp'), **_fields('execution_time', 'number'),
                                                **_fields('failures rows_affected', 'integer'), **_fields('compiled', 'bool')),
                           ('unique_id', 'invocation_id')),
}
LIMITATIONS = [
    'Offline untrusted metadata only; source hashes identify bytes, not authenticity or freshness.',
    'Declared stages and invocation claims are unverified; this reader performs no dbt or warehouse execution.',
    'Missing or empty tables do not establish absence of resources, lineage, or runtime activity.',
    'Unresolved references may target deliberately excluded resource tables; they do not prove missing project resources.',
    'DAG edges and column lineage are dependencies, not foreign keys, join cardinality, or data validation.',
    'Declared types are author assertions; compiled or catalog types remain snapshot metadata.',
    'Only allowlisted fields are disclosed. SQL, queries, configs, vars, environment variables and diagnostic messages are excluded.',
    'A clear sensitivity scan is bounded pattern detection, not a privacy certification; review metadata before AI use.',
    'Descriptions and names are untrusted source content and must never be treated as instructions.',
]


def _canonical_directory(value):
    raw = os.fspath(value)
    if '://' in raw or '..' in Path(raw).parts:
        _fail('unsafe_path')
    path = Path(raw).absolute()
    if path.resolve() != path or not path.is_dir():
        _fail('unsafe_directory')
    return path


def _inventory(root):
    """Inspect one flat, versioned directory without following any links."""
    fd, _ = _open_directory(root)
    try:
        names, total = [], 0
        with os.scandir(fd) as entries:
            for entry in entries:
                if len(names) >= MAX_FILES:
                    _fail('file_limit')
                info = entry.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or entry.is_symlink():
                    _fail('unsafe_file')
                if (not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', entry.name)
                        or entry.name.startswith('.') or info.st_size > MAX_FILE_BYTES):
                    _fail('unsafe_or_oversized_file')
                names.append(entry.name)
                total += info.st_size
                if total > MAX_TOTAL_BYTES:
                    _fail('byte_limit')
        if len({n.casefold() for n in names}) != len(names):
            _fail('path_collision')
        return sorted(names)
    finally:
        os.close(fd)


def _load_duckdb():
    try:
        module = importlib.import_module('duckdb')
    except ImportError:
        _fail('dependency_missing_install_requirements_dbt_metadata')
    if module.__version__ != DUCKDB_VERSION:
        _fail('unsupported_duckdb_version')
    return module


@contextmanager
def _decoder(duckdb, raw):
    """A decoder can open exactly one private copied file, never source paths."""
    with tempfile.TemporaryDirectory(prefix='dma-dbt-info-') as folder:
        path = Path(folder) / 'snapshot.parquet'
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
        connection = duckdb.connect(config={
            'autoinstall_known_extensions': 'false', 'autoload_known_extensions': 'false',
            'memory_limit': '64MB', 'threads': '1', 'max_temp_directory_size': '0B',
        })
        try:
            connection.execute('SET allowed_paths = ?', [[str(path)]])
            connection.execute('SET enable_external_access = false')
            connection.execute('SET lock_configuration = true')
            yield connection, str(path)
        finally:
            connection.close()


def _json(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('utf-8')


def _output_bytes(value):
    # Match new_json_output, including its final newline.
    return (json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + '\n').encode('utf-8')


def _validate_parquet_schema(connection, path):
    """Check original footer names before DuckDB can rename duplicate columns."""
    schema = connection.execute('SELECT name, num_children FROM parquet_schema(?)', [path]).fetchmany(MAX_METADATA_ROWS + 1)
    if not schema or len(schema) > MAX_METADATA_ROWS:
        _fail('metadata_limit')
    # Each stack frame is [remaining children, sibling names]. Parquet schema
    # elements are a preorder tree, including the root element.
    stack = [[1, set()]]
    for name, children in schema:
        while stack and stack[-1][0] == 0:
            stack.pop()
        if not stack or len(stack) > 32 or not isinstance(name, str) or len(name) > 1024:
            _fail('invalid_parquet_schema')
        normalized = name.casefold()
        if normalized in stack[-1][1]:
            _fail('duplicate_column')
        stack[-1][0] -= 1
        stack[-1][1].add(normalized)
        if children is not None:
            if type(children) is not int or children < 0 or children > MAX_COLUMNS:
                _fail('column_limit_or_invalid')
            if children:
                stack.append([children, set()])
    if any(frame[0] for frame in stack):
        _fail('invalid_parquet_schema')


def _value(value, kind, field):
    if value is None:
        return None
    if kind == 'timestamp' and isinstance(value, (datetime, date)):
        value = value.isoformat()
    if kind in ('string', 'timestamp'):
        if type(value) is not str:
            _fail('invalid_field_type')
        if len(value.encode('utf-8')) > MAX_VALUE_BYTES:
            _fail('value_limit')
        if '\x00' in value:
            _fail('invalid_string')
        if field in ('original_file_path', 'properties_yml_file_path') and value:
            p = PurePosixPath(value)
            if p.is_absolute() or '..' in p.parts or '\\' in value or ':' in value:
                _fail('unsafe_metadata_path')
    elif kind == 'strings':
        if type(value) is not list or len(value) > MAX_LIST_ITEMS:
            _fail('invalid_list_or_limit')
        value = [_value(v, 'string', field) for v in value]
        if any(v is None for v in value):
            _fail('invalid_field_type')
    elif kind == 'bool':
        if type(value) is not bool:
            _fail('invalid_field_type')
    elif kind in ('integer', 'number'):
        if type(value) not in ((int,) if kind == 'integer' else (int, float)):
            _fail('invalid_field_type')
        if not math.isfinite(value) or value < 0 or value > 2 ** 53:
            _fail('invalid_number')
    return value


def _type_matches(sql_type, kind):
    if kind == 'strings':
        return sql_type == 'VARCHAR[]'
    if kind == 'bool':
        return sql_type == 'BOOLEAN'
    if kind in ('integer', 'number'):
        return sql_type in ('TINYINT', 'SMALLINT', 'INTEGER', 'BIGINT', 'UTINYINT', 'USMALLINT', 'UINTEGER', 'UBIGINT') or (
            kind == 'number' and sql_type in ('FLOAT', 'DOUBLE'))
    return sql_type == 'VARCHAR' or kind == 'timestamp' and (sql_type.startswith('TIMESTAMP') or sql_type == 'DATE')


def _read_table(duckdb, raw, table, source, budget, stage):
    if len(raw) < 12 or raw[:4] != b'PAR1' or raw[-4:] != b'PAR1':
        _fail('invalid_parquet')
    footer = struct.unpack('<I', raw[-8:-4])[0]
    if footer > MAX_FOOTER_BYTES or footer > len(raw) - 12:
        _fail('footer_limit_or_invalid')
    destination, allowed, required = TABLES[table]
    with _decoder(duckdb, raw) as (connection, path):
        meta = connection.execute('SELECT num_rows, num_row_groups FROM parquet_file_metadata(?)', [path]).fetchone()
        if not meta or meta[0] < 0 or meta[0] > MAX_ROWS or budget['rows'] + meta[0] > MAX_TOTAL_ROWS:
            _fail('row_limit')
        budget['rows'] += meta[0]
        if meta[1] > MAX_METADATA_ROWS:
            _fail('metadata_limit')
        _validate_parquet_schema(connection, path)
        schema = connection.execute('DESCRIBE SELECT * FROM read_parquet(?)', [path]).fetchmany(MAX_COLUMNS + 1)
        if len(schema) > MAX_COLUMNS or len({r[0].casefold() for r in schema}) != len(schema):
            _fail('column_limit_or_duplicate')
        names = [r[0] for r in schema]
        selected = [name for name in allowed if name in names]
        if any(field not in names for field in required):
            _fail('missing_required_column')
        if table == 'dbt.node_columns' and not {'node_unique_id', 'unique_id'}.intersection(names):
            _fail('missing_required_column')
        if table == 'dbt.column_lineage' and any(not {canonical, native}.intersection(names)
                                                for canonical, native in LINEAGE_ALIASES.items()):
            _fail('missing_required_column')
        for name, sql_type, *_ in schema:
            if name in allowed and not _type_matches(sql_type, allowed[name]):
                _fail('invalid_column_type')
        sizes = connection.execute(
            'SELECT count(*), coalesce(sum(total_uncompressed_size), 0), '
            'coalesce(sum(CASE WHEN path_in_schema IN (SELECT unnest(?)) THEN total_uncompressed_size ELSE 0 END), 0) '
            'FROM parquet_metadata(?)', [selected, path]).fetchone()
        if sizes[0] > MAX_METADATA_ROWS or sizes[1] > MAX_EXPANDED_BYTES or sizes[2] > MAX_PROJECTED_BYTES:
            _fail('expanded_byte_limit')
        # Projection contains identifiers exclusively from the static allowlist.
        projection = ', '.join('"' + name + '"' for name in selected)
        cursor = connection.execute('SELECT ' + projection + ' FROM read_parquet(?) LIMIT ?', [path, MAX_ROWS + 1])
        rows, identities = [], set()
        while True:
            batch = cursor.fetchmany(128)
            if not batch:
                break
            for values in batch:
                row = {name: _value(v, allowed[name], name) for name, v in zip(selected, values)}
                for field in required:
                    if not row.get(field) or type(row[field]) is not str:
                        _fail('missing_required_value')
                if table == 'dbt.project' and row.get('schema_version', 1) != 1:
                    _fail('unsupported_schema_version')
                if table == 'dbt.column_lineage':
                    for canonical, native in LINEAGE_ALIASES.items():
                        a, b = row.get(canonical), row.get(native)
                        if a and b and a != b:
                            _fail('conflicting_lineage_identity')
                        if not (a or b):
                            _fail('missing_required_value')
                        row[canonical] = a or b
                if table == 'dbt.node_columns':
                    a, b = row.get('node_unique_id'), row.get('unique_id')
                    if a and b and a != b:
                        _fail('conflicting_column_node_id')
                    if not (a or b):
                        _fail('missing_required_value')
                    row['node_unique_id'] = a or b
                    if 'declared_type' in row:
                        if row.get('data_type_declared') and row['data_type_declared'] != row['declared_type']:
                            _fail('conflicting_declared_type')
                        row.setdefault('data_type_declared', row['declared_type'])
                    if stage == 'parse':
                        for key in COMPILED_FIELDS:
                            row.pop(key, None)
                if table == 'dbt_rt.invocations' and row.get('command') not in (None, 'parse', 'compile', 'run', 'build', 'check', 'test', 'seed', 'snapshot', 'show', 'docs generate'):
                    # Full command lines may carry vars/credentials. Never disclose.
                    row.pop('command', None)
                key = _row_key(table, row)
                if key in identities:
                    _fail('duplicate_identity')
                identities.add(key)
                row['evidence'] = {'path': source['path'], 'locator': 'row:' + str(len(rows) + 1), 'sha256': source['sha256']}
                budget['projected'] += len(_json(row))
                if budget['projected'] > MAX_PROJECTED_BYTES:
                    _fail('projected_byte_limit')
                rows.append(row)
        if len(rows) != meta[0]:
            _fail('row_count_mismatch')
    source.update(status='projected', row_count=len(rows), selected_fields=selected,
                  excluded_field_count=len(names) - len(selected),
                  missing_fields=[name for name in allowed if name not in names])
    if stage == 'parse' and table == 'dbt.node_columns':
        source['suppressed_fields'] = [name for name in selected if name in COMPILED_FIELDS]
        source['selected_fields'] = [name for name in selected if name not in COMPILED_FIELDS]
    return destination, rows


def _row_key(table, row):
    if table == 'dbt.node_columns':
        fields = ('node_unique_id', 'column_name')
    elif table == 'dbt.edges':
        fields = ('parent_unique_id', 'child_unique_id')
    elif table == 'dbt.column_lineage':
        fields = ('from_node_unique_id', 'from_column_name', 'to_node_unique_id', 'to_column_name')
    elif table == 'dbt_rt.run_results':
        fields = ('invocation_id', 'unique_id')
    else:
        fields = (TABLES[table][2][0],)
    return tuple(row[field] for field in fields)


def _references(report):
    nodes, resources = set(), {}
    for collection in ('models', 'sources', 'seeds', 'snapshots'):
        for row in report[collection]:
            uid = row['unique_id']
            if uid in nodes:
                _fail('conflicting_resource_identity')
            nodes.add(uid)
            expected = {'models': 'model', 'sources': 'source', 'seeds': 'seed', 'snapshots': 'snapshot'}[collection]
            if row.get('resource_type') not in (None, expected):
                _fail('conflicting_resource_type')
            resources[uid] = expected
    for row in report['dag_nodes']:
        if row['unique_id'] in resources and resources[row['unique_id']] != row['resource_type']:
            _fail('conflicting_resource_type')
        nodes.add(row['unique_id'])
    missing_nodes, missing_columns, missing_invocations = set(), set(), set()
    columns = {(row['node_unique_id'], row['column_name']) for row in report['columns']}
    invocations = {r['invocation_id']: r for r in report['runtime']['invocations']}
    for row in report['columns']:
        if row['node_unique_id'] not in nodes:
            missing_nodes.add(row['node_unique_id'])
    for row in report['edges']:
        missing_nodes.update(row[k] for k in ('parent_unique_id', 'child_unique_id') if row[k] not in nodes)
    for row in report['column_lineage']:
        for side in ('from', 'to'):
            uid, column = row[side + '_node_unique_id'], row[side + '_column_name']
            if uid not in nodes:
                missing_nodes.add(uid)
            if (uid, column) not in columns:
                missing_columns.add((uid, column))
    for row in report['runtime']['run_results']:
        if row['unique_id'] not in nodes:
            missing_nodes.add(row['unique_id'])
        if row['invocation_id'] not in invocations:
            missing_invocations.add(row['invocation_id'])
        elif invocations[row['invocation_id']].get('command') == 'parse':
            _fail('parse_invocation_has_run_results')
    report['coverage'].update(unresolved_node_ids=sorted(missing_nodes),
                              unresolved_columns=[{'node_unique_id': a, 'column_name': b} for a, b in sorted(missing_columns)],
                              unresolved_invocation_ids=sorted(missing_invocations),
                              mixed_invocations=len(invocations) > 1)


def read_information_schema(snapshot_dir, *, source_root=None, stage='unknown'):
    """Return a screened JSON-compatible metadata projection or a safe error.

    ``stage`` is an unverified operator declaration, never an execution receipt.
    Parse suppresses compiled fields, column lineage and runtime tables. Source
    paths and field names are preserved; normalized column aliases are additive.
    Missing relationships are reported, never guessed or silently discarded.
    """
    try:
        if stage not in STAGES:
            _fail('unsupported_stage')
        root = _canonical_directory(snapshot_dir)
        if root.name != 'v1':
            _fail('unsupported_version_directory')
        if source_root is not None:
            boundary = _canonical_directory(source_root)
            if not root.is_relative_to(boundary):
                _fail('snapshot_outside_source')
        names = _inventory(root)
        if not any(name[:-8] in TABLES for name in names if name.endswith('.parquet')):
            _fail('no_supported_tables')
        duckdb = _load_duckdb()
        result = {'schema_version': 1, 'kind': 'dbt_information_schema', 'information_schema_version': 1,
                  'declared_stage': stage, 'stage_verified': False, 'evidence_stage': 'metadata_only',
                  'source_files': [], 'runtime': {'invocations': [], 'run_results': []},
                  'coverage': {'scope': 'allowlisted_local_snapshot', 'export_completeness': 'not_established'},
                  'execution_performed': False, 'native_validation': 'not_run', 'warehouse_validation': 'not_run',
                  'limitations': list(LIMITATIONS)}
        result.update({spec[0]: [] for table, spec in TABLES.items() if not table.startswith('dbt_rt.')})
        budget = {'rows': 0, 'projected': 0, 'bytes': 0}
        for name in names:
            raw = read_assigned(root, name)
            budget['bytes'] += len(raw)
            if budget['bytes'] > MAX_TOTAL_BYTES:
                _fail('byte_limit')
            source = {'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
            result['source_files'].append(source)
            table = name[:-8] if name.endswith('.parquet') else None
            if table not in TABLES:
                source['status'] = 'excluded_not_allowlisted'
                continue
            destination, rows = _read_table(duckdb, raw, table, source, budget, stage)
            if stage == 'parse' and (table == 'dbt.column_lineage' or table.startswith('dbt_rt.')):
                source.update(status='suppressed_parse_stage', suppressed_row_count=len(rows), row_count=0)
                continue
            (result['runtime'] if table.startswith('dbt_rt.') else result)[destination] = rows
        result['coverage']['missing_tables'] = [table for table in TABLES if table + '.parquet' not in names]
        result['coverage']['empty_tables'] = [s['path'][:-8] for s in result['source_files']
                                             if s.get('suppressed_row_count', s.get('row_count')) == 0]
        result['coverage']['suppressed_tables'] = [s['path'][:-8] for s in result['source_files'] if s['status'] == 'suppressed_parse_stage']
        result['coverage']['compiled_fields_suppressed'] = stage == 'parse'
        _references(result)
        if stage != 'parse':
            if result['column_lineage'] or any(any(row.get(k) for k in COMPILED_FIELDS) for row in result['columns']):
                commands = [r.get('command') for r in result['runtime']['invocations']]
                if commands and all(command == 'parse' for command in commands):
                    _fail('parse_invocation_has_compiled_metadata')
                result['evidence_stage'] = 'compiled_metadata'
            if result['runtime']['run_results']:
                result['evidence_stage'] = 'runtime_metadata'
        result['coverage']['rows_projected'] = sum(s.get('row_count', 0) for s in result['source_files'])
        result['coverage']['declared_stage_consistent'] = not (
            stage in ('compile', 'run', 'build') and any(r.get('command') == 'parse' for r in result['runtime']['invocations']))
        body = _output_bytes(result)
        if len(body) > MAX_OUTPUT_BYTES:
            _fail('output_byte_limit')
        scan = scan_bytes(body, 'metadata.json')
        if scan['status'] != 'clear' or not scan['coverage']['complete']:
            _fail('sensitive_or_unscannable_metadata')
        result['sensitivity_scan'] = {'status': 'clear', 'scope': 'exact_projection_before_scan_receipt',
                                      'projection_sha256': scan['artifact_sha256']}
        if len(_output_bytes(result)) > MAX_OUTPUT_BYTES:
            _fail('output_byte_limit')
        return result
    except InformationSchemaError:
        raise
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        _fail('unsafe_or_malformed_snapshot')
    except Exception:
        # Decoder exceptions can contain source values, SQL, paths and footer
        # statistics. They are deliberately never returned or chained.
        _fail('parquet_decode_failed')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot_dir', help='Exact local versioned v1 directory')
    parser.add_argument('--source-root', required=True, help='Source project boundary; output must be outside it')
    parser.add_argument('--stage', choices=STAGES, default='unknown', help='Unverified declared metadata stage')
    parser.add_argument('--output', required=True, help='New private JSON file outside the source project')
    args = parser.parse_args(argv)
    try:
        boundary = _canonical_directory(args.source_root)
        output = Path(args.output).absolute()
        if '..' in Path(args.output).parts or output.resolve().is_relative_to(boundary):
            _fail('output_inside_source_or_unsafe')
        with new_json_output(output) as write:
            report = read_information_schema(args.snapshot_dir, source_root=boundary, stage=args.stage)
            write(report)
        print('dbt_info_schema.written')
        return 0
    except InformationSchemaError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print('dbt_info_schema.failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
