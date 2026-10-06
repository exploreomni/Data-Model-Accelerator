"""Offline, pinned, progressive Omni knowledge. Never executes upstream skills.

Knowledge is guidance, not authorization or native qualification. Callers must
retain both returned digests in task/evidence records. No network or install
operations occur here. Trusted code chooses the skill root and expected pins.
"""
import argparse
import copy
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

ROOT = Path(__file__).resolve().parents[1]
OBJECTS = ('models', 'views', 'inherited_views', 'query_views', 'relationships',
           'topics', 'filtered_measures', 'level_of_detail', 'composite_topics',
           'aggregate_awareness', 'ai_context', 'security', 'lifecycle')
OPERATIONS = ('inspect', 'preserve', 'generate', 'static_validate', 'native_validate', 'deploy')
DIALECTS = ('snowflake', 'bigquery', 'databricks', 'redshift', 'clickhouse', 'motherduck')
MAX_BYTES = 1024 * 1024
SHA = re.compile(r'[0-9a-f]{64}\Z')
REVISION = re.compile(r'[0-9a-f]{40}\Z')
REPOSITORY = 'https://github.com/exploreomni/omni-agent-skills'


class KnowledgeError(ValueError):
    """Stable public code only; do not echo paths or untrusted file contents."""


def _need(ok, code):
    if not ok:
        raise KnowledgeError(code)


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('utf-8')


def _keys(value, keys, code):
    _need(type(value) is dict and set(value) == set(keys), code)


def _text(value):
    return type(value) is str and bool(value.strip())


def _selection(value, choices):
    _need(type(value) in (list, tuple) and bool(value) and
          all(type(x) is str and x in choices for x in value) and len(set(value)) == len(value),
          'knowledge.invalid_selection')
    return sorted(value)


def _day(value):
    if type(value) is date:
        return value
    _need(type(value) is str, 'knowledge.invalid_date')
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise KnowledgeError('knowledge.invalid_date') from None
    _need(parsed.isoformat() == value, 'knowledge.invalid_date')
    return parsed


def _read(root, relative, expected=None):
    _need(type(relative) is str and '\\' not in relative, 'knowledge.invalid_path')
    path = PurePosixPath(relative)
    _need(not path.is_absolute() and path.as_posix() == relative and
          all(p not in ('', '.', '..') for p in path.parts), 'knowledge.invalid_path')
    base = Path(root).resolve()
    target = base.joinpath(*path.parts)
    cursor = base
    for part in path.parts:
        cursor = cursor / part
        _need(not cursor.is_symlink(), 'knowledge.symlink_refused')
    _need(target.is_file(), 'knowledge.missing_reference')
    try:
        with target.open('rb') as handle:
            data = handle.read(MAX_BYTES + 1)
    except OSError:
        raise KnowledgeError('knowledge.unreadable_reference') from None
    _need(len(data) <= MAX_BYTES, 'knowledge.byte_limit')
    if expected is not None:
        _need(type(expected) is str and SHA.fullmatch(expected), 'knowledge.invalid_pin')
        _need(_hash(data) == expected, 'knowledge.pin_mismatch')
    return data


def _json(data):
    def pairs(items):
        output = {}
        for key, value in items:
            _need(key not in output, 'knowledge.duplicate_key')
            output[key] = value
        return output
    try:
        value = json.loads(data.decode('utf-8'), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(KnowledgeError('knowledge.invalid_json')))
    except KnowledgeError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise KnowledgeError('knowledge.invalid_json') from None
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop(); count += 1
        _need(depth <= 24 and count <= 15000, 'knowledge.structure_limit')
        if type(item) in (dict, list):
            children = item.values() if type(item) is dict else item
            pending.extend((child, depth + 1) for child in children)
    return value


