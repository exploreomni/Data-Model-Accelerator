"""Lossless consolidation of adapter evidence from one approved source inventory.

No native execution, source acquisition, target mapping or coverage inference.
Source hashes are checked for internal consistency here; the coordinator must
verify them against pinned input bytes before claiming source authenticity.
"""
import copy
import json
import re

from .base import bounded, occurrence_id, sha, validate_files

_CATEGORIES = ('objects', 'expressions', 'dependencies', 'gaps')
_HASH = re.compile(r'[0-9a-f]{64}\Z')


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False)


def _file_key(item):
    if (not isinstance(item, dict) or not isinstance(item.get('source'), str) or not item['source']
            or not isinstance(item.get('path'), str) or not isinstance(item.get('sha256'), str)
            or not _HASH.fullmatch(item['sha256'])):
        raise ValueError('source.invalid_file_evidence')
    validate_files({item['path']: ''})
    return item['source'], item['path']


def _contract(report):
    bounded(report)
    if (not isinstance(report, dict) or report.get('schema_version') != 1
            or report.get('kind') != 'source_adapter_result'
            or not isinstance(report.get('source'), str) or not report['source']
            or not isinstance(report.get('source_files'), list)
            or any(not isinstance(report.get(key), list) for key in _CATEGORIES)):
        raise ValueError('source.invalid_contract')
    if (report.get('execution_performed') is not False or report.get('native_validation') != 'not_run'
            or report.get('export_completeness') != 'not_established'):
        raise ValueError('source.false_completeness_claim')
    source, files = report['source'], {}
    for item in report['source_files']:
        if not isinstance(item, dict):
            raise ValueError('source.invalid_file_evidence')
        _file_key(dict(item, source=source))
        if item.get('status') not in ('parsed', 'partial', 'unsupported'):
            raise ValueError('source.invalid_file_evidence')
        if item['path'] in files:
            raise ValueError('source.duplicate_file')
        files[item['path']] = item['sha256']
    validate_files({path: '' for path in files})
    object_ids = {o.get('id') for o in report['objects'] if isinstance(o, dict) and isinstance(o.get('id'), str)}
    for category in _CATEGORIES:
        identities = set()
        seen = {}
        for item in report[category]:
            if not isinstance(item, dict) or not isinstance(item.get('evidence'), dict):
                raise ValueError('source.invalid_evidence')
            evidence = item['evidence']
            if (evidence.get('path') not in files or evidence.get('sha256') != files[evidence['path']]
                    or not isinstance(evidence.get('locator'), str) or not evidence['locator']):
                raise ValueError('source.invalid_evidence')
            if category in ('objects', 'expressions'):
                identity = item.get('id')
                if not isinstance(identity, str) or not identity or identity in identities:
                    raise ValueError('source.duplicate_or_invalid_identity')
                identities.add(identity)
            owner = item.get('object_id', item.get('source_id'))
            if (category == 'dependencies' and owner is None) or (owner is not None and owner not in object_ids):
                raise ValueError('source.dangling_owner')
            key = (evidence['path'], evidence['locator'])
            ordinal = seen.get(key, 0)
            if ('occurrence_id' in item and item['occurrence_id'] !=
                    occurrence_id(source, category, *key, ordinal)):
                raise ValueError('source.invalid_occurrence')
            seen[key] = ordinal + 1
            if category == 'expressions':
                if not isinstance(item.get('text'), str):
                    raise ValueError('source.invalid_expression')
                if 'content_sha256' in item and item['content_sha256'] != sha(item['text']):
                    raise ValueError('source.invalid_expression_hash')
    for item in report['source_files']:
        if item['status'] == 'parsed' and any(g['evidence']['path'] == item['path'] for g in report['gaps']):
            raise ValueError('source.hidden_coverage_gap')


