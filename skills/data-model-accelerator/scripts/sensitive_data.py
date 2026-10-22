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
import subprocess
import sys
import warnings
import xml.etree.ElementTree as ET
import zipfile
import zlib


MAX_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_MEMBERS = 256
MAX_DEPTH = 4
MAX_FINDINGS = 500
MAX_IMAGE_PIXELS = 8_000_000
MAX_IMAGE_DIMENSION = 8192
MAX_PDF_PAGES = 100
MAX_PDF_OBJECTS = 4096
MAX_PDF_NODES = 50000
MAX_PDF_DEPTH = 32
PDF_TIMEOUT_SECONDS = 15
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
    'Supported Office raster images are structurally checked and metadata-scanned; pixels are not OCR-scanned.',
    'Supported PDFs scan extracted text and metadata, not visual appearance, raster text, or embedded font semantics; image-only pages are unsupported.',
    'Rich document readers require the exact versions in requirements-documents.txt; dependency failures never obtain clear status.',
]


class _UnsupportedDocument(ValueError):
    """Only fixed, value-free reason codes may cross the scanner boundary."""


def _validate_exif(value):
    data = value[6:]
    if len(data) < 8 or data[:2] not in (b'II', b'MM'):
        raise _UnsupportedDocument('coverage.invalid_image_metadata')
    endian = '<' if data[:2] == b'II' else '>'
    if struct.unpack_from(endian + 'H', data, 2)[0] != 42:
        raise _UnsupportedDocument('coverage.invalid_image_metadata')
    visited = set()
    def directory(offset, depth):
        if not offset:
            return
        if depth > 4 or offset in visited or offset + 2 > len(data):
            raise _UnsupportedDocument('coverage.invalid_image_metadata')
        visited.add(offset)
        count = struct.unpack_from(endian + 'H', data, offset)[0]
        if count > MAX_MEMBERS or offset + 6 + count * 12 > len(data):
            raise _UnsupportedDocument('coverage.invalid_image_metadata')
        for index in range(count):
            at = offset + 2 + index * 12
            tag, kind, length, pointer = struct.unpack_from(endian + 'HHII', data, at)
            sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
            if kind not in sizes or tag in (513, 514, 37500) or (kind == 7 and tag != 37510):
                raise _UnsupportedDocument('coverage.unsupported_image_metadata')
            size = sizes[kind] * length
            if size > len(data) or (size > 4 and (pointer < 8 or pointer + size > len(data))):
                raise _UnsupportedDocument('coverage.invalid_image_metadata')
            if tag in (34665, 34853, 40965):
                if kind != 4 or length != 1:
                    raise _UnsupportedDocument('coverage.invalid_image_metadata')
                directory(pointer, depth + 1)
        directory(struct.unpack_from(endian + 'I', data, offset + 2 + count * 12)[0], depth + 1)
    directory(struct.unpack_from(endian + 'I', data, 4)[0], 0)


def _validate_icc(profile):
    if (len(profile) < 132 or profile[36:40] != b'acsp'
            or struct.unpack_from('>I', profile)[0] != len(profile)):
        raise _UnsupportedDocument('coverage.invalid_image_metadata')
    count = struct.unpack_from('>I', profile, 128)[0]
    if count > MAX_MEMBERS or 132 + 12 * count > len(profile):
        raise _UnsupportedDocument('coverage.invalid_image_metadata')
    for index in range(count):
        offset, size = struct.unpack_from('>II', profile, 136 + 12 * index)
        if (size < 8 or offset < 132 + 12 * count or offset + size > len(profile)
                or profile[offset:offset + 4] not in {b'XYZ ', b'curv', b'para', b'sf32', b'desc', b'text', b'mluc'}):
            raise _UnsupportedDocument('coverage.unsupported_image_metadata')


