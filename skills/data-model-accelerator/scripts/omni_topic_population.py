"""Advisory topic consolidation, preserving population and access differences.

A shared base view is a review opportunity, never a requirement to merge. Exact
rules are hashed privately; output contains identifiers, categories and hashes,
not filter values or SQL. This is neither native validation nor access approval.
"""
import copy
import re

from omni_contract import _bounded, _load, _merge, canonical_hash
from omni_query_views import _identity

VERSION = 'omni-topic-population-v2'
QUALIFICATION = ('Declared candidate semantics only. Shared bases do not require consolidation; '
                 'preserve security, joins, fields, measures and audiences pending review. '
                 'No merge is authorized. Native access, row counts and business acceptance remain separate.')
RESOLUTIONS = {'confirmed', 'open_question'}
MAX_DEPTH = 20
CODES = {
    'population.multiple_main_topics': 'Several independent topics share a base view. Separate topics may be intentional; review security, joins, fields, measures and audiences before considering shared definitions.',
    'population.variant_same_population': 'These topics have the same declared fixed population and compatible declared structure. Consolidation is optional; confirm audience and workflow needs before changing either topic.',
    'population.consolidation_incompatible': 'These topics differ in security, joins, fields, measures, scoped views or audience. Keep them separate pending explicit compatibility review; removable defaults do not replace these differences.',
    'population.default_promoted_to_always_where': 'A removable default became a fixed population rule. Confirm this behavior is intended; do not weaken a mandatory or security rule into a default.',
    'population.ai_context_missing_variant': 'Consider documenting this related topic and its intended audience or population in the main topic ai_context.',
    'population.ai_context_missing_main': 'Consider documenting the inherited topic and the intended audience or population difference in this topic ai_context.',
    'population.always_where_unconfirmed': 'Review this fixed population rule and its purpose. Preserve mandatory or security restrictions; optional workflow defaults are a separate choice.',
    'population.extends_unresolved': 'Topic inheritance is malformed, missing, cyclic or unsupported. Keep this evidence gap visible; no compatibility conclusion is available.',
    'population.definition_unresolved': 'The topic definition is invalid, ambiguous or lacks a base view. No compatibility conclusion is available.',
}
GAP_CODES = {'population.extends_unresolved', 'population.definition_unresolved'}
SECURITY_KEYS = {'access_filters', 'required_access_grants', 'access_grants', 'user_attributes', 'permissions', 'roles'}
AUDIENCE_KEYS = {'audience', 'audiences', 'group_label', 'label', 'hidden', 'ignored', 'tags'}


def _need(ok, code):
    if not ok: raise ValueError(code)


def _fields(value):
    return sorted(value) if type(value) is dict else []


def _parents(raw):
    """Match the existing bounded single-parent native contract, fail visibly."""
    if 'extends' not in raw: return []
    value = raw['extends']
    if (type(value) is not list or len(value) != 1 or
            type(value[0]) is not str or not value[0].strip()):
        return None
    return value


def _selected(value, keys):
    """Keep nested security/field rules for hashing, without publishing them."""
    if type(value) is dict:
        result = {}
        for key, item in value.items():
            selected = item if key in keys else _selected(item, keys)
            if key in keys or selected: result[key] = selected
        return result
    if type(value) is list:
        return [v for item in value if (v := _selected(item, keys))]
    return None


