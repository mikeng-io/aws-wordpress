#!/usr/bin/env python3
"""Render the reviewed run classification; never grade or modify raw results."""
import json
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[1]


def render() -> str:
    manifest = json.loads((REPO / 'docs/study-runs.json').read_text())
    listed = [r['path'] for r in manifest['runs']]
    actual = sorted(p.relative_to(REPO).as_posix() for group in (REPO/'results').iterdir()
                    if group.is_dir() and re.fullmatch(r'E\d+(?:-[a-z-]+)?', group.name)
                    for p in group.iterdir() if p.is_dir())
    if sorted(listed) != actual or len(set(listed)) != len(listed):
        raise ValueError('run classification is missing, duplicated, or stale; review study-runs.json')
    lines = ['# Evidence index', '', f"Observation set: {manifest['as_of']}. {len(listed)} experimental run directories.", '',
             'A run directory is not automatically a completed campaign or independent replication.',
             'This index classifies frozen evidence; it does not pool unlike methods or regrade failures.',
             'See [study closeout](study-status.md) for current claims, limits and deferred work.', '',
             '## Reference collections', '',
             '| Question | Evidence | What is eligible |', '|---|---|---|',
             '| E0 count demand | [corrected census](../results/E0/20260902T105746Z-f62a686/) | n=10, aged n=3; counts only |',
             '| E1 mount topology | [host inspection](../results/E1/20260902T060000Z-24d9bb9/) | one direct inspection, not a latency replication |',
             '| E2 block/mount matrix | [block](../results/E2/20260910T163206Z-66dcff8/), [mount](../results/E2/20260910T182051Z-53b5423/) | three deployments each; campaign-specific grades |',
             '| E2 FSx | [formal collection](../results/E2/20261015T000959Z-85382cc/) | three deployments; P1 NOT EVALUABLE; recorded resume exception |',
             '| E2 FUSE | [formal collection](../results/E2/20261029T070456Z-a2041d6/) | three deployments; P2 INCONCLUSIVE, P4 SUPPORTED; dirty-provenance note |',
             '| E3 local substrate | [Fargate collection](../results/E3/20260910T113000Z-6016f58/) | three independent tasks |',
             '| E4 read-only hydration | [formal collection](../results/E4/20261029T091909Z-842d596/) | three clean independent deployments; smoke/failed campaigns excluded |',
             '| E5 old-file/repeat cost | [run 1](../results/E5-formal/20261028T103017Z-342d6b4/), [run 2](../results/E5-formal/20261028T125412Z-f6659e0/), [run 3](../results/E5-formal/20261028T160106Z-dd5fce0/) | three eligible formal-v3 deployments only |', '',
             '## Every retained run', '',
             '| Group / run | Role | Rep directories | Metadata files | Recorded interpretation |', '|---|---|--:|--:|---|']
    for row in manifest['runs']:
        p = REPO / row['path']
        lines.append(f"| [{row['path'].removeprefix('results/')}]({('../'+row['path'])}/) | {row['role']} | {len(list(p.glob('rep-*')))} | {len(list(p.rglob('meta.json')))} | {row['note']} |")
    lines += ['', '## Reading the provenance', '',
              '- E0 repetitions are requests on local Docker, not independent AWS deployments.',
              '- E5 formal-v3 has one rep-1 directory in each of three run IDs; historical study labels rep 2/3/4 refer to those deployments.',
              '- Missing metadata/arms are an eligibility limitation, not a zero latency or a negative performance grade.',
              '- E2 FSx rep-3 records a collector-only resume exception; E2 FUSE records git_dirty=true. Neither is rewritten here.',
              '- H2 whole-claim and H4/H5/H6/H7 unanswered questions remain deferred, not silently passed.',
              '- Frozen snapshots remain authoritative for their original rules; the old E5 P7 ERROR is not in the newer pool.',
              '- Archived smoke/diagnostic output may have incomplete Git timing logs; the closeout replay only claims checks named in its receipt.',
              '- Offline replay receipts under results/closeout are validation artifacts, not additional experiment replications.', '',
              '## Reproduce this index', '', '```sh', 'make study-index', '```', '',
              'Classification is reviewed data in study-runs.json. The renderer refuses a missing or duplicated run.', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    (REPO/'docs/evidence-index.md').write_text(render())
