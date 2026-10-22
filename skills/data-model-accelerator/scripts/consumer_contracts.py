"""Consumer-visible changes, separated from source fidelity and acceptance.

Baseline metadata is supplied evidence. Optional expression-reference checks read
SQL without running it. A host-recorded decision accepts a change, not data parity.
"""
import copy
from pathlib import Path

from ae_common import hash_json, require, safe_relative
from engagement_stages import fields, identifier, ids, text

DIMENSIONS = ('grain', 'history', 'filters', 'currency', 'access')
QUALIFICATION = ('Source/target contract comparison and bounded static checks only; '
                 'accepted changes are host-attributed decisions, not native validation or consumer parity.')


def _store(state):
    return state.get('workflow', {}).get('consumer_contracts')


def _entities(state):
    return {e['id']: e for e in (state.get('workflow', {}).get('design') or {}).get('entities', [])}


def _columns(value):
    require(type(value) is list and len(value) <= 20000, 'Expected bounded source column list')
    seen = set()
    for column in value:
        fields(column, {'name', 'type', 'description'})
        for key in column: text(column[key])
        require(column['name'] not in seen, 'Duplicate baseline column'); seen.add(column['name'])


def _validate(row, entities):
    fields(row, {'id', 'source_id', 'entity_id', 'consumer_ids', 'baseline', 'proposed_materialization', 'evidence_refs'},
           {'renames', 'proposed_behavior', 'definition_checks'})
    identifier(row['id']); identifier(row['source_id'])
    require(':' in row['source_id'] or '.' in row['source_id'], 'Consumer source must be qualified')
    require(row['entity_id'] in entities, 'Consumer contract target entity is absent')
    ids(row['consumer_ids']); require(row['evidence_refs'], 'Consumer comparison needs baseline evidence references')
    for ref in row['evidence_refs']: text(ref)
    base = row['baseline']
    fields(base, {'columns', 'materialization'}, set(DIMENSIONS))
    _columns(base['columns'])
    for value in [base['materialization'], row['proposed_materialization']]:
        require(value is None or value in {'table', 'view', 'incremental', 'ephemeral', 'materialized_view', 'external', 'unknown'},
                'Use an explicit known materialization or null/unknown')
    for key in DIMENSIONS:
        if key in base and base[key] is not None: text(base[key])
    renames = row.get('renames', {})
    require(type(renames) is dict and set(renames) <= {c['name'] for c in base['columns']}, 'Rename source must be a baseline field')
    for name in renames.values(): text(name)
    require(len(set(renames.values())) == len(renames), 'Several source fields cannot silently collapse under a rename')
    behavior = row.get('proposed_behavior', {})
    require(type(behavior) is dict and set(behavior) <= {'filters', 'currency'}, 'Unsupported consumer behavior field')
    for value in behavior.values():
        if value is not None: text(value)
    checks = row.get('definition_checks', [])
    require(type(checks) is list and len(checks) <= 20000, 'Invalid description checks')
    target_columns = {c['name'] for c in entities[row['entity_id']]['columns']}
    for check in checks:
        fields(check, {'column', 'query_path', 'expression_output', 'described_references'})
        require(check['column'] in target_columns, 'Description check needs an actual public target field')
        safe_relative(check['query_path']); text(check['expression_output'])
        require(check['expression_output']==check['column'], 'Expression output must be the canonical public target field')
        require(type(check['described_references']) is list and check['described_references'], 'Supply the references implied by the description')
        for ref in check['described_references']: text(ref)
    return copy.deepcopy(row)


def register(state, request, artifact_root=None):
    fields(request, {'schema_version', 'contracts'})
    require(request['schema_version'] == 1 and type(request['contracts']) is list and 0 < len(request['contracts']) <= 20000,
            'Invalid consumer contract inventory')
    entities = _entities(state)
    saved = copy.deepcopy(_store(state) or {'schema_version': 1, 'contracts': [], 'reviews': [], 'history': []})
    incoming = [_validate(r, entities) for r in request['contracts']]
    require(len({r['id'] for r in incoming}) == len(incoming), 'Duplicate consumer contract ID')
    prior = {r['id']: r for r in saved['contracts']}
    for row in incoming:
        if row['id'] in prior:
            require(all(prior[row['id']][k] == row[k] for k in ('source_id', 'entity_id', 'baseline')),
                    'Consumer identity and frozen baseline cannot be reassigned; retain a new version separately')
        old_consumers = set(prior.get(row['id'], {}).get('consumer_ids', []))
        require(old_consumers <= set(row['consumer_ids']), 'Consumer requirements cannot silently disappear')
        prior[row['id']] = row
    require(len(prior) <= 20000, 'Consumer contract inventory bound exceeded')
    saved['contracts'] = [prior[key] for key in sorted(prior)]
    if artifact_root is not None:
        from ae_common import _path
        saved['artifact_root'] = str(_path(artifact_root))
    if saved != _store(state):
        saved['history'].append({'contracts_sha256': hash_json(saved['contracts']), 'ids': sorted(r['id'] for r in incoming)})
    state['workflow']['consumer_contracts'] = saved
    return summarize(state)


