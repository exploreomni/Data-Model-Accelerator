"""Versioned authoring evidence. File checks never grant approval or execution.

Records are additive to the existing stage engine. Missing evidence is a result,
not permission to manufacture a value or prevent an explicitly requested draft.
"""
import copy
from pathlib import Path
import re

from ae_common import require, safe_relative, hash_json, hash_file, _path

SHA = re.compile(r'[a-f0-9]{64}\Z')
STATUSES = {'passed', 'failed', 'unsupported', 'not_run'}


def fields(value, required, optional=()):
    require(type(value) is dict and set(required) <= set(value) <= set(required) | set(optional),
            'Invalid authoring evidence fields')


def text(value):
    require(type(value) is str and value.strip() and len(value) <= 8000, 'Expected bounded evidence text')
    return value


def strings(value):
    require(type(value) is list and len(value) <= 20000, 'Expected bounded evidence list')
    require(len(value) == len(set(text(x) for x in value)), 'Duplicate evidence identifiers')
    return value


def validate_contract(value):
    fields(value, ('schema_version', 'kind', 'mode', 'bindings', 'models', 'assumptions', 'provenance'), ('sql_rules',))
    require(type(value['schema_version']) is int and value['schema_version'] == 1
            and value['kind'] == 'authoring_contract', 'Unsupported authoring contract version')
    require(value['mode'] in {'provisional', 'reviewed_candidate'}, 'Invalid authoring mode')
    fields(value['bindings'], ('source_sha256', 'design_sha256', 'catalogue_sha256'))
    for key, digest in value['bindings'].items():
        require((key == 'catalogue_sha256' and digest is None) or
                (type(digest) is str and SHA.fullmatch(digest)), 'Invalid authoring binding')
    for key in ('models', 'assumptions', 'provenance'):
        require(type(value[key]) is list and len(value[key]) <= 20000, 'Invalid authoring collection')
    ids, paths = set(), set()
    for model in value['models']:
        fields(model, ('id', 'path', 'depends_on', 'columns'), ('expressions',))
        require(text(model['id']) not in ids, 'Duplicate authoring model')
        ids.add(model['id'])
        if model['path'] is not None:
            path = safe_relative(model['path'])
            require(path not in paths, 'Ambiguous authoring file ownership')
            paths.add(path)
        for key in ('depends_on', 'columns'):
            require(model[key] is None or type(model[key]) is list, 'Unknown contracts must be null')
            if model[key] is not None:
                strings(model[key])
        expressions = model.get('expressions', {})
        require(type(expressions) is dict and len(expressions) <= 20000, 'Invalid expression contracts')
        for column, expression in expressions.items():
            text(column); text(expression)
            require(model['columns'] is not None and column in model['columns'], 'Expression column outside contract')
    assumption_ids = set()
    for item in value['assumptions']:
        fields(item, ('id', 'model_ids', 'fields', 'category', 'status', 'required_check', 'evidence_refs'))
        require(text(item['id']) not in assumption_ids, 'Duplicate assumption')
        assumption_ids.add(item['id'])
        require(set(strings(item['model_ids'])) <= ids and item['model_ids'], 'Assumption model scope is required')
        strings(item['fields']); strings(item['evidence_refs']); text(item['required_check'])
        require(item['category'] in {'physical', 'business', 'security', 'definition'}, 'Invalid assumption category')
        require(item['status'] in {'unresolved', 'proposed', 'resolved'}, 'Invalid assumption status')
        require(item['status'] != 'resolved' or item['evidence_refs'], 'Resolved assumption needs evidence')
    # Provenance entries are checked by the contextual checker, never accepted
    # as verified merely because an author supplied them.
    require(all(type(row) is dict for row in value['provenance']), 'Invalid provenance entries')
    if 'sql_rules' in value:
        rules = value['sql_rules']; fields(rules, ('contract', 'upstream_paths'))
        from sql_contracts import validate_contract as validate_sql_rules
        validate_sql_rules(rules['contract'])
        strings(rules['upstream_paths'])
        require(len(rules['upstream_paths']) <= 1000, 'SQL upstream file scope is too broad')
        for path in rules['upstream_paths']:
            safe_relative(path)
            require(Path(path).suffix.lower() == '.sql', 'SQL upstream evidence requires SQL files')
    return copy.deepcopy(value)


def capture(root, paths):
    root = _path(root)
    result = {}
    for name in strings(paths):
        path = _path(root / safe_relative(name))
        require(root in path.parents, 'Evidence escapes declared root')
        result[name] = hash_file(path)
    return result


def finding(code, status, *, model_id=None, path=None, field=None):
    require(status in STATUSES, 'Invalid check result')
    return {'code': code, 'status': status, 'model_id': model_id,
            'path': path, 'field': field}


def summarize(findings):
    counts = {status: sum(x['status'] == status for x in findings) for status in sorted(STATUSES)}
    status = ('failed' if counts['failed'] else 'unsupported' if counts['unsupported'] else
              'not_run' if counts['not_run'] or not findings else 'passed')
    return {'status': status, 'counts': counts, 'total': len(findings)}


def make_receipt(contract, outputs, findings, *, checker_sha256, source_evidence=None):
    contract = validate_contract(contract)
    require(type(checker_sha256) is str and SHA.fullmatch(checker_sha256), 'Invalid checker version')
    for inventory in (outputs, source_evidence or {}):
        require(type(inventory) is dict, 'Invalid evidence inventory')
        for path, digest in inventory.items():
            safe_relative(path)
            require(type(digest) is str and SHA.fullmatch(digest), 'Invalid evidence digest')
    findings = copy.deepcopy(findings)
    for item in findings:
        fields(item, ('code', 'status', 'model_id', 'path', 'field'))
        require(item['status'] in STATUSES, 'Invalid check result')
    for assumption in contract['assumptions']:
        if assumption['status'] != 'resolved':
            findings.extend(finding('assumption_unresolved:' + assumption['id'], 'not_run', model_id=model_id)
                            for model_id in assumption['model_ids'])
    return {'schema_version': 1, 'kind': 'authoring_observation',
            'contract_sha256': hash_json(contract), 'bindings': contract['bindings'],
            'mode': contract['mode'], 'outputs': copy.deepcopy(outputs),
            'checker_sha256': checker_sha256, 'source_evidence': source_evidence or {},
            'assumptions': copy.deepcopy(contract['assumptions']),
            'findings': copy.deepcopy(findings), **summarize(findings),
            'authority': 'Static authoring evidence only. No native execution, business acceptance or deployment approval.'}
