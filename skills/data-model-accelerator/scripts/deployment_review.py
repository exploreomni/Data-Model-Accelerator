#!/usr/bin/env python3
"""Export an offline deployment review without changing the prepared handoff.

The runner policy comes from DMA_RUNNER_POLICY. This command verifies current
bindings and optionally reads an authenticated local runner record; it never
submits, polls, approves, publishes or deploys. HTML downloads are requests only.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from ae_common import _json_bytes, load_json, require
from deployment_authority import canonical_path
import deployment_workflow as deployment
import delivery_portal as portal

REVIEW_FIELDS = ('schema_version', 'title', 'description', 'source_fingerprint', 'context_sha256',
                'target', 'models', 'relationships', 'changes', 'decisions', 'validation', 'artifacts', 'quality_checks', 'disclosure')
ARTIFACT_FIELDS = ('id', 'path', 'sha256', 'category', 'audiences', 'requires', 'description')


def _receipt_record(receipt, plan, policy_path):
    if receipt is None:
        return None
    # The supplied file locates a runner operation. Its status and claims are not
    # trusted: status() authenticates the current journal under installed policy.
    locator = load_json(canonical_path(receipt))
    require(isinstance(locator, dict) and isinstance(locator.get('operation_id'), str),
            'Receipt must identify a recorded runner operation_id')
    record = deployment.status(policy_path, locator['operation_id'])
    require(record.get('plan_sha256') == plan['plan_sha256'], 'Receipt belongs to a different deployment plan')
    require(record.get('target_sha256') == deployment.digest(plan['target'])
            and record.get('policy_sha256') == plan['policy_sha256'] and record.get('mode') == plan['mode'],
            'Receipt target, policy or mode differs from the reviewed plan')
    return record


def _public_bytes(value, private_paths):
    """Fail rather than silently redact bytes whose hashes are already reviewed."""
    deployment._assert_public(value)
    def inspect(item):
        if isinstance(item, str):
            require(not any(str(path) in item for path in private_paths),
                    'Deployment review contains an internal path; curate the source description')
        elif isinstance(item, list):
            for child in item:
                inspect(child)
        elif isinstance(item, dict):
            for key, child in item.items():
                inspect(key);inspect(child)
    inspect(value)
    return _json_bytes(value) + b'\n'


def export_review(planpath, policypath, outputdir, receipt=None):
    """Create a separate artifact root, extended review, offline page and ZIP.

    ``receipt`` is an optional JSON file containing an operation_id. The current
    local authenticated runner status is used instead of any supplied claims.
    Original handoff records and artifact bytes are never modified or re-pinned.
    The coordinator's _current() refreshes ordinary workflow drift assessment.
    """
    plan_path, policy_path = canonical_path(planpath), canonical_path(policypath)
    output = canonical_path(outputdir, exists=False)
    require(output.parent.is_dir() and not output.exists(), 'Choose a new output directory with an existing parent')
    plan = deployment.load_plan(plan_path)
    policy = deployment._current(plan, policy_path)
    state, handoff, bindings = deployment._handoff(plan['engagement_run'])
    require(bindings == plan['bindings'], 'Deployment review context changed')
    original_root = canonical_path(handoff['artifact_root'])
    private_paths = [original_root, canonical_path(state['inputs']['source']['path']),
                     canonical_path(plan['engagement_run']), policy_path, plan_path,
                     canonical_path(policy['state_root'], exists=False)]
    for root in private_paths:
        require(output != root and root not in output.parents, 'Deployment review output must be outside protected input and runner paths')
    require(handoff['audience'] == 'engineer', 'Deployment review requires an engineering handoff')
    original_review = load_json(handoff['review_path'])
    selected = portal.select_artifacts(original_review, original_root, handoff['audience'], handoff['deliverables'])
    record = _receipt_record(receipt, plan, policy_path)
    projection = deployment.review_projection(plan, record=record)
    semantic = state.get('answers', {}).get('semantic_target')
    if semantic:
        projection['target']['semantic_target'] = semantic
    # Versions and operations describe the frozen selected files, never a branch
    # label or inferred action from the browser.
    projection['plan']['files'] = [{'path':a['path'], 'sha256':a['sha256'],
                                    'version':plan['commit_sha'], 'operation':a['role']}
                                   for a in plan['selected_artifacts']]
    extended = {key:copy.deepcopy(original_review[key]) for key in REVIEW_FIELDS if key in original_review}
    extended['artifacts'] = [{key:copy.deepcopy(item[key]) for key in ARTIFACT_FIELDS if key in item}
                             for item in selected]
    names = {item['path'] for item in selected}
    ids = {item['id'] for item in selected}
    generated = {}
    def evidence(name, value, label):
        relative = 'deployment/' + name
        aid = 'deployment-review-' + label + '-' + plan['plan_sha256'][:12]
        require(relative not in names and aid not in ids, 'Deployment review artifact collides with the original handoff')
        body = _public_bytes(value, private_paths)
        if isinstance(value, str):
            body = value.encode('utf-8')
        digest = hashlib.sha256(body).hexdigest()
        generated[relative] = body
        extended['artifacts'].append({'id':aid, 'path':relative, 'sha256':digest, 'category':'validation',
                                      'audiences':['engineer'], 'description':'Sanitized deployment ' + label + '; reported display only.'})
        if state.get('answers', {}).get('migration_scope'):
            disclosure = extended.get('disclosure', {})
            classification = disclosure.get('generated_evidence', {}).get(label)
            require(type(classification) is dict, 'Generated deployment evidence needs a reviewed disclosure classification: ' + label)
            disclosure.setdefault('artifacts', {})[aid] = copy.deepcopy(classification)
        return aid, digest
    preview = {'schema_version':1, 'kind':'deployment_plan_review', 'request_only':True,
               'plan_sha256':plan['plan_sha256'], 'context_sha256':bindings['context_sha256'],
               'handoff_manifest_sha256':bindings['handoff_manifest_sha256'],
               'target':projection['target'], 'plan':copy.deepcopy(projection['plan']),
               'authority':'Plan review only. No approval, submission or execution is conferred.'}
    aid, sha = evidence('deployment-plan-review.json', preview, 'plan')
    projection['plan'].update(evidence_artifact_id=aid, evidence_sha256=sha)
    if record:
        summary = copy.deepcopy(projection['receipts'][0])
        receipt_preview = {'schema_version':1, 'kind':'deployment_receipt_review', 'plan_sha256':plan['plan_sha256'],
                           'context_sha256':bindings['context_sha256'], 'operation_id':record['operation_id'],
                           'runner_record_sha256':deployment.digest(record), 'result':summary,
                           'authority':'Current runner journal checked at export; offline display remains reported, not authenticated.'}
        aid, sha = evidence('deployment-receipt-review.json', receipt_preview, 'receipt')
        projection['receipts'][0].update(evidence_artifact_id=aid, sha256=sha)
    if plan.get('quality'):
        from release_quality import quality_evidence
        quality = quality_evidence(plan)
        lint_report = load_json(plan['quality']['report_path'])
        evidence('lint-manifest.json', lint_report['manifest'], 'lint-manifest')
        evidence('lint-target.json', lint_report['target'], 'lint-target')
        evidence('sqlfluff-config.txt', lint_report['configuration'], 'lint-configuration')
        public_findings = {'schema_version': 1, 'kind': 'lint_findings_review',
            'source_report_sha256': plan['quality']['report_sha256'], 'status': lint_report['status'],
            'coverage': lint_report['coverage'], 'findings': lint_report['findings'],
            'modeling_findings': lint_report['modeling_findings'],
            'files': [{k: item[k] for k in ('path', 'sha256', 'status', 'check_type', 'findings')} for item in lint_report['files']],
            'limitations': lint_report['limitations']}
        evidence('lint-findings.json', public_findings, 'lint-findings')
        guide = '# Static lint findings\n\nSQLFluff ' + lint_report['runtime']['sqlfluff_version'] + ' checked the declared scope. Native project, warehouse and data acceptance remain separate.\n\n'
        for finding in lint_report['modeling_findings']:
            guide += '- ' + finding['code'] + ': ' + finding['message'] + '\n'
        guide += '\nUse the included lint manifest, target and configuration with the accelerator lint runner against the approved candidate root. Paths in the lint manifest are relative to that root. The ZIP organizes files into audience folders; reconstruct original relative paths using its package manifest before rerunning. Native compilation/rendering must be separately reviewed. See the accelerator linting guide for commands.\n'
        evidence('LINT_README.md', guide, 'lint-guide')
        aid, sha = evidence('quality-evidence.json', quality, 'quality')
        prior = {check['id']: check for check in extended.get('quality_checks', [])
                 if check.get('evidence_artifact_id') in ids}
        merged = []
        for check in quality['checks']:
            existing = prior.get(check['id'])
            # A new static check cannot erase a different lane's evidence, or
            # dismiss a previously reported static failure under other rules.
            if existing and (check['id'] != 'code_conventions' or existing.get('status') != 'pass'):
                merged.append(existing)
            else:
                merged.append(dict(check, context_sha256=bindings['context_sha256'],
                                   evidence_artifact_id=aid, sha256=sha))
        extended['quality_checks'] = merged
    working_state = copy.deepcopy(state)
    working_state['deployment_review'] = projection
    working_state['next_actions'] = [{'title':'Review the proposed deployment', 'scope':'deployment',
                                     'section':'deployment', 'action':projection['next_action']}]
    # Validate the public projection before writing anything. The state copy stays
    # in memory: writing full workflow state would disclose internal roots.
    portal._deployment_presentation(working_state, 'engineer')
    review_bytes = _public_bytes(extended, private_paths)
    include = sorted(set(handoff['deliverables']) | {'validation'})
    with tempfile.TemporaryDirectory(prefix='.deployment-review-', dir=output.parent) as temp:
        staging = Path(temp)
        artifact_root = staging / 'artifacts'
        artifact_root.mkdir()
        for item in selected:
            for private in private_paths:
                require(str(private).encode() not in item['content'], 'Selected artifact contains an internal path; curate it before export')
            path = artifact_root / item['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(item['content'])
        for relative, body in generated.items():
            path = artifact_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        (staging / 'review.json').write_bytes(review_bytes)
        package = staging / 'deployment-review.zip'
        manifest = portal.package_delivery(working_state, extended, artifact_root, package,
                                           audience='engineer', include=include)
        portal.verify_delivery(package)
        # The standalone entrypoint is the same embedded-payload page shipped in
        # the ZIP; it can inspect files without depending on an installed runner.
        import zipfile
        with zipfile.ZipFile(package) as archive:
            (staging / 'START_HERE.html').write_bytes(archive.read('START_HERE.html'))
        require(deployment.load_plan(plan_path) == plan, 'Deployment plan changed during review export')
        deployment._current(plan, policy_path)
        output.mkdir(mode=0o700)  # Fails if another writer claimed the destination.
        for path in staging.iterdir():
            shutil.move(str(path), str(output / path.name))
    return {'status':'deployment_review_exported', 'page':str(output / 'START_HERE.html'),
            'package':str(output / 'deployment-review.zip'), 'review':str(output / 'review.json'),
            'artifact_root':str(output / 'artifacts'), 'plan_sha256':plan['plan_sha256'],
            'context_sha256':manifest['context_sha256'],
            'authority':'Review and requests only; original handoff unchanged. No approval or execution performed.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, help='Current coordinator deployment-plan JSON')
    parser.add_argument('--output', required=True, help='New output directory')
    parser.add_argument('--receipt', help='Optional runner receipt JSON containing operation_id; status is verified afresh')
    args = parser.parse_args(argv)
    try:
        policy = os.environ.get('DMA_RUNNER_POLICY')
        require(bool(policy), 'Provision DMA_RUNNER_POLICY before exporting the deployment review')
        print(json.dumps(export_review(args.plan, policy, args.output, args.receipt), indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('Deployment review blocked: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