def _manifest(data):
    m = _json(data)
    _keys(m, ('schema_version', 'kind', 'version', 'reviewed_on', 'review_after', 'upstream',
              'sources', 'modules', 'capabilities', 'conflicts', 'runtime_evidence'), 'knowledge.invalid_manifest')
    _need(m['schema_version'] == 1 and type(m['schema_version']) is int and
          m['kind'] == 'omni_knowledge' and _text(m['version']), 'knowledge.invalid_manifest')
    _need(_day(m['reviewed_on']) <= _day(m['review_after']), 'knowledge.invalid_date')
    for key in ('sources', 'modules', 'capabilities', 'runtime_evidence'):
        _need(type(m[key]) is dict and bool(m[key]), 'knowledge.invalid_manifest')
    _need(type(m['conflicts']) is list, 'knowledge.invalid_manifest')
    u = m['upstream']
    _keys(u, ('repository', 'revision', 'license', 'license_url', 'modules'), 'knowledge.invalid_upstream')
    _need(u['repository'] == REPOSITORY and type(u['revision']) is str and REVISION.fullmatch(u['revision'])
          and u['license'] == 'Apache-2.0' and type(u['modules']) is dict and bool(u['modules']),
          'knowledge.invalid_upstream')
    _need(u['license_url'].startswith(REPOSITORY + '/blob/' + u['revision'] + '/'), 'knowledge.invalid_upstream')
    for module in u['modules'].values():
        _keys(module, ('path', 'sha256', 'url', 'purpose'), 'knowledge.invalid_upstream')
        _need(type(module['path']) is str and module['url'] == REPOSITORY + '/blob/' + u['revision'] + '/' + module['path']
              and type(module['sha256']) is str and SHA.fullmatch(module['sha256'])
              and _text(module['purpose']), 'knowledge.invalid_upstream')
    _need(set(m['capabilities']) == set(OBJECTS), 'knowledge.incomplete_matrix')
    for obj, record in m['capabilities'].items():
        _keys(record, ('module', 'source_ids', 'scope', 'operations'), 'knowledge.invalid_capability')
        _need(record['module'] in m['modules'] and set(record['operations']) == set(OPERATIONS)
              and _text(record['scope']), 'knowledge.incomplete_matrix')
        _need(type(record['source_ids']) is list and record['source_ids'] and
              all(s in m['sources'] for s in record['source_ids']), 'knowledge.missing_source')
        for operation in record['operations'].values():
            _keys(operation, ('documented', 'implemented', 'locally_tested', 'live_qualified', 'evidence_ids', 'limitation'),
                  'knowledge.invalid_qualification')
            _need(type(operation['documented']) is bool and type(operation['live_qualified']) is bool and
                  operation['live_qualified'] is False, 'knowledge.unqualified_native_claim')
            _need(_text(operation['limitation']), 'knowledge.invalid_qualification')
            for field in ('implemented', 'locally_tested'):
                _need(type(operation[field]) is list and len(set(operation[field])) == len(operation[field]) and
                      all(d in DIALECTS for d in operation[field]), 'knowledge.invalid_qualification')
            _need(set(operation['locally_tested']) <= set(operation['implemented']), 'knowledge.invalid_qualification')
            _need(type(operation['evidence_ids']) is list and all(e in m['runtime_evidence'] for e in operation['evidence_ids']),
                  'knowledge.missing_evidence')
            _need(not operation['implemented'] or bool(operation['evidence_ids']), 'knowledge.missing_evidence')
    return m


