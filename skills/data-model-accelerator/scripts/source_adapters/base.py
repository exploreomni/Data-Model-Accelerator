"""Shared evidence contract for bounded source adapters (Python 3.9+).

Inputs are approved UTF-8 snapshots, never executable modules. Completeness of
the exported source and native behavior cannot be inferred from file coverage.
"""
import hashlib
import json
import math
import unicodedata
from pathlib import PurePosixPath

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_FILES = 512
MAX_NODES = 150000
MAX_DEPTH = 48


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def occurrence_id(source, category, path, locator, ordinal=0):
    """Identify an occurrence at a source location, separately from its content.

    The ordinal distinguishes repeated declarations at the same locator. Moving
    or reordering source locations can change this ID; it is not a native ID.
    """
    return source + ':occurrence:' + sha(json.dumps(
        [category, path, locator, ordinal], ensure_ascii=True))[:24]


def bounded(value):
    stack, count = [(value, 0)], 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise ValueError('source.structure_limit')
        if isinstance(item, dict):
            if not all(isinstance(k, str) for k in item):
                raise ValueError('source.non_string_key')
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError('source.nonfinite_number')
        elif item is not None and type(item) not in (str, bool, int, float):
            raise ValueError('source.non_json_value')
    return value


def unique_pairs(pairs):
    value = {}
    for k, v in pairs:
        if k in value:
            raise ValueError('source.duplicate_key')
        value[k] = v
    return value


def read_json(text):
    if len(text.encode('utf-8')) > MAX_FILE_BYTES:
        raise ValueError('source.byte_limit')
    try:
        return bounded(json.loads(text, object_pairs_hook=unique_pairs,
                                  parse_constant=lambda _: (_ for _ in ()).throw(ValueError('source.nonfinite_number'))))
    except (RecursionError, UnicodeError, json.JSONDecodeError):
        raise ValueError('source.invalid_json') from None


def read_yaml(text):
    import yaml
    if len(text.encode('utf-8')) > MAX_FILE_BYTES:
        raise ValueError('source.byte_limit')
    try:
        if any(isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for t in yaml.scan(text)):
            raise ValueError('source.yaml_alias')
        class Loader(yaml.SafeLoader):
            pass
        def mapping(loader, node, deep=False):
            return unique_pairs([(loader.construct_object(k, deep=deep), loader.construct_object(v, deep=deep)) for k, v in node.value])
        Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
        return bounded(yaml.load(text, Loader=Loader))
    except (yaml.YAMLError, RecursionError, TypeError):
        raise ValueError('source.invalid_yaml') from None


def validate_files(files):
    if not isinstance(files, dict) or len(files) > MAX_FILES:
        raise ValueError('source.file_limit')
    total = 0
    prefixes, file_keys = {}, set()
    for path, content in files.items():
        if not isinstance(path, str) or not path or not isinstance(content, str):
            raise ValueError('source.invalid_file')
        p = PurePosixPath(path)
        if p.is_absolute() or '..' in p.parts or '\\' in path or ':' in path or str(p) != path or any(ord(c) < 32 for c in path):
            raise ValueError('source.unsafe_path')
        if len(p.parts) > MAX_DEPTH:
            raise ValueError('source.path_depth_limit')
        # Staging on case-insensitive or Unicode-normalizing filesystems must
        # never bind one file's parsed values to another file's byte hash.
        for i in range(1, len(p.parts) + 1):
            prefix = '/'.join(p.parts[:i])
            key = unicodedata.normalize('NFC', prefix).casefold()
            if key in prefixes and prefixes[key] != prefix:
                raise ValueError('source.path_collision')
            if i < len(p.parts) and key in file_keys:
                raise ValueError('source.file_directory_collision')
            prefixes[key] = prefix
        key = unicodedata.normalize('NFC', path).casefold()
        if any(other.startswith(key + '/') for other in prefixes):
            raise ValueError('source.file_directory_collision')
        file_keys.add(key)
        size = len(content.encode('utf-8'))
        total += size
        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError('source.byte_limit')


