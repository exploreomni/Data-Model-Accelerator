"""Capture local DuckDB relation/column metadata after a verified native build.

Fixed metadata queries only; no candidate SQL, plugins or remote connections.
This local adapter does not establish Snowflake, Databricks or BigQuery behavior.
"""
from datetime import datetime, timezone
from pathlib import Path

from ae_common import _path, hash_file, load_json, require, safe_relative, snapshot
from verify_dbt_evidence import verify as verify_native
from verify_engagement import physical_denominator, qualified_relation

MAX_COLUMNS = 100_000


def capture(database, native_path, project):
    import duckdb
    database = _path(database)
    candidate = snapshot(project)
    receipt_hash = hash_file(native_path)
    verified = verify_native(native_path, project_root=project)
    require(verified['evidence_complete'], 'Native build must pass before metadata capture')
    receipt = load_json(native_path)
    require(receipt['expected_adapter_type'] == 'duckdb' and receipt['validation_scope'] == 'local',
            'DuckDB capture supports local DuckDB evidence only')
    manifest = load_json(Path(native_path).parent / safe_relative(receipt['manifest']['path']), max_bytes=100 * 1024 * 1024)
    physical_denominator(manifest)  # Refuse incomplete source identities rather than silently omit them.
    scopes = set()
    for node in list(manifest['nodes'].values()) + list(manifest.get('sources', {}).values()):
        if node.get('resource_type') in ('model', 'seed', 'snapshot', 'source') and node.get('config', {}).get('enabled', True) is not False:
            if node.get('config', {}).get('materialized') != 'ephemeral':
                qualified_relation(node)  # Require fully qualified native identifiers.
                scopes.add((node['database'], node['schema']))
    require(scopes, 'Nonempty native schema scope is required')
    relations, count = {}, 0
    # Block extensions, external file functions and networking for this fixed-query reader.
    with duckdb.connect(str(database), read_only=True, config={'enable_external_access': False}) as connection:
        for catalog, schema in sorted(scopes):
            cursor = connection.execute('select table_catalog, table_schema, table_name, column_name '
                                        'from information_schema.columns where table_catalog = ? and table_schema = ? '
                                        'order by table_name, ordinal_position', [catalog, schema])
            for row in iter(cursor.fetchone, None):
                count += 1
                require(count <= MAX_COLUMNS, 'Metadata population exceeded bound; no partial export produced')
                name = qualified_relation({'database': row[0], 'schema': row[1], 'alias': row[2]})
                relations.setdefault(name, []).append(row[3])
    require(snapshot(project) == candidate and hash_file(native_path) == receipt_hash, 'Candidate/native receipt drift during metadata capture')
    return {'schema_version': 1, 'kind': 'physical_schema_observation', 'candidate_sha256': candidate['sha256'],
            'origin': 'executed_metadata', 'validation_scope': 'local', 'adapter_type': 'duckdb',
            'captured_at': datetime.now(timezone.utc).isoformat(), 'identifier_policy': 'exact',
            'scope': ['"' + catalog.replace('"', '""') + '"."' + schema.replace('"', '""') + '"' for catalog, schema in sorted(scopes)],
            'native_receipt_sha256': receipt_hash, 'invocation_id': manifest['metadata']['invocation_id'],
            'relations': [{'physical_name': name, 'columns': columns} for name, columns in sorted(relations.items())]}