def _load_knowledge(objects, operations, dialects, *, as_of=None, root=None,
                    expected_manifest_sha256=None, expected_upstream_commit=None, upstream_root=None):
    """Return only selected verified guidance and qualifications; no fetch/write.

    Explicit as_of is useful for reproducible tests, not bypassing freshness in a
    live runner. The runner owns today's date and optional expected digest/pin.
    upstream_root is optional: public local guidance works without vendor files.
    Supplied vendor files must match exact reviewed hashes before any are returned.
    """
    objects = _selection(objects, OBJECTS)
    operations = _selection(operations, OPERATIONS)
    dialects = _selection(dialects, DIALECTS)
    today = _day(as_of) if as_of is not None else date.today()
    root = Path(root) if root is not None else ROOT
    raw = _read(root, 'assets/omni-knowledge.json', expected_manifest_sha256)
    m = _manifest(raw)
    _need(_day(m['reviewed_on']) <= today <= _day(m['review_after']), 'knowledge.stale_review')
    if expected_upstream_commit is not None:
        _need(expected_upstream_commit == m['upstream']['revision'], 'knowledge.upstream_pin_mismatch')
    module_ids = sorted({'core'} | {m['capabilities'][obj]['module'] for obj in objects})
    modules, source_ids, upstream_ids = [], set(), set()
    for identity in module_ids:
        _need(identity in m['modules'], 'knowledge.missing_module')
        module = m['modules'][identity]
        _keys(module, ('path', 'sha256', 'source_ids', 'upstream_ids'), 'knowledge.invalid_module')
        _need(type(module['source_ids']) is list and type(module['upstream_ids']) is list, 'knowledge.invalid_module')
        try:
            content = _read(root, module['path'], module['sha256']).decode('utf-8')
        except UnicodeError:
            raise KnowledgeError('knowledge.invalid_reference_text') from None
        modules.append({'id':identity, 'path':module['path'], 'sha256':module['sha256'], 'content':content})
        source_ids.update(module['source_ids']); upstream_ids.update(module['upstream_ids'])
    rows, evidence_ids = [], set()
    for obj in objects:
        c = m['capabilities'][obj]; source_ids.update(c['source_ids'])
        for op in operations:
            q = c['operations'][op]; evidence_ids.update(q['evidence_ids'])
            for dialect in dialects:
                rows.append({'object':obj, 'operation':op, 'dialect':dialect, 'scope':c['scope'],
                             'documented':q['documented'], 'implemented':dialect in q['implemented'],
                             'locally_tested':dialect in q['locally_tested'], 'live_qualified':False,
                             'evidence_ids':copy.deepcopy(q['evidence_ids']), 'limitation':q['limitation']})
    sources = {}
    for identity in sorted(source_ids):
        _need(identity in m['sources'], 'knowledge.missing_source')
        s = m['sources'][identity]
        _keys(s, ('url', 'retrieved_on', 'review_after', 'revision', 'sha256', 'release_status',
                  'evidence_type', 'confidence', 'claim', 'dialects'), 'knowledge.invalid_source')
        _need(type(s['url']) is str and s['url'].startswith('https://docs.omni.co/') and
              s['evidence_type'] == 'official_documentation' and s['confidence'] in ('high','medium','low') and
              type(s['release_status']) is str and bool(s['release_status']) and
              (s['sha256'] is None or type(s['sha256']) is str and SHA.fullmatch(s['sha256'])) and
              (s['revision'] is None or _text(s['revision'])) and _text(s['claim']), 'knowledge.invalid_source')
        _selection(s['dialects'], DIALECTS)
        _need(_day(s['retrieved_on']) <= today <= _day(s['review_after']), 'knowledge.stale_source')
        sources[identity] = copy.deepcopy(s)
    evidence = {}
    for identity in sorted(evidence_ids):
        record = m['runtime_evidence'][identity]
        _keys(record, ('path', 'sha256', 'description'), 'knowledge.invalid_evidence')
        _need(_text(record['description']), 'knowledge.invalid_evidence')
        _read(root, record['path'], record['sha256'])
        evidence[identity] = copy.deepcopy(record)
    dependencies = []
    for identity in sorted(upstream_ids):
        _need(identity in m['upstream']['modules'], 'knowledge.missing_upstream')
        dep = copy.deepcopy(m['upstream']['modules'][identity]); dep['id'] = identity
        dep['loaded'] = upstream_root is not None
        if upstream_root is not None:
            try:
                dep['content'] = _read(upstream_root, dep['path'], dep['sha256']).decode('utf-8')
            except UnicodeError:
                raise KnowledgeError('knowledge.invalid_reference_text') from None
        dependencies.append(dep)
    conflicts = []
    for conflict in m['conflicts']:
        _keys(conflict, ('id', 'source_ids', 'status', 'resolution'), 'knowledge.invalid_conflict')
        _need(type(conflict['source_ids']) is list and all(s in m['sources'] for s in conflict['source_ids']) and
              conflict['status'] in ('resolved_by_current_docs', 'review_required') and
              _text(conflict['id']) and _text(conflict['resolution']), 'knowledge.invalid_conflict')
        if source_ids.intersection(conflict['source_ids']):
            conflicts.append(copy.deepcopy(conflict))
    output = {'schema_version':1, 'kind':'omni_knowledge_selection', 'version':m['version'],
              'as_of':today.isoformat(), 'manifest_sha256':_hash(raw), 'upstream_revision':m['upstream']['revision'],
              'upstream_license':m['upstream']['license'], 'selection':{'objects':objects,'operations':operations,'dialects':dialects},
              'modules':modules, 'sources':sources, 'conflicts':conflicts, 'capabilities':rows,
              'runtime_evidence':evidence, 'upstream_modules':dependencies,
              'native_verified':False, 'deployment_authorized':False}
    output['knowledge_sha256'] = _hash(_canonical(output))
    return output


def load_knowledge(objects, operations, dialects, *, as_of=None, root=None,
                   expected_manifest_sha256=None, expected_upstream_commit=None, upstream_root=None):
    """Public boundary; malformed manifests never expose library diagnostics."""
    try:
        return _load_knowledge(objects, operations, dialects, as_of=as_of, root=root,
                               expected_manifest_sha256=expected_manifest_sha256,
                               expected_upstream_commit=expected_upstream_commit, upstream_root=upstream_root)
    except KnowledgeError:
        raise
    except (TypeError, KeyError, AttributeError, OSError, ValueError, RecursionError, OverflowError):
        raise KnowledgeError('knowledge.invalid_manifest') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('objects', 'operations', 'dialects'):
        parser.add_argument('--' + name, required=True, help='Comma-separated explicit selection')
    parser.add_argument('--as-of'); parser.add_argument('--expect-manifest'); parser.add_argument('--expect-upstream')
    parser.add_argument('--upstream-root'); parser.add_argument('--metadata-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = load_knowledge(args.objects.split(','), args.operations.split(','), args.dialects.split(','),
                                as_of=args.as_of, expected_manifest_sha256=args.expect_manifest,
                                expected_upstream_commit=args.expect_upstream, upstream_root=args.upstream_root)
        if args.metadata_only:
            result = copy.deepcopy(result)
            for module in result['modules'] + result['upstream_modules']:
                module.pop('content', None)
            result['presentation'] = 'content_omitted; knowledge_sha256 binds full selection'
        print(json.dumps(result, indent=2, sort_keys=True)); return 0
    except KnowledgeError as error:
        print(json.dumps({'status':'blocked', 'code':str(error)})); return 2


if __name__ == '__main__':
    raise SystemExit(main())
