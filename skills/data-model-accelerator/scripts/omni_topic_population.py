"""Topic population contract: one topic per base view and population.

A topic's population is its base view plus its always-where filters. Default
filters, access grants and field lists are removable presentation choices and
never make a second population. The assessment reads exact candidate bytes,
keeps filter values out of the contract (field names and hashes only) and
reports findings that block delivery until a human decision or an open question
is recorded. It is a structural rule check, not native validation or approval.
"""
import copy
import re

from omni_contract import _bounded, _load, canonical_hash
from omni_query_views import _identity

VERSION = 'omni-topic-population-v1'
QUALIFICATION = ('Declared candidate populations only. Findings need a recorded human decision or open question; '
                 'native row counts, access and business acceptance remain separate.')
RESOLUTIONS = {'confirmed', 'open_question'}
MAX_DEPTH = 20
CODES = {
    'population.multiple_main_topics': 'Several topics share this base view without extending one main topic. Merge them; express filter differences as removable default filters.',
    'population.variant_same_population': 'This topic has the same always-where population as the main topic. Differences in default filters, access or fields do not justify a second topic; merge it into the main topic.',
    'population.default_promoted_to_always_where': 'A default filter of the main topic became a fixed always-where filter in this variant. Confirm the population is intended or keep it removable.',
    'population.ai_context_missing_variant': 'The main topic ai_context does not name this variant and how its population differs.',
    'population.ai_context_missing_main': 'The variant ai_context does not name its main topic and how its population differs.',
    'population.always_where_unconfirmed': 'An always-where population rule was declared. Confirm it is intended (it may have been copied from a legacy explore) or list it as an open question.',
    'population.extends_unresolved': 'The topic extends a topic that is missing, cyclic or too deep.',
}


def _need(ok, code):
    if not ok: raise ValueError(code)


def _fields(value):
    return sorted(value) if type(value) is dict else []


def _parents(raw):
    value = raw.get('extends')
    if value is None: return []
    if type(value) is str: return [value]
    return [v for v in value if type(v) is str] if type(value) is list else []


def _finding(code, base_view, topics, fields=()):
    topics, fields = sorted(topics), sorted(fields)
    return {'id': 'TP-' + canonical_hash([code, base_view, topics, fields])[:12], 'code': code,
            'severity': 'blocking', 'base_view': base_view, 'topics': topics, 'fields': fields,
            'message': CODES[code]}


def _names(text, topic):
    return re.search(r'(?<![A-Za-z0-9_])' + re.escape(topic) + r'(?![A-Za-z0-9_])', str(text or '')) is not None


def _decisions(value):
    _need(type(value) is list and len(value) <= 2000, 'population.decisions')
    seen = set()
    for item in value:
        _need(type(item) is dict and set(item) == {'finding_id', 'resolution', 'reference', 'reason'}
              and all(type(v) is str and 0 < len(v) <= 4000 for v in item.values())
              and item['resolution'] in RESOLUTIONS and item['finding_id'] not in seen, 'population.decision')
        seen.add(item['finding_id'])
    return copy.deepcopy(value)


