"""Verify externally issued deployment attestations; never mint human approval.

The trusted runner provisions policy/public keys outside candidate content. Private
approval and validation keys belong to separately controlled issuers. Filesystem
location alone is not isolation from a process running as the same principal.
"""
import base64
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import stat

from ae_common import require, hash_json, load_json, _json_bytes

VERSION = 1
ACTIONS = {'publish_pr', 'deploy_development', 'promote'}
PURPOSES = {'model_signoff', 'deployment_approval', 'deployment_acceptance', 'adapter_qualification', 'deployment_recovery', 'deployment_reconciliation', 'delivery_evidence'}


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value):
    require(isinstance(value, str), 'Timestamp must be an ISO-8601 string')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError('Invalid timestamp') from error
    require(result.tzinfo is not None, 'Timestamp must include a timezone')
    return result.astimezone(timezone.utc)


def canonical_path(value, *, exists=True):
    path = Path(value).expanduser().absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'Symlink path is not allowed')
    require('..' not in path.parts, 'Parent traversal is not allowed')
    if exists:
        require(path.exists(), 'Required path is unavailable: ' + str(path))
    return path


def outside(path, roots):
    path = canonical_path(path, exists=False)
    for root in roots:
        root = canonical_path(root)
        require(path != root and root not in path.parents,
                'Runner policy/state must be outside the input and candidate directories')
    return path


def publication_destination(value):
    """Validate an exact publication destination, with no wildcard ref policy."""
    require(type(value) is dict and set(value) == {'repository', 'base', 'head'},
            'Publication destination requires exact repository/base/head')
    require(isinstance(value['repository'], str) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value['repository']),
            'Invalid publication repository')
    for key in ('base', 'head'):
        ref = value[key]
        require(isinstance(ref, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]{0,180}', ref)
                and '..' not in ref and not ref.endswith(('/', '.', '.lock')) and '//' not in ref,
                'Invalid exact publication Git ref')
    require(value['base'] != value['head'], 'Publication base and head must differ')
    return dict(value)


