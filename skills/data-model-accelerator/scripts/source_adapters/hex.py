"""Adapt the pinned Hex v3 reader into the offline source-evidence contract."""
from collections import defaultdict
import logging
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from .base import Report, read_yaml
from .sql import _QuietParser


CAPABILITY = {
    'formats': ['Hex schemaVersion 3 .hex.yaml project and component exports'],
    'interpretation': 'bounded_static_extraction',
    'acquisition': 'supplied_exports',
    'limitations': [
        'Reuses the checksum-pinned Hex v3 schema and hex_source.inspect_repo; no automatic downloads.',
        'Supplied text is staged in a private temporary directory; notebook code and queries are never run.',
        'SQL/Python dependency analysis is a bounded candidate graph, not the native reactive execution graph.',
        'Warehouse SQL uses an unverified Snowflake parsing assumption; dataframe SQL uses DuckDB.',
        'Runtime inputs, external data, component execution, report interactions and effective access remain unverified.',
        'Other schema versions, notebook exports and unsupported cell languages require separate review.',
    ],
}


def _gap_all(report, paths, code, message):
    for path in paths:
        report.gap(path, code, message)


def _emit(report, native, inventory):
    """Bind every legacy finding to original supplied bytes and native location."""
    projects, cells = defaultdict(list), defaultdict(list)
    for project in inventory['projects']:
        path = project['path']
        value = native[path]
        owner = report.object(path, '$.meta',
                              'hex_component' if project['type'] == 'COMPONENT' else 'hex_project',
                              project['title'], project['project_id'],
                              source_version_id=project['source_version_id'],
                              native_properties={k: v for k, v in value.items() if k != 'cells'},
                              schema_sha256=inventory['schema']['sha256'])
        projects[project['id']].append(owner)
        report.cover(path)
        report.gap(path, 'hex.execution_order_unverified',
                   'Cell array order and execution settings are retained; the native reactive DAG and runtime order are not validated.')
        if value.get('appLayout') or value.get('dataAppCellIds') or value.get('sharedFilters') or value.get('genAppFiles'):
            report.gap(path, 'hex.report_interactions_unverified',
                       'App layout, shared filters and generated app declarations are retained without evaluating report interactions.')

    for cell in inventory['cells']:
        path, order = cell['path'], cell['order']
        location = '$.cells[%d]' % order
        value = native[path]['cells'][order]
        language = native[path]['meta']['codeLanguage']
        parent = projects[cell['project_id']]
        owner = report.object(path, location, 'hex_cell',
                              cell['label'] or cell['cell_type'], cell['cell_id'],
                              project_id=cell['project_id'], scoped_native_id=cell['id'],
                              parent_object_id=parent[0] if len(parent) == 1 else None,
                              cell_order=order, cell_type=cell['cell_type'],
                              native_properties=value, analysis=cell['analysis'],
                              reads=cell['reads'], writes=cell['writes'], status=cell['status'])
        cells[cell['id']].append((owner, path, location))
        source = cell.get('source')
        if isinstance(source, str):
            report.expression(path, location + '.config.source',
                              'sql' if cell['cell_type'] == 'SQL' else language.lower(),
                              source, owner, interpretation='native_source',
                              parsing_dialect=('duckdb' if cell['config'].get('dataFrameCell') else 'snowflake')
                              if cell['cell_type'] == 'SQL' else None)
        if cell['cell_type'] == 'SQL' and not cell['config'].get('dataFrameCell'):
            report.gap(path, 'hex.sql_dialect_unverified',
                       'Legacy analysis assumes Snowflake for warehouse SQL; a connection ID does not verify its dialect.', location)
        if cell['cell_type'] == 'CODE' and language != 'PYTHON':
            report.gap(path, 'hex.unsupported_language',
                       'Code source is retained but only the bounded Python subset is analyzed.', location)
        if cell['cell_type'] == 'INPUT':
            report.gap(path, 'hex.external_inputs_unverified',
                       'Input name, defaults and options are declarations; actual app/run parameter values are unavailable.', location)
        if cell['cell_type'] == 'COMPONENT_IMPORT':
            ref = cell['config'].get('component') or {}
            target = projects.get(ref.get('id'), [])
            resolved = cell['analysis'].get('resolved_component_id') is not None and len(target) == 1
            report.dependency(path, location + '.config.component', owner, ref.get('id', 'unbound'),
                              kind='component_reference', requested_version=ref.get('version'),
                              resolution='supplied_version' if resolved else 'unresolved',
                              target_object_id=target[0] if resolved else None)
            report.gap(path, 'hex.component_runtime_unverified',
                       'Component ID and requested version are retained; matching supplied code is not native component execution.', location)
        for filename in cell['analysis'].get('files', []):
            report.dependency(path, location + '.config.source', owner, filename,
                              kind='external_file_reference', resolution='native_reference')
            report.gap(path, 'hex.external_data_unverified',
                       'A referenced file is evidence only; its data, freshness and runtime availability are not validated.', location)

    resolved_reads = set()
    for edge in inventory['edges']:
        consumers = cells.get(edge['to'], [])
        producers = cells.get(edge['from'], [])
        for owner, path, location in consumers:
            unambiguous = len(consumers) == 1 and (len(producers) == 1 or edge['kind'] in ('warehouse_read', 'file_read'))
            report.dependency(path, location + '.config', owner, edge['from'],
                              kind=edge['kind'], native_evidence=edge['evidence'],
                              resolution='static_candidate' if unambiguous else 'ambiguous',
                              target_object_id=producers[0][0] if len(producers) == 1 else None,
                              supplied_file_sha256=edge.get('sha256'))
            if edge['kind'] == 'variable_read':
                resolved_reads.add((owner, edge['evidence']))
    for cell in inventory['cells']:
        for owner, path, location in cells[cell['id']]:
            # Duplicate identities are not resolved by choosing a last writer.
            if location != '$.cells[%d]' % cell['order'] or path != cell['path']:
                continue
            for name in cell['reads']:
                if (owner, name) not in resolved_reads:
                    report.dependency(path, location + '.config', owner, name,
                                      kind='variable_read', resolution='unresolved')

    for gap in inventory['gaps']:
        locations = cells.get(gap.get('cell'), [])
        if gap.get('asset') in report.files:
            locations = [v for v in locations if v[1] == gap['asset']] or [(None, gap['asset'], '$')]
        if not locations:
            locations = [(None, p, '$') for p in native]
        for _, path, location in locations:
            report.gap(path, 'hex.' + gap['kind'], gap['message'], location)