def assess(model_files, decisions=None):
    """Return the population contract for exact candidate files.

    decisions: [{finding_id, resolution: confirmed|open_question, reference, reason}].
    `reference` is the actual decision or question ID; a decision for an unknown
    finding is rejected as stale rather than silently ignored.
    """
    _bounded(model_files)
    _need(type(model_files) is dict and all(type(k) is str and type(v) is str for k, v in model_files.items()), 'population.files')
    decisions = _decisions([] if decisions is None else decisions)
    raw = {}
    for path, text in sorted(model_files.items()):
        kind, name = _identity(path)
        if kind != 'topic': continue
        try:
            obj = _load(text)
        except Exception:
            obj = None
        raw[name] = obj if type(obj) is dict else {}
    findings = []

    def chain(name):
        seen, out = [], name
        while out is not None:
            if out in seen or out not in raw or len(seen) > MAX_DEPTH: return None
            seen.append(out)
            parents = _parents(raw[out])
            if len(parents) > 1: return None
            out = parents[0] if parents else None
        return seen

    effective = {}
    for name in raw:
        lineage = chain(name)
        if lineage is None:
            findings.append(_finding('population.extends_unresolved', None, [name])); continue
        merged = {}
        for member in reversed(lineage):
            merged.update({k: v for k, v in raw[member].items() if k != 'extends'})
        effective[name] = {'lineage': lineage, 'definition': merged}

    def population(name):
        d = effective[name]['definition']
        return {'fields': _fields(d.get('always_where_filters')),
                'sha256': canonical_hash([d.get('always_where_filters'), d.get('always_where_sql')]),
                'has_sql': d.get('always_where_sql') is not None}

    groups = {}
    for name, item in effective.items():
        base = item['definition'].get('base_view')
        if type(base) is str: groups.setdefault(base, []).append(name)
    rows = []
    for base, members in sorted(groups.items()):
        for name in sorted(members):
            local = raw[name]
            parent_filters = (effective[effective[name]['lineage'][1]]['definition'].get('always_where_filters')
                              if len(effective[name]['lineage']) > 1 and effective[name]['lineage'][1] in effective else None)
            new = [f for f in _fields(local.get('always_where_filters'))
                   if type(parent_filters) is not dict or parent_filters.get(f) != local['always_where_filters'][f]]
            if local.get('always_where_sql') is not None: new.append('always_where_sql')
            if new: findings.append(_finding('population.always_where_unconfirmed', base, [name], new))
        if len(members) < 2:
            continue
        roots = [n for n in members if not any(p in members for p in effective[n]['lineage'][1:])]
        if len(roots) != 1:
            findings.append(_finding('population.multiple_main_topics', base, roots))
        main = sorted(roots)[0]
        main_def = effective[main]['definition']; main_pop = population(main)
        for name in sorted(members):
            role = 'main' if name == main else 'variant' if main in effective[name]['lineage'] else 'unlinked'
            pop = population(name); d = effective[name]['definition']
            rows.append({'base_view': base, 'topic': name, 'role': role,
                         'extends': (_parents(raw[name]) or [None])[0],
                         'always_where_fields': pop['fields'] + (['always_where_sql'] if pop['has_sql'] else []),
                         'default_filter_fields': _fields(d.get('default_filters')),
                         'population_sha256': pop['sha256'],
                         'same_population_as_main': pop['sha256'] == main_pop['sha256']})
            if role != 'variant': continue
            if pop['sha256'] == main_pop['sha256']:
                findings.append(_finding('population.variant_same_population', base, [main, name]))
            promoted = set(_fields(main_def.get('default_filters'))) & set(pop['fields']) - set(main_pop['fields'])
            if promoted:
                findings.append(_finding('population.default_promoted_to_always_where', base, [main, name], promoted))
            if not _names(main_def.get('ai_context'), name):
                findings.append(_finding('population.ai_context_missing_variant', base, [main, name]))
            # An inherited ai_context cannot describe the variant's difference.
            if not _names(raw[name].get('ai_context'), main):
                findings.append(_finding('population.ai_context_missing_main', base, [main, name]))
    unique = {f['id']: f for f in findings}
    findings = [unique[k] for k in sorted(unique)]
    by_id = {d['finding_id']: d for d in decisions}
    _need(set(by_id) <= set(unique), 'population.decision_stale')
    for finding in findings:
        decision = by_id.get(finding['id'])
        finding['resolution'] = decision['resolution'] if decision else 'unresolved'
        finding['reference'] = decision['reference'] if decision else None
    justification = {}
    for finding in findings:
        if by_id.get(finding['id']):
            for topic in finding['topics']:
                justification.setdefault(topic, []).append(by_id[finding['id']]['reason'])
    for row in rows:
        row['justification'] = ' '.join(justification.get(row['topic'], [])) or None
    open_questions = [{'finding_id': f['id'], 'code': f['code'], 'base_view': f['base_view'], 'topics': f['topics'],
                       'fields': f['fields'], 'question': f['message'], 'reference': f['reference']}
                      for f in findings if f['resolution'] != 'confirmed']
    unresolved = [f['id'] for f in findings if f['resolution'] == 'unresolved']
    result = {'schema_version': 1, 'kind': 'omni_topic_population', 'version': VERSION,
              'model_candidate_sha256': canonical_hash(model_files),
              'status': 'blocked' if unresolved else 'open_questions' if open_questions else 'complete',
              'unresolved_finding_ids': unresolved, 'findings': findings, 'shared_base_views': rows,
              'open_questions': open_questions, 'decisions': decisions,
              'native_verified': False, 'qualification': QUALIFICATION}
    return result


def summary_line(contract):
    """Short human message for a blocked delivery; never includes filter values."""
    codes = sorted({f['code'] for f in contract.get('findings', []) if f.get('resolution') == 'unresolved'})
    return ('Omni topic population findings need a recorded decision or open question: ' + ', '.join(codes)
            + '. See references/omni-modeler-joins-topics.md#topic-population.')
