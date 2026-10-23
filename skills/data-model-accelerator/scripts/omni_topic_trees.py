"""Pinned, SQL-free native topic topology and explicit warehouse coverage.

Occurrences preserve a topic's join paths. Warehouse mappings are supplied by
the review, never inferred from similar names or a view's physical table name.
Local extraction is not native validation, business approval or deployment.
"""
import copy

from omni_contract import (_bounded, _load, canonical_hash, NAME, MAX_DEPTH, RELATION,
                           relationship_reversible)
from omni_query_views import _identity, analyze_query_views

VERSION = 'omni-topic-trees-v1'
QUALIFICATION = ('Declared candidate topology and explicit review bindings only. '
                 'Native execution, security, business acceptance and deployment remain separate.')
CARDINALITIES = {'many_to_one', 'one_to_many', 'one_to_one', 'many_to_many', 'assumed_many_to_one'}
JOIN_TYPES = {'left', 'inner', 'full_outer', 'always_left', 'always_inner'}


def _diagnostic(code, *, path='', node_id=None, severity='gap'):
    return {'code': code, 'path': path, 'node_id': node_id, 'severity': severity}


def _status(diagnostics):
    return ('unresolved' if any(d['severity'] == 'error' for d in diagnostics) else
            'unsupported' if any(d['severity'] == 'unsupported' for d in diagnostics) else 'complete')


def _unique(values):
    return [value for _, value in sorted({canonical_hash(value): value for value in values}.items())]


def _occurrence(topic, path):
    return 'topic-node-' + canonical_hash([topic, path])[:24]


