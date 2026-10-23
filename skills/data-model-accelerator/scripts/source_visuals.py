"""Source lineage companions; source evidence never expands the target design."""
import base64
import copy
import hashlib
import json
from urllib.parse import quote

from ae_common import require
import upstream_context


def prepare(state, data):
    models = data.get('review', {}).get('models', [])
    if data.get('audience') == 'audit' or not models or not state.get('workflow', {}).get('upstream_context'):
        return
    ids = sorted(m['id'] for m in models)
    projection = upstream_context.public_projection(state, selected=ids)
    data['source_lineage'] = {'projection': projection, 'csv': upstream_context.csv_export(state, selected=ids)}


def exports(data):
    value = data.get('source_lineage')
    if not value: return []
    projection = value['projection']
    ids = {m['id'] for m in data.get('review', {}).get('models', [])}
    require(set(projection['generation_entity_ids']) <= ids, 'Source context exceeds selected target review')
    folder = '03_Design_Documents/Upstream' if data.get('package_layout_version') == 2 else '01_Model/Upstream'
    mappings = '05_Mappings' if data.get('package_layout_version') == 2 else '01_Model'
    records = []
    def add(key, path, category, body):
        records.append({'id': key, 'path': path, 'category': category, 'requires': [], 'origin': 'review_projection',
                        'description': upstream_context.QUALIFICATION, 'sha256': hashlib.sha256(body).hexdigest(),
                        'size': len(body), 'base64': base64.b64encode(body).decode()})
    lines = ['# Source upstream lineage', '', upstream_context.QUALIFICATION, '',
             'These diagrams retain known source dependencies. They are evidence for the design, not additional approved target models.', '',
             '## Model-specific source context', '']
    for association in projection['entity_roots']:
        scoped = copy.deepcopy(projection)
        keep = set(association['context_object_ids'])
        scoped['nodes'] = [n for n in scoped['nodes'] if n['id'] in keep]
        scoped['edges'] = [e for e in scoped['edges'] if e['consumer_id'] in keep]
        scoped['entity_roots'] = [association]
        scoped['generation_entity_ids'] = [association['entity_id']]
        scoped['seed_object_ids'] = association['root_object_ids']
        scoped['gaps'] = [g for g in scoped['gaps'] if (not g.get('entity_id') or g['entity_id'] == association['entity_id'])
                          and (not g.get('object_ids') or set(g['object_ids']) & keep)]
        name = 'source-' + hashlib.sha256(association['entity_id'].encode()).hexdigest()[:20] + '.svg'
        add('generated:source-lineage:' + name[:-4], folder + '/' + name, 'diagrams', upstream_context.render_svg(scoped).encode())
        from delivery_portal import _markdown_cell
        lines.append('- [' + _markdown_cell(association['entity_id']) + '](' + quote(name) + ') — '
                     + str(len(scoped['nodes'])) + ' known source objects; ' + str(len(scoped['gaps'])) + ' recorded gaps')
    add('generated:source-lineage-index', folder + '/INDEX.md', 'diagrams', ('\n'.join(lines) + '\n').encode())
    add('generated:source-lineage-json', folder + '/SOURCE_LINEAGE.json', 'diagrams',
        (json.dumps(projection, sort_keys=True, ensure_ascii=True) + '\n').encode())
    add('generated:source-lineage-csv', mappings + '/SOURCE_LINEAGE.csv', 'dictionary', value['csv'].encode())
    return records
