"""Source support is separate from warehouse generation/deployment support."""
import hashlib
import importlib
import importlib.metadata
from pathlib import Path
import sys

SOURCES = ('bigquery', 'periscope', 'looker', 'tableau', 'powerbi', 'hex',
           'domo', 'sigma', 'webfocus', 'snowflake', 'redshift', 'clickhouse',
           'motherduck', 'databricks', 'dbt', 'coalesce', 'fabric')


def module(source):
    if source not in SOURCES:
        raise ValueError('source.unknown_adapter')
    return importlib.import_module('source_adapters.' + source)


def capability(source):
    data = dict(module(source).CAPABILITY)
    return dict(data, source=source, native_validation='not_qualified',
                documentation='references/source-adapters/' + source + '.md')


def component_fingerprint(source, _ancestors=()):
    if source in _ancestors:
        raise ValueError('source.component_dependency_cycle')
    from . import base, sql
    selected = module(source)
    paths = {Path(__file__), Path(base.__file__), Path(sql.__file__), Path(selected.__file__)}
    # Include legacy adapter implementations used by compatibility wrappers.
    scripts = Path(__file__).resolve().parent.parent
    research = scripts.parent / 'references' / 'source-adapters' / (source + '.md')
    if research.is_file():
        paths.add(research)
    for name in (source + '_source.py',):
        candidate = scripts / name
        if candidate.is_file():
            paths.add(candidate)
    for name in getattr(selected, 'COMPONENTS', ()):
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError('source.invalid_component_path')
        paths.add(Path(__file__).parent / name)
    if source == 'hex':
        schema = scripts / 'schemas' / 'hex-file-schema.v3.json'
        if schema.is_file():
            paths.add(schema)
    if source in ('powerbi', 'tableau'):
        schema_root = scripts / 'schemas' / source
        if schema_root.is_dir():
            paths.update(p for p in schema_root.rglob('*') if p.is_file() and not p.is_symlink())
    h = hashlib.sha256()
    for path in sorted(paths):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    for dependency in getattr(selected, 'ADAPTER_DEPENDENCIES', ()):
        if dependency not in SOURCES:
            raise ValueError('source.invalid_adapter_dependency')
        h.update((dependency + ':' + component_fingerprint(dependency, _ancestors + (source,))).encode())
    h.update(('python:%d.%d' % sys.version_info[:2]).encode())
    for name in ('sqlglot', 'PyYAML', 'lkml', 'jsonschema', 'referencing', 'lxml'):
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = 'absent'
        h.update((name + ':' + version).encode())
    return h.hexdigest()


def parse(source, files):
    from .base import validate_files
    validate_files(files)
    report = module(source).parse(dict(sorted(files.items())))
    if report.get('source') != source:
        raise ValueError('source.adapter_identity_mismatch')
    report['component_sha256'] = component_fingerprint(source)
    validate(report, files)
    return report


def validate(report, files):
    from .base import sha, bounded
    bounded(report)
    if report.get('kind') != 'source_adapter_result' or report.get('schema_version') != 1:
        raise ValueError('source.invalid_contract')
    if report.get('execution_performed') is not False or report.get('native_validation') != 'not_run':
        raise ValueError('source.false_execution_claim')
    if report.get('export_completeness') != 'not_established':
        raise ValueError('source.false_completeness_claim')
    coverage = report.get('source_files', [])
    if len(coverage) != len(files) or {v['path'] for v in coverage} != set(files):
        raise ValueError('source.incomplete_file_accounting')
    for item in coverage:
        if item['sha256'] != sha(files[item['path']]) or item['status'] not in ('parsed', 'partial', 'unsupported'):
            raise ValueError('source.invalid_file_evidence')
        if item['status'] == 'parsed' and any(g['evidence']['path'] == item['path'] for g in report['gaps']):
            raise ValueError('source.hidden_coverage_gap')
    ids = [o['id'] for o in report['objects']]
    if len(ids) != len(set(ids)):
        raise ValueError('source.duplicate_object')
    expression_ids = [e['id'] for e in report['expressions']]
    if len(expression_ids) != len(set(expression_ids)):
        raise ValueError('source.duplicate_expression')
    for category in ('objects', 'expressions', 'dependencies', 'gaps'):
        for item in report[category]:
            e = item['evidence']
            if e['path'] not in files or e['sha256'] != sha(files[e['path']]) or not e['locator']:
                raise ValueError('source.invalid_evidence')
            owner = item.get('object_id', item.get('source_id'))
            if category == 'dependencies' and owner is None:
                raise ValueError('source.unbound_dependency_owner')
            if owner is not None and owner not in ids:
                raise ValueError('source.dangling_owner')