def build_topic_trees(model_files, model_context, warehouse_bindings=None, models=None, domain_map=None):
    """Build from exact candidate bytes, including unresolved topic identities.

    domain_map accepts {topics:{id:domain}, source_folders:{path:domain}} (or a
    flat topic-id map). Bound base-table domains are the final fallback. No raw
    SQL, filters, field definitions or context credentials enter this contract.
    """
    _bounded(model_files); _bounded(model_context)
    if type(model_files) is not dict or not all(type(k) is str and type(v) is str for k, v in model_files.items()):
        raise ValueError('topic_trees.files')
    result = {'schema_version': 1, 'kind': 'omni_topic_trees', 'version': VERSION,
              'pins': {'model_candidate_sha256': canonical_hash(model_files),
                       'model_context_sha256': canonical_hash(model_context)},
              'expected_topic_ids': [], 'topics': [], 'diagnostics': [],
              'structural_status': 'complete', 'binding_status': 'unbound',
              'native_status': 'pending', 'native_verified': False,
              'acceptance_ready': False, 'qualification': QUALIFICATION}
    inventory = {}; global_relations = []; topic_objects = {}
    for path, text in sorted(model_files.items()):
        kind, name = _identity(path)
        if kind == 'topic':
            inventory.setdefault(name, []).append(path)
            try:
                obj = _load(text)
                if type(obj) is dict: topic_objects[name] = obj
            except Exception:
                pass
        elif kind == 'relationships':
            try:
                value = _load(text)
                if type(value) is list:
                    global_relations.extend((path, index, relation) for index, relation in enumerate(value))
                else: result['diagnostics'].append(_diagnostic('topic.relationships_shape', path=path, severity='unsupported'))
            except Exception:
                result['diagnostics'].append(_diagnostic('topic.relationships_parse', path=path, severity='unsupported'))
    result['expected_topic_ids'] = sorted(inventory)
    global_analysis = analyze_query_views(model_files, model_context)
    for topic_id, paths in sorted(inventory.items()):
        source_path = paths[0]
        analysis = analyze_query_views(model_files, model_context, topic=topic_id)
        definition = analysis.get('topic_definition')
        resolved = type(definition) is dict
        definition = definition if resolved else topic_objects.get(topic_id, {})
        base = definition.get('base_view')
        base = base if type(base) is str else None
        topic = {'id': topic_id, 'name': definition.get('label') if type(definition.get('label')) is str else topic_id,
                 'source_path': source_path, 'domain': 'Unassigned', 'domain_source': 'unassigned',
                 'base_view': base, 'joins_state': 'explicit' if 'joins' in definition else 'implicit',
                 'nodes': [], 'edges': [], 'diagnostics': [], 'analysis_diagnostics': copy.deepcopy(analysis['findings']),
                 'structural_status': 'complete', 'binding_status': 'unbound', 'native_status': 'pending',
                 'native_verified': False}
        diagnostics = topic['diagnostics']
        if len(paths) != 1: diagnostics.append(_diagnostic('topic.duplicate_identity', path=source_path, severity='error'))
        if not resolved: diagnostics.append(_diagnostic('topic.definition_unresolved', path=source_path, severity='unsupported'))
        if topic_id not in topic_objects: diagnostics.append(_diagnostic('topic.definition_parse', path=source_path, severity='unsupported'))
        effective = analysis.get('effective_views', {})
        local_views = definition.get('views', {})
        local_views = local_views if type(local_views) is dict else {}
        relations = list(global_relations)
        local_relations = definition.get('relationships', [])
        if type(local_relations) is list:
            relations += [(source_path, index, relation) for index, relation in enumerate(local_relations)]
        else: diagnostics.append(_diagnostic('topic.relationships_shape', path=source_path, severity='unsupported'))

        def node(view_id, path, parent_id):
            identifier = _occurrence(topic_id, path)
            obj = effective.get(view_id, {})
            exists = view_id in effective
            kind = 'modeled_query' if 'query' in obj else 'sql_query' if 'sql' in obj else 'physical_or_inherited'
            origin = analysis.get('binding_origins', {}).get(view_id)
            descriptor = analysis.get('descriptors', {}).get(view_id)
            sources = []
            if kind in ('modeled_query', 'sql_query'):
                if descriptor:
                    columns = list(descriptor.get('population_columns', []))
                    for output in descriptor.get('outputs', {}).values(): columns += output.get('physical_columns', [])
                    sources = sorted({column['view'] for column in columns if type(column.get('view')) is str})
                if not sources: diagnostics.append(_diagnostic('topic.query_dependencies_unresolved', path='/'.join(path), node_id=identifier, severity='unsupported'))
            elif exists:
                sources = [origin or view_id]
            binding_candidates = [topic_id + '/' + view_id, view_id] if view_id in local_views else [view_id]
            shared = global_analysis.get('effective_views', {}).get(view_id)
            local_source_changed = (view_id in local_views and shared is not None and
                                    any(obj.get(key) != shared.get(key) for key in ('catalog','schema','table_name','query','sql')))
            if local_source_changed:
                binding_candidates = [topic_id + '/' + view_id]
                if kind == 'physical_or_inherited': sources = [topic_id + '/' + view_id]
            if origin and origin not in binding_candidates: binding_candidates.append(origin)
            if local_source_changed: binding_candidates = [topic_id + '/' + view_id]
            row = {'id': identifier, 'view_id': view_id, 'name': obj.get('label') if type(obj.get('label')) is str else view_id,
                   'path': list(path), 'parent_id': parent_id, 'kind': kind,
                   'binding_origin': origin, 'binding_candidates': binding_candidates,
                   'physical_view_ids': sources, 'dependencies_complete': bool(sources),
                   'model_ids': [], 'binding_status': 'unbound',
                   'structural_status': 'complete' if exists else 'unresolved'}
            if not exists: diagnostics.append(_diagnostic('topic.view_unresolved', path='/'.join(path), node_id=identifier, severity='error'))
            topic['nodes'].append(row)
            return row

        def edge(parent, child):
            matches = []
            for rel_path, index, relation in relations:
                if type(relation) is not dict: continue
                left, right = relation.get('join_from_view'), relation.get('join_to_view')
                direction = ('forward' if (left, right) == (parent['view_id'], child['view_id']) else
                             'reverse' if (left, right) == (child['view_id'], parent['view_id']) and relationship_reversible(relation) else None)
                if direction: matches.append((rel_path, index, relation, direction))
            row = {'id': 'topic-edge-' + canonical_hash([topic_id, parent['id'], child['id']])[:24],
                   'from': parent['id'], 'to': child['id'], 'from_view': parent['view_id'], 'to_view': child['view_id'],
                   'path': child['path'], 'relationship_id': None, 'relationship_direction': 'unresolved',
                   'declared_relationship_type': None, 'relationship_type': None, 'join_type': None,
                   'relationship_status': 'unresolved'}
            if len(matches) == 1:
                rel_path, index, relation, direction = matches[0]
                cardinality = relation.get('relationship_type')
                join_type = relation.get('join_type')
                supported = (cardinality in CARDINALITIES and join_type in JOIN_TYPES and
                             set(relation) <= RELATION and type(relation.get('on_sql')) is str and
                             bool(relation['on_sql'].strip()) and
                             ('reversible' not in relation or type(relation['reversible']) is bool))
                row.update(relationship_id='topic-relationship-' + canonical_hash([rel_path, index, relation])[:24],
                           relationship_direction=direction, declared_relationship_type=cardinality,
                           relationship_type=({'many_to_one': 'one_to_many', 'one_to_many': 'many_to_one',
                                               'assumed_many_to_one': 'one_to_many'}.get(cardinality, cardinality)
                                              if direction == 'reverse' else cardinality),
                           join_type=join_type, relationship_status='resolved' if supported else 'unsupported')
                if not supported: diagnostics.append(_diagnostic('topic.relationship_unqualified', path='/'.join(child['path']), severity='unsupported'))
            else:
                diagnostics.append(_diagnostic('topic.relationship_ambiguous' if matches else 'topic.relationship_unresolved',
                                               path='/'.join(child['path']), severity='error'))
            topic['edges'].append(row)

        def walk(tree, parent, trail):
            if tree is None: return  # Native leaf syntax: view_name:
            if type(tree) is not dict:
                diagnostics.append(_diagnostic('topic.joins_form_unsupported', path='/'.join(parent['path']), severity='unsupported')); return
            if len(trail) >= MAX_DEPTH:
                diagnostics.append(_diagnostic('topic.join_depth', path='/'.join(parent['path']), severity='unsupported')); return
            for child_id, nested in sorted(tree.items(), key=lambda pair: str(pair[0])):
                if type(child_id) is not str or NAME.fullmatch(child_id) is None:
                    diagnostics.append(_diagnostic('topic.join_identifier_unsupported', path='/'.join(parent['path']), severity='unsupported')); continue
                child = node(child_id, parent['path'] + [child_id], parent['id']); edge(parent, child)
                if child_id in trail:
                    diagnostics.append(_diagnostic('topic.join_cycle', path='/'.join(child['path']), severity='error')); continue
                walk(nested, child, trail + [child_id])

        if base is None:
            diagnostics.append(_diagnostic('topic.base_view_unresolved', path=source_path, severity='error'))
        else:
            root = node(base, [base], None)
            if 'joins' in definition:
                if definition['joins'] is None:
                    diagnostics.append(_diagnostic('topic.joins_form_unsupported', path=source_path, severity='unsupported'))
                else: walk(definition['joins'], root, [base])
            else:
                # Native implicit graphs can be ambiguous; retain the base and
                # disclose the missing expansion instead of treating it as {}.
                diagnostics.append(_diagnostic('topic.implicit_joins_unqualified', path=source_path, severity='unsupported'))
        topic['diagnostics'] = _unique(diagnostics)
        topic['structural_status'] = _status(topic['diagnostics'])
        result['topics'].append(topic)
    result['structural_status'] = _status(result['diagnostics'] + [d for t in result['topics'] for d in t['diagnostics']])
    return bind_topic_trees(result, warehouse_bindings or [], models or [], domain_map=domain_map)