def _image_text(body, suffix):
    """Validate passive raster framing, metadata and decoded pixel bounds.

    No files are created, external resources opened or metadata executed. Unknown
    PNG chunks/JPEG application payloads fail closed; EXIF/ICC are passive metadata.
    Textual metadata is scanned in common encodings, never returned in reports.
    """
    try:
        from PIL import Image
        from PIL import __version__ as pillow_version
    except ImportError:
        raise _UnsupportedDocument('coverage.image_dependency_missing') from None
    if pillow_version != '13.0.0':
        raise _UnsupportedDocument('coverage.image_dependency_unqualified')
    metadata, icc_parts = [], {}
    if suffix == '.png':
        if not body.startswith(b'\x89PNG\r\n\x1a\n'):
            raise _UnsupportedDocument('coverage.invalid_image')
        pos, chunks = 8, []
        allowed = {b'IHDR', b'PLTE', b'IDAT', b'IEND', b'tRNS', b'sRGB', b'gAMA',
                   b'cHRM', b'pHYs', b'bKGD', b'tEXt', b'zTXt', b'iTXt'}
        while pos < len(body):
            if len(chunks) >= MAX_MEMBERS or pos + 12 > len(body):
                raise _UnsupportedDocument('coverage.invalid_image')
            size, kind = struct.unpack_from('>I4s', body, pos)
            end = pos + 12 + size
            if end > len(body) or kind not in allowed:
                raise _UnsupportedDocument('coverage.unsupported_image_metadata')
            value = body[pos + 8:end - 4]
            if zlib.crc32(kind + value) & 0xffffffff != struct.unpack_from('>I', body, end - 4)[0]:
                raise _UnsupportedDocument('coverage.invalid_image')
            chunks.append(kind)
            if kind == b'tEXt':
                metadata.append(value)
            if kind in (b'zTXt', b'iTXt'):
                # Pillow supplies decoded text with its own decompression bounds.
                metadata.append(value.split(b'\0', 1)[0])
            pos = end
            if kind == b'IEND':
                if size or pos != len(body):
                    raise _UnsupportedDocument('coverage.invalid_image')
                break
        if (not chunks or chunks[0] != b'IHDR' or chunks[-1] != b'IEND'
                or chunks.count(b'IHDR') != 1 or b'IDAT' not in chunks):
            raise _UnsupportedDocument('coverage.invalid_image')
    else:
        if not body.startswith(b'\xff\xd8'):
            raise _UnsupportedDocument('coverage.invalid_image')
        pos, ended, count = 2, False, 0
        while pos < len(body):
            count += 1
            if count > 4096 or body[pos] != 255:
                raise _UnsupportedDocument('coverage.invalid_image')
            while pos < len(body) and body[pos] == 255:
                pos += 1
            if pos >= len(body):
                raise _UnsupportedDocument('coverage.invalid_image')
            marker = body[pos]; pos += 1
            if marker == 0xd9:
                # Word's stock JPEG thumbnail has one alignment byte after EOI.
                ended = len(body) - pos <= 3 and not any(body[pos:])
                break
            if marker in (0, 0xd8) or 0xd0 <= marker <= 0xd7 or pos + 2 > len(body):
                raise _UnsupportedDocument('coverage.invalid_image')
            size = struct.unpack_from('>H', body, pos)[0]
            if size < 2 or pos + size > len(body):
                raise _UnsupportedDocument('coverage.invalid_image')
            value = body[pos + 2:pos + size]; pos += size
            if 0xe0 <= marker <= 0xef:
                prefixes = {0xe0: b'JFIF\0', 0xe1: b'Exif\0\0', 0xe2: b'ICC_PROFILE\0', 0xee: b'Adobe'}
                if marker not in prefixes or not value.startswith(prefixes[marker]):
                    raise _UnsupportedDocument('coverage.unsupported_image_metadata')
                if marker == 0xe0 and (len(value) < 14 or len(value) != 14 + 3 * value[12] * value[13]):
                    raise _UnsupportedDocument('coverage.invalid_image_metadata')
                if marker == 0xe1:
                    _validate_exif(value)
                if marker == 0xe2:
                    if len(value) < 14 or value[12] in icc_parts or not 1 <= value[12] <= value[13]:
                        raise _UnsupportedDocument('coverage.invalid_image_metadata')
                    icc_parts[value[12]] = (value[13], value[14:])
                if marker == 0xee and len(value) != 12:
                    raise _UnsupportedDocument('coverage.invalid_image_metadata')
                metadata.append(value)
            elif marker == 0xfe:
                metadata.append(value)
            elif marker not in {0xc0, 0xc1, 0xc2, 0xc4, 0xdb, 0xdd, 0xda}:
                raise _UnsupportedDocument('coverage.unsupported_image_encoding')
            if marker == 0xda:
                # Entropy data may contain stuffed FF bytes and restart markers.
                while pos < len(body):
                    if body[pos] != 255:
                        pos += 1; continue
                    if pos + 1 >= len(body):
                        break
                    if body[pos + 1] == 0 or 0xd0 <= body[pos + 1] <= 0xd7:
                        pos += 2; continue
                    break
        if not ended:
            raise _UnsupportedDocument('coverage.invalid_image')
        if icc_parts:
            if (set(icc_parts) != set(range(1, len(icc_parts) + 1))
                    or any(total != len(icc_parts) for total, _ in icc_parts.values())):
                raise _UnsupportedDocument('coverage.invalid_image_metadata')
            _validate_icc(b''.join(icc_parts[index][1] for index in sorted(icc_parts)))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            with Image.open(io.BytesIO(body)) as img:
                if img.format != ('PNG' if suffix == '.png' else 'JPEG') or getattr(img, 'n_frames', 1) != 1:
                    raise _UnsupportedDocument('coverage.unsupported_image_encoding')
                if (min(img.size) <= 0 or max(img.size) > MAX_IMAGE_DIMENSION
                        or img.width * img.height > MAX_IMAGE_PIXELS):
                    raise _UnsupportedDocument('coverage.image_pixel_limit')
                img.verify()
            with Image.open(io.BytesIO(body)) as img:
                img.load()
                metadata.extend(v for v in img.info.values() if isinstance(v, (bytes, str)))
                if img.info.get('exif'):
                    exif = img.getexif()
                    metadata.extend(str(value) for value in exif.values())
                    for tag in (34665, 34853, 40965):
                        if tag in exif:
                            metadata.extend(str(value) for value in exif.get_ifd(tag).values())
    except _UnsupportedDocument:
        raise
    except Exception:
        raise _UnsupportedDocument('coverage.invalid_image') from None
    texts = []
    for value in metadata:
        if isinstance(value, str):
            texts.append(value)
        else:
            texts.extend(value.decode(enc, errors='replace') for enc in ('utf-8', 'latin-1', 'utf-16-be', 'utf-16-le'))
    if sum(len(value.encode('utf-8')) for value in texts) > MAX_BYTES:
        raise _UnsupportedDocument('coverage.image_metadata_limit')
    return texts


