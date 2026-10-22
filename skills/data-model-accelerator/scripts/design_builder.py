"""Assemble explicit design proposals and derive review files without guessing joins.

This helper never reads input repositories or executes SQL. Source extraction,
architectural reasoning and independent review remain separately evidenced work.
"""
import argparse
import base64
import copy
import csv
import io
import json
from pathlib import Path

from ae_common import hash_json, require
from engagement_stages import fields, ids, text, validate_design

NODE_FIELDS = {'id', 'name', 'domain', 'layer', 'object_kind', 'grain', 'keys', 'columns',
               'depends_on', 'asset_ids', 'security', 'history', 'disposition', 'reuse',
               'source_paths', 'catalogue_pointers', 'description', 'display_label',
               'replacement_decision_id', 'mapping_status'}
QUALIFICATION = ('Provisional design projection. Source declarations, proposed keys and relationships '
                 'are not physical verification, business acceptance or execution authority.')


def object_kind(entity):
    # Preserve historical entities; no heuristic based on a display name.
    return entity.get('object_kind', 'source' if entity.get('layer') == 'bronze' else 'model')


def counts(entities):
    result = {'objects': len(entities), 'models': 0, 'sources': 0, 'interfaces': 0,
              'new_models': 0, 'reused_models': 0, 'changed_models': 0,
              'undetermined_models': 0, 'by_layer': {k: 0 for k in ('bronze', 'silver', 'gold')}}
    for entity in entities:
        kind = object_kind(entity)
        result[{'model': 'models', 'source': 'sources', 'interface': 'interfaces'}[kind]] += 1
        if kind != 'model':
            continue
        result['by_layer'][entity['layer']] += 1
        disposition = entity.get('disposition', 'undetermined')
        result[{'create': 'new_models', 'reuse': 'reused_models', 'extend': 'changed_models',
                'replace': 'changed_models', 'undetermined': 'undetermined_models'}[disposition]] += 1
    return result


