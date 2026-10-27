import importlib.util,json,hashlib,subprocess,sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
spec=importlib.util.spec_from_file_location('preflight','experiments/E5-attribute-cache/scripts/preflight.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
p=m.Preflight();d,e=p.query('regions','ec2','describe-regions');assert not e,e
regions=sorted(x['RegionName'] for x in d['Regions'])
with ThreadPoolExecutor(max_workers=6) as pool: scans=list(pool.map(p.scan,regions))
b,e=p.query('buckets','s3api','list-buckets');assert not e,e
buckets=sum(x['Name'].startswith('e5-attributecache-dev-') for x in b['Buckets'])
root=Path(json.loads(Path('.e5-watchdog/latest.json').read_text())['directory']);s=json.loads((root/'state.json').read_text())
assert hashlib.sha256(s['token'].encode()).hexdigest()=='6e5f8b53c31be1b13ea3e72fac59bf69a75b70bfdb0a84a1ed6d7fe9d0025206', 'audit guard identity mismatch'
history=[]
for arn in s['stacks']:
 d,e=p.query('final-stack-events','cloudformation','describe-stack-events','--stack-name',arn);assert not e,e
 events=[x for x in d['StackEvents'] if x['ResourceType']=='AWS::CloudFormation::Stack']
 history.append({'created':min(x['Timestamp'] for x in events),'last_event':events[0]['Timestamp'],'status':events[0]['ResourceStatus']})
report={'utc':p.utc,'source_commit':p.sha,'scope':'18 enabled regions; direct service inventories selected by E5 tags or exact stack/cluster names; no mutation','regions':scans,'e5_diagnostics_buckets':buckets,'stack_history':history,'guard':{k:s.get(k) for k in ['phase','cleanup_verified','runner_stopped','runner_exit','stop_reason','remaining_backups','remaining_stacks']},'private_raw_directory':str(p.private.relative_to(Path.cwd()))}
report['clean']=all(not x['errors'] and all(y['e5_count']==0 for y in x['checks'].values()) for x in scans) and buckets==0 and s.get('phase')=='complete' and s.get('cleanup_verified') is True
assert s.get('run_kind')=='formal-isolation'
out=Path(sys.argv[1]);assert 'E5-formal' in out.parts
assert not out.exists(), 'refusing to overwrite an audit receipt'
meta=json.loads((out.parent/'rep-1/meta.json').read_text())
assert meta['run_id']==out.parent.name and meta['protocol_method']=='isolation-formal-v3'
assert len(s['stacks'])==1 and hashlib.sha256(next(iter(s['stacks'])).encode()).hexdigest()==meta['deployment_id'], 'deployment identity mismatch'
report['guard_identity_sha256']=hashlib.sha256(s['token'].encode()).hexdigest()
report['source_script_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
assert report['clean'],'Final audit not clean'
out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'clean':report['clean'],'regions':len(scans),'errors':sum(len(x['errors']) for x in scans),'guard':report['guard'],'history':history}))
assert report['clean'],'Final audit not clean'
