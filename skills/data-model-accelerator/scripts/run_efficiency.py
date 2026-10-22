"""Small execution summary from existing receipts; never estimates spend or duration."""
from collections import Counter


def summarize(state):
    workflow = state.get('workflow', {})
    runs = workflow.get('runs', [])
    observations = [r['execution_observation'] for r in runs if r.get('execution_observation')]
    packets = {o['packet_sha256']: o['packet_bytes'] for o in observations}
    attempts = Counter((r.get('task_id'), r.get('fingerprint')) for r in runs)
    plan = (workflow.get('last_plan') or {}).get('tasks', [])
    actions = Counter(r.get('action', 'unknown') for r in plan)
    return {'schema_version': 1, 'kind': 'run_efficiency',
        'recorded_runs': len(runs), 'runs_with_packet_receipts': len(observations),
        'runs_without_packet_receipts': len(runs) - len(observations),
        'unique_packet_count': len(packets), 'unique_packet_bytes': sum(packets.values()),
        'dispatched_packet_bytes': sum(o['packet_bytes'] for o in observations),
        'repeated_task_attempts': sum(max(0, n - 1) for n in attempts.values()),
        'planned_reuse': actions['reuse'], 'planned_regeneration': actions['regenerate'],
        'planned_blocked': actions['blocked'],
        'qualification': 'Recorded task and packet inventory only. Missing receipts are unknown; byte reuse is not token, time or dollar savings. Host billing remains outside the accelerator.'}
