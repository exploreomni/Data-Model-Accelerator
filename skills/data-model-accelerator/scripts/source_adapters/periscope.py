"""Read the documented Sisense CDT Git layout without executing source code.

The vendor does not version this YAML schema. This deliberately does not accept
Sisense Fusion dashboard JSON or infer a warehouse dialect from a connection name.
"""
import ast
import json
import re
from pathlib import PurePosixPath

from .base import Report, read_yaml
from .sql import parse_sql


CAPABILITY = {
    'formats': ['CDT Git Configuration YAML with SQL/Python/R sidecars',
                'CDT custom_modules Python/R source'],
    'interpretation': 'bounded_static_extraction',
    'acquisition': 'supplied_exports',
    'limitations': [
        'Unversioned documented CDT Git layout only; not Sisense Fusion JSON.',
        'SQL dialect and template expansion remain unresolved.',
        'Inherited filters, unsynced snippets, encrypted chart settings and effective security are incomplete.',
        'Python/R bodies and static import candidates are preserved, never executed.',
    ],
}

_TOKEN = re.compile(r'^(.+)\.([A-Za-z0-9]{32})$')
_KNOWN = {
    'dashboard': {'display_name', 'disable_filters', 'configured_filters', 'dashboard_preferences'},
    'chart': {'chart_type', 'database_name', 'display_name', 'code_language', 'limit_preview',
              'encrypted_definition', 'color_theme', 'advanced', 'position', 'size'},
    'view': {'Database Name', 'Code Language', 'Settings'},
    'snippet': {'Parameters', 'Settings'},
}
_REQUIRED = {
    'dashboard': [('display_name',), ('dashboard_preferences', 'settings', 'owner')],
    'chart': [('display_name',), ('chart_type',), ('database_name',), ('position',), ('size',)],
    'view': [('Database Name',), ('Settings', 'Materialize View'), ('Settings', 'Metadata', 'Owner')],
    'snippet': [('Settings', 'Metadata', 'Owner')],
}


def _layout(path):
    parts = PurePosixPath(path).parts
    suffix = PurePosixPath(path).suffix
    if not parts:
        return None
    # Assigned evidence retains repository-relative paths in a monorepo.
    # Recognize the native container while retaining the full evidence path.
    starts = [i for i, p in enumerate(parts) if p in ('dashboards', 'snippets', 'views', 'custom_modules')]
    if not starts:
        return None
    parts = parts[starts[0]:]
    if len(parts) >= 2 and parts[0] == 'custom_modules' and suffix in ('.py', '.r'):
        return 'module', str(PurePosixPath(path).parent), PurePosixPath(path).stem, None
    kind = None
    if parts[0] == 'dashboards' and len(parts) in (3, 4):
        kind = 'dashboard' if len(parts) == 3 else 'chart'
    elif parts[0] in ('snippets', 'views') and len(parts) == 3:
        kind = {'snippets': 'snippet', 'views': 'view'}[parts[0]]
    if not kind:
        return None
    match = _TOKEN.fullmatch(parts[-2]) if kind in ('dashboard', 'chart') else None
    name, token = (match.group(1), match.group(2)) if match else (parts[-2], None)
    allowed = ('.yaml',) if kind == 'dashboard' else ('.yaml', '.sql')
    if kind in ('chart', 'view'):
        allowed += ('.py', '.r')
    if suffix not in allowed or PurePosixPath(path).stem != name:
        return None
    return kind, str(PurePosixPath(path).parent), name, token


def _get(config, keys):
    value = config
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _filters(report, path, config, owner):
    # These are per-dashboard declarations, not the global filter definitions.
    filters = config.get('configured_filters', {})
    if not isinstance(filters, dict):
        report.gap(path, 'periscope.invalid_filters', 'configured_filters must be a mapping.')
        return
    for visibility, entries in filters.items():
        if visibility not in ('hidden', 'visible') or not isinstance(entries, list):
            report.gap(path, 'periscope.invalid_filters', 'Only documented hidden/visible filter lists are interpreted.')
            continue
        for index, entry in enumerate(entries):
            loc = '$.configured_filters.%s[%d]' % (visibility, index)
            if not isinstance(entry, dict) or len(entry) != 1:
                report.gap(path, 'periscope.invalid_filter', 'Expected one named filter mapping.', loc)
                continue
            name, settings = next(iter(entry.items()))
            filter_id = report.object(path, loc, 'filter', name, parent_id=owner,
                                      visibility=visibility, native_configuration=settings)
            report.dependency(path, loc, owner, filter_id, kind='configured_filter', resolution='declared')
            report.expression(path, loc, 'periscope_filter', json.dumps(entry, ensure_ascii=False),
                              filter_id, interpretation='preserved_declaration')
            report.gap(path, 'periscope.filter_definition_missing',
                       'Filter declaration/defaults do not include the global filter query or access behavior.', loc)


