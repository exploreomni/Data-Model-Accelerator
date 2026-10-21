"""Deterministic local exports of an already validated, disclosure-scoped plan.

No filesystem, network, credential or provider writes. OOXML uses the standard
library; cloud content is a typed proposal, never a claimed document URL. The
core remains responsible for validating plan meaning, freshness and disclosure.
"""
import csv
import hashlib
import html
import io
import json
import re
import zipfile
from datetime import date
from xml.sax.saxutils import escape

MIME_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
MIME_DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
PLATFORMS = {'jira', 'linear', 'azure_devops', 'monday', 'asana', 'github', 'generic'}
LIMIT = 2000
QUALIFICATION = ('Planning proposal only. Review before creating or updating anything. '
                 'No import, cloud creation, native validation, business acceptance or deployment was executed.')
SOURCES = {
    'jira': 'https://support.atlassian.com/jira-cloud-administration/docs/import-data-from-a-csv-file/',
    'linear': 'https://linear.app/docs/cli-importer',
    'azure_devops': 'https://learn.microsoft.com/en-us/azure/devops/boards/queries/import-work-items-from-csv?view=azure-devops',
    'monday': 'https://support.monday.com/hc/en-us/articles/360000219209-Import-files-from-Excel',
    'asana': 'https://help.asana.com/s/article/preparing-data-for-csv-import?language=en_US',
}
LIMITATIONS = {
    'jira': 'Create proposals only. Confirm the proposed Task work type and map Summary/Description. '
            'No hierarchy or dependency links are imported by this adapter. Jira hierarchy import needs explicit '
            'parent IDs and parent-before-child ordering; dependency order alone is not hierarchy.',
    'linear': 'Use a current workspace-exported CSV template and confirm field mapping. The CLI importer does not '
              'import projects or comments. Priority, status, assignee, dates and estimate are blank because '
              'workspace mappings were not supplied. Hierarchy and dependency links need manual follow-up.',
    'azure_devops': 'Review the proposed Task Work Item Type against the target process before import. '
                   'New-item CSV intentionally omits ID, Assigned To, State and creation dates. '
                   'This adapter does not encode title indentation or parent-child links. Other link types '
                   'are unsupported by CSV; dependencies remain manual. Import at most 1,000 work items per file.',
    'monday': 'Map Name to the item name and review suggested column types. All rows are ordinary items; '
              'no subitems, dependency links or update matching are claimed. Excel import reads only the first '
              'tab, so this adapter supplies one flat CSV instead of the multi-sheet inventory.',
    'asana': 'CSV creates new tasks; it does not update existing tasks. Inspect matching names before importing '
             'and do not reimport blindly. This adapter emits no parent-task or dependency mapping. '
             'Requested ownership remains in the description for identity review.',
    'github': 'Copy the Markdown issue drafts after repository/label/identity review. No API calls, issue creation, '
              'bulk import, project hierarchy or dependency links are executed or implied.',
    'generic': 'Provider-neutral CSV and Markdown proposals. Review field mappings, duplicate detection, '
               'hierarchy and dependency support in the selected destination before any write.',
}


def _require(test, message):
    if not test:
        raise ValueError(message)


def _text(value):
    if value is None:
        return ''
    _require(type(value) in (str, int, float, bool), 'Export cells must be scalar public values')
    text = str(value)
    _require(len(text) <= 32767, 'Export text exceeds the Excel cell limit; partition the plan')
    # XML 1.0 excludes surrogate code points, NUL and most C0 controls. Preserve
    # visible evidence of replacement rather than silently deleting characters.
    return ''.join(c if (c in '\t\n\r' or 0x20 <= ord(c) <= 0xD7FF or
                            0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)
                   else '\ufffd' for c in text)


def _id(value):
    _require(type(value) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}', value),
             'Invalid stable planning identifier')
    return value


def _rows(value, label):
    _require(type(value) is list and len(value) <= LIMIT and all(type(x) is dict for x in value),
             'Invalid or oversized ' + label)
    return value


def _strings(values):
    _require(type(values) is list and len(values) <= LIMIT and all(type(x) is str for x in values),
             'Expected a bounded public string list')
    return [_text(x) for x in values]


def _join(values):
    return '; '.join(_strings(values))


def _md(value):
    text = html.escape(_text(value), quote=False)
    return re.sub(r'([\\`*_{}\[\]()#+!|>~])', r'\\\1', text).replace('\n', '<br>')


def _csv_cell(value):
    text = _text(value)
    if text and (text[0] in '\t\r\n' or text.lstrip().startswith(('=', '+', '-', '@'))):
        return "'" + text
    return text


