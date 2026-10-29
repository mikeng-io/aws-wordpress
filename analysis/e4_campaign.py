#!/usr/bin/env python3
"""Recompute E4 provenance and cost proxies from retained task/teardown evidence."""
from __future__ import annotations
import json, math, sys
from datetime import datetime
from pathlib import Path

def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))

def campaign(root: Path) -> dict:
    reps = []
    pricing_id = None
    task_seconds = 0.0
    for rep in sorted(root.glob('rep-*')):
        meta_path = rep / 'meta.json'
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        pricing_id = meta.get('pricing_snapshot', pricing_id)
        tasks = {}
        for arm in ('seed', 'efs', 'hydrated'):
            path = rep / f'{arm}.task.json'
            if not path.exists():
                continue
            task = json.loads(path.read_text())['tasks'][0]
            seconds = (stamp(task['stoppedAt']) - stamp(task['createdAt'])).total_seconds()
            # Conservative duration proxy: includes pre-pull provisioning and all
            # shutdown; not an AWS billing export. Include failed init attempts.
            task_seconds += max(60.0, seconds)
            tasks[arm] = {
                'availability_zone': task['availabilityZone'],
                'platform_version': task.get('platformVersion'),
                'cpu': task.get('cpu'), 'memory': task.get('memory'),
                'ephemeral_storage': task.get('ephemeralStorage'),
                'image_digests': [c.get('imageDigest') for c in task['containers']],
                'exit_codes': [c.get('exitCode') for c in task['containers']],
                'created_to_stopped_s': seconds,
            }
        reps.append({'replication': rep.name, 'meta': meta, 'tasks': tasks})
    snapshot = root.parents[1] / 'pricing' / pricing_id / 'pricing.json'
    prices = json.loads(snapshot.read_text())
    cpu = next(p['usd'] for p in prices['fargate'] if p['usagetype'] == 'APS1-Fargate-ARM-vCPU-Hours:perCPU')
    mem = next(p['usd'] for p in prices['fargate'] if p['usagetype'] == 'APS1-Fargate-ARM-GB-Hours')
    endpoint = next(p['usd'] for p in prices['vpc_endpoint'] if p['usagetype'] == 'APS1-VpcEndpoint-Hours')
    verification = json.loads((root / 'campaign-verification.json').read_text())
    stack_hours = []
    for stack in verification['stacks']:
        start = stamp(stack['stack']['CreationTime'])
        # Last retained DELETE_COMPLETE is an observed lower bound on complete
        # stack deletion; collector verification is separately retained in logs.
        end = max(stamp(r['LastUpdatedTimestamp']) for r in stack['resources'])
        stack_hours.append((end - start).total_seconds() / 3600)
    task_cost = task_seconds / 3600 * (0.5 * cpu + mem)
    reserve = sum(math.ceil(h) * 3 * endpoint for h in stack_hours)
    return {
        'run_id': root.name, 'provenance': reps,
        'pricing_snapshot': str(snapshot),
        'cost_estimate': {
            'status': 'estimate, not invoice; ancillary usage excluded',
            'task_duration_proxy_s': task_seconds,
            'task_rate_usd_per_hour': 0.5 * cpu + mem,
            'task_cost_proxy_usd': task_cost,
            'stack_observed_lifetimes_hours': stack_hours,
            'endpoint_rate_usd_per_hour': endpoint,
            'endpoint_prorated_proxy_usd': sum(stack_hours) * 3 * endpoint,
            'endpoint_whole_hour_reserve_usd': reserve,
            'task_plus_endpoint_reserve_usd': task_cost + reserve,
            'excluded': ['EFS storage and elastic-throughput IO', 'S3 requests and storage', 'CloudWatch ingestion', 'endpoint data processing', 'shared CDK/ECR asset storage'],
            'assumptions': ['three interface endpoints per deployment', '0.5 ARM vCPU and 1 GiB per task', 'task created-to-stopped with 60s minimum is a conservative duration proxy', 'endpoint reserve rounds each deployment up to whole hours; not a billing assertion'],
        },
    }

def main():
    root = Path(sys.argv[1])
    report = campaign(root)
    (root / 'campaign-summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['cost_estimate'], indent=2))

if __name__ == '__main__':
    main()