def _sql_references(report, path, text, owner, names):
    # Brackets are overloaded by CDT and some SQL dialects. These are lexical
    # candidates, including tokens inside literals; never authoritative lineage.
    for index, match in enumerate(re.finditer(r'\[([^\[\]\n]+)\]', text)):
        if index >= 128:
            report.gap(path, 'periscope.reference_limit', 'Further bracket candidates are retained only in original SQL.')
            break
        token = match.group(1)
        name = re.split(r'\(|\s+as\s+', token, maxsplit=1, flags=re.I)[0].strip()
        loc = '$sql.offset[%d:%d]' % (match.start(), match.end())
        matches = names.get(name, [])
        report.expression(path, loc, 'periscope_template', match.group(0), owner,
                          interpretation='lexical_candidate')
        report.dependency(path, loc, owner, matches[0] if len(matches) == 1 else token,
                          kind='native_reference_candidate', resolution='candidate' if len(matches) == 1 else 'unresolved',
                          native_reference=match.group(0))
        report.gap(path, 'periscope.template_unresolved',
                   'Bracket syntax may represent a snippet, view, filter, formatter, parameter or dialect identifier; expansion is unverified.', loc)
    if '{{' in text or '{%' in text:
        report.gap(path, 'periscope.template_unresolved', 'Template code is preserved without rendering or execution.')