def bind_topic_trees(topology, warehouse_bindings, models, domain_map=None, expected_pins=None):
    """Rebind SQL-free selected evidence using only exact reviewed model IDs.

    Invalid/stale pins raise ValueError; gaps in explicit mappings stay visible.
    Binding status is independent of structural status and native validation.
    """
    _bounded(topology); _bounded(warehouse_bindings); _bounded(models); _bounded(domain_map)
    if type(topology) is not dict or topology.get('kind') != 'omni_topic_trees' or topology.get('version') != VERSION:
        raise ValueError('topic_trees.contract')
    if expected_pins is not None and any(topology.get('pins', {}).get(k) != v for k, v in expected_pins.items()):
        raise ValueError('topic_trees.stale_pins')
    if type(warehouse_bindings) is not list or type(models) is not list:
        raise ValueError('topic_trees.binding_input')
    result = copy.deepcopy(topology)
    result.update(native_status='pending', native_verified=False, acceptance_ready=False)
    model_index = {}; mapping = {}
    for model in models:
        if type(model) is dict and type(model.get('id')) is str: model_index.setdefault(model['id'], []).append(model)
    for binding in warehouse_bindings:
        if type(binding) is not dict or type(binding.get('view_id')) is not str or type(binding.get('model_ids')) is not list:
            raise ValueError('topic_trees.binding_shape')
        if any(type(v) is not str for v in binding['model_ids']): raise ValueError('topic_trees.binding_shape')
        mapping.setdefault(binding['view_id'], []).append(binding['model_ids'])
    domain_map = domain_map or {}
    if type(domain_map) is not dict: raise ValueError('topic_trees.domain_map')
    domains = domain_map.get('topics', domain_map if 'source_folders' not in domain_map else {})
    folders = domain_map.get('source_folders', {})
    if type(domains) is not dict or type(folders) is not dict: raise ValueError('topic_trees.domain_map')
    for topic in result['topics']:
        topic.update(native_status='pending', native_verified=False)
        topic['binding_diagnostics'] = []
        for node in topic['nodes']:
            diagnostics = []; ids = []; selected = []
            explicit = next((name for name in node.get('binding_candidates', []) if name in mapping), None)
            needed = [explicit] if explicit is not None else node.get('physical_view_ids', [])
            if not needed or not node.get('dependencies_complete'):
                diagnostics.append(_diagnostic('topic.binding_dependencies_unresolved', node_id=node['id']))
            for view in needed:
                matches = mapping.get(view, [])
                if len(matches) != 1:
                    diagnostics.append(_diagnostic('topic.binding_ambiguous' if matches else 'topic.binding_missing', node_id=node['id'])); continue
                selected.append(view)
                if not matches[0]: diagnostics.append(_diagnostic('topic.binding_missing', node_id=node['id']))
                for model_id in matches[0]:
                    candidates = model_index.get(model_id, [])
                    if len(candidates) != 1:
                        diagnostics.append(_diagnostic('topic.model_ambiguous' if candidates else 'topic.model_missing', node_id=node['id'])); continue
                    ids.append(model_id)
                    if candidates[0].get('layer') != 'gold': diagnostics.append(_diagnostic('topic.binding_non_gold', node_id=node['id']))
            node['model_ids'] = sorted(set(ids)); node['bound_view_ids'] = sorted(set(selected))
            node['binding_diagnostics'] = _unique(diagnostics)
            node['binding_status'] = 'complete' if ids and not diagnostics else 'gap'
            topic['binding_diagnostics'] += node['binding_diagnostics']
        topic['binding_status'] = 'complete' if topic['nodes'] and all(n['binding_status'] == 'complete' for n in topic['nodes']) else 'gap'
        topic['model_ids'] = sorted({m for n in topic['nodes'] for m in n['model_ids']})
        domain = domains.get(topic['id']); source = 'explicit_topic_map'
        if type(domain) is not str or not domain.strip():
            matches = [(folder.rstrip('/'), value) for folder, value in folders.items()
                       if type(folder) is str and type(value) is str and value.strip() and
                       (topic['source_path'] == folder.rstrip('/') or topic['source_path'].startswith(folder.rstrip('/') + '/'))]
            matches.sort(key=lambda pair: (-len(pair[0]), pair[0]))
            domain = matches[0][1] if matches else None; source = 'source_folder_map'
        if not domain:
            base = next((n for n in topic['nodes'] if n['parent_id'] is None), {})
            values = [model_index[m][0].get('domain') for m in base.get('model_ids', [])]
            domains_known = values and all(type(v) is str and v.strip() for v in values)
            domain = values[0] if domains_known and len(set(values)) == 1 else None; source = 'bound_base_model'
        topic['domain'] = domain or 'Unassigned'; topic['domain_source'] = source if domain else 'unassigned'
    result['binding_status'] = 'complete' if result['topics'] and all(t['binding_status'] == 'complete' for t in result['topics']) else 'gap'
    result['binding_pins'] = {'warehouse_bindings_sha256': canonical_hash(warehouse_bindings),
                              'models_sha256': canonical_hash(models), 'domain_map_sha256': canonical_hash(domain_map)}
    result['coverage'] = topic_tree_coverage(result)
    return result