class Report:
    def __init__(self, source, files):
        validate_files(files)
        self.source, self.files = source, dict(files)
        self.objects, self.expressions, self.dependencies, self.gaps = [], [], [], []
        self.coverage = {}
        self._ids = set()

    def evidence(self, path, locator):
        if path not in self.files or not isinstance(locator, str) or not locator:
            raise ValueError('source.invalid_evidence')
        return {'path': path, 'locator': locator, 'sha256': sha(self.files[path])}

    def _id(self, category, path, locator, name):
        return self.source + ':' + category + ':' + sha(json.dumps([path, locator, str(name)], ensure_ascii=True))[:24]

    def object(self, path, locator, kind, name, native_id=None, **details):
        identity = self._id('object', path, locator, native_id if native_id is not None else name)
        if identity in self._ids:
            raise ValueError('source.duplicate_object')
        self._ids.add(identity)
        self.objects.append({'id': identity, 'native_id': None if native_id is None else str(native_id),
                             'kind': kind, 'name': str(name), 'evidence': self.evidence(path, locator),
                             'details': bounded(details)})
        return identity

    def expression(self, path, locator, language, text, object_id=None, **details):
        if not isinstance(text, str):
            raise ValueError('source.invalid_expression')
        identity = self._id('expression', path, locator, text)
        self.expressions.append({'id': identity, 'object_id': object_id, 'language': language,
                                 'text': text, 'evidence': self.evidence(path, locator), 'details': bounded(details)})
        return identity

    def dependency(self, path, locator, source_id, target, **details):
        self.dependencies.append({'source_id': source_id, 'target': str(target),
                                  'evidence': self.evidence(path, locator), 'details': bounded(details)})

    def gap(self, path, code, message, locator='$'):
        item = {'code': code, 'message': message, 'evidence': self.evidence(path, locator)}
        if not any(all(existing.get(key) == value for key, value in item.items()) for existing in self.gaps):
            self.gaps.append(item)

    def cover(self, path, status='parsed', reason=''):
        if path not in self.files or status not in ('parsed', 'partial', 'unsupported'):
            raise ValueError('source.invalid_coverage')
        self.coverage[path] = {'path': path, 'sha256': sha(self.files[path]), 'status': status, 'reason': reason}

    def finish(self):
        for path in sorted(self.files):
            if path not in self.coverage:
                self.cover(path, 'unsupported', 'No supported parser claimed this file.')
            if any(g['evidence']['path'] == path for g in self.gaps) and self.coverage[path]['status'] == 'parsed':
                self.coverage[path]['status'] = 'partial'
        for category in ('objects', 'expressions', 'dependencies', 'gaps'):
            seen = {}
            for item in getattr(self, category):
                evidence = item['evidence']
                key = (evidence['path'], evidence['locator'])
                ordinal = seen.get(key, 0)
                item['occurrence_id'] = occurrence_id(self.source, category, *key, ordinal)
                seen[key] = ordinal + 1
                if category == 'expressions':
                    item['content_sha256'] = sha(item['text'])
        return {'schema_version': 1, 'kind': 'source_adapter_result', 'source': self.source,
                'adapter_version': 1, 'source_files': [self.coverage[p] for p in sorted(self.files)],
                'coverage_summary': {'unit': 'supplied_source_files', 'expected': len(self.files),
                                     'observed': len(self.coverage), 'missing': 0,
                                     'statuses': {status: sum(f['status'] == status for f in self.coverage.values())
                                                  for status in ('parsed', 'partial', 'unsupported')}},
                'objects': self.objects, 'expressions': self.expressions,
                'dependencies': self.dependencies, 'gaps': self.gaps,
                'export_completeness': 'not_established', 'native_validation': 'not_run',
                'execution_performed': False,
                'limitations': ['File coverage is not export completeness or semantic parity.',
                                'Declarations do not establish effective access, actual grain, or uniqueness.']}
