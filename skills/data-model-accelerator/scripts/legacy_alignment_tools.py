"""Read bounded legacy comparison inputs without rescanning the source project.

Results are local, private preparation data. Use agent_context.py for disclosure
before dispatch and the existing migration comparator for actual parity tests.
"""
import argparse
from pathlib import Path

from ae_common import hash_json, require


def inspect(state, action, domain_id=None, max_bytes=32768, budget_reason=None, record_ids=None):
    import legacy_alignment as alignment
    require(action in {'summary', 'candidates', 'context', 'validation-cases'}, 'Unknown comparison inspection')
    require(record_ids is None or action == 'context', 'Record partitions apply only to comparison context')
    if action == 'summary':
        return alignment.public_summary(state)
    require(isinstance(domain_id, str) and domain_id.strip(), 'Select a comparison domain')
    if action == 'candidates':
        return alignment.candidates(state, domain_id)
    if action == 'validation-cases':
        return alignment.validation_cases(state, domain_id)
    require(type(max_bytes) is int and 1024 <= max_bytes <= 65536,
            'Context limit must be between 1024 and 65536 bytes')
    require(max_bytes <= 32768 or isinstance(budget_reason, str) and bool(budget_reason.strip()),
            'A larger comparison packet needs an explicit budget reason')
    return alignment.context_packet(state, domain_id, max_bytes=max_bytes, record_ids=record_ids)


def main(argv=None):
    from guided_workflow import load_engagement, _nonsecret_json
    from omni_native import _private_file
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('summary', 'candidates', 'context', 'validation-cases'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--domain')
    parser.add_argument('--max-bytes', type=int, default=32768)
    parser.add_argument('--budget-reason')
    parser.add_argument('--record', action='append', dest='record_ids',
                        help='Explicit kind:id context record; repeat to partition an oversized domain. Omissions stay visible.')
    parser.add_argument('--previous', type=Path,
                        help='Previous local inspection receipt; equality means unchanged inputs, not completed review.')
    parser.add_argument('--output', type=Path, required=True, help='New private output file outside the input repository.')
    args = parser.parse_args(argv)
    state = load_engagement(args.run)
    source = Path(state['inputs']['source']['path']).resolve()
    destination = args.output.absolute()
    require(source != destination and source not in destination.resolve().parents,
            'Comparison output must be outside the source repository')
    result = inspect(state, args.action, args.domain, args.max_bytes, args.budget_reason, args.record_ids)
    digest = hash_json(result)
    previous = _nonsecret_json(args.previous)[0] if args.previous else None
    same = (isinstance(previous, dict) and previous.get('kind') == 'legacy_alignment_inspection'
            and previous.get('action') == args.action and previous.get('domain_id') == args.domain
            and previous.get('engagement_id') == state['engagement_id']
            and previous.get('result_sha256') == digest
            and hash_json(previous.get('result')) == digest)
    receipt = {'schema_version': 1, 'kind': 'legacy_alignment_inspection',
               'engagement_id': state['engagement_id'], 'action': args.action,
               'domain_id': args.domain, 'result_sha256': digest,
               'unchanged_inputs': same, 'result': result,
               'qualification': 'Local inspection only. Unchanged inputs do not prove a completed reviewer run. '
                                'Check retained output bytes and existing run-control receipts before reusing work. '
                                'Route data through agent-input disclosure before dispatch; no parity or execution authority.'}
    _private_file(destination, receipt)
    print('Comparison inspection saved; inputs ' + ('unchanged.' if same else 'new or changed.'))
    return 0


if __name__ == '__main__':
    main()