def parse(files):
    report = Report('hex', files)
    paths = [p for p in sorted(files) if p.endswith('.hex.yaml')]
    if not paths:
        return report.finish()
    try:
        import hex_source
        # Resolve dependencies before legacy code can turn ImportError into a
        # generic cell parse failure; no dependency is installed here.
        import yaml  # noqa: F401
        import jsonschema  # noqa: F401
        import sqlglot  # noqa: F401
    except ImportError:
        _gap_all(report, paths, 'hex.missing_dependency',
                 'Pinned PyYAML, jsonschema and sqlglot dependencies are required for Hex extraction.')
        for path in paths:
            report.cover(path, 'partial')
        return report.finish()

    native = {}
    for path in paths:
        report.cover(path, 'partial')
        report.expression(path, '$', 'hex_yaml', files[path], interpretation='original_export')
        if len(files[path].encode('utf-8')) > hex_source.MAX_BYTES:
            report.gap(path, 'hex.oversized_asset', 'Export exceeds the legacy Hex reader byte bound.')
            continue
        try:
            native[path] = read_yaml(files[path])
        except (ValueError, TypeError, RecursionError):
            report.gap(path, 'hex.yaml_invalid', 'Export is not bounded, unambiguous, JSON-compatible safe YAML.')

    if not native:
        return report.finish()
    try:
        hex_source._schema_validator()
    except (ValueError, OSError):
        _gap_all(report, native, 'hex.schema_unavailable',
                 'Pinned Hex v3 schema is missing or fails its checksum; explicitly bootstrap the reviewed schema before analysis. No schema was downloaded.')
        return report.finish()

    # Reject path prefix collisions before filesystem materialization. Only
    # supplied bytes enter this private directory; source code is never loaded.
    if any(str(parent) in files for path in files for parent in PurePosixPath(path).parents if str(parent) != '.'):
        _gap_all(report, native, 'hex.path_collision', 'Supplied file and directory paths collide; no files were staged.')
        return report.finish()
    with TemporaryDirectory(prefix='dma-hex-source-') as directory:
        root = Path(directory)
        for path, text in sorted(files.items()):
            if path in paths and path not in native:
                continue
            destination = root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding='utf-8')
        try:
            logger, quiet = logging.getLogger('sqlglot'), _QuietParser()
            logger.addFilter(quiet)
            try:
                inventory = hex_source.inspect_repo(root)
            finally:
                logger.removeFilter(quiet)
        except (ValueError, TypeError, RecursionError):
            _gap_all(report, native, 'hex.inspection_failed', 'Bounded Hex inspection failed; native interpretation is unavailable.')
            return report.finish()
    _emit(report, native, inventory)
    return report.finish()
