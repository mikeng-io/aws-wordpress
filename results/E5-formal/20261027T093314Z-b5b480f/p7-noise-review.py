from pathlib import Path
import csv,json,collections,hashlib
r=Path(__file__).resolve().parent
a=json.loads((r/'analysis-v3.json').read_text());x=next(iter(a['replications'].values()))
intervals={}
for d in ('0.1','1','10'):
 c=x['matched_controls'][d];target=x['b']['fsx_lustre'][d];boundary=target['stat_split']['threshold_ns'];noise=c['stat_split']['slow_centroid_ns']
 intervals[d]=dict(control_slow_share=c['slow_share_stat'],control_slow_centroid_ns=noise,lustre_threshold_ns=boundary,lustre_slow_share=target['slow_share_stat'],share_gate_triggered=c['slow_share_stat']>.01,centroid_gate_triggered=boundary is not None and noise is not None and noise>=boundary and c['slow_share_stat']>0)
p=r/'rep-1/formal/batches/lustre-10/ebs-10.raw.csv';per=collections.defaultdict(list)
with p.open() as file:
 for k,op,seq,ns in csv.reader(file):
  if int(k)>=30 and op=='stat':per[int(k)].append((int(seq),int(ns)))
assert set(per)==set(range(30,90))
assert all(sorted(seq for seq,_ in rows)==list(range(1000)) for rows in per.values())
values=sorted(ns for rows in per.values() for _,ns in rows);boundary=intervals['10']['lustre_threshold_ns']
tails={str(k):sum(ns>=boundary for _,ns in rows) for k,rows in per.items()};tails={k:v for k,v in tails.items() if v}
out=dict(method='isolation-formal-v3',grade_unchanged='P7 ERROR',interval_checks=intervals,exact_10s_control_positive_operations=dict(operations=len(values),sampling='all 60 measured requests, 1000 stat calls each; warm requests excluded',at_or_above_lustre_boundary=sum(ns>=boundary for ns in values),requests_with_such_operations=len(tails),sequence_positions=dict(collections.Counter(str(seq) for rows in per.values() for seq,ns in rows if ns>=boundary)),top_requests=sorted(tails.items(),key=lambda x:-x[1])[:10],p50_ns=values[(len(values)-1)//2],p99_ns=values[(len(values)*99+99)//100-1],maximum_ns=values[-1],source_sha256=hashlib.sha256(p.read_bytes()).hexdigest()),limitations=['Descriptive raw-tail review only; does not alter the registered histogram classifier or P7 gate.','CPU/wall telemetry does not identify the producer of a timing outlier or distinguish OS scheduling from filesystem waits.','n=1; no causal DLM or general performance verdict.'])
print(json.dumps(out,indent=2))