def _code(report, path, text, owner, modules):
    language = 'python' if path.endswith('.py') else 'r'
    report.expression(path, '$code', language, text, owner, interpretation='preserved_original')
    report.gap(path, 'periscope.code_not_interpreted',
               'Source preserved without runtime execution, dataframe lineage, package resolution or output validation.')
    references = []
    if language == 'python':
        try:
            tree = ast.parse(text)
            for index, node in enumerate(ast.walk(tree)):
                if index >= 10000:
                    report.gap(path, 'periscope.code_limit', 'Static Python import scan reached its node bound.')
                    break
                if isinstance(node, ast.Import):
                    references.extend((alias.name, node.lineno) for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    references.append(('.' * node.level + (node.module or ''), node.lineno))
        except (SyntaxError, ValueError, RecursionError):
            report.gap(path, 'periscope.code_parse_error', 'Python syntax was not understood; original code retained.')
    else:
        for index, match in enumerate(re.finditer(r"periscope\.source\(\s*(['\"])([^'\"\n]+)\1\s*\)", text)):
            if index >= 128:
                report.gap(path, 'periscope.reference_limit', 'Further R references remain in the original source.')
                break
            references.append((match.group(2), text.count('\n', 0, match.start()) + 1))
    for reference, line in sorted(set(references)):
        targets = modules.get((language, reference), [])
        report.dependency(path, 'line:%d' % line, owner, targets[0] if len(targets) == 1 else reference,
                          kind='module_reference_candidate', resolution='candidate' if len(targets) == 1 else 'unresolved',
                          native_reference=reference)
    report.cover(path, 'partial', 'Code preserved and import candidates scanned; not executed.')


def parse(files):
    """Parse one supplied Space snapshot rooted at dashboards/snippets/views."""
    report = Report('periscope', files)
    layouts, owners, names, modules, configs, native_ids = {}, {}, {}, {}, {}, {}
    for path in sorted(files):
        if path in ('dashboards/.gitkeep', 'snippets/.gitkeep', 'views/.gitkeep'):
            report.cover(path, 'parsed', 'Documented empty-directory marker; no analytics object.')
            continue
        layout = _layout(path)
        if not layout:
            report.cover(path, 'unsupported', 'Outside the documented CDT Git layout or file suffix.')
            report.gap(path, 'periscope.unsupported_format', 'File is retained by hash but its format is not interpreted.')
            continue
        layouts[path] = layout
        kind, folder, name, token = layout
        if kind == 'module':
            owner = report.object(path, '$', 'module', name, native_path=path)
            language = 'python' if path.endswith('.py') else 'r'
            relative = path.split('custom_modules/', 1)[1].rsplit('.', 1)[0]
            modules.setdefault((language, relative.replace('/', '.') if language == 'python' else relative), []).append(owner)
            owners[path] = owner
            continue
        if not path.endswith('.yaml'):
            continue
        report.expression(path, '$', 'yaml', files[path], interpretation='preserved_original')
        try:
            config = read_yaml(files[path])
        except (ValueError, ImportError):
            report.gap(path, 'periscope.invalid_yaml', 'YAML rejected or the YAML parser dependency is unavailable.')
            report.cover(path, 'unsupported')
            continue
        if not isinstance(config, dict) or not config:
            report.gap(path, 'periscope.invalid_configuration', 'Expected a nonempty documented settings mapping.')
            report.cover(path, 'unsupported')
            continue
        if not any(key in _KNOWN[kind] for key in config):
            report.gap(path, 'periscope.unknown_configuration', 'No documented settings keys matched this object kind.')
            report.cover(path, 'unsupported')
            continue
        display = config.get('display_name', name)
        if not isinstance(display, str) or not display:
            report.gap(path, 'periscope.invalid_name', 'display_name must be a nonempty string.')
            display = name
        owner = report.object(path, '$', kind, display, native_id=token,
                              native_configuration=config, native_path=folder, format_version='unversioned_cdt_git')
        owners[folder], configs[folder] = owner, config
        if token is not None:
            identity = (kind, token)
            if identity in native_ids:
                report.gap(path, 'periscope.duplicate_native_id', 'Native token is also declared at ' + native_ids[identity])
            else:
                native_ids[identity] = path
        if kind in ('view', 'snippet'):
            names.setdefault(name, []).append(owner)
        if kind in ('dashboard', 'chart') and token is None:
            report.gap(path, 'periscope.native_id_missing', 'Directory lacks the documented 32-character synced-object token.')
        for keys in _REQUIRED[kind]:
            if _get(config, keys) is None:
                report.gap(path, 'periscope.required_setting_missing', 'Documented required setting is missing: ' + '.'.join(keys))
        unknown = sorted(set(config) - _KNOWN[kind])
        if unknown:
            report.gap(path, 'periscope.unknown_setting', 'Uninterpreted settings retained: ' + ', '.join(unknown))
        if kind == 'dashboard':
            _filters(report, path, config, owner)
            report.gap(path, 'periscope.inherited_filters_missing', 'Globally inherited filters may be absent from dashboard YAML.')
        if kind == 'snippet' and 'Parameters' in config:
            parameters = config['Parameters']
            if not isinstance(parameters, list) or any(not isinstance(p, str) for p in parameters):
                report.gap(path, 'periscope.invalid_parameters', 'Snippet Parameters must be a list of names; raw settings retained.')
            else:
                for index, parameter in enumerate(parameters):
                    report.object(path, '$.Parameters[%d]' % index, 'parameter', parameter, parent_id=owner)
        if config.get('encrypted_definition'):
            report.gap(path, 'periscope.encrypted_definition', 'Encrypted chart series/format settings are retained as opaque text.')
        if kind != 'dashboard' and folder + '/' + name + '.sql' not in files:
            report.gap(path, 'periscope.sql_missing', 'Documented SQL sidecar is absent from the supplied snapshot.')
        report.cover(path)

    for path, (kind, folder, name, _) in sorted(layouts.items()):
        if kind == 'chart' and path.endswith('.yaml') and folder in owners:
            parent = str(PurePosixPath(folder).parent)
            report.dependency(path, '$', owners[folder], owners.get(parent, parent),
                              kind='contained_in', resolution='declared' if parent in owners else 'unresolved')
            if parent not in owners:
                report.gap(path, 'periscope.dashboard_missing', 'The containing dashboard settings are absent or invalid.')
        if path.endswith('.yaml'):
            continue
        owner = owners.get(path) if kind == 'module' else owners.get(folder)
        if owner is None:
            report.gap(path, 'periscope.configuration_missing', 'Owning YAML settings are absent or invalid.')
            owner = report.object(path, '$orphan', 'source_artifact', name,
                                  owning_configuration='missing_or_invalid')
        if path.endswith('.sql'):
            parse_sql(report, path, files[path], None, owner_id=owner)
            _sql_references(report, path, files[path], owner, names)
        else:
            _code(report, path, files[path], owner, modules)
            if kind != 'module':
                config = configs.get(folder, {})
                key = 'code_language' if kind == 'chart' else 'Code Language'
                language = config.get(key)
                if not isinstance(language, str) or not language.startswith('python' if path.endswith('.py') else 'r'):
                    report.gap(path, 'periscope.code_language_missing_or_conflicting', 'Sidecar and configured code language are not corroborated.')
    if files:
        first = sorted(files)[0]
        report.gap(first, 'periscope.export_incomplete', 'Snapshot completeness is unverified; failed snippet sync and non-exported filter definitions require independent inventory.')
        report.gap(first, 'periscope.security_not_exported', 'Space/RBAC, database permissions, sharing and effective row restrictions are not established by Git settings.')
    return report.finish()
