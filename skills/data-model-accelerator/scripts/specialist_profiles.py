"""Portable source profiles and explicit host-role aliases; no agent execution."""
import hashlib
from pathlib import Path


SOURCES = frozenset({'bigquery', 'periscope', 'looker', 'tableau', 'powerbi',
                    'hex', 'domo', 'sigma', 'webfocus', 'snowflake', 'redshift',
                    'clickhouse', 'motherduck', 'databricks', 'dbt', 'coalesce', 'fabric'})
ROLES = frozenset({'source_specialist', 'catalogue_specialist', 'warehouse_architect',
                  'analytics_engineer', 'semantic_modeler', 'validation_analyst',
                  'independent_reviewer', 'documentation_specialist', 'migration_project_manager'})
ROLE_ALIASES = {'semantic_architect': 'semantic_modeler',
                'independent_qa': 'independent_reviewer',
                'omni_modeler': 'semantic_modeler'}
PROFILE_ROOT = Path(__file__).resolve().parents[1] / 'references' / 'specialists'
MAX_PROFILE_BYTES = 16384
DISPOSITION_DESTINATIONS = {
    'move_upstream': {'warehouse'}, 'retain_semantic': {'semantic'},
    'retain_presentation': {'presentation'}, 'split': {'split'},
    'unresolved': {'unresolved'},
    'reuse_existing': {'warehouse', 'semantic', 'presentation', 'unresolved'},
    'consolidate_candidate': {'unresolved'}, 'retire_candidate': {'unresolved'},
}


def disposition_matches(disposition, destination):
    """Check vocabulary consistency only, not business correctness or approval."""
    return (isinstance(disposition, str) and isinstance(destination, str)
            and destination in DISPOSITION_DESTINATIONS.get(disposition, set()))


def context_role(role):
    """Resolve context transport names without renaming the logical task owner."""
    if not isinstance(role, str):
        raise ValueError('Unsupported specialist role')
    canonical = ROLE_ALIASES.get(role, role)
    if canonical not in ROLES:
        raise ValueError('Unsupported specialist role')
    return canonical


def load_profile(source):
    """Read only the selected installed profile; never a user-supplied path."""
    if not isinstance(source, str) or source not in SOURCES:
        raise ValueError('Unsupported specialist source profile')
    path = PROFILE_ROOT / (source + '.md')
    if PROFILE_ROOT.is_symlink() or path.is_symlink():
        raise ValueError('Specialist profile must not be redirected')
    with path.open('rb') as stream:
        raw = stream.read(MAX_PROFILE_BYTES + 1)
    if not raw or len(raw) > MAX_PROFILE_BYTES:
        raise ValueError('Specialist profile exceeds its bounded size')
    return {'source_type': source, 'role': 'source_specialist',
            'path': 'references/specialists/' + source + '.md',
            'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
            'text': raw.decode('utf-8')}


def profile_binding(source):
    return {key: value for key, value in load_profile(source).items() if key != 'text'}