def _pdf_worker(body, available_bytes):
    """Run only in a resource-limited child; return no extracted input values."""
    import logging
    class RejectRecovery(logging.Handler):
        def emit(self, record):
            raise _UnsupportedDocument('coverage.pdf_parser_recovery')
    logger = logging.getLogger('pypdf')
    logger.handlers = [RejectRecovery()]
    logger.propagate = False
    logger.setLevel(logging.WARNING)
    try:
        import pypdf
        from pypdf import PdfReader, filters
        from pypdf.generic import (ArrayObject, ByteStringObject, ContentStream, DictionaryObject,
                                  IndirectObject, NameObject, StreamObject, TextStringObject)
    except ImportError:
        raise _UnsupportedDocument('coverage.pdf_dependency_missing') from None
    if pypdf.__version__ != '6.21.2':
        raise _UnsupportedDocument('coverage.pdf_dependency_unqualified')
    for name in ('ZLIB_MAX_OUTPUT_LENGTH', 'LZW_MAX_OUTPUT_LENGTH', 'RUN_LENGTH_MAX_OUTPUT_LENGTH',
                 'MAX_DECLARED_STREAM_LENGTH', 'MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH'):
        setattr(filters, name, min(MAX_BYTES, available_bytes))
    if (not re.match(rb'%PDF-1\.[0-7][\r\n]', body)
            or not re.search(rb'%%EOF[\r\n \t]*\Z', body)):
        raise _UnsupportedDocument('coverage.invalid_pdf')
    # Qualify ordinary single-revision PDFs, not parser recovery, object streams,
    # incremental revisions or arbitrary data appended after the last EOF.
    reader = PdfReader(io.BytesIO(body), strict=True, root_object_recovery_limit=0)
    if reader.is_encrypted:
        raise _UnsupportedDocument('coverage.pdf_encrypted')
    if '/Prev' in reader.trailer or '/XRefStm' in reader.trailer or reader.xref_objStm:
        raise _UnsupportedDocument('coverage.pdf_revision_or_object_stream')
    objects = [(generation, number) for generation, entries in reader.xref.items()
               for number in entries if number != 0 and generation != 65535]
    if len(objects) > MAX_PDF_OBJECTS:
        raise _UnsupportedDocument('coverage.pdf_object_limit')
    roles, role_nodes = {}, 0
    def assign(value, role):
        if isinstance(value, IndirectObject):
            roles[(value.generation, value.idnum)] = role
        elif isinstance(value, ArrayObject):
            for item in value:
                assign(item, role)
    def collect_roles(value, depth=0):
        nonlocal role_nodes
        role_nodes += 1
        if role_nodes > MAX_PDF_NODES or depth > MAX_PDF_DEPTH:
            raise _UnsupportedDocument('coverage.pdf_structure_limit')
        if isinstance(value, DictionaryObject):
            for key, child in value.items():
                if key in ('/Contents', '/ToUnicode', '/FontFile2', '/FontFile3'):
                    assign(child, key)
                if key == '/FontFile':
                    raise _UnsupportedDocument('coverage.pdf_font_encoding')
                collect_roles(child, depth + 1)
        elif isinstance(value, ArrayObject):
            if len(value) == 2 and value[0] == '/ICCBased':
                assign(value[1], '/ICC')
            for child in value:
                collect_roles(child, depth + 1)
    for generation, number in objects:
        collect_roles(reader.get_object(IndirectObject(number, generation, reader)))
    denied_keys = {'/AA', '/OpenAction', '/JS', '/JavaScript', '/EmbeddedFiles', '/EF',
                   '/XFA', '/AcroForm', '/Collection', '/RichMediaContent', '/RichMediaSettings',
                   '/Launch', '/URI', '/SubmitForm', '/ImportData', '/GoToR', '/GoToE',
                   '/Rendition', '/Movie', '/Sound', '/3DD', '/Ref', '/OPI', '/Alternates'}
    denied_names = {'/Action', '/JavaScript', '/Launch', '/URI', '/GoToR', '/GoToE', '/SubmitForm',
                    '/ImportData', '/Rendition', '/Movie', '/Sound', '/RichMedia', '/3D',
                    '/Filespec', '/EmbeddedFile', '/XRef', '/ObjStm', '/GoTo', '/Hide', '/Named',
                    '/ResetForm', '/SetOCGState', '/Trans', '/Thread'}
    count, consumed, texts, visited, pending = 0, 0, [], set(), []

    def add_text(value):
        nonlocal consumed
        encoded = value.encode('utf-8', errors='replace')
        consumed += len(encoded)
        if len(encoded) > MAX_BYTES or consumed > available_bytes:
            raise _UnsupportedDocument('coverage.pdf_decoded_byte_limit')
        texts.append(encoded)

    def walk(value, depth=0):
        nonlocal count, consumed
        count += 1
        if count > MAX_PDF_NODES or depth > MAX_PDF_DEPTH:
            raise _UnsupportedDocument('coverage.pdf_structure_limit')
        if isinstance(value, IndirectObject):
            identity = (value.generation, value.idnum)
            if identity in visited:
                return
            visited.add(identity)
            if len(visited) > MAX_PDF_OBJECTS:
                raise _UnsupportedDocument('coverage.pdf_object_limit')
            # Graph links (including tagged-PDF sibling/parent pointers) are
            # not nested containers. Resolve them in a bounded queue so normal
            # long lists cannot consume the local dictionary nesting allowance.
            pending.append(value)
        elif isinstance(value, DictionaryObject):
            if denied_keys.intersection(value):
                raise _UnsupportedDocument('coverage.pdf_active_or_external_content')
            if any(isinstance(value.get(key), NameObject) and value.get(key) in denied_names
                   for key in ('/Type', '/Subtype', '/S')):
                raise _UnsupportedDocument('coverage.pdf_active_or_external_content')
            if '/A' in value:
                # Tagged PDFs use /StructElem /A for passive layout attributes;
                # annotation/catalog /A remains an action and is rejected.
                if value.get('/Type') != '/StructElem':
                    raise _UnsupportedDocument('coverage.pdf_active_or_external_content')
                attributes = value['/A']
                attributes = attributes if isinstance(attributes, ArrayObject) else [attributes]
                for attribute in attributes:
                    attribute = attribute.get_object()
                    if isinstance(attribute, int):  # Attribute revision number.
                        continue
                    if (not isinstance(attribute, DictionaryObject)
                            or attribute.get('/O') not in ('/Layout', '/List', '/Table', '/PrintField')):
                        raise _UnsupportedDocument('coverage.pdf_unsupported_structure_attributes')
            if isinstance(value, StreamObject):
                if '/F' in value or '/FFilter' in value or '/FDecodeParms' in value:
                    raise _UnsupportedDocument('coverage.pdf_active_or_external_content')
                raw_filters = value.get('/Filter', [])
                stream_filters = [raw_filters] if isinstance(raw_filters, NameObject) else raw_filters
                if not isinstance(stream_filters, (list, ArrayObject)) or len(stream_filters) > 2:
                    raise _UnsupportedDocument('coverage.pdf_stream_encoding')
                if any(item not in ('/FlateDecode', '/ASCII85Decode', '/ASCIIHexDecode', '/DCTDecode')
                       for item in stream_filters):
                    raise _UnsupportedDocument('coverage.pdf_stream_encoding')
                decoded = value.get_data()
                consumed += len(decoded)
                if len(decoded) > MAX_BYTES or consumed > available_bytes:
                    raise _UnsupportedDocument('coverage.pdf_decoded_byte_limit')
                if value.get('/Subtype') == '/Image':
                    width, height = value.get('/Width', 0), value.get('/Height', 0)
                    if (not isinstance(width, int) or not isinstance(height, int)
                            or min(width, height) <= 0 or max(width, height) > MAX_IMAGE_DIMENSION
                            or width * height > MAX_IMAGE_PIXELS):
                        raise _UnsupportedDocument('coverage.image_pixel_limit')
                    if '/DCTDecode' in stream_filters:
                        for text in _image_text(decoded, '.jpg'):
                            add_text(text)
                    elif '/FlateDecode' not in stream_filters and stream_filters:
                        raise _UnsupportedDocument('coverage.pdf_stream_encoding')
                    else:
                        bits = value.get('/BitsPerComponent', 1 if value.get('/ImageMask') else 0)
                        space = value.get('/ColorSpace', '/DeviceGray' if value.get('/ImageMask') else None)
                        channels = {'/DeviceGray': 1, '/DeviceRGB': 3, '/DeviceCMYK': 4}.get(str(space))
                        if isinstance(space, ArrayObject) and len(space) == 2 and space[0] == '/ICCBased':
                            channels = space[1].get_object().get('/N')
                        if bits not in (1, 2, 4, 8, 16) or channels not in (1, 3, 4):
                            raise _UnsupportedDocument('coverage.pdf_image_encoding')
                        if len(decoded) != ((width * channels * bits + 7) // 8) * height:
                            raise _UnsupportedDocument('coverage.invalid_image')
                elif value.get('/Type') == '/Metadata':
                    try:
                        xml = decoded.decode('utf-8-sig')
                        if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', xml, re.I):
                            raise ValueError()
                        ET.fromstring(xml)
                    except (UnicodeError, ValueError, ET.ParseError):
                        raise _UnsupportedDocument('coverage.pdf_metadata_encoding') from None
                    add_text(html.unescape(xml))
                else:
                    reference = getattr(value, 'indirect_reference', None)
                    role = roles.get((reference.generation, reference.idnum)) if reference else None
                    if role == '/FontFile2':
                        if decoded[:4] not in (b'\x00\x01\x00\x00', b'true', b'OTTO'):
                            raise _UnsupportedDocument('coverage.pdf_font_encoding')
                    elif role == '/FontFile3':
                        if value.get('/Subtype') not in ('/Type1C', '/CIDFontType0C', '/OpenType'):
                            raise _UnsupportedDocument('coverage.pdf_font_encoding')
                    elif role == '/ICC':
                        _validate_icc(decoded)
                    elif role not in ('/Contents', '/ToUnicode') and value.get('/Subtype') != '/Form':
                        raise _UnsupportedDocument('coverage.pdf_unclassified_stream')
                    if role == '/Contents' or value.get('/Subtype') == '/Form':
                        operations = ContentStream(value, reader).operations
                        count += len(operations)
                        if count > MAX_PDF_NODES:
                            raise _UnsupportedDocument('coverage.pdf_structure_limit')
                        if any(operator == b'INLINE IMAGE' for _, operator in operations):
                            raise _UnsupportedDocument('coverage.pdf_inline_image')
                    # Supplementary printable-stream scan; page extraction handles
                    # encoded text. Binary font programs are not interpreted.
                    add_text('\n'.join(match.decode('latin-1') for match in re.findall(rb'[\x20-\x7e]{4,}', decoded)))
            for key, child in value.items():
                walk(key, depth + 1)
                walk(child, depth + 1)
        elif isinstance(value, (list, ArrayObject)):
            for child in value:
                walk(child, depth + 1)
        elif isinstance(value, NameObject):
            if value in denied_names:
                raise _UnsupportedDocument('coverage.pdf_active_or_external_content')
            add_text(str(value))
        elif isinstance(value, TextStringObject):
            add_text(str(value))
        elif isinstance(value, ByteStringObject):
            for encoding in ('latin-1', 'utf-16-be', 'utf-16-le'):
                add_text(bytes(value).decode(encoding, errors='replace'))

    walk(reader.trailer)
    # Include unreferenced objects, so hidden metadata or active content cannot
    # obtain clear status merely by being absent from the visible page tree.
    for generation, number in objects:
        walk(IndirectObject(number, generation, reader))
    position = 0
    while position < len(pending):
        walk(pending[position].get_object())
        position += 1
    if not 0 < len(reader.pages) <= MAX_PDF_PAGES:
        raise _UnsupportedDocument('coverage.pdf_page_limit')
    has_text = False
    for page in reader.pages:
        text = page.extract_text()
        if not isinstance(text, str):
            raise _UnsupportedDocument('coverage.pdf_text_extraction')
        if text.strip():
            has_text = True
        elif page.get('/Contents') is not None or page.get('/Resources', {}).get('/XObject'):
            raise _UnsupportedDocument('coverage.pdf_image_only_or_unextractable_page')
        add_text(text)
    if not has_text:
        raise _UnsupportedDocument('coverage.pdf_image_only_or_unextractable_page')
    reports = [scan_bytes(text, 'extracted.txt') for text in texts]
    findings = []
    for index, report in enumerate(reports):
        for row in report['findings']:
            row['location']['member_indices'].insert(0, index)
            findings.append(row)
            if len(findings) >= MAX_FINDINGS:
                break
        if len(findings) >= MAX_FINDINGS:
            break
    return {'findings': findings, 'complete': len(findings) < MAX_FINDINGS and all(report['coverage']['complete'] for report in reports),
            'decoded_bytes': consumed, 'objects_inspected': len(objects) + len(reader.pages)}


def _inspect_pdf(body, available_bytes):
    """Parser CPU/memory isolation is required, never silently bypassed."""
    try:
        worker = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()),
                                 '--bounded-pdf-worker', str(available_bytes)], input=body,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=PDF_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        raise _UnsupportedDocument('coverage.pdf_worker_timeout') from None
    except OSError:
        raise _UnsupportedDocument('coverage.pdf_worker_unavailable') from None
    if worker.returncode == 91:
        raise _UnsupportedDocument('coverage.pdf_worker_memory_limit')
    if worker.returncode or len(worker.stdout) > 256 * 1024:
        raise _UnsupportedDocument('coverage.pdf_worker_resource_or_parse_failure')
    try:
        report = json.loads(worker.stdout)
    except (ValueError, UnicodeError):
        raise _UnsupportedDocument('coverage.pdf_worker_protocol') from None
    if 'error' in report:
        raise _UnsupportedDocument(report['error'])
    return report


