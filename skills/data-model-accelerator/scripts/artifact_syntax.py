"""Syntax-only checks for declared YAML/JSON artifacts and native Omni filenames.

Does not validate an Omni capability, execute templates, or change candidate files.
"""
from pathlib import Path

from authoring_evidence import finding
from authoring_provenance import _read
from source_adapters.base import read_json, read_yaml


def check_structured_artifacts(root, paths):
    result = []
    for path in paths:
        suffix = Path(path).suffix.lower()
        if suffix not in {'.json', '.yaml', '.yml', '.view', '.topic'} and Path(path).name not in {'model', 'relationships'}:
            continue
        kind = 'json' if suffix == '.json' else 'yaml'
        try:
            text, _, _ = _read(Path(root), path)
        except (ValueError, OSError, UnicodeError):
            result.append(finding(kind + '_syntax_unreadable', 'unsupported', path=path))
            continue
        try:
            (read_json if kind == 'json' else read_yaml)(text)
            result.append(finding(kind + '_syntax_checked', 'passed', path=path))
        except ImportError:
            result.append(finding(kind + '_syntax_parser_unavailable', 'unsupported', path=path))
        except (ValueError, OSError, UnicodeError, RecursionError) as error:
            # Syntactically valid constructs outside this bounded loader remain
            # unsupported, never silently reported as invalid vendor syntax.
            unsupported = isinstance(error, RecursionError) or str(error) in {
                'source.yaml_alias', 'source.structure_limit', 'source.byte_limit', 'source.non_json_value'}
            result.append(finding(kind + ('_syntax_unsupported' if unsupported else '_syntax_invalid'),
                                  'unsupported' if unsupported else 'failed', path=path))
    return result