def load_policy(path, *, excluded_roots=()):
    path = outside(path, excluded_roots)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode), 'Runner policy must be a regular file')
    require(info.st_mode & 0o022 == 0, 'Runner policy cannot be group/world writable')
    require(info.st_uid == os.getuid(), 'Runner policy must be owned by the configured runner account')
    policy = load_json(path)
    require(type(policy.get('schema_version')) is int and policy.get('schema_version') == VERSION and policy.get('kind') == 'deployment_runner_policy',
            'Unsupported runner policy')
    require(isinstance(policy.get('runner_id'), str) and policy['runner_id'], 'Runner identity is required')
    require(policy.get('mode') in {'simulation', 'live'}, 'Runner mode must be simulation or live')
    require(type(policy.get('allowed_actions')) is list and bool(policy['allowed_actions'])
            and set(policy['allowed_actions']) <= ACTIONS, 'Invalid allowed actions')
    require(type(policy.get('destinations')) is dict and bool(policy['destinations']), 'No configured destinations')
    publication = policy.get('publication_destinations', {})
    require(type(publication) is dict, 'Invalid publication destination registry')
    for destination, identity in publication.items():
        require(destination in policy['destinations'], 'Publication destination must name a configured destination')
        publication_destination(identity)
    require(type(policy.get('issuers')) is dict and bool(policy['issuers']), 'No trusted approval issuers')
    require(type(policy.get('tools', {})) is dict, 'Invalid executable registry')
    require(type(policy.get('runtime_env', {})) is dict and all(isinstance(k, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', k) and isinstance(v, str) and re.fullmatch(r'[a-f0-9]{64}', v) for k, v in policy.get('runtime_env', {}).items()), 'Runtime environment must map names to pinned value hashes')
    public_keys = []
    for issuer_id, issuer in policy['issuers'].items():
        require(isinstance(issuer_id, str) and type(issuer) is dict, 'Invalid issuer registry')
        require(type(issuer.get('purposes')) is list and set(issuer['purposes']) <= PURPOSES, 'Invalid issuer purposes')
        if 'delivery_evidence' in issuer['purposes']:
            from delivery_assurance import LANES
            lanes = issuer.get('evidence_lanes')
            require(type(lanes) is list and bool(lanes) and all(type(v) is str for v in lanes)
                    and len(lanes) == len(set(lanes)) and set(lanes) <= LANES,
                    'Evidence issuers require an explicit lane allowlist')
        require(type(issuer.get('actors')) is list and bool(issuer['actors']) and
                all(isinstance(v, str) and v for v in issuer['actors']), 'Issuer actor allowlist is required')
        require(type(issuer.get('public_key')) is str, 'Issuer public key is required')
        try:
            key = base64.b64decode(issuer['public_key'], validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError('Invalid Ed25519 public key') from error
        require(len(key) == 32, 'Expected a raw Ed25519 public key')
        require(base64.b64encode(key).decode() == issuer['public_key'], 'Public key encoding must be canonical')
        require(key not in public_keys, 'Distinct issuers must use distinct public keys')
        public_keys.append(key)
    ttl = policy.get('max_attestation_age_seconds', 86400)
    require(type(ttl) is int and 1 <= ttl <= 31 * 86400, 'Invalid attestation lifetime policy')
    state_root = outside(policy['state_root'], excluded_roots)
    require(state_root != path, 'Runner state cannot replace its policy')
    require(type(policy.get('revoked_ids', [])) is list, 'Invalid revocation list')
    return policy, hash_json(policy)


def verify_attestation(envelope, policy, *, purpose, bindings, now=None):
    """Authenticate exact claims against a provisioned issuer, scope and lifetime.

    An issuer must authenticate the approver/validator outside this program. This
    verifies that issuer's statement, not an unauthenticated actor name in JSON.
    """
    require(type(envelope) is dict and set(envelope) == {'payload', 'signature'}, 'Invalid signed envelope')
    payload = envelope['payload']
    require(type(payload) is dict and type(payload.get('schema_version')) is int and payload.get('schema_version') == VERSION,
            'Invalid attestation payload')
    require(payload.get('kind') == 'deployment_attestation' and payload.get('purpose') == purpose,
            'Attestation purpose mismatch')
    require(payload.get('mode') == policy['mode'], 'Simulation evidence cannot authorize live work')
    issuer = policy['issuers'].get(payload.get('issuer'))
    require(issuer is not None and purpose in issuer['purposes'], 'Issuer is not trusted for this purpose')
    require(payload.get('actor') in issuer['actors'], 'Attestation actor is outside the issuer allowlist')
    require(isinstance(payload.get('id'), str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', payload['id']),
            'Invalid attestation identity')
    require(payload['id'] not in policy.get('revoked_ids', []), 'Attestation has been revoked')
    require(isinstance(payload.get('review_reference'), str) and payload['review_reference'].strip(),
            'Authenticated review reference is required')
    require(payload.get('bindings') == bindings, 'Attestation binding mismatch: version, target, policy or context changed')
    issued, expires = timestamp(payload.get('issued_at')), timestamp(payload.get('expires_at'))
    observed_now = now or utc_now()
    require(issued <= observed_now < expires, 'Attestation is expired or not yet valid')
    require(0 < (expires - issued).total_seconds() <= policy.get('max_attestation_age_seconds', 86400),
            'Attestation lifetime exceeds runner policy')
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError as error:
        raise ValueError('Install the pinned deployment verification requirements in the runner environment') from error
    try:
        public = base64.b64decode(issuer['public_key'], validate=True)
        signature = base64.b64decode(envelope['signature'], validate=True)
        require(len(signature) == 64, 'Invalid Ed25519 signature length')
        Ed25519PublicKey.from_public_bytes(public).verify(signature, _json_bytes(payload))
    except (InvalidSignature, ValueError, TypeError) as error:
        raise ValueError('Attestation signature verification failed') from error
    return payload
