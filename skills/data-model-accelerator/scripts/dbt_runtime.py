"""Explicit dbt runtime capabilities; discovery never executes or downloads.

Engine/distribution identity comes from separately pinned runtime observations,
never from a manifest schema URI. Qualification is narrower than vendor support.
Primary contracts reviewed 2026-10-16: docs.getdbt.com/docs/local/install-dbt,
docs/dbt-versions/dbt-upgrade/upgrading-to-v2, blog/comparing-dbt-and-dbt-oss,
and reference/artifacts/manifest-json.
"""
import copy
from email.parser import Parser
import hashlib
from pathlib import Path
import platform
import re

DISTRIBUTIONS = ('dbt_core', 'dbt', 'dbt_oss')
FEATURES = ('sql_analysis', 'native_lint', 'information_schema', 'checks',
            'batch_tests', 'model_freshness', 'docs_v2', 'incremental', 'snapshots',
            'unit_tests', 'contracts', 'model_versions', 'dbt_state',
            'local_unit_tests', 'multi_adapter')
MANIFEST_SCHEMA = 'https://schemas.getdbt.com/dbt/manifest/v12.json'
RESULTS_SCHEMA = 'https://schemas.getdbt.com/dbt/run-results/v6.json'
PINNED_VERSIONS = {'dbt_core': '1.12.4', 'dbt': '2.0.8', 'dbt_oss': '2.0.8'}
_SEMVER = re.compile(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?\Z')


def validate_selection(selection):
    """Validate an exact selection without guessing installed runtime state."""
    if (type(selection) is not dict or not {'distribution', 'version'} <= set(selection)
            or set(selection) - {'distribution', 'version', 'analysis_mode', 'features'}):
        raise ValueError('dbt runtime requires distribution and exact version')
    distribution, version = selection['distribution'], selection['version']
    if not isinstance(distribution, str) or distribution not in DISTRIBUTIONS:
        raise ValueError('Unsupported dbt distribution')
    if not isinstance(version, str) or not _SEMVER.fullmatch(version):
        raise ValueError('dbt runtime version must be an exact semantic version')
    mode = selection.get('analysis_mode', 'baseline' if distribution == 'dbt' else 'none')
    if mode not in ('none', 'baseline', 'strict'):
        raise ValueError('Unsupported dbt analysis mode')
    features = selection.get('features', [])
    if (type(features) is not list or any(type(f) is not str or f not in FEATURES for f in features)
            or len(features) != len(set(features))):
        raise ValueError('Unknown or duplicate dbt runtime feature')
    return {'distribution': distribution, 'version': version, 'analysis_mode': mode,
            'features': list(features)}


def runtime_contract(selection, warehouse=None):
    """Return documented capabilities and bounded qualification independently."""
    selected = validate_selection(selection)
    dist, version, mode = (selected[k] for k in ('distribution', 'version', 'analysis_mode'))
    if warehouse is not None and (type(warehouse) is not str or not warehouse):
        raise ValueError('Invalid dbt warehouse')
    v2 = dist in ('dbt', 'dbt_oss')
    pinned = version == PINNED_VERSIONS[dist]
    documented = pinned
    features = {}
    for feature in FEATURES:
        available = documented and (v2 or feature in {
            'incremental', 'snapshots', 'unit_tests', 'contracts', 'model_versions', 'dbt_state'})
        if dist == 'dbt_oss' and feature in ('sql_analysis', 'native_lint'):
            available = False
        status = 'documented_unqualified' if available else 'unsupported' if documented else 'unassessed_version'
        reason = ('Documented feature; not qualified by the bounded execution/evidence lane.'
                  if available else 'Unavailable for this selected distribution/version contract.')
        if available and feature in ('local_unit_tests', 'multi_adapter'):
            status, reason = 'experimental', 'Experimental opt-in behavior is outside bundled execution qualification.'
        if available and feature == 'sql_analysis' and mode == 'strict':
            status, reason = 'requires_login', 'Strict analysis requires login and may fall back to baseline; no login is performed.'
        features[feature] = {'documented': available, 'status': status, 'qualified': False, 'reason': reason}
    qualified = pinned and ((dist == 'dbt_core' and warehouse in ('duckdb', 'snowflake')) or
                            (v2 and warehouse == 'duckdb'))
    reason = ('Legacy Core 1.12.4 full-root-project evidence contract; target execution still requires authorization.'
              if qualified and not v2 else
              'Native 2.0.8 local DuckDB parse/build contract; plain models, seeds and data tests only.'
              if qualified else 'Native execution/evidence qualification is not established for this exact runtime and warehouse.')
    if mode != ('baseline' if dist == 'dbt' else 'none'):
        qualified = False
        reason = 'Requested analysis mode is outside the qualified runtime contract.'
    if selected['features']:
        qualified = False
        reason = 'Requested feature execution needs separate qualification; declarations do not authorize commands.'
    qualification = {'status': 'qualified' if qualified else 'unqualified', 'qualified': qualified,
                     'scope': 'full_root_project', 'reason': reason}
    return {'selection': selected, 'distribution': dist, 'engine': 'rust' if v2 else 'python',
            'package': {'dbt_core': 'dbt-core', 'dbt': 'dbt', 'dbt_oss': 'dbt-oss'}[dist],
            'documented': documented, 'pinned_version': PINNED_VERSIONS[dist],
            'warehouse': warehouse,
            'adapter_lifecycle': ('CLI only; local qualification' if warehouse == 'duckdb' and v2 else
                                  'Private beta' if warehouse == 'clickhouse' and v2 else
                                  'documented' if warehouse in ('snowflake', 'databricks', 'bigquery', 'redshift') or
                                      warehouse == 'duckdb' and not v2 else
                                  'unqualified; not inferred from another adapter'),
            'artifact_schemas': {'manifest': MANIFEST_SCHEMA, 'run_results': RESULTS_SCHEMA},
            'qualification': qualification, 'execution': copy.deepcopy(qualification),
            'features': features, 'probe_performed': False,
            'limitations': ['Schema versions do not identify an engine or distribution.',
                            'Runtime selection does not prove installation, authentication, execution or approval.']}


def runtime_argv(executable, verb, project, profiles, profile, target, output, selection):
    """Construct only the reviewed parse/build commands; never execute them."""
    selected = validate_selection(selection)
    if verb not in ('parse', 'build'):
        raise ValueError('Only parse/build are qualified runtime commands')
    if selected['distribution'] == 'dbt_core':
        args = [str(executable), '--no-use-colors', '--no-send-anonymous-usage-stats', '--no-partial-parse', verb]
    else:
        args = [str(executable), verb, '--no-send-anonymous-usage-stats', '--no-manage-state']
        if verb == 'build':
            args += ['--static-analysis', 'off' if selected['analysis_mode'] == 'none' else selected['analysis_mode']]
    return args + ['--project-dir', str(project), '--profiles-dir', str(profiles), '--profile', profile,
                   '--target', target, '--target-path', str(output), '--log-path', str(output / 'logs')]


def observed_version(text, selection):
    """Match exact native distribution/version output, not artifact metadata."""
    selected = validate_selection(selection)
    label = {'dbt': 'dbt', 'dbt_oss': 'dbt-oss'}.get(selected['distribution'])
    if label is None:
        raise ValueError('Versioned native probing currently requires a v2 distribution')
    if text.strip() != label + ' ' + selected['version']:
        raise ValueError('Observed dbt distribution/version differs from the selected runtime')
    return {'distribution': selected['distribution'], 'version': selected['version'],
            'version_output': text.strip()}


def _file_pin(path):
    path = Path(path).absolute()
    if path.resolve(strict=True) != path or any(p.is_symlink() for p in (path,) + tuple(path.parents)):
        raise ValueError('Runtime files must have canonical paths')
    if not path.is_file() or path.stat().st_size > 1024 * 1024 * 1024:
        raise ValueError('Missing or oversized runtime file')
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(block)
    return {'path': str(path), 'sha256': sha.hexdigest()}


def runtime_identity(executable, selection):
    """Read-only identity for a separately installed v2 Python wheel/venv.

    Does not import the package, execute the binary or install anything. A caller
    must obtain these pins before authorization, then compare before and after
    execution. This associates bytes, not publisher authenticity or a sandbox.
    """
    selected = validate_selection(selection)
    if selected['distribution'] not in ('dbt', 'dbt_oss'):
        raise ValueError('Wheel identity requires an explicit v2 distribution')
    executable = Path(_file_pin(executable)['path'])
    if executable.stat().st_size > 64 * 1024:
        raise ValueError('Qualified executable must be the installed wheel entry point')
    lines = executable.read_text(encoding='utf-8').splitlines()
    if not lines or not lines[0].startswith('#!'):
        raise ValueError('Missing wheel interpreter')
    interpreter = Path(lines[0][2:])
    root = executable.parent.parent
    if interpreter.parent != executable.parent or interpreter.name not in ('python', 'python3', 'python3.12'):
        raise ValueError('Wheel interpreter must belong to the selected isolated runtime')
    sites = list((root / 'lib').glob('python*/site-packages'))
    if len(sites) != 1:
        raise ValueError('Runtime must contain one isolated site-packages directory')
    site = sites[0]
    metadata_name = ('dbt' if selected['distribution'] == 'dbt' else 'dbt_oss') + '-' + selected['version'] + '.dist-info'
    metadata_path = site / metadata_name / 'METADATA'
    _file_pin(metadata_path)
    if metadata_path.stat().st_size > 1024 * 1024:
        raise ValueError('Oversized package metadata')
    metadata = Parser().parsestr(metadata_path.read_text(encoding='utf-8'))
    expected_package = 'dbt' if selected['distribution'] == 'dbt' else 'dbt-oss'
    if metadata.get_all('Name') != [expected_package] or metadata.get_all('Version') != [selected['version']]:
        raise ValueError('Installed package metadata differs from runtime selection')
    files = [executable, interpreter.resolve(strict=True), root / 'pyvenv.cfg', metadata_path]
    package_files = sorted(p for p in (site / 'dbt').rglob('*') if p.is_file() and p.suffix in ('.py', '.pyc', '.so', '.pyd'))
    if not package_files or len(package_files) > 1000 or not any(p.name.startswith('_core.') for p in package_files):
        raise ValueError('Missing or unsupported native dbt implementation')
    files.extend(package_files)
    return {'distribution': selected['distribution'], 'version': selected['version'],
            'package': expected_package, 'files': [_file_pin(p) for p in files]}


def driver_contract(system=None, machine=None):
    """Pinned preinstalled DuckDB ADBC driver; this function never downloads."""
    key = (system or platform.system(), machine or platform.machine())
    entries = {
        ('Darwin', 'arm64'): ('aarch64-apple-darwin', 'dylib',
            '0094c4c34218fad716c6d88409d78c90b10a1cbcdb16675989a5ba4db550c95d',
            '4890e5b4a340aae7d5fc207d267b9ac78a1578abbc6eec9061a56d086fee93de'),
        ('Linux', 'x86_64'): ('x86_64-manylinux_2_17-linux-gnu', 'so',
            '23528e49435b97f2dfa924f5d19513849937e671bd392696ea26f3457f656556',
            'd7f30ef2ef4b813edb94ce82906329cc689672624a4161617ea33431040ce174'),
    }
    if key not in entries:
        raise ValueError('Native v2 driver/platform contract is unqualified')
    triplet, suffix, compressed, checksum = entries[key]
    filename = 'libadbc_driver_duckdb-1.5.4.' + suffix
    cache = 'Library/Caches' if key[0] == 'Darwin' else '.cache'
    return {'adapter': 'duckdb', 'version': '1.5.4', 'platform': '/'.join(key),
            'sha256': checksum, 'compressed_sha256': compressed,
            'cache_relative_path': cache + '/com.getdbt/adbc/' + triplet + '/' + filename,
            'download_url': 'https://public.cdn.getdbt.com/fs/adbc/duckdb/adbc_driver_duckdb-1.5.4-' + triplet + '.' + suffix + '.zst'}