def _csv(headers, rows):
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\r\n')
    writer.writerow(headers)
    for row in rows:
        _require(len(row) == len(headers), 'Export row width differs from headers')
        writer.writerow([_csv_cell(x) for x in row])
    return output.getvalue().encode('utf-8-sig')


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def _zip(parts):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path, value in sorted(parts.items()):
            info = zipfile.ZipInfo(path, (2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, value.encode('utf-8') if isinstance(value, str) else value)
    return output.getvalue()


def _xml(value):
    return escape(_text(value), {'"': '&quot;', "'": '&apos;'})


def _order(items, dependency_key='dependencies'):
    indexed = {_id(x['id']): x for x in items}
    _require(len(indexed) == len(items), 'Duplicate planning IDs')
    for item in items:
        deps = _strings(item.get(dependency_key, []))
        _require(len(set(deps)) == len(deps) and set(deps) <= set(indexed), 'Dangling or duplicate dependency')
        _require(item['id'] not in deps, 'Self dependency')
    done, ordered = set(), []
    while len(done) != len(items):
        ready = sorted(k for k, v in indexed.items() if k not in done and set(v.get(dependency_key, [])) <= done)
        _require(ready, 'Cyclic planning dependencies')
        for key in ready:
            done.add(key)
            ordered.append(indexed[key])
    return ordered


def _domain(raw):
    """Allowlisted projection; private/unknown keys never cross the boundary."""
    _id(raw['domain_id'])
    config = raw.get('config', {})
    output = config.get('output_format', 'local')
    platform = config.get('ticket_platform', 'generic')
    _require(output in {'local', 'google', 'both'} and platform in PLATFORMS, 'Unsupported export selection')
    _require(raw.get('freshness') in {'current', 'stale', 'unavailable', 'unassessed'}, 'Invalid plan freshness')
    snapshot = raw.get('plan_sha256')
    _require(isinstance(snapshot, str) and re.fullmatch('[a-f0-9]{64}', snapshot), 'A retained plan snapshot is required')
    d = {'domain_id': raw['domain_id'], 'plan_sha256': snapshot, 'freshness': raw['freshness'],
         'output_format': output, 'ticket_platform': platform, 'narrative': _text(raw.get('narrative')),
         'models': [], 'work_items': [], 'consumers': [], 'decisions': [], 'questions': [],
         'waves': [], 'tables': [], 'mappings': [], 'edges': [], 'warnings': []}
    for row in _rows(raw.get('models', []), 'models'):
        d['models'].append({k: _text(row.get(k)) for k in ('id', 'name', 'domain', 'layer', 'grain', 'disposition')} |
                           {'columns': [{k: _text(c.get(k)) for k in ('name', 'type', 'description', 'key')}
                                        for c in _rows(row.get('columns', []), 'model columns')],
                            'keys': _strings(row.get('keys', [])),
                            'depends_on': _strings(row.get('depends_on', []))})
        for column in d['models'][-1]['columns']:
            if not column['key'] and column['name'] in d['models'][-1]['keys']:
                column['key'] = 'Declared key'
    models = {m['id'] for m in d['models']}
    _require(len(models) == len(d['models']), 'Duplicate model IDs')
    for row in _rows(raw.get('work_items', []), 'work items'):
        item = {k: _text(row.get(k)) for k in ('id', 'title', 'outcome', 'scope', 'owner', 'priority', 'due_date', 'notes', 'external_id')}
        item['operation'] = row.get('operation', 'create')
        _require(item['operation'] in {'create', 'update', 'review'}, 'Invalid proposal operation')
        _require(item['operation'] != 'update' or item['external_id'], 'Update proposals require an external ID')
        for key in ('model_ids', 'mapping_ids', 'consumer_ids', 'dependencies'):
            item[key] = _strings(row.get(key, []))
        _require(set(item['model_ids']) <= models, 'Work item references an undisclosed model')
        item['acceptance_criteria'] = [{k: _text(c.get(k)) for k in ('id', 'expected', 'evidence_label')} |
                                       {'evidence_recorded': c.get('evidence_recorded') is True}
                                       for c in _rows(row.get('acceptance_criteria', []), 'acceptance criteria')]
        effort = row.get('effort', {})
        item['effort'] = {k: _text(effort.get(k)) for k in ('complexity', 'confidence', 'basis')}
        _require(item['effort']['complexity'] in {'', 'Easy', 'Somewhat easy', 'Difficult', 'Very difficult'}, 'Invalid effort complexity')
        d['work_items'].append(item)
    d['work_items'] = _order(d['work_items'])
    item_ids = {i['id'] for i in d['work_items']}
    for row in _rows(raw.get('waves', []), 'waves'):
        wave = {'id': _id(row['id']), 'title': _text(row.get('title')), 'item_ids': _strings(row.get('item_ids', [])),
                'depends_on': _strings(row.get('depends_on', []))}
        _require(set(wave['item_ids']) <= item_ids, 'Wave references an unknown work item')
        d['waves'].append(wave)
    d['waves'] = _order(d['waves'], 'depends_on')
    for key in ('decisions', 'questions'):
        for row in _rows(raw.get(key, []), key):
            d[key].append({'id': _text(row.get('id')), 'text': _text(row.get('text')),
                           'model_ids': _strings(row.get('model_ids', [])), 'consumer_ids': _strings(row.get('consumer_ids', []))})
    for row in _rows(raw.get('consumers', []), 'consumers'):
        d['consumers'].append({k: _text(row.get(k)) for k in ('id', 'kind', 'label', 'parent_id', 'status', 'disposition')} |
                             {k: _strings(row.get(k, [])) for k in ('model_ids', 'topic_ids', 'legacy_table_ids')})
    inventory = raw.get('inventory', {})
    d['baseline_status'] = _text(inventory.get('baseline_status', 'not_supplied'))
    d['omitted_details'] = inventory.get('omitted_details') is True
    count_names = ('total', 'mapped', 'unmatched', 'unsupported', 'excluded')
    d['coverage'] = [(kind, key, _text(inventory.get('coverage', {}).get(kind, {}).get(key, 'Unknown')))
                     for kind in ('tables', 'columns', 'rules') for key in count_names]
    d['consumer_coverage'] = {k: _text(raw.get('consumer_coverage', {}).get(k, 'Unknown'))
                              for k in ('total', 'supplied', 'missing', 'observed', 'proposed', 'unresolved',
                                        'unsupported', 'retirement_candidates', 'completeness')}
    d['unmatched'] = [{k: _text(x.get(k)) for k in ('table_id', 'kind', 'field_id', 'table_name', 'label')}
                      for x in _rows(inventory.get('unmatched', []), 'unmatched inventory')]
    for table in _rows(inventory.get('tables', []), 'legacy tables'):
        d['tables'].append({k: _text(table.get(k)) for k in ('id', 'name')} |
                           {'model_ids': _strings(table.get('model_ids', []))})
    for row in _rows(inventory.get('mappings', []), 'mappings'):
        sources = [{k: _text(x.get(k)) for k in ('table_id', 'kind', 'field_id', 'label')}
                   for x in _rows(row.get('legacy_sources', row.get('sources', [])), 'mapping sources')]
        targets = [{k: _text(x.get(k)) for k in ('model_id', 'kind', 'field')}
                   for x in _rows(row.get('targets', []), 'mapping targets')]
        d['mappings'].append({k: _text(row.get(k)) for k in ('id', 'disposition', 'relationship', 'status', 'review_status', 'rationale')} |
                             {'sources': sources, 'targets': targets})
    for row in _rows(raw.get('relationships', []), 'relationships'):
        _require(row.get('from') in models and row.get('to') in models, 'Relationship references an undisclosed model')
        d['edges'].append({'id': _text(row.get('id', 'relationship:' + str(len(d['edges']) + 1))),
                           'source': _text(row['from']), 'target': _text(row['to']),
                           'kind': _text(row.get('kind')), 'cardinality': _text(row.get('cardinality')),
                           'label': _text(row.get('label', row.get('predicate'))), 'status': 'supplied'})
    for row in _rows(raw.get('graph_edges', []), 'graph edges'):
        source, target = row.get('source', {}), row.get('target', {})
        d['edges'].append({'id': _text(row.get('id')), 'source': _text(source.get('id')), 'target': _text(target.get('id')),
                           'kind': _text(source.get('kind')) + ' → ' + _text(target.get('kind')),
                           'label': _text(row.get('mapping_id')), 'cardinality': '', 'status': _text(row.get('status'))})
    lineage = raw.get('source_lineage', {})
    d['source_nodes'] = [{k: _text(n.get(k)) for k in ('id', 'kind', 'label', 'legacy_table_id', 'native_id')}
                         for n in _rows(lineage.get('nodes', []), 'source lineage nodes')]
    for row in _rows(lineage.get('edges', []), 'source lineage edges'):
        d['edges'].append({'id': _text(row.get('id')), 'source': _text(row.get('source_id')), 'target': _text(row.get('target_id')),
                           'kind': 'supplied source lineage', 'label': _text(row.get('native_id')), 'cardinality': '', 'status': _text(row.get('status'))})
    context = raw.get('migration_context', {})
    dimensions = ('definition', 'formula', 'grain', 'population', 'exclusions', 'time', 'currency', 'history', 'security', 'nulls')
    d['definitions'] = [{k: _text(x.get(k)) for k in ('id', 'name', 'statement', 'status')} |
                        {'model_ids': _strings(x.get('model_ids', [])),
                         'definition': '\n'.join(k + ': ' + _text(x['definition'][k]) for k in dimensions if k in x.get('definition', {}))}
                        for x in _rows(context.get('definitions', []), 'business definitions')]
    d['crosswalk'] = [{k: _text(x.get(k)) for k in ('subject_kind', 'subject_id', 'dashboard_id', 'dashboard_label', 'source_label')} |
                      {k: _strings(x.get(k, [])) for k in ('model_ids', 'topic_ids')}
                      for x in _rows(context.get('consumer_crosswalk', []), 'consumer crosswalk')]
    # Warning objects are intentionally narrowed, never serialized wholesale.
    for warning in raw.get('warnings', []):
        d['warnings'].append(_text(warning) if isinstance(warning, str) else
                             _text(warning.get('code')) + ': ' + _text(warning.get('message', warning.get('text'))))
    d['missing_consumers'] = [{k: _text(x.get(k)) for k in ('id', 'label', 'status')}
                              for x in _rows(raw.get('missing_consumers', []), 'missing consumers')]
    d['archived_edits'] = [{k: _text(x.get(k)) for k in ('id', 'notes', 'owner', 'priority', 'due_date')}
                           for x in _rows(raw.get('archived_edits', []), 'archived edits')]
    return d


def _endpoint(row):
    return row.get('table_id', row.get('model_id', '')) + ('.' + row.get('field_id', row.get('field', ''))
                                                        if row.get('field_id', row.get('field')) else '')


def _sheets(d):
    """One stable tabular projection also drives typed cloud sheet content."""
    snap, domain = d['plan_sha256'], d['domain_id']
    tabs = []
    def tab(name, headers, rows):
        tabs.append({'name': name, 'headers': ['Snapshot ID', 'Domain'] + headers,
                     'rows': [[snap, domain] + list(row) for row in rows]})
    tab('Summary', ['Field', 'Value'], [('Freshness', d['freshness']), ('Qualification', QUALIFICATION),
        ('Baseline', d['baseline_status']), ('Omitted detail', str(d['omitted_details'])), ('Plan narrative', d['narrative']),
        ('Models', len(d['models'])), ('Legacy tables', len(d['tables'])), ('Mappings', len(d['mappings'])),
        ('Work items', len(d['work_items'])), ('Known missing consumers', len(d['missing_consumers'])),
        ('Migration context validation', 'not_revalidated')] +
        [('Consumer coverage: '+k,v or 'Unknown') for k,v in d['consumer_coverage'].items()])
    tab('Coverage', ['Kind', 'Measure', 'Count'], d['coverage'])
    tab('Inventory', ['Kind', 'Stable ID', 'Name', 'Layer', 'Grain', 'Model IDs', 'Disposition'],
        [('legacy_table', t['id'], t['name'], '', '', _join(t['model_ids']), '') for t in d['tables']] +
        [('model', m['id'], m['name'], m['layer'], m['grain'], m['id'], m['disposition']) for m in d['models']])
    tab('Sources', ['Source node ID', 'Native ID', 'Kind', 'Label', 'Legacy table ID'],
        [(n['id'], n['native_id'], n['kind'], n['label'], n['legacy_table_id']) for n in d['source_nodes']])
    tab('Columns', ['Model ID', 'Column', 'Type', 'Key', 'Description'],
        [(m['id'], c['name'], c['type'], c['key'], c['description']) for m in d['models'] for c in m['columns']])
    tab('Mappings', ['Mapping ID', 'Disposition', 'Sources', 'Targets', 'Status', 'Review', 'Rationale'],
        [(m['id'], m['disposition'], '; '.join(_endpoint(x) for x in m['sources']),
          '; '.join(_endpoint(x) for x in m['targets']), m['status'], m['review_status'], m['rationale']) for m in d['mappings']])
    tab('Unmatched', ['Legacy table ID', 'Kind', 'Field ID', 'Table name', 'Label'],
        [[x[k] for k in ('table_id','kind','field_id','table_name','label')] for x in d['unmatched']])
    tab('Definitions', ['Rule ID', 'Name', 'Statement', 'Definition dimensions', 'Supplied status', 'Model IDs', 'Validation'],
        [(x['id'],x['name'],x['statement'],x['definition'],x['status'],_join(x['model_ids']),'not_revalidated') for x in d['definitions']])
    tab('Crosswalk', ['Subject kind', 'Subject ID', 'Dashboard ID', 'Dashboard label', 'Source label', 'Model IDs', 'Topic IDs', 'Validation'],
        [[x[k] for k in ('subject_kind','subject_id','dashboard_id','dashboard_label','source_label')] +
         [_join(x['model_ids']),_join(x['topic_ids']),'not_revalidated'] for x in d['crosswalk']])
    tab('Relationships', ['Edge ID', 'Source ID', 'Target ID', 'Kind', 'Cardinality', 'Label', 'Status'],
        [(x['id'], x['source'], x['target'], x['kind'], x['cardinality'], x['label'], x['status']) for x in d['edges']])
    tab('Consumers', ['Consumer ID', 'Kind', 'Label', 'Disposition', 'Status', 'Model IDs', 'Topic IDs', 'Legacy table IDs'],
        [(c['id'], c['kind'], c['label'], c['disposition'], c['status'], _join(c['model_ids']),
          _join(c['topic_ids']), _join(c['legacy_table_ids'])) for c in d['consumers']])
    tab('Work items', ['Planning ID', 'Operation proposal', 'External ID', 'Title', 'Outcome', 'Scope', 'Model IDs',
                      'Mapping IDs', 'Consumer IDs', 'Dependencies', 'Complexity', 'Confidence', 'Effort basis',
                      'Requested owner', 'Requested priority', 'Requested due date', 'Notes'],
        [(w['id'], w['operation'], w['external_id'], w['title'], w['outcome'], w['scope'], _join(w['model_ids']),
          _join(w['mapping_ids']), _join(w['consumer_ids']), _join(w['dependencies']), w['effort']['complexity'],
          w['effort']['confidence'], w['effort']['basis'], w['owner'], w['priority'], w['due_date'], w['notes']) for w in d['work_items']])
    tab('Acceptance', ['Planning ID', 'Criterion ID', 'Expected outcome', 'Evidence label', 'Evidence recorded'],
        [(w['id'], c['id'], c['expected'], c['evidence_label'], str(c['evidence_recorded'])) for w in d['work_items'] for c in w['acceptance_criteria']])
    tab('Dependencies', ['Prerequisite planning ID', 'Dependent planning ID', 'Import support'],
        [(dep, w['id'], 'Manual link review; not encoded as native relationship') for w in d['work_items'] for dep in w['dependencies']])
    tab('Waves', ['Wave ID', 'Title', 'Item IDs', 'Predecessor wave IDs'],
        [(w['id'], w['title'], _join(w['item_ids']), _join(w['depends_on'])) for w in d['waves']])
    tab('Review', ['Kind', 'Stable ID', 'Text', 'Model IDs', 'Consumer IDs'],
        [(kind, x['id'], x['text'], _join(x['model_ids']), _join(x['consumer_ids'])) for kind in ('decisions', 'questions') for x in d[kind]] +
        [('warning', '', x, '', '') for x in d['warnings']] +
        [('missing_consumer', x['id'], x['label'] + ' ' + x['status'], '', x['id']) for x in d['missing_consumers']] +
        [('archived_edit', x['id'], '; '.join(x[k] for k in ('notes', 'owner', 'priority', 'due_date') if x[k]), '', '') for x in d['archived_edits']])
    return tabs


def _col(index):
    result = ''
    while index:
        index, mod = divmod(index - 1, 26)
        result = chr(65 + mod) + result
    return result


def _xlsx(tabs):
    _require(sum((len(t['rows']) + 1) * len(t['headers']) for t in tabs) <= 300000,
             'Spreadsheet exceeds the bounded export size; partition the plan')
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    parts = {'_rels/.rels': f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>'}
    sheets, links, types = [], [], []
    for i, tab in enumerate(tabs, 1):
        columns = len(tab['headers']); rows = [tab['headers']] + tab['rows']
        body = []
        for j, row in enumerate(rows, 1):
            cells = ''.join(f'<c r="{_col(k)}{j}" s="{1 if j == 1 else 0}" t="inlineStr"><is><t xml:space="preserve">{_xml(value)}</t></is></c>' for k, value in enumerate(row, 1))
            body.append(f'<row r="{j}">{cells}</row>')
        end = f'{_col(columns)}{len(rows)}'
        parts[f'xl/worksheets/sheet{i}.xml'] = (f'<worksheet xmlns="{ns}"><dimension ref="A1:{end}"/>'
            '<sheetViews><sheetView workbookViewId="0"><pane xSplit="2" ySplit="1" topLeftCell="C2" activePane="bottomRight" state="frozen"/></sheetView></sheetViews>'
            '<sheetFormatPr defaultRowHeight="30"/><cols>' + ''.join(f'<col min="{k}" max="{k}" width="{20 if k < 3 else 32}" customWidth="1"/>' for k in range(1, columns + 1)) +
            '</cols><sheetData>' + ''.join(body) + f'</sheetData><autoFilter ref="A1:{end}"/>'
            '<pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.2" footer="0.2"/></worksheet>')
        sheets.append(f'<sheet name="{_xml(tab["name"])}" sheetId="{i}" r:id="rId{i}"/>')
        links.append(f'<Relationship Id="rId{i}" Type="{rel}/worksheet" Target="worksheets/sheet{i}.xml"/>')
        types.append(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
    parts['xl/workbook.xml'] = f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets>{"".join(sheets)}</sheets></workbook>'
    links.append(f'<Relationship Id="rIdStyles" Type="{rel}/styles" Target="styles.xml"/>')
    parts['xl/_rels/workbook.xml.rels'] = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(links) + '</Relationships>'
    parts['xl/styles.xml'] = f'''<styleSheet xmlns="{ns}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF17324D"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf numFmtId="49" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
    parts['[Content_Types].xml'] = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' + ''.join(types) + '</Types>'
    return _zip(parts)


def _paragraph(text, style=None):
    props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ''
    runs = '<w:br/>'.join(f'<w:t xml:space="preserve">{_xml(line)}</w:t>' for line in _text(text).split('\n'))
    return '<w:p>' + props + '<w:r>' + runs + '</w:r></w:p>'


def _table(headers, rows, widths=None):
    widths = widths or [9000 // len(headers)] * len(headers)
    result = '<w:tbl><w:tblPr><w:tblW w:w="9000" w:type="dxa"/><w:tblLayout w:type="fixed"/><w:tblBorders>'
    result += ''.join(f'<w:{side} w:val="single" w:sz="4" w:color="D9D9D9"/>' for side in ('top','left','bottom','right','insideH','insideV')) + '</w:tblBorders><w:tblCellMar><w:top w:w="100" w:type="dxa"/><w:left w:w="100" w:type="dxa"/><w:bottom w:w="100" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid>'
    result += ''.join(f'<w:gridCol w:w="{width}"/>' for width in widths) + '</w:tblGrid>'
    for index, row in enumerate([headers] + rows):
        result += '<w:tr><w:trPr><w:cantSplit/>' + ('<w:tblHeader/>' if index == 0 else '') + '</w:trPr>'
        for value, width in zip(row, widths):
            result += f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/><w:vAlign w:val="center"/>' + ('<w:shd w:fill="F2F2F2"/>' if index == 0 else '') + '</w:tcPr>' + _paragraph(value, 'TableText') + '</w:tc>'
        result += '</w:tr>'
    return result + '</w:tbl>'


def _blocks(d):
    """Typed document content. Native Word relationship cards are editable diagrams."""
    blocks = [{'type':'heading','level':1,'text':'Migration plan for ' + re.sub('[^A-Za-z0-9 ]', ' ', d['domain_id'])},
              {'type':'paragraph','text':'Snapshot: ' + d['plan_sha256'] + '\nFreshness: ' + d['freshness']},
              {'type':'paragraph','text':QUALIFICATION}, {'type':'paragraph','text':d['narrative']},
              {'type':'heading','level':2,'text':'Inventory and transformation scope'},
              {'type':'table','headers':['Stable model ID','Layer','Grain','Disposition'],
               'rows':[[m['id'],m['layer'],m['grain'],m['disposition']] for m in d['models']]},
              {'type':'paragraph','text':'Baseline: '+d['baseline_status']+'; omitted detail: '+str(d['omitted_details'])+
               '\nConsumer coverage: '+ '; '.join(k+'='+ (v or 'Unknown') for k,v in d['consumer_coverage'].items())},
              {'type':'table','headers':['Kind','Total','Mapped','Unmatched','Unsupported','Excluded'],
               'rows':[[kind]+[value or 'Unknown' for group, key, value in d['coverage'] if group==kind]
                       for kind in ('tables','columns','rules')]}]
    blocks.append({'type':'heading','level':2,'text':'Declared table and lineage diagrams'})
    labels = {m['id']: m['name'] or m['id'] for m in d['models']}
    labels.update({t['id']:t['name'] or t['id'] for t in d['tables']})
    labels.update({n['id']:n['label'] or n['id'] for n in d['source_nodes']})
    labels.update({c['id']:c['label'] or c['id'] for c in d['consumers']})
    models = {m['id']:m for m in d['models']}
    def card(identity):
        model = models.get(identity)
        return labels.get(identity, identity) + '\nID: ' + identity + (('\n' + model['grain'] + '\n' +
            '\n'.join(c['name'] + ' : ' + c['type'] + (' [' + c['key'] + ']' if c['key'] else '') for c in model['columns'])) if model else '')
    if not d['edges']:
        blocks.append({'type':'paragraph','text':'No relationship edges were supplied. No connections or cardinalities have been inferred.'})
    for edge in d['edges']:
        blocks.append({'type':'relationship_diagram','id':edge['id'],'source_id':edge['source'],'target_id':edge['target'],
                       'source_text':card(edge['source']), 'target_text':card(edge['target']),
                       'label':' → \n' + '\n'.join(x for x in (edge['kind'], edge['cardinality'], edge['label'], edge['status']) if x)})
    blocks += [{'type':'heading','level':2,'text':'Legacy mappings'},
               {'type':'table','headers':['Mapping / disposition','Legacy source IDs','Target IDs','Review status'],
                'rows':[[m['id']+'\n'+m['disposition'], '\n'.join(_endpoint(x) for x in m['sources']),
                         '\n'.join(_endpoint(x) for x in m['targets']),m['review_status']] for m in d['mappings']]},
               {'type':'heading','level':2,'text':'Consumer disposition'},
               {'type':'table','headers':['Consumer ID','Disposition / status','Models / topics'],
                'rows':[[c['id'],c['disposition']+' / '+c['status'],_join(c['model_ids'])+'\n'+_join(c['topic_ids'])] for c in d['consumers']]}]
    if d['unmatched']:
        blocks += [{'type':'heading','level':2,'text':'Unmatched legacy inventory'},
                   {'type':'table','headers':['Legacy table ID','Kind / field ID','Label'],
                    'rows':[[x['table_id'],x['kind']+' / '+x['field_id'],x['label']] for x in d['unmatched']]}]
    if d['definitions'] or d['crosswalk']:
        blocks += [{'type':'heading','level':2,'text':'Retained definitions and consumer crosswalk'},
                   {'type':'paragraph','text':'Supplied context only; not_revalidated. No validation pass/fail is inherited.'}]
        blocks.extend({'type':'paragraph','text':x['id']+' — '+x['name']+'\n'+x['statement']+'\n'+x['definition']+
                       '\nSupplied status: '+x['status']+'; models: '+_join(x['model_ids'])} for x in d['definitions'])
        blocks.append({'type':'table','headers':['Subject / dashboard','Source label','Models / topics'],
                       'rows':[[x['subject_kind']+': '+x['subject_id']+'\n'+x['dashboard_id'],x['source_label'],
                                _join(x['model_ids'])+'\n'+_join(x['topic_ids'])] for x in d['crosswalk']]})
    blocks.append({'type':'heading','level':2,'text':'Proposed migration waves'})
    for wave in d['waves']:
        blocks.append({'type':'paragraph','text':wave['id']+' — '+wave['title']+'\nItems: '+_join(wave['item_ids'])+'\nAfter waves: '+(_join(wave['depends_on']) or 'None declared')})
    blocks.append({'type':'heading','level':2,'text':'Work items and acceptance evidence'})
    for item in d['work_items']:
        blocks.extend([{'type':'heading','level':3,'text':item['id']+' — '+item['title']},
                       {'type':'paragraph','text':_ticket_body(d,item)}])
    for key in ('decisions','questions'):
        blocks.append({'type':'heading','level':2,'text':key.title()})
        blocks.extend({'type':'paragraph','text':x['id']+' — '+x['text']} for x in d[key])
        if not d[key]:blocks.append({'type':'paragraph','text':'None supplied.'})
    blocks.append({'type':'heading','level':2,'text':'Gaps and retained edits'})
    blocks.extend({'type':'paragraph','text':x} for x in d['warnings'])
    blocks.extend({'type':'paragraph','text':'Missing consumer: '+x['id']+' — '+x['label']+' / '+x['status']} for x in d['missing_consumers'])
    blocks.extend({'type':'paragraph','text':'Archived edit '+x['id']+': '+'; '.join(x[k] for k in ('notes','owner','priority','due_date') if x[k])} for x in d['archived_edits'])
    return blocks


def _docx(blocks):
    body = []
    for block in blocks:
        if block['type'] == 'heading':
            body.append(_paragraph(block['text'], 'Title' if block['level']==1 else 'Heading'+str(block['level'])))
        elif block['type'] == 'paragraph':
            body.append(_paragraph(block['text']))
        elif block['type'] == 'relationship_diagram':
            body.append(_paragraph('Declared edge: ' + block['id'], 'Heading3'))
            body.append(_table(['Source table / object','Declared relationship','Target table / object'],
                               [[block['source_text'],block['label'],block['target_text']]], [3500,2000,3500]))
        else:
            body.append(_table(block['headers'],block['rows']))
    ns='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    document=f'<w:document xmlns:w="{ns}" xmlns:r="{rel}"><w:body>'+''.join(body)+ '<w:sectPr><w:footerReference w:type="default" r:id="rIdFooter"/><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="1620" w:bottom="1080" w:left="1620" w:header="360" w:footer="360"/></w:sectPr></w:body></w:document>'
    styles=f'<w:styles xmlns:w="{ns}"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="140"/></w:pPr></w:pPrDefault></w:docDefaults>'
    for identity,size in [('Title',36),('Heading2',28),('Heading3',24),('TableText',19)]:
        styles+=f'<w:style w:type="paragraph" w:styleId="{identity}"><w:name w:val="{identity}"/><w:pPr>'+('<w:keepNext/><w:spacing w:before="180" w:after="120"/>' if identity!='TableText' else '<w:spacing w:after="80"/>')+f'</w:pPr><w:rPr><w:sz w:val="{size}"/><w:color w:val="000000"/>'+('<w:b/>' if identity!='TableText' else '')+'</w:rPr></w:style>'
    styles+='</w:styles>'
    return _zip({'word/document.xml':document,'word/styles.xml':styles,
        'word/footer.xml':f'<w:ftr xmlns:w="{ns}"><w:p><w:pPr><w:jc w:val="right"/></w:pPr><w:r><w:t>Draft plan · </w:t></w:r><w:fldSimple w:instr="PAGE"/></w:p></w:ftr>',
        '_rels/.rels':f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="word/document.xml"/></Relationships>',
        'word/_rels/document.xml.rels':f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdStyles" Type="{rel}/styles" Target="styles.xml"/><Relationship Id="rIdFooter" Type="{rel}/footer" Target="footer.xml"/></Relationships>',
        '[Content_Types].xml':'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/footer.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/></Types>'})


def _ticket_body(d, item):
    parts=['Planning ID: '+item['id'],'Snapshot ID: '+d['plan_sha256'],'Domain: '+d['domain_id'],
           'Operation: '+item['operation']+' proposal'+('; external ID: '+item['external_id'] if item['external_id'] else ''),
           'Outcome: '+item['outcome'],'Scope: '+item['scope'],'Models: '+_join(item['model_ids']),
           'Mappings: '+_join(item['mapping_ids']),'Consumers: '+_join(item['consumer_ids']),
           'Manual dependency follow-up: '+(_join(item['dependencies']) or 'None declared'),
           'Complexity: '+(item['effort']['complexity'] or 'Unknown')+'; confidence: '+(item['effort']['confidence'] or 'unknown'),
           'Effort basis: '+item['effort']['basis']]
    for key in ('owner','priority','due_date'):
        if item[key]:parts.append('Requested '+key.replace('_',' ')+': '+item[key])
    parts.append('Acceptance criteria (recorded evidence is not native qualification):')
    for c in item['acceptance_criteria']:
        parts.append(c['id']+': '+c['expected']+' | Evidence: '+c['evidence_label']+' | Recorded: '+str(c['evidence_recorded']))
    if item['notes']:parts.append('Notes: '+item['notes'])
    parts.append(QUALIFICATION)
    return '\n'.join(parts)


def _tickets(d):
    parts=['# Migration ticket proposals — '+_md(d['domain_id']), 'Snapshot: '+d['plan_sha256'], QUALIFICATION]
    for w in d['work_items']:
        parts.extend(['## '+_md(w['id'])+' — '+_md(w['title']), _md(_ticket_body(d,w))])
    return ('\n\n'.join(parts)+'\n').encode('utf-8')


def _imports(d):
    platform=d['ticket_platform'];create=[w for w in d['work_items'] if w['operation']=='create'];result=[]
    def title(w):return '['+w['id']+'] '+w['title']
    if platform=='jira':
        headers=['Summary','Description','Work type','Labels']
        rows=[[title(w),_ticket_body(d,w),'Task','dma-migration'] for w in create]
    elif platform=='linear':
        headers=['Title','Description','Priority','Status','Assignee','Created','Completed','Labels','Estimate']
        rows=[[title(w),_ticket_body(d,w),'','','','','','dma-migration',''] for w in create]
    elif platform=='azure_devops':
        headers=['Work Item Type','Title','Description']
        rows=[['Task',title(w),'<p>'+html.escape(_ticket_body(d,w)).replace('\n','</p><p>')+'</p>'] for w in create]
    elif platform=='monday':
        headers=['Name','Description','Planning ID','Snapshot ID']
        rows=[[title(w),_ticket_body(d,w),w['id'],d['plan_sha256']] for w in create]
    elif platform=='asana':
        headers=['Name','Description','Section','Assignee','Collaborators','Start Date','Due Date']
        def asana_date(value):
            try:
                return date.fromisoformat(value).strftime('%m/%d/%Y')
            except ValueError:
                return ''  # Non-ISO supplied requests remain in the review description.
        rows=[[title(w),_ticket_body(d,w),'','','','',asana_date(w['due_date'])] for w in create]
    elif platform=='github':
        for w in create:
            name=hashlib.sha256(w['id'].encode()).hexdigest()[:12]
            result.append(('imports/github/'+name+'.md', ('# '+_md(title(w))+'\n\n'+_md(_ticket_body(d,w))+'\n').encode(), 'text/markdown'))
        headers=None
    else:
        headers=['Planning ID','Snapshot ID','Operation proposal','Title','Description']
        rows=[[w['id'],d['plan_sha256'],'create',w['title'],_ticket_body(d,w)] for w in create]
    if headers is not None:
        # Azure has a documented 1,000-item import bound; no dropped rows.
        batches=[rows[i:i+1000] for i in range(0,len(rows),1000)] or [[]]
        for i,batch in enumerate(batches,1):
            result.append((f'imports/{platform}/create-{i:03}.csv',_csv(headers,batch),'text/csv'))
    manual=[(d['plan_sha256'],w['id'],w['operation'],w['external_id'],_join(w['dependencies']),_ticket_body(d,w)) for w in d['work_items'] if w['operation']!='create' or w['dependencies']]
    result.append(('imports/manual-follow-up.csv',_csv(['Snapshot ID','Planning ID','Operation proposal','External ID','Dependencies','Review notes'],manual),'text/csv'))
    return result


def export_files(summary):
    """Return bounded deterministic file bytes; callers own validation and saving.

    Domains with no retained snapshot are omitted, not manufactured. Stale plans
    remain visibly stale and retain draft-only authority. Returned records have
    exactly path, content, media_type and domain_id. No filesystem is touched.
    """
    _require(type(summary) is dict and summary.get('schema_version')==1, 'Unsupported public plan summary')
    domains=_rows(summary.get('domains',[]),'domains');seen=set();files=[]
    for raw in sorted(domains,key=lambda r:r.get('domain_id','')):
        identity=_id(raw['domain_id']);_require(identity not in seen,'Duplicate domain');seen.add(identity)
        if raw.get('plan_sha256') is None:
            _require(raw.get('freshness') in {'unassessed','unavailable'},'Missing retained plan snapshot')
            continue
        d=_domain(raw);tabs=_sheets(d);blocks=_blocks(d)
        slug=re.sub('[^A-Za-z0-9_-]','-',identity)[:60]+'-'+hashlib.sha256(identity.encode()).hexdigest()[:10]
        base='05_Migration/'+slug+'/'
        def add(path,content,media):files.append({'path':base+path,'content':content,'media_type':media,'domain_id':identity})
        if d['output_format'] in {'local','both'}:
            add('inventory.xlsx',_xlsx(tabs),MIME_XLSX);add('migration-plan.docx',_docx(blocks),MIME_DOCX)
        if d['output_format'] in {'google','both'}:
            common={'schema_version':1,'domain_id':identity,'snapshot_id':d['plan_sha256'],
                    'status':'pending_host_creation','provider':'provider_neutral','qualification':QUALIFICATION}
            typed=[{'name':t['name'],'columns':[{'name':h,'type':'string'} for h in t['headers']],
                    'rows':[[{'type':'string','value':_text(c)} for c in row] for row in t['rows']],
                    'freeze_rows':1,'freeze_columns':2,'filter':True} for t in tabs]
            add('cloud/sheet-content.json',_json({**common,'kind':'typed_spreadsheet_content','sheets':typed}),'application/json')
            add('cloud/document-content.json',_json({**common,'kind':'typed_document_content','blocks':blocks}),'application/json')
        add('tickets.md',_tickets(d),'text/markdown')
        for path,content,media in _imports(d):add(path,content,media)
        readme=('# Migration plan exports — '+_md(identity)+'\n\nSnapshot: '+d['plan_sha256']+'\n\nFreshness: '+d['freshness']+'\n\n'+QUALIFICATION+
          '\n\nInventory rows and every ticket retain the same snapshot and planning IDs. Excel uses text cells, frozen headers and filters; CSV formula-like cells receive a leading apostrophe. XML-invalid controls are visibly replaced with U+FFFD. '
          'Do not remove these protections without reviewing the data. Word diagrams are editable native table/object cards connected by supplied relationship arrows; no missing edges or cardinalities are inferred.\n\n'+
          'Import steps: review tickets.md and manual-follow-up.csv; reconcile stable planning IDs against existing destination items; confirm destination field mappings and requested owners; then import only the reviewed create CSV or copy a Markdown draft. '
          'Update/review proposals never enter create imports. Their IDs and requested changes remain in manual-follow-up.csv. Preserve unsupported dependencies manually; ordering alone does not create links. Reimporting can create duplicates.\n\n'+
          LIMITATIONS[d['ticket_platform']]+('\n\nProvider reference: '+SOURCES[d['ticket_platform']] if d['ticket_platform'] in SOURCES else '')+
          '\n\nGoogle selection emits provider-neutral typed content with pending_host_creation status. A separately authorized host must create native Sheets/Docs and return real IDs/URLs. No cloud URL or successful creation is claimed. Local XLSX/DOCX fallback exists only when local or both was selected.\n')
        add('README.md',readme.encode('utf-8'),'text/markdown')
    _require(len({f['path'] for f in files})==len(files),'Export path collision')
    return sorted(files,key=lambda f:f['path'])
