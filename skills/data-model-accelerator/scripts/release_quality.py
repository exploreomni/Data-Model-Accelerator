"""Bind static lint evidence to a frozen handoff; never grant deployment authority."""
import copy
from pathlib import Path

from ae_common import load_json, require, hash_file
from deployment_authority import canonical_path


def quality_target(plan):
    target = plan.get('review_target', plan['target'])
    return {'framework': target['framework'], 'warehouse': target['warehouse'],
            'context_sha256': plan['bindings']['context_sha256']}


def bind_quality(reference, artifact_root, handoff, target):
    """Check current evidence and require coverage of every implementation input.

    The report is a content-bound local observation, not an authenticated issuer.
    A live approver must independently confirm its provenance and required native
    checks before signing. No executable path is accepted from the report.
    """
    from lint_delivery import verify_report
    require(type(reference) is dict and set(reference) == {'report_path', 'manifest_path'},
            'Quality requires report_path and manifest_path')
    report_path, manifest_path = (canonical_path(reference[k]) for k in ('report_path', 'manifest_path'))
    report, manifest = load_json(report_path), load_json(manifest_path)
    verified = verify_report(report, artifact_root, target=target, manifest=manifest)
    inventory = {item['path']: item['sha256'] for item in manifest['files']}
    review = load_json(handoff['review_path'])
    implementation = {item['path'] for item in review['artifacts'] if item['category'] == 'implementation'}
    # SQL cannot evade the denominator by being relabelled documentation.
    selected = {item['path']: item['sha256'] for item in handoff['artifacts']}
    required = {path for path in selected if path in implementation or Path(path).suffix.lower() in {'.sql', '.sqlx', '.jinja', '.j2', '.py'}}
    require(bool(required), 'Release has no implementation scope for lint coverage')
    require(all(inventory.get(path) == selected[path] for path in required),
            'Lint coverage omits or changes a prepared implementation input')
    return {'status': 'verified_static', 'report_path': str(report_path), 'manifest_path': str(manifest_path),
            'report_sha256': hash_file(report_path), 'manifest_sha256': hash_file(manifest_path),
            'target': copy.deepcopy(target), 'coverage': verified,
            'assurance': 'Static SQL/configuration only; no native validity, data accuracy or deployment authority.'}


def verify_quality(plan, handoff):
    quality = plan.get('quality')
    require(type(quality) is dict and quality.get('status') == 'verified_static',
            'A complete, current lint report is required for live release')
    actual = bind_quality({k: quality[k] for k in ('report_path', 'manifest_path')},
                          plan['artifact_root'], handoff, quality_target(plan))
    require(actual == quality, 'Lint evidence changed; prepare and review a new plan')
    return actual


def quality_evidence(plan):
    """Produce a small public summary, not raw logs, paths or authentication."""
    report = load_json(plan['quality']['report_path'])
    counts = {key: 0 for key in ('checked', 'failed', 'skipped', 'unsupported', 'pending', 'unknown', 'not_applicable')}
    for file in report['files']:
        status = file.get('status', 'unknown')
        if status in {'checked', 'failed'}:
            counts['checked'] += 1
            counts['failed'] += int(status == 'failed')
        else:
            counts[status if status in counts else 'unknown'] += 1
    summary = 'Static SQL and configuration checks.'
    exceptions = report.get('style_exceptions', {})
    if exceptions.get('used_count', 0):
        summary += (' Includes %s exact-file convention policy exceptions covering %s raw findings; '
                    'see the lint report for reasons. This is not a zero-finding result or human approval.') % (
                        exceptions['used_count'], exceptions['excepted_finding_count'])
    check = dict(id='code_conventions', status='pass' if report['status'] == 'passed' else 'fail',
                 scope='static', unit='files', total=len(report['files']), summary=summary,
                 next_action='Complete framework, native warehouse and independent data validation.', gaps=[], **counts)
    checks = [check]
    for lane, scope, action in (
        ('project_validity', 'framework', 'Run the selected framework checks in the reviewed runtime.'),
        ('warehouse_validation', 'warehouse', 'Run scoped native checks against the selected development destination.'),
        ('data_accuracy', 'independent_data', 'Reconcile grain, fanout, source metrics, access and semantic behavior independently.'),
    ):
        checks.append(dict(id=lane, status='unknown', scope=scope, unit='checks', total=None,
                           summary='No evidence for this lane is included in the static lint report.',
                           next_action=action, gaps=['Required scope and evidence remain to be established.'],
                           **{key: 0 for key in counts}))
    return {'schema_version': 1, 'kind': 'quality_evidence',
            'context_sha256': plan['bindings']['context_sha256'],
            'target': {k: quality_target(plan)[k] for k in ('framework', 'warehouse')}, 'checks': checks}