def assemble(request):
    """Normalize one bounded proposal, retaining every node and edge or failing clearly."""
    fields(request, {'schema_version', 'kind', 'id', 'revision', 'nodes', 'edges'},
           {'assets', 'decisions', 'existing_models'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1
            and request['kind'] == 'design_assembly', 'Unsupported design assembly contract')
    require(type(request['nodes']) is list and 0 < len(request['nodes']) <= 20000,
            'Assembly needs a bounded nonempty node list')
    require(type(request['edges']) is list and len(request['edges']) <= 20000,
            'Assembly needs a bounded edge list')
    entities = []
    for value in request['nodes']:
        fields(value, {'id', 'name', 'domain', 'layer'}, NODE_FIELDS)
        kind = value.get('object_kind', 'source' if value['layer'] == 'bronze' else 'model')
        require(kind in {'model', 'source', 'interface'}, 'Unknown object kind')
        entity = {'grain': 'unknown', 'keys': [], 'columns': [], 'depends_on': [],
                  'asset_ids': [], 'security': 'unknown', 'history': 'unknown',
                  'disposition': 'undetermined', 'reuse': None, 'source_paths': [],
                  'catalogue_pointers': [], 'mapping_status': 'inferred',
                  **copy.deepcopy(value), 'object_kind': kind}
        require(type(entity['columns']) is list, 'Columns must be a list')
        columns = []
        for column in entity['columns']:
            fields(column, {'name'}, {'type', 'description', 'key', 'nullable'})
            columns.append({'type': 'unknown', 'description': 'Definition not supplied.', **column})
        entity['columns'] = columns
        # No key/type fabrication and no copying target claims into an existing baseline.
        entities.append(entity)
    design = {'schema_version': 1, 'id': request['id'], 'revision': request['revision'],
              'entities': entities, 'relationships': copy.deepcopy(request['edges']),
              'assets': copy.deepcopy(request.get('assets', [])),
              'decisions': copy.deepcopy(request.get('decisions', [])),
              'existing_models': copy.deepcopy(request.get('existing_models', []))}
    for edge in design['relationships']:
        require(type(edge) is dict, 'Edges must be objects')
        # A data derivation is not an assertion of relational multiplicity.
        require(edge.get('kind') != 'lineage' or not any(
            key in edge for key in ('cardinality', 'from_columns', 'to_columns', 'predicate')),
            'Keep lineage and join conditions on separate edges')
        if edge.get('kind') == 'relationship' and 'cardinality' in edge:
            require(edge['cardinality'] in {'unknown', 'one_to_one', 'one_to_many', 'many_to_one', 'many_to_many'},
                    'Unknown relationship cardinality; use unknown rather than guessing')
    return validate_design(design)


def scaffold(nodes, *, design_id, revision=1):
    """Turn normalized inventory nodes into an explicitly incomplete authoring request."""
    request = {'schema_version': 1, 'kind': 'design_assembly', 'id': design_id,
               'revision': revision, 'nodes': copy.deepcopy(nodes), 'edges': []}
    assemble(request)
    return request


def _cell(value):
    return str(value).replace('|', '\\|').replace('\r', ' ').replace('\n', ' ')


def narrative(design):
    from design_consistency import project_review, assess_design
    projected = project_review(design)
    totals = counts(projected['models'])
    checks = assess_design(design)
    lines = ['# Data model design', '', 'Design: ' + _cell(design['id']) +
             ' · Revision: ' + str(design['revision']), '', QUALIFICATION, '',
             '{} model candidates · {} source objects · {} external interfaces'.format(
                 totals['models'], totals['sources'], totals['interfaces']), '',
             '{} structural findings · {} unknowns. Completeness requires the separate source coverage record.'.format(
                 len(checks['findings']), len(checks['unknowns'])), '']
    for layer in ('bronze', 'silver', 'gold'):
        rows = [e for e in design['entities'] if e['layer'] == layer]
        lines += ['## ' + layer.title(), '']
        if not rows:
            lines += ['No objects declared in this layer. Confirm the scoped architecture; this does not establish completeness.', '']
        for entity in rows:
            lines += ['### ' + _cell(entity['name']), '',
                      'ID: `' + _cell(entity['id']) + '` · Kind: ' + object_kind(entity) +
                      ' · Disposition: ' + entity['disposition'], '',
                      'Grain: ' + _cell(entity['grain']), '',
                      'Declared/proposed keys: ' + (', '.join(map(_cell, entity['keys'])) or 'Not supplied'), '',
                      'History: ' + _cell(entity['history']), '',
                      'Security: ' + _cell(entity['security']), '',
                      'Dependencies: ' + (', '.join(map(_cell, entity['depends_on'])) or 'None declared'), '',
                      '| Column | Type | Key | Definition |', '|---|---|---|---|']
            lines += ['| ' + ' | '.join(_cell(v) for v in (c['name'], c['type'],
                       'declared/proposed' if c['name'] in entity['keys'] else '', c['description'])) + ' |'
                      for c in entity['columns']]
            if not entity['columns']:
                lines += ['| Not supplied | unknown | | Interface or incomplete column inventory |']
            lines.append('')
    lines += ['## Relationships and lineage', '', '| From | To | Kind | Cardinality | Bindings / condition |',
              '|---|---|---|---|---|']
    for edge in projected['relationships']:
        binding = edge.get('predicate') or (' → '.join(', '.join(edge.get(k, [])) for k in ('from_columns', 'to_columns'))
                                          if edge.get('from_columns') else 'Not supplied')
        lines.append('| ' + ' | '.join(_cell(v) for v in (edge['from'], edge['to'], edge['kind'],
                     edge.get('cardinality', 'not applicable' if edge['kind'] == 'lineage' else 'unknown'), binding)) + ' |')
    lines += ['', '## Decisions', '']
    for decision in design['decisions']:
        lines += ['- ' + _cell(decision['id']) + ': ' + _cell(decision['question']) +
                  ' — proposed recommendation: ' + _cell(decision.get('recommendation') or 'none') +
                  '. Answer through the engagement; a recommendation is not approval.']
    if not design['decisions']:
        lines += ['No decisions declared. This does not establish business acceptance.']
    return '\n'.join(lines) + '\n'


def export_design(design, destination, *, diagram_mode='classic'):
    """Derive portable design files once. No customer source corpus is exported."""
    from design_consistency import project_review
    from delivery_portal import model_svg, diagram_views
    from guided_workflow import _path, _atomic_write, _secrets
    import hashlib
    design = validate_design(design)
    _secrets(design)
    projected = project_review(design)
    destination = _path(destination)
    require(not destination.exists(), 'Use a new design export directory; existing evidence is immutable')
    require(diagram_mode in ('classic', 'pipelines'), 'Unknown design diagram mode')
    payloads = {'design.json': json.dumps(design, indent=2).encode() + b'\n',
                'DESIGN.md': narrative(design).encode(),
                'model-graph.json': json.dumps(projected, indent=2).encode() + b'\n'}
    if diagram_mode == 'classic':
        payloads['ERD.svg'] = model_svg(projected['models'], projected['relationships']).encode()
        for index, view in enumerate(diagram_views(projected['models'], projected['relationships'])):
            payloads['ERD-view-' + str(index + 1) + '.svg'] = base64.b64decode(view['base64'], validate=True)
    else:
        from pipeline_diagrams import pipeline_views
        from delivery_portal import diagram_export_path, _markdown_cell
        from urllib.parse import quote
        lines = ['# Model pipelines', '', 'Choose one gold output. Read each diagram from raw inputs down to its output. Joins remain in the model graph and design document.', '']
        for index, view in enumerate(pipeline_views(projected['models'], projected['relationships']), 1):
            name = diagram_export_path(view, index, 2).split('/', 1)[1]
            payloads[name] = base64.b64decode(view['base64'], validate=True)
            lines.append('- [' + _markdown_cell(view['label']) + '](' + quote(name, safe='/') + ')')
        payloads['PIPELINES.md'] = ('\n'.join(lines) + '\n').encode()
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    def safe(value):
        value = str(value)
        return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
    writer.writerow(projected['dictionary_fields'])
    writer.writerows([[safe(v) for v in row] for row in projected['dictionary_rows']])
    payloads['DICTIONARY.csv'] = stream.getvalue().encode('utf-8-sig')
    manifest = {'schema_version': 1, 'kind': 'canonical_design_export',
                'design_binding': projected['design_binding'], 'counts': counts(design['entities']),
                'model_ids': [e['id'] for e in design['entities']],
                'files': {name: hashlib.sha256(raw).hexdigest() for name, raw in payloads.items()},
                'qualification': QUALIFICATION}
    destination.mkdir(parents=True)
    for name, raw in payloads.items():
        (destination / name).parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(destination / name, raw, replace=False)
    _atomic_write(destination / 'DESIGN_MANIFEST.json', json.dumps(manifest, indent=2).encode() + b'\n', replace=False)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('assemble', 'export'):
        command = sub.add_parser(name)
        command.add_argument('--document', type=Path, required=True)
        command.add_argument('--output', type=Path, required=True)
        if name == 'export':
            command.add_argument('--diagram-mode', choices=('pipelines', 'classic'), default='pipelines')
    args = parser.parse_args(argv)
    try:
        from guided_workflow import _nonsecret_json, _atomic_write
        value = _nonsecret_json(args.document)[0]
        if args.command == 'assemble':
            result = assemble(value)
            _atomic_write(args.output, json.dumps(result, indent=2).encode() + b'\n', replace=False)
            print(json.dumps({'design_id': result['id'], 'counts': counts(result['entities']), 'qualification': QUALIFICATION}))
        else:
            print(json.dumps(export_design(value, args.output, diagram_mode=args.diagram_mode), indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, 'Design authoring: ' + str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
