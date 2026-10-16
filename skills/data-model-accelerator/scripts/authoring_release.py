"""Optional exact-byte authoring qualification for a protected promotion runner.

Diagnostic receipts never authorize authoring, warehouse execution or release.
The external runner policy selects enforcement after its supported scope has
been qualified. Existing signed native/data/security gates remain independent.
"""
from ae_common import hash_file, hash_json, load_json, require
from authoring_evidence import fields, validate_contract
from authoring_quality import evaluate, bindings
from deployment_authority import canonical_path


def bind(reference, root, selected, required, target):
    fields(reference, ('contract_path', 'report_path', 'source_root'))
    contract_path, report_path, source_root = (canonical_path(reference[key])
        for key in ('contract_path', 'report_path', 'source_root'))
    root = canonical_path(root)
    require(source_root != root and source_root not in root.parents and root not in source_root.parents,
            'Authoring source and candidate roots must be separate')
    contract_pin, report_pin = hash_file(contract_path), hash_file(report_path)
    contract, report = validate_contract(load_json(contract_path)), load_json(report_path)
    require(type(report) is dict and type(report.get('outputs')) is dict and report['outputs'],
            'Authoring report needs a nonempty output denominator')
    require(set(required) <= set(report['outputs']) <= set(selected),
            'Authoring coverage must include every release implementation input and only selected artifacts')
    require(all(selected[path] == digest for path, digest in report['outputs'].items()),
            'Authoring outputs differ from the frozen handoff')
    dialect = {'motherduck': 'duckdb', 'fabric': 'tsql'}.get(target['warehouse'], target['warehouse'])
    current = evaluate(root, source_root, contract, list(report['outputs']), dialect)
    require(current == report, 'Authoring evidence differs from current checks; recheck before preparing release')
    require(hash_file(contract_path) == contract_pin and hash_file(report_path) == report_pin,
            'Authoring evidence changed while binding release')
    return {'reference': {key: str(value) for key, value in zip(
                ('contract_path', 'report_path', 'source_root'), (contract_path, report_path, source_root))},
            'contract_sha256': contract_pin, 'report_sha256': report_pin,
            'checker_sha256': report['checker_sha256'], 'bindings': contract['bindings'],
            'mode': contract['mode'], 'status': report['status'], 'counts': report['counts'],
            'output_count': len(report['outputs']), 'required_count': len(required),
            'target_sha256': hash_json(target),
            'qualification': 'Recomputed static observations only; independent native and acceptance evidence is still required.'}


def require_promotion(plan, policy):
    if policy['mode'] != 'live' or plan['action'] != 'promote' or not policy.get('require_authoring_quality', False):
        return
    quality = plan.get('quality', {}).get('authoring')
    require(type(quality) is dict and quality.get('status') == 'passed'
            and quality.get('mode') == 'reviewed_candidate',
            'Protected promotion requires complete passing authoring evidence for reviewed candidates')
    from guided_workflow import load_engagement
    state = load_engagement(plan['engagement_run'])
    require(state.get('workflow', {}).get('design') is not None,
            'Protected authoring promotion requires a saved model design')
    require(quality['bindings'] == bindings(state) and quality['bindings']['catalogue_sha256'] is not None,
            'Authoring promotion bindings differ from the current design/source/catalogue')
    require(canonical_path(quality['reference']['source_root']) == canonical_path(state['inputs']['source']['path']),
            'Authoring promotion must use the engagement source')
    from deployment_workflow import _handoff
    from release_quality import verify_quality
    _, handoff, _ = _handoff(plan['engagement_run'])
    verify_quality(plan, handoff)
    contract = validate_contract(load_json(quality['reference']['contract_path']))
    entities = {e['id']: e for e in state['workflow']['design']['entities']}
    for model in contract['models']:
        require(model['id'] in entities, 'Authoring release model is outside saved design')
        entity = entities[model['id']]
        require(model['columns'] == [column['name'] for column in entity['columns']],
                'Authoring release columns differ from saved design')
        require(model['depends_on'] is not None and
                set(model['depends_on']) & set(entities) == set(entity['depends_on']),
                'Authoring release dependency contract differs from saved design')
    # The plan signature binds all references. This gate also recomputes them;
    # a pasted passed summary cannot satisfy protected promotion.
