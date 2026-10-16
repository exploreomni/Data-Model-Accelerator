"""Bounded, non-executing dbt upgrade assessment from already inventoried text.

Declarations are not installed-runtime observations. This module never imports
dbt, executes Jinja, reads profiles, fetches packages or authenticates a user.
"""
import hashlib
import json
import re
from pathlib import PurePosixPath

UPGRADE_DOC = 'https://docs.getdbt.com/docs/dbt-versions/dbt-upgrade/upgrading-to-v2'
MAX_FINDINGS = 200
VERSION = re.compile(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?\Z')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _constraint_accepts(value, target):
    """Evaluate only simple released-version intersections; unknown stays unknown."""
    if not re.fullmatch(r'\d+\.\d+\.\d+', target):
        return None
    if isinstance(value, str):
        values = value.split(',')
    elif isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        values = [p for v in value for p in v.split(',')]
    else:
        return None
    version = tuple(map(int, target.split('.')))
    tests = []
    for part in values:
        match = re.fullmatch(r'\s*(>=|<=|!=|==|=|>|<)?\s*(\d+)\.(\d+)\.(\d+)\s*', part)
        if not match:
            return None
        operator, *digits = match.groups()
        other = tuple(map(int, digits))
        tests.append({'<': version < other, '>': version > other, '<=': version <= other,
                      '>=': version >= other, '!=': version != other,
                      '=': version == other, '==': version == other, None: version == other}[operator])
    return all(tests) if tests else None


def assess_texts(texts, selection=None, warehouse=None):
    """Assess a selected snapshot; output contains locators, never source values."""
    from dbt_runtime import runtime_contract, validate_selection
    if not isinstance(texts, dict) or len(texts) > 20000:
        raise ValueError('dbt.compatibility_input_limit')
    if any(not isinstance(p, str) or not isinstance(t, str) for p, t in texts.items()):
        raise ValueError('dbt.compatibility_text_required')
    total = 0
    for path, text in texts.items():
        p = PurePosixPath(path)
        if not path or p.is_absolute() or '..' in p.parts or str(p) != path or '\\' in path or ':' in path or any(ord(c) < 32 for c in path):
            raise ValueError('dbt.compatibility_unsafe_path')
        size = len(text.encode('utf-8'))
        total += size
        if size > 10 * 1024 * 1024 or total > 100 * 1024 * 1024:
            raise ValueError('dbt.compatibility_byte_limit')
    selected = validate_selection(selection) if selection is not None else None
    contract = runtime_contract(selected, warehouse=warehouse) if selected else None
    declarations, findings, hashes = [], [], []
    truncated = False

    def finding(code, path, detail, action, severity='review_required'):
        nonlocal truncated
        if len(findings) >= MAX_FINDINGS:
            truncated = True
            return
        findings.append({'code': code, 'path': path, 'severity': severity,
                         'summary': detail, 'next_action': action})

    target_version = selected['version'] if selected else None
    target_v2 = bool(selected and selected['distribution'] in ('dbt', 'dbt_oss'))
    for path, text in sorted(texts.items()):
        hashes.append({'path': path, 'sha256': hashlib.sha256(text.encode()).hexdigest()})
        name = path.rsplit('/', 1)[-1].lower()
        if name == 'manifest.json':
            try:
                def pairs(items):
                    out = {}
                    for key, val in items:
                        if key in out:
                            raise ValueError('duplicate')
                        out[key] = val
                    return out
                manifest = json.loads(text, object_pairs_hook=pairs,
                                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
                meta = manifest.get('metadata', {}) if isinstance(manifest, dict) else {}
                if not isinstance(meta, dict):
                    raise ValueError('metadata')
                version = meta.get('dbt_version')
                schema = meta.get('dbt_schema_version')
                declarations.append({'path': path, 'version': version if isinstance(version, str) and VERSION.fullmatch(version) else None,
                                     'manifest_v12': schema == 'https://schemas.getdbt.com/dbt/manifest/v12.json',
                                     'distribution': 'unknown', 'assurance': 'artifact_declaration_only'})
                if selected and isinstance(version, str) and VERSION.fullmatch(version) and version != target_version:
                    finding('dbt.runtime_difference', path, 'Source-declared version differs from the selected target.',
                            'Review an explicit upgrade; do not replace the source runtime.', 'info')
            except (ValueError, RecursionError):
                finding('dbt.invalid_manifest', path, 'Manifest declarations could not be read.', 'Obtain a valid bounded native artifact.')
        if name in ('dbt_project.yml', 'dbt_project.yaml') and 'require-dbt-version' in text:
            accepted = None
            if target_version:
                try:
                    from source_adapters.base import read_yaml
                    # Reuse the adapter YAML boundary (duplicate keys, tags and aliases).
                    config = read_yaml(text)
                    accepted = _constraint_accepts(config.get('require-dbt-version'), target_version) if isinstance(config, dict) else None
                except (ImportError, ValueError, TypeError, AttributeError):
                    accepted = None
            if accepted is not True:
                finding('dbt.version_constraint', path,
                        'The declared version range excludes the selected target.' if accepted is False else 'The version range needs native compatibility review.',
                        'Review require-dbt-version and package constraints; keep the original configuration.')
        if name in ('packages.yml', 'packages.yaml', 'dependencies.yml', 'dependencies.yaml', 'package-lock.yml'):
            finding('dbt.package_review', path, 'Package compatibility and dependency closure require review.',
                    'Use locked dependencies; review package code and bundled agent skills before an authorized installation.')
        rules = [
            ('dbt.hooks_review', r'\b(?:pre[-_]hook|post[-_]hook|on[-_]run[-_]start|on[-_]run[-_]end)\b',
             'Hooks may execute code during native validation.', 'Review hooks and use an explicitly qualified execution route.'),
            ('dbt.macro_review', r'{%[-+]?\s*macro\b|\brun_query\s*\(|\badapter\.(?:dispatch|get_|execute)',
             'Macro behavior needs engine and adapter compatibility evidence.', 'Inspect only referenced macro dependencies; never execute them during discovery.'),
        ]
        if target_v2:
            rules += [
                ('dbt.deprecated_selector', r'--models?\b|(?:^|\s)-m(?:\s|$)',
                 'Legacy selection flags need review for v2.', 'Prepare a reviewed --select replacement without changing selection scope.'),
                ('dbt.partial_parse_flag', r'--(?:no-)?partial-parse\b',
                 'v1 partial-parse flags do not establish fresh v2 parsing.', 'Use the selected engine command builder and fresh isolated evidence directories.'),
                ('dbt.analysis_alias', r'static_analysis\s*[:=]\s*[\"\x27]?(?:on|unsafe)\b',
                 'A deprecated static-analysis value is present.', 'Review migration to strict and verify the effective mode after authentication.'),
                ('dbt.package_skills', r'\bai_provider\s*:',
                 'Package installation may write agent instructions.', 'Review package skills as untrusted input; preserve existing host instructions.'),
            ]
        for code, pattern, detail, action in rules:
            if re.search(pattern, text, re.M):
                finding(code, path, detail, action)
    if selected is None:
        finding('dbt.target_runtime_unselected', None, 'The target dbt distribution and exact version have not been selected.',
                'Retain the existing project; select a runtime before native execution.', 'info')
    return {'schema_version': 1, 'kind': 'dbt_compatibility_assessment',
            'selection': selected, 'runtime_contract': contract, 'source_declarations': declarations,
            'observed_runtime': None, 'observed_runtime_status': 'not_probed',
            'findings': findings, 'coverage': {'files': len(hashes), 'findings_truncated': truncated},
            'snapshot_sha256': _digest(hashes),
            'assessment_sha256': _digest({'files': hashes, 'selection': selected, 'contract': contract, 'findings': findings}),
            'execution_performed': False, 'native_validation': 'not_run', 'warehouse_validation': 'not_run',
            'strict_analysis': 'not_run', 'business_acceptance': 'not_assessed',
            'documentation': UPGRADE_DOC}


def setup_guidance(selection):
    """Reviewable setup hints, not executable descriptors or installation consent."""
    from dbt_runtime import validate_selection
    selected = validate_selection(selection)
    package = {'dbt_core': 'dbt-core', 'dbt': 'dbt', 'dbt_oss': 'dbt-oss'}[selected['distribution']]
    return {'commands': ['python3 -m venv /absolute/new/isolated-dbt-environment',
                         '/absolute/new/isolated-dbt-environment/bin/python -m pip install ' + package + '==' + selected['version']],
            'prerequisites': ['Choose an isolated environment; do not replace the source runtime.',
                              'Provision and pin the selected adapter/driver separately; review any first-run download.',
                              'Keep profiles and authentication outside the source and delivery.',
                              'Use the reviewed execution request and explicit --execute for native validation.'],
            'execution_authorized': False}