def _finding(code, base_view, topics, evidence, fields=(), differences=()):
    topics, fields = sorted(topics), sorted(fields)
    digest = canonical_hash(evidence)
    return {'id': 'TP-' + canonical_hash([VERSION, code, base_view, topics, fields, digest])[:24],
            'code': code, 'severity': 'advisory', 'base_view': base_view, 'topics': topics,
            'fields': fields, 'differences': sorted(differences), 'evidence_sha256': digest,
            'message': CODES[code], 'merge_authorized': False}


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
    """Review exact candidate files without merging or blocking generation.

    Decisions retain {finding_id, resolution, reference, reason}. A decision is
    valid only for its current rule fingerprint. Unmatched decisions remain in
    stale_decisions and require review; independent unchanged decisions survive.
    """
    _bounded(model_files)
    _need(type(model_files) is dict and all(type(k) is str and type(v) is str for k, v in model_files.items()), 'population.files')
    decisions = _decisions([] if decisions is None else decisions)
    raw, views, sources, invalid, relationships, models = {}, {}, {}, set(), [], []
    for path, text in sorted(model_files.items()):
        kind, name = _identity(path)
        if kind not in ('topic', 'view', 'relationships', 'model'): continue
        try:
            obj = _load(text)
        except Exception:
            obj = None
        if kind == 'topic':
            sources.setdefault(name, []).append([path, canonical_hash(text)])
            if type(obj) is not dict or name in raw: invalid.add(name)
            raw[name] = obj if type(obj) is dict else {}
        elif kind == 'view':
            # Preserve duplicate/invalid evidence in fingerprints, never select
            # an arbitrary duplicate as authoritative.
            views.setdefault(name, []).append([path, obj, canonical_hash(text)])
        elif kind == 'relationships': relationships.append([path, obj, canonical_hash(text)])
        else: models.append([path, obj, canonical_hash(text)])
    findings = []

    def chain(name):
        seen, out = [], name
        while out is not None:
            if out in seen or out not in raw or out in invalid or len(seen) >= MAX_DEPTH: return None
            seen.append(out)
            parents = _parents(raw[out])
            if parents is None: return None
            out = parents[0] if parents else None
        return seen

    effective = {}
    for name in raw:
        lineage = chain(name)
        if lineage is None:
            # The malformed local bytes plus the reachable inheritance evidence
            # are private hashes; never echo an invalid value into the report.
            seen, pending, evidence = set(), [name], {}
            while pending and len(seen) <= MAX_DEPTH:
                member = pending.pop()
                if member in seen: continue
                seen.add(member); evidence[member] = sources.get(member)
                parents = _parents(raw.get(member, {}))
                pending.extend(parents or [])
            code = 'population.definition_unresolved' if name in invalid else 'population.extends_unresolved'
            findings.append(_finding(code, None, [name], evidence)); continue
        merged = {}
        for member in reversed(lineage):
            merged = _merge(merged, {k: v for k, v in raw[member].items() if k != 'extends'})
        if type(merged.get('base_view')) is not str or not merged['base_view'].strip():
            findings.append(_finding('population.definition_unresolved', None, [name],
                                     {member: sources[member] for member in lineage})); continue
        effective[name] = {'lineage': lineage, 'definition': merged}

    def dependencies(definition):
        """Bind decisions to supplied referenced view definitions and inheritance.

        This is a fingerprint dependency inventory, not a native selector or
        expression resolver. Implicit joins conservatively pin relationship
        evidence because their selected paths cannot be qualified here.
        """
        names = {definition['base_view']}
        overrides = definition.get('views', {})
        if type(overrides) is dict: names.update(overrides)
        def collect(value, joins=False):
            if type(value) is dict:
                for key, val in value.items():
                    if joins: names.add(key)
                    collect(val, joins)
                    collect(key)
            elif type(value) is list:
                for item in value: collect(item, joins)
            elif type(value) is str:
                names.update(re.findall(r'(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z_*]', value))
        collect(definition); collect(definition.get('joins'), True)
        result, pending = {}, sorted(names)
        while pending:
            name = pending.pop()
            if name in result: continue
            entries = views.get(name, [])
            result[name] = entries
            for _, obj, _ in entries:
                if type(obj) is dict:
                    before = set(names); collect(obj)
                    parents = _parents(obj)
                    if parents: names.update(parents)
                    pending.extend(sorted(names - before - set(result)))
        # Local views can extend a source that is not otherwise referenced.
        if type(overrides) is dict:
            for obj in overrides.values():
                if type(obj) is dict:
                    for parent in _parents(obj) or []:
                        if parent not in result: result[parent] = views.get(parent, [])
        return result

    evidence, categories = {}, {}
    for name, item in effective.items():
        d = item['definition']; deps = dependencies(d)
        payload = {'topic': d, 'views': deps}
        relevant_relations = []
        for path, rels, digest in relationships:
            if type(rels) is not list or 'joins' not in d:
                relevant_relations.append([path, rels, digest])
            else:
                relevant_relations.extend([path, r] for r in rels if type(r) is dict and
                                          r.get('join_from_view') in deps and r.get('join_to_view') in deps)
        evidence[name] = {'definition': d, 'inheritance': item['lineage'],
                          'views': deps, 'relationships': relevant_relations, 'model': models}
        categories[name] = {
            'security': _selected(payload, SECURITY_KEYS),
            'joins': [d.get('joins'), d.get('relationships'), relevant_relations],
            'fields': _selected(payload, {'fields', 'ai_fields', 'dimensions'}),
            'measures': _selected(payload, {'measures'}),
            'audience': _selected(payload, AUDIENCE_KEYS),
            'scoped_views': d.get('views'),
        }

    def finding(code, base, names, fields=(), differences=()):
        findings.append(_finding(code, base, names, {n: evidence[n] for n in sorted(names)}, fields, differences))

    def population(name):
        d = effective[name]['definition']
        return {'fields': _fields(d.get('always_where_filters')),
                'sha256': canonical_hash([d.get('always_where_filters'), d.get('always_where_sql')]),
                'has_sql': d.get('always_where_sql') is not None}

    groups = {}
    for name, item in effective.items(): groups.setdefault(item['definition']['base_view'], []).append(name)
    rows = []
    for base, members in sorted(groups.items()):
        for name in sorted(members):
            local = raw[name]
            parent_filters = (effective[effective[name]['lineage'][1]]['definition'].get('always_where_filters')
                              if len(effective[name]['lineage']) > 1 and effective[name]['lineage'][1] in effective else None)
            new = [f for f in _fields(local.get('always_where_filters'))
                   if type(parent_filters) is not dict or parent_filters.get(f) != local['always_where_filters'][f]]
            if local.get('always_where_sql') is not None: new.append('always_where_sql')
            if new: finding('population.always_where_unconfirmed', base, [name], new)
        if len(members) < 2: continue
        roots = [n for n in members if not any(p in members for p in effective[n]['lineage'][1:])]
        if len(roots) != 1: finding('population.multiple_main_topics', base, roots)
        main = sorted(roots)[0]
        main_def = effective[main]['definition']; main_pop = population(main)
        for name in sorted(members):
            role = 'main' if name == main else 'variant' if main in effective[name]['lineage'] else 'unlinked'
            pop = population(name); d = effective[name]['definition']
            differences = sorted(k for k in categories[name] if categories[name][k] != categories[main][k])
            rows.append({'base_view': base, 'topic': name, 'role': role,
                         'extends': (_parents(raw[name]) or [None])[0],
                         'always_where_fields': pop['fields'] + (['always_where_sql'] if pop['has_sql'] else []),
                         'default_filter_fields': _fields(d.get('default_filters')),
                         'population_sha256': pop['sha256'], 'evidence_sha256': canonical_hash(evidence[name]),
                         'same_population_as_main': pop['sha256'] == main_pop['sha256'],
                         'compatibility_differences': differences,
                         'consolidation': 'keep_separate_pending_review' if differences else 'candidate_for_review',
                         'merge_authorized': False})
            if role == 'main': continue
            if differences: finding('population.consolidation_incompatible', base, [main, name], differences=differences)
            elif pop['sha256'] == main_pop['sha256']:
                finding('population.variant_same_population', base, [main, name])
            if role != 'variant': continue
            promoted = set(_fields(main_def.get('default_filters'))) & set(pop['fields']) - set(main_pop['fields'])
            if promoted: finding('population.default_promoted_to_always_where', base, [main, name], promoted)
            if not _names(main_def.get('ai_context'), name): finding('population.ai_context_missing_variant', base, [main, name])
            if not _names(raw[name].get('ai_context'), main): finding('population.ai_context_missing_main', base, [main, name])
    unique = {f['id']: f for f in findings}
    findings = [unique[k] for k in sorted(unique)]
    by_id = {d['finding_id']: d for d in decisions}
    stale = [dict(d, status='review_required', code='population.decision_stale') for d in decisions if d['finding_id'] not in unique]
    for item in findings:
        decision = by_id.get(item['id'])
        item['resolution'] = decision['resolution'] if decision else 'unresolved'
        item['reference'] = decision['reference'] if decision else None
        item['review_required'] = item['resolution'] == 'unresolved' or item['code'] in GAP_CODES
    justification = {}
    for item in findings:
        if by_id.get(item['id']):
            for topic in item['topics']: justification.setdefault(topic, []).append(by_id[item['id']]['reason'])
    for row in rows: row['justification'] = ' '.join(justification.get(row['topic'], [])) or None
    open_questions = [{'finding_id': f['id'], 'code': f['code'], 'base_view': f['base_view'], 'topics': f['topics'],
                       'fields': f['fields'], 'question': f['message'], 'reference': f['reference']}
                      for f in findings if f['resolution'] != 'confirmed' or f['review_required']]
    unresolved = [f['id'] for f in findings if f['review_required']]
    return {'schema_version': 1, 'kind': 'omni_topic_population', 'version': VERSION,
            'model_candidate_sha256': canonical_hash(model_files),
            'status': 'review_required' if unresolved or stale else 'open_questions' if open_questions else 'complete',
            'unresolved_finding_ids': unresolved, 'findings': findings, 'shared_base_views': rows,
            'open_questions': open_questions, 'decisions': decisions, 'stale_decisions': stale,
            'native_verified': False, 'merge_authorized': False, 'qualification': QUALIFICATION}


def summary_line(contract):
    """Short advisory message; never includes filter values."""
    codes = sorted({f['code'] for f in contract.get('findings', []) if f.get('review_required')})
    if contract.get('stale_decisions'): codes.append('population.decision_stale')
    return ('Omni topic consolidation needs review: ' + ', '.join(codes)
            + '. Candidate generation may continue; no merge or native access is authorized.')