def merge_reports(reports, *, expected_files=None):
    """Merge v1 contracts without selecting columns or overwriting conflicts.

    ``expected_files`` optionally supplies ``source/path/sha256`` records from
    the pinned inventory. Missing files are counted, not a generation gate.
    Without it the denominator covers received reports only, never all native
    assets or fields. Original contracts preserve unknown/additive metadata.
    """
    if not isinstance(reports, (list, tuple)):
        raise ValueError('source.invalid_reports')
    contracts, files, components = {}, {}, {}
    merged = {category: {} for category in _CATEGORIES}
    occurrences = {category: {} for category in _CATEGORIES}
    for report in reports:
        _contract(report)
        source = report['source']
        component = report.get('component_sha256')
        if component is not None:
            if not isinstance(component, str) or not _HASH.fullmatch(component):
                raise ValueError('source.invalid_component')
            if source in components and components[source] != component:
                raise ValueError('source.conflicting_component')
            components[source] = component
        contracts[_json(report)] = report
        for item in report['source_files']:
            key = (source, item['path'])
            if key in files and files[key] != item:
                raise ValueError('source.conflicting_file')
            files[key] = item
        for category in _CATEGORIES:
            for item in report[category]:
                evidence = item['evidence']
                if category in ('objects', 'expressions'):
                    identity = item['id']
                elif 'occurrence_id' in item:
                    identity = item['occurrence_id']
                elif category == 'dependencies':
                    if not isinstance(item.get('details', {}), dict):
                        raise ValueError('source.invalid_contract')
                    identity = _json([evidence['path'], evidence['locator'], item['source_id'],
                                      item.get('target'), item.get('details', {}).get('kind')])
                else:
                    identity = _json([evidence['path'], evidence['locator'], item.get('code')])
                key = (source, identity)
                if key in merged[category] and merged[category][key] != item:
                    raise ValueError('source.conflicting_record')
                if 'occurrence_id' in item:
                    occurrence = (source, item['occurrence_id'])
                    if occurrence in occurrences[category] and occurrences[category][occurrence] != item:
                        raise ValueError('source.conflicting_record')
                    occurrences[category][occurrence] = item
                merged[category][key] = item
    expected = {}
    if expected_files is not None:
        if not isinstance(expected_files, (list, tuple)):
            raise ValueError('source.invalid_expected_files')
        for item in expected_files:
            key = _file_key(item)
            if key in expected and expected[key] != item['sha256']:
                raise ValueError('source.conflicting_file')
            expected[key] = item['sha256']
        for key, item in files.items():
            if key not in expected:
                raise ValueError('source.unexpected_file')
            if expected[key] != item['sha256']:
                raise ValueError('source.conflicting_file')
    else:
        expected = {key: item['sha256'] for key, item in files.items()}
    missing = sorted(set(expected) - set(files))
    result = {'schema_version': 1, 'kind': 'source_adapter_evidence_bundle',
              'source_contracts': [contracts[key] for key in sorted(contracts)],
              'source_files': [{'source': source, 'coverage': files[(source, path)]}
                               for source, path in sorted(files)],
              **{category: [records[key] for key in sorted(records)] for category, records in merged.items()},
              'coverage_summary': {'unit': 'supplied_source_files',
                                   'denominator_basis': 'explicit_inventory' if expected_files is not None else 'received_reports_only',
                                   'expected': len(expected), 'observed': len(files), 'missing': len(missing),
                                   'statuses': {status: sum(f['status'] == status for f in files.values())
                                                for status in ('parsed', 'partial', 'unsupported')}},
              'missing_files': [{'source': source, 'path': path, 'sha256': expected[(source, path)]}
                                for source, path in missing],
              'record_counts': {category: len(records) for category, records in merged.items()},
              'export_completeness': 'not_established', 'semantic_mapping': 'not_assessed',
              'native_validation': 'not_run', 'execution_performed': False,
              'limitations': ['Counts describe retained supplied evidence, not native field coverage or semantic parity.',
                              'Byte authenticity must be verified against the pinned source inventory separately.']}
    return copy.deepcopy(result)
