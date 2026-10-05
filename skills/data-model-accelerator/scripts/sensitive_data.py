"""Bounded local disclosure scanning. Signals are not a privacy certification.

Never return input names, snippets, matched values or hashes of individual values.
Callers must scan the exact bytes they disclose and separately enforce reviewed
classification, destination policy and the host boundary before agent access.
"""
import argparse
import base64
import hashlib
import html
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import zipfile


MAX_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_MEMBERS = 256
MAX_DEPTH = 4
MAX_FINDINGS = 500
TEXT_SUFFIXES = {'.txt', '.md', '.sql', '.yml', '.yaml', '.json', '.csv', '.tsv',
                 '.html', '.htm', '.svg', '.xml', '.twb', '.tds', '.lkml', '.lookml',
                 '.view', '.topic', '.mmd', '.py', '.js', '.toml', '.lock', '.tmdl'}
RULES = (
    ('credential.private_key', 'CREDENTIAL', re.compile(r'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----')),
    ('credential.bearer', 'CREDENTIAL', re.compile(r'\bBearer\s+[A-Za-z0-9._~+/=-]{8,}', re.I)),
    ('credential.provider_token', 'CREDENTIAL', re.compile(r'\b(?:AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{16,})\b')),
    ('credential.assignment', 'CREDENTIAL', re.compile(r'''\b(?:password|passwd|access_token|api_key|private_key|client_secret)\s*["']?\s*[:=]\s*["']?[^\s"'{}]{4,}''', re.I)),
    ('pii.email', 'PII', re.compile(r'(?<![\w.+-])[A-Z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9.-]*[A-Z0-9])?\.[A-Z]{2,}(?![\w.-])', re.I)),
    ('pii.ssn', 'PII', re.compile(r'(?<!\d)\d{3}[- ]\d{2}[- ]\d{4}(?!\d)')),
    ('pci.authentication_value', 'PCI', re.compile(r'''\b(?:cvv|cvc|card_verification_value|pin_code)\s*["']?\s*[:=]\s*["']?\d{3,6}\b''', re.I)),
    ('phi.contextual_value', 'PHI', re.compile(r'''\b(?:patient_name|patient_id|medical_record_number|diagnosis|health_condition)[ \t]*["']?[ \t]*[:=][ \t]*["']?[^\s"'{}\[\],]{2,}''', re.I)),
    ('pii.synthetic_marker', 'PII', re.compile(r'\b(?:SYNTHETIC_PII_CANARY|PII_TEST_CANARY)\b')),
    ('pci.synthetic_marker', 'PCI', re.compile(r'\b(?:SYNTHETIC_PCI_CANARY|NOT_A_CARD_NUMBER_TEST_ONLY)\b')),
    ('phi.synthetic_marker', 'PHI', re.compile(r'\b(?:SYNTHETIC_PHI_CANARY|TEST_ONLY_NOT_PATIENT_DATA)\b')),
)
CARD = re.compile(r'(?<!\w)(?:\d[ -]?){12,18}\d(?!\w)')
UUID_TOKEN = re.compile(r'(?<![\w-])[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}(?![\w-])', re.I)
LIMITATIONS = [
    'Local bounded pattern detection only; clear means no supported signal detected, not absence of sensitive data.',
    'Names, contextual health data, obfuscation, unsupported formats and novel credentials can evade detection.',
    'Classification, lineage, destination authorization and host isolation require separate evidence.',
    'The report contains a whole-artifact integrity hash; it is not anonymization or authenticated execution evidence.',
]