def _expression_check(state, row, check):
    from naming_artifacts import _read
    from authoring_provenance import mask_static_dbt_sql
    root = (_store(state) or {}).get('artifact_root') or state.get('workflow', {}).get('artifact_root')
    if not root: return {'status': 'unverified', 'reason': 'candidate_root_missing'}
    try:
        import hashlib
        import sqlglot
        from sqlglot import exp
        raw = _read(Path(root), check['query_path'])
        masked, _, gaps = mask_static_dbt_sql(raw.decode('utf-8'))
        # Config is intentionally outside the supported expression reader; a
        # compiled SQL projection may be supplied without running it here.
        if gaps: return {'status': 'unverified', 'reason': 'dynamic_sql', 'sha256': hashlib.sha256(raw).hexdigest()}
        dialect = state.get('answers', {}).get('warehouse')
        trees = sqlglot.parse(masked, read={'motherduck': 'duckdb', 'fabric': 'tsql'}.get(dialect, dialect))
        # Unused CTEs cannot satisfy a public-field assertion. More complex
        # statements need a compiled terminal SELECT, not guessed lineage.
        if len(trees)!=1 or not isinstance(trees[0],exp.Select):
            return {'status':'unverified','reason':'terminal_select_unavailable','sha256':hashlib.sha256(raw).hexdigest()}
        expressions=[p for p in trees[0].expressions if p.alias_or_name==check['expression_output']]
        digest = hashlib.sha256(raw).hexdigest()
        if len(expressions) != 1: return {'status': 'unverified', 'reason': 'expression_not_unique', 'sha256': digest}
        refs = sorted({c.name for c in expressions[0].find_all(exp.Column)})
        missing = sorted(set(check['described_references']) - set(refs))
        return {'status': 'conflict' if missing else 'references_consistent', 'observed_references': refs,
                'missing_references': missing, 'sha256': digest,
                'qualification': 'Direct expression references only; this does not interpret arbitrary business prose or prove complete lineage.'}
    except (ImportError, OSError, UnicodeError, ValueError):
        return {'status': 'unverified', 'reason': 'reader_or_evidence_unavailable'}
    except Exception:
        return {'status': 'unverified', 'reason': 'sql_uninterpreted'}


def _comparison(state, row):
    entity = _entities(state).get(row['entity_id'])
    findings = []
    def add(kind, column=None, before=None, after=None, blocking=True):
        findings.append({'kind': kind, 'column': column, 'before': before, 'after': after, 'requires_decision': blocking})
    if entity is None:
        add('target_missing')
        return {'contract_id': row['id'], 'entity_id': row['entity_id'], 'source_id': row['source_id'],
                'consumer_ids': row['consumer_ids'], 'findings': findings, 'definition_checks': []}
    target = {c['name']: c for c in entity['columns']}
    if not row['baseline']['columns']: add('source_fields_unknown')
    for column in row['baseline']['columns']:
        old = column['name']; new = row.get('renames', {}).get(old, old)
        if new not in target:
            add('public_field_removed', old, column, None); continue
        if old != new: add('public_field_renamed', old, old, new)
        for key in ('type', 'description'):
            if column[key] != target[new][key]:
                add('field_' + key + '_changed', new, column[key], target[new][key])
        if column['type'].lower() in {'unknown','tbd'} or target[new]['type'].lower() in {'unknown','tbd'}:
            add('field_type_unverified', new, column['type'], target[new]['type'], False)
    old, new = row['baseline']['materialization'], row['proposed_materialization']
    if old in (None,'unknown') or new in (None,'unknown'): add('materialization_unverified', before=old, after=new, blocking=False)
    elif old != new: add('materialization_changed', before=old, after=new)
    behavior = {'grain': entity['grain'], 'history': entity['history'], 'access': entity['security'], **row.get('proposed_behavior', {})}
    for key in DIMENSIONS:
        before, after = row['baseline'].get(key), behavior.get(key)
        if before is None or after is None: add(key + '_unverified', before=before, after=after, blocking=False)
        elif before != after: add(key + '_changed', before=before, after=after)
    checks = []
    checked = set()
    for check in row.get('definition_checks', []):
        observed = _expression_check(state,row,check)
        checks.append(dict(check, observation=observed)); checked.add(check['column'])
        if observed['status'] == 'conflict': add('description_expression_conflict',check['column'],check['described_references'],observed.get('observed_references'))
        elif observed['status'] == 'unverified': add('description_expression_unverified',check['column'],blocking=False)
    for column in row['baseline']['columns']:
        new = row.get('renames',{}).get(column['name'],column['name'])
        if new in target and new not in checked:
            add('description_meaning_unverified',new,blocking=False)
    return {'contract_id':row['id'],'entity_id':row['entity_id'],'source_id':row['source_id'],
            'consumer_ids':copy.deepcopy(row['consumer_ids']),'findings':findings,'definition_checks':checks,
            'evidence_refs':copy.deepcopy(row['evidence_refs'])}