def _pdf_worker_main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (10, 11))
        if sys.platform != 'darwin':
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        # macOS has no enforceable address-space rlimit. The worker can inspect
        # its own high-water RSS without privileged process inspection. This is
        # a watchdog, not a hard allocation cap; byte/node limits still apply.
        import threading
        import time
        def memory_watchdog():
            while True:
                resident = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                if sys.platform != 'darwin':
                    resident *= 1024
                if resident > 512 * 1024 * 1024:
                    os._exit(91)
                time.sleep(0.1)
        threading.Thread(target=memory_watchdog, daemon=True).start()
        available = min(int(sys.argv[2]), MAX_TOTAL_BYTES)
        if available <= 0:
            raise _UnsupportedDocument('coverage.pdf_decoded_byte_limit')
        body = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise _UnsupportedDocument('coverage.byte_or_depth_limit')
        report = _pdf_worker(body, available)
    except _UnsupportedDocument as error:
        report = {'error': str(error)}
    except (ImportError, OSError):
        report = {'error': 'coverage.pdf_resource_isolation_unavailable'}
    except Exception as error:
        report = {'error': ('coverage.pdf_decoded_byte_limit' if type(error).__name__ == 'LimitReachedError'
                            else 'coverage.invalid_pdf')}
    print(json.dumps(report, sort_keys=True))
    return 0


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

    def inspect(body, name, location, depth, office_media=False):
        if depth > MAX_DEPTH or len(body) > MAX_BYTES or budget['bytes'] + len(body) > MAX_TOTAL_BYTES:
            finding('coverage.byte_or_depth_limit', 'COVERAGE', location, unsupported=True)
            return
        budget['bytes'] += len(body)
        budget['members'] += 1
        if budget['members'] > MAX_MEMBERS:
            finding('coverage.member_limit', 'COVERAGE', location, unsupported=True)
            return
        result['coverage']['objects_inspected'] += 1
        format_path = PurePosixPath(name.replace('\\', '/'))
        suffix = format_path.suffix.lower()
        # OPC/OOXML relationship parts are XML, including the extension-only
        # root member _rels/.rels (whose pathlib suffix is empty). This does not
        # permit other Office members or bypass recursive archive inspection.
        relationship_xml = suffix == '.rels' or format_path.name.lower() == '.rels'
        if relationship_xml:
            suffix = '.xml'
        signals(name, location)
        if suffix == '.pdf' or body.startswith(b'%PDF-'):
            # Comments are not extracted as PDF text. Avoid interpreting xref
            # offset/generation columns as account numbers; objects are parsed below.
            for comment in re.findall(rb'(?m)^[ \t]*%[^\r\n]*', body):
                signals(comment.decode('latin-1'), location)
            try:
                report = _inspect_pdf(body, MAX_TOTAL_BYTES - budget['bytes'])
                budget['bytes'] += report['decoded_bytes']
                result['coverage']['objects_inspected'] += report['objects_inspected']
                if not report['complete']:
                    finding('coverage.pdf_incomplete_text_scan', 'COVERAGE', location, unsupported=True)
                for row in report['findings']:
                    finding(row['rule_id'], row['category'], location + row['location']['member_indices'],
                            row['location'].get('line'), unsupported=row['category'] == 'COVERAGE')
            except _UnsupportedDocument as error:
                finding(str(error), 'COVERAGE', location, unsupported=True)
            return
        if office_media and suffix in ('.png', '.jpg', '.jpeg'):
            try:
                for text in _image_text(body, suffix):
                    budget['bytes'] += len(text.encode('utf-8'))
                    if budget['bytes'] > MAX_TOTAL_BYTES:
                        raise _UnsupportedDocument('coverage.byte_or_depth_limit')
                    signals(text, location)
            except _UnsupportedDocument as error:
                finding(str(error), 'COVERAGE', location, unsupported=True)
            return
        if body.startswith(b'PK') or suffix == '.zip':
            try:
                with zipfile.ZipFile(io.BytesIO(body)) as archive:
                    members = archive.infolist()
                    office_root = {'.docx': 'word/document.xml', '.xlsx': 'xl/workbook.xml',
                                   '.pptx': 'ppt/presentation.xml'}.get(suffix)
                    if office_root and not {'[Content_Types].xml', '_rels/.rels', office_root}.issubset(archive.namelist()):
                        finding('coverage.invalid_office_package', 'COVERAGE', location, unsupported=True)
                    if len({info.filename for info in members}) != len(members):
                        finding('coverage.duplicate_archive_member', 'COVERAGE', location, unsupported=True)
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
                        passive_media = bool(office_root and (
                            re.fullmatch(r'(?:word|xl|ppt)/media/[^/]+\.(?:png|jpg|jpeg)', info.filename, re.I)
                            or re.fullmatch(r'docProps/thumbnail\.(?:png|jpg|jpeg)', info.filename, re.I)))
                        inspect(content, info.filename, at, depth + 1, office_media=passive_media)
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
        if suffix in ('.xml', '.svg', '.twb', '.tds'):
            # HTMLParser below is intentionally tolerant for HTML; relationship
            # XML must also be well-formed. DTD/entity declarations are outside
            # this supported part format and are never expanded or fetched.
            if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I):
                finding('coverage.unsupported_xml_declaration', 'COVERAGE', location, unsupported=True)
                return
            try:
                ET.fromstring(text)
            except (ET.ParseError, ValueError):
                finding('coverage.invalid_xml', 'COVERAGE', location, unsupported=True)
                return
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
    raise SystemExit(_pdf_worker_main() if len(sys.argv) == 3 and sys.argv[1] == '--bounded-pdf-worker' else main())
