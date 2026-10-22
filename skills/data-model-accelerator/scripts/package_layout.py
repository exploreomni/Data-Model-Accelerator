"""Readable handoff paths; never copies source repositories or rewrites artifacts."""
from ae_common import require


SECTIONS = {
    'input_sources': ('01_Input_Sources', 'Input sources', 'Source inventory and explicitly selected source snapshots. Original repositories remain read-only and outside this handoff.'),
    'input_context': ('02_Input_Context_Files', 'Input context files', 'Selected requirements, business rules and catalogue context. Only registered, audience-permitted files are included.'),
    'design': ('03_Design_Documents', 'Design documents', 'Start with the design document, then choose a gold-table pipeline. The dictionary contains complete supplied column definitions.'),
    'code': ('04_Code_Generation', 'Code generation', 'Generated warehouse and semantic code, setup instructions and validation evidence. File presence does not establish execution or approval.'),
    'mappings': ('05_Mappings', 'Mappings', 'Historical-to-target tables, dashboard destinations and migration planning files. Unresolved mappings remain explicit.'),
}
DEFAULT_SECTIONS = {'documentation': 'design', 'diagrams': 'design', 'dictionary': 'design',
                    'implementation': 'code', 'validation': 'code', 'sample_data': 'input_sources'}
ALLOWED = {'input_sources': {'documentation', 'sample_data'},
           'input_context': {'documentation', 'dictionary'},
           'design': {'documentation', 'diagrams', 'dictionary'},
           'code': {'implementation', 'validation', 'documentation'},
           'mappings': {'documentation', 'dictionary'}}


def version(review):
    value = review.get('package_layout_version', 1)
    require(type(value) is int and value in (1, 2), 'Package layout must be version 1 or 2')
    return value


def artifact_destination(record, layout_version, classic_folders):
    category = record['category']
    section = record.get('section')
    if section is not None:
        require(section in ALLOWED and category in ALLOWED[section], 'Artifact section is incompatible with its category')
    if layout_version == 1 or category == 'technical_audit':
        return classic_folders[category] + '/' + record['path']
    section = section or DEFAULT_SECTIONS[category]
    folder = SECTIONS[section][0]
    if category == 'validation':
        folder += '/Validation'
    return folder + '/' + record['path']


def generated_path(path, layout_version):
    if layout_version != 2:
        return path
    if path.startswith('05_Migration/'):
        return SECTIONS['mappings'][0] + '/Migration_Plan/' + path[len('05_Migration/'):]
    if path.startswith('01_Model/legacy-table-') or path == '01_Model/migration-review.md':
        return SECTIONS['mappings'][0] + '/' + path.split('/', 1)[1]
    if path.startswith('01_Model/'):
        return SECTIONS['design'][0] + '/' + path.split('/', 1)[1]
    return path


def section_guides(data, records):
    """Always explain the five destinations; empty folders never imply completion."""
    if data.get('package_layout_version') != 2 or 'documentation' not in data.get('selected_categories', []):
        return []
    from urllib.parse import quote
    from delivery_portal import _markdown_cell
    files = data.get('files', []) + records
    guides = []
    for key, (folder, title, description) in SECTIONS.items():
        included = [f for f in files if f['path'].startswith(folder + '/')]
        lines = ['# ' + title, '', description, '']
        if included:
            lines += ['## Included files', '']
            for row in sorted(included, key=lambda row: row['path']):
                relative = row['path'][len(folder) + 1:]
                lines.append('- [' + _markdown_cell(relative) + '](' + quote(relative, safe='/') + ')')
        else:
            lines += ['No files are included in this section yet.',
                      'This is an explicit gap or an unselected deliverable, not a completed stage.']
        if key == 'input_sources':
            source = data.get('engagement', {}).get('source_fingerprint', {})
            lines += ['', 'Source inventory is retained in the engagement. This package does not clone input repositories.']
            digest = source.get('sha256') or source.get('content_sha256') if isinstance(source, dict) else None
            if digest:
                lines += ['Source content fingerprint: `' + str(digest) + '`.']
            for root in data.get('input_roots', []):
                lines.append('- Registered source: ' + _markdown_cell(root.get('id', 'primary')) + '.')
        guides.append({'id': 'generated:section:' + key, 'path': folder + '/README.md',
                       'category': 'documentation', 'description': title + ' index and inclusion status.',
                       'body': ('\n'.join(lines) + '\n').encode()})
    return guides