def review_bindings(state, contract_ids):
    saved = _store(state) or {}; rows = {r['id']:r for r in saved.get('contracts',[])}
    ids(contract_ids, rows, True)
    return {key:hash_json({'contract':rows[key],'comparison':_comparison(state,rows[key])}) for key in sorted(contract_ids)}


def review(state, request):
    fields(request, {'schema_version','contract_ids','decision','reviewer','review_reference','bindings'})
    require(request['schema_version']==1 and request['decision'] in {'accept_changes','requires_fix','defer'},'Unsupported consumer review')
    text(request['reviewer']); text(request['review_reference'])
    require(request['bindings']==review_bindings(state,request['contract_ids']),'Consumer review is stale or has different scope')
    entry=dict(copy.deepcopy(request),assurance='host_reported_human_change_review')
    saved=_store(state)
    if entry not in saved['reviews']: saved['reviews'].append(entry)
    return summarize(state)


def _review_status(state, row, pin=None):
    pin=pin or review_bindings(state,[row['id']])[row['id']]
    for review in reversed((_store(state) or {}).get('reviews',[])):
        if row['id'] in review['contract_ids'] and review['bindings'].get(row['id'])==pin:
            return review['decision']
    return 'unreviewed'


def summarize(state, selected=None):
    saved=_store(state)
    if not saved: return {'status':'not_adopted','rows':[],'qualification':QUALIFICATION}
    wanted=set(selected) if selected is not None else None
    rows=[]
    for row in saved['contracts']:
        if wanted is not None and row['entity_id'] not in wanted: continue
        comparison=_comparison(state,row)
        pin=hash_json({'contract':row,'comparison':comparison})
        decision=_review_status(state,row,pin)
        pending=[f for f in comparison['findings'] if f['requires_decision']]
        status=('needs_review' if decision in {'requires_fix','defer'} or pending and decision!='accept_changes'
                else 'changes_accepted' if pending else 'no_structural_changes_observed')
        rows.append(dict(comparison,review_status=decision,status=status,comparison_sha256=pin))
    return {'schema_version':1,'status':'needs_review' if any(r['status']=='needs_review' for r in rows) else 'recorded',
            'rows':rows,'counts':{'contracts':len(rows),'needs_review':sum(r['status']=='needs_review' for r in rows),
                                 'changes':sum(sum(f['requires_decision'] for f in r['findings']) for r in rows),
                                 'unverified':sum(sum(not f['requires_decision'] for f in r['findings']) for r in rows)},
            'qualification':QUALIFICATION}


def gaps(state, selected):
    return ['consumer_contract:'+r['contract_id']+':review public contract changes' for r in summarize(state,selected)['rows']
            if r['status']=='needs_review']


def scope_bindings(state):
    saved=_store(state)
    if not saved:return {}
    grouped={}; entities=_entities(state)
    for row in saved['contracts']:
        entity=entities.get(row['entity_id'],{})
        # Authoring changes output bytes by definition. Candidate observations
        # belong to review_bindings, not their own generation prerequisites.
        grouped.setdefault(row['entity_id'],[]).append({'contract':row,'target':
            {key:entity.get(key) for key in ('columns','grain','history','security')}})
    return {key:hash_json(value) for key,value in grouped.items()}