def _luhn(value):
    digits = [int(c) for c in value if c.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    return sum((d * 2 - 9 if d * 2 > 9 else d * 2) if (len(digits) - i) % 2 == 0 else d
               for i, d in enumerate(digits)) % 10 == 0


def _json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Non-finite JSON value')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


class _HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.json_depth = 0
        self.buffers = []
        self.embedded = []
        self.duplicate_attributes = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        self.duplicate_attributes |= len(values) != len(attrs)
        if tag.lower() == 'script' and (values.get('type') or '').lower() in ('application/json', 'application/ld+json'):
            self.json_depth += 1
            self.buffers.append([])
        # Preserve every value: converting attrs to a dict alone lets a later
        # duplicate attribute hide an earlier embedded payload from inspection.
        for _, value in attrs:
            if value and value.lower().startswith('data:'):
                self.embedded.append(value)

    def handle_data(self, data):
        if self.json_depth:
            self.buffers[-1].append(data)

    def handle_endtag(self, tag):
        if tag.lower() == 'script' and self.json_depth:
            self.json_depth -= 1


def scan_bytes(data, filename):
    """Inspect bytes without execution/network; use opaque indexed locations only.

    Status is blocked for a detected signal, unsupported for incomplete coverage,
    otherwise clear. Malformed or bounded-out content never obtains clear status.
    Nested ZIPs and portal HTML JSON/base64 payloads share one total read budget.
    """
    if type(data) is not bytes or type(filename) is not str:
        raise ValueError('Scanner requires bytes and a format filename')
    result = {'schema_version': 1, 'kind': 'sensitive_data_scan', 'status': 'clear',
              'artifact_sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
              'findings': [], 'coverage': {'complete': True, 'objects_inspected': 0},
              'limitations': list(LIMITATIONS)}
    budget = {'bytes': 0, 'members': 0}
    seen = set()

    def finding(rule, category, location, line=None, unsupported=False):
        if unsupported:
            result['coverage']['complete'] = False
        key = (rule, tuple(location), line)
        if key not in seen and len(result['findings']) < MAX_FINDINGS:
            seen.add(key)
            where = {'member_indices': list(location)}
            if line is not None:
                where['line'] = line
            result['findings'].append({'rule_id': rule, 'category': category, 'location': where})
        elif key not in seen:
            result['coverage']['complete'] = False

    def signals(text, location):
        for rule, category, pattern in RULES:
            for match in pattern.finditer(text):
                finding(rule, category, location, text.count('\n', 0, match.start()) + 1)
                if len(result['findings']) >= MAX_FINDINGS:
                    result['coverage']['complete'] = False
                    return
        uuid_spans = [match.span() for match in UUID_TOKEN.finditer(text)]
        uuid_index = 0
        for match in CARD.finditer(text):
            # A numeric UUID segment is an identifier, not a complete card
            # number. This exception affects only PAN matching, not other rules.
            while uuid_index < len(uuid_spans) and uuid_spans[uuid_index][1] <= match.start():
                uuid_index += 1
            if uuid_index < len(uuid_spans) and uuid_spans[uuid_index][0] <= match.start() and match.end() <= uuid_spans[uuid_index][1]:
                continue
            if _luhn(match.group()):
                finding('pci.pan_candidate', 'PCI', location, text.count('\n', 0, match.start()) + 1)
                if len(result['findings']) >= MAX_FINDINGS:
                    result['coverage']['complete'] = False
                    return

    def embedded(value, location, depth, content_type='text/plain'):
        if depth > MAX_DEPTH or len(value) > MAX_BYTES * 2:
            finding('coverage.embedded_limit', 'COVERAGE', location, unsupported=True)
            return
        try:
            decoded = base64.b64decode(value, validate=True)
        except (ValueError, UnicodeError):
            finding('coverage.invalid_base64', 'COVERAGE', location, unsupported=True)
            return
        suffix = {'application/zip': '.zip', 'application/json': '.json', 'text/html': '.html'}.get(content_type, '.txt')
        # A Markdown link starts with '[' too. Only sniff a JSON array when
        # its first token can be JSON; explicit JSON MIME remains strict.
        if re.match(rb'(?:\{\s*["}]|\[\s*(?:["\[{0-9\-\]]|true\b|false\b|null\b))', decoded.lstrip()):
            suffix = '.json'
        elif decoded.lstrip().startswith(b'<'):
            suffix = '.html'
        inspect(decoded, 'embedded' + suffix, location, depth)

    def json_values(value, location, depth, container_depth):
        if depth > 16:
            finding('coverage.json_depth', 'COVERAGE', location, unsupported=True)
            return
        if type(value) is str:
            signals(value, location)
            if value.lower().startswith('data:'):
                data_url(value, location, container_depth)
        elif type(value) is list:
            for index, child in enumerate(value):
                json_values(child, location + [index], depth + 1, container_depth)
        elif type(value) is dict:
            for index, (key, child) in enumerate(value.items()):
                signals(key, location + [index])
                if key.lower() == 'base64' and type(child) is str:
                    # Parent-provided paths are untrusted and never used as files.
                    embedded(child, location + [index], container_depth + 1)
                else:
                    json_values(child, location + [index], depth + 1, container_depth)

    def data_url(value, location, depth):
        header, sep, payload = value.partition(',')
        if not sep or ';base64' not in header.lower():
            finding('coverage.unsupported_data_url', 'COVERAGE', location, unsupported=True)
        else:
            embedded(payload, location, depth + 1, header[5:].split(';', 1)[0].lower())

    def inspect(body, name, location, depth):
        if depth > MAX_DEPTH or len(body) > MAX_BYTES or budget['bytes'] + len(body) > MAX_TOTAL_BYTES:
            finding('coverage.byte_or_depth_limit', 'COVERAGE', location, unsupported=True)
            return
        budget['bytes'] += len(body)
        budget['members'] += 1
        if budget['members'] > MAX_MEMBERS:
            finding('coverage.member_limit', 'COVERAGE', location, unsupported=True)
            return
        result['coverage']['objects_inspected'] += 1
        suffix = PurePosixPath(name.replace('\\', '/')).suffix.lower()
        signals(name, location)
        if body.startswith(b'PK') or suffix == '.zip':
            try:
                with zipfile.ZipFile(io.BytesIO(body)) as archive:
                    members = archive.infolist()
                    # ZipFile accepts self-extracting prefixes and trailing data.
                    # This disclosure route accepts plain bounded ZIPs only.
                    if (members and min(info.header_offset for info in members) != 0
                            or not body.startswith((b'PK\x03\x04', b'PK\x05\x06'))
                            or body[-22-len(archive.comment):][:4] != b'PK\x05\x06'):
                        finding('coverage.archive_wrapper', 'COVERAGE', location, unsupported=True)
                    if archive.comment:
                        signals(archive.comment.decode('utf-8', errors='replace'), location)
                        finding('coverage.archive_comment', 'COVERAGE', location, unsupported=True)
                    expected_offset = 0
                    for info in sorted(members, key=lambda item: item.header_offset):
                        header = body[info.header_offset:info.header_offset + 30]
                        if len(header) != 30 or header[:4] != b'PK\x03\x04':
                            finding('coverage.archive_structure', 'COVERAGE', location, unsupported=True)
                            break
                        name_size, extra_size = struct.unpack_from('<HH', header, 26)
                        if info.header_offset != expected_offset or info.flag_bits & 8 or extra_size:
                            finding('coverage.archive_uninspected_bytes', 'COVERAGE', location, unsupported=True)
                        expected_offset = info.header_offset + 30 + name_size + extra_size + info.compress_size
                    if expected_offset != archive.start_dir:
                        finding('coverage.archive_uninspected_bytes', 'COVERAGE', location, unsupported=True)
                    if len(members) > MAX_MEMBERS:
                        finding('coverage.member_limit', 'COVERAGE', location, unsupported=True)
                        return
                    for index, info in enumerate(members):
                        at = location + [index]
                        signals(info.filename, at)
                        if info.comment or info.extra:
                            signals(info.comment.decode('utf-8', errors='replace'), at)
                            finding('coverage.archive_member_metadata', 'COVERAGE', at, unsupported=True)
                        path = PurePosixPath(info.filename)
                        unsafe = (path.is_absolute() or '..' in path.parts or '\\' in info.filename
                                  or ':' in info.filename or '\0' in info.filename
                                  or stat.S_ISLNK(info.external_attr >> 16))
                        if unsafe or info.flag_bits & 1:
                            finding('coverage.unsafe_archive_member', 'COVERAGE', at, unsupported=True)
                            continue
                        if info.is_dir():
                            if info.file_size:
                                finding('coverage.archive_directory_payload', 'COVERAGE', at, unsupported=True)
                            continue
                        if (info.file_size > MAX_BYTES or info.file_size > MAX_TOTAL_BYTES - budget['bytes']
                                or info.file_size > max(info.compress_size, 1) * 200):
                            finding('coverage.archive_expansion_limit', 'COVERAGE', at, unsupported=True)
                            continue
                        with archive.open(info) as stream:
                            content = stream.read(min(MAX_BYTES, MAX_TOTAL_BYTES - budget['bytes']) + 1)
                        inspect(content, info.filename, at, depth + 1)
            except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, NotImplementedError, struct.error):
                finding('coverage.invalid_archive', 'COVERAGE', location, unsupported=True)
            return
        if suffix not in TEXT_SUFFIXES and PurePosixPath(name).name not in ('model', 'relationships'):
            finding('coverage.unsupported_format', 'COVERAGE', location, unsupported=True)
            return
        try:
            text = body.decode('utf-8-sig')
        except UnicodeError:
            finding('coverage.unsupported_encoding', 'COVERAGE', location, unsupported=True)
            return
        if '\0' in text:
            finding('coverage.binary_content', 'COVERAGE', location, unsupported=True)
            return
        signals(text, location)
        if suffix == '.json':
            try:
                json_values(_json(text), location, 0, depth)
            except (ValueError, RecursionError):
                finding('coverage.invalid_json', 'COVERAGE', location, unsupported=True)
        elif suffix in ('.html', '.htm', '.svg', '.xml', '.twb', '.tds'):
            signals(html.unescape(text), location)
            parser = _HTML()
            try:
                parser.feed(text)
                if parser.duplicate_attributes:
                    finding('coverage.duplicate_html_attribute', 'COVERAGE', location, unsupported=True)
                for index, buffer in enumerate(parser.buffers):
                    json_values(_json(''.join(buffer)), location + [index], 0, depth)
                for index, value in enumerate(parser.embedded):
                    data_url(value, location + [len(parser.buffers) + index], depth)
            except (ValueError, RecursionError):
                finding('coverage.invalid_embedded_json', 'COVERAGE', location, unsupported=True)

    try:
        inspect(data, filename, [], 0)
    except (ValueError, OverflowError, RecursionError, UnicodeError):
        finding('coverage.scanner_failure', 'COVERAGE', [], unsupported=True)
    if any(item['category'] != 'COVERAGE' for item in result['findings']):
        result['status'] = 'blocked'
    elif not result['coverage']['complete']:
        result['status'] = 'unsupported'
    return result


def scan_file(path):
    """Bounded regular-file read; no symlinks, no output containing the path."""
    path = Path(path).absolute()
    if path.resolve() != path:
        raise ValueError('Scanner input must be a canonical regular file')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Scanner input must be a regular file')
        data = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('Scanner input changed during inspection')
    if before.st_size > MAX_BYTES:
        raise ValueError('Scanner input exceeds the byte limit')
    return scan_bytes(data, path.name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    args = parser.parse_args(argv)
    try:
        report = scan_file(args.path)
    except (ValueError, OSError):
        report = {'schema_version': 1, 'kind': 'sensitive_data_scan', 'status': 'unsupported',
                  'findings': [{'rule_id': 'coverage.input_unavailable', 'category': 'COVERAGE',
                                'location': {'member_indices': []}}], 'limitations': list(LIMITATIONS)}
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] == 'clear' else 1


if __name__ == '__main__':
    raise SystemExit(main())