def topic_tree_coverage(topology):
    """Independent inventory/occurrence coverage; completeness is not approval."""
    expected = topology.get('expected_topic_ids', [])
    topics = topology.get('topics', []); actual = [t.get('id') for t in topics]
    diagnostics = []
    if len(expected) != len(set(expected)) or len(actual) != len(set(actual)) or set(expected) != set(actual):
        diagnostics.append('topic.coverage_inventory_mismatch')
    all_nodes = []; all_edges = []
    for topic in topics:
        nodes = topic.get('nodes', []); edges = topic.get('edges', [])
        ids = [n.get('id') for n in nodes]; edge_ids = [e.get('id') for e in edges]
        all_nodes += ids; all_edges += edge_ids
        roots = [n for n in nodes if n.get('parent_id') is None]
        if (topic.get('base_view') is not None or nodes) and (len(roots) != 1 or len(edges) != len(nodes) - 1):
            diagnostics.append('topic.coverage_tree_shape')
        if roots and (roots[0].get('view_id') != topic.get('base_view') or roots[0].get('path') != [topic.get('base_view')]):
            diagnostics.append('topic.coverage_root_mismatch')
        for node in nodes:
            path = node.get('path', [])
            if not path or node.get('id') != _occurrence(topic['id'], path) or path[-1] != node.get('view_id'):
                diagnostics.append('topic.coverage_occurrence_mismatch')
            if node.get('parent_id') is not None:
                matches = [e for e in edges if e.get('to') == node['id'] and e.get('from') == node['parent_id']]
                if len(matches) != 1: diagnostics.append('topic.coverage_parent_mismatch')
                parents = [p for p in nodes if p.get('id') == node['parent_id']]
                if len(parents) != 1 or parents[0].get('path') != path[:-1]: diagnostics.append('topic.coverage_path_mismatch')
        if any(e.get('from') not in ids or e.get('to') not in ids for e in edges): diagnostics.append('topic.coverage_edge_unresolved')
        for edge in edges:
            if edge.get('id') != 'topic-edge-' + canonical_hash([topic['id'], edge.get('from'), edge.get('to')])[:24]:
                diagnostics.append('topic.coverage_edge_identity')
    if len(all_nodes) != len(set(all_nodes)) or len(all_edges) != len(set(all_edges)): diagnostics.append('topic.coverage_duplicate_identity')
    return {'status': 'complete' if not diagnostics else 'failed', 'expected_topics': len(expected),
            'represented_topics': len(topics), 'nodes': len(all_nodes), 'edges': len(all_edges),
            'fully_bound_topics': sum(t.get('binding_status') == 'complete' for t in topics),
            'structurally_complete_topics': sum(t.get('structural_status') == 'complete' for t in topics),
            'diagnostics': sorted(set(diagnostics)), 'qualification': QUALIFICATION}
