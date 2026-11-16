"""Команды изолированного стенда и неизменяемые журналы каждого опыта."""
import contextlib,json,os,subprocess,threading,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RESULTS=ROOT/'results';RESULTS.mkdir(exist_ok=True)
ENV={**os.environ,'KUBECONFIG':str(ROOT/'.runtime/kubeconfig'),'PATH':str(ROOT/'.tools')+':'+os.environ['PATH']}

def command(*args,check=True,timeout=180,input=None):
    result=subprocess.run(args,cwd=ROOT,env=ENV,text=True,input=input,capture_output=True,timeout=timeout)
    if check and result.returncode:raise RuntimeError(' '.join(args)+'\n'+result.stdout+result.stderr)
    return result.stdout

def kubectl(*args,**kw):return command('kubectl','-n','hw11',*args,**kw)
def objects(kind,selector=None):
    args=['get',kind,'-o','json']
    if selector:args+=['-l',selector]
    return json.loads(kubectl(*args))['items']
def api_pods():return objects('pods','app=hw11-api')
def save(name,value):
    p=RESULTS/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');return p

def upgrade(**values):
    args=['helm','upgrade','hw11','charts/hw11','-n','hw11','-f','source/installed-values.json']
    for k,v in values.items():args+=['--set',k+'='+str(v).lower() if isinstance(v,bool) else k+'='+str(v)]
    out=command(*args)
    with (RESULTS/'commands.log').open('a') as stream:stream.write('$ '+' '.join(args)+'\n'+out+'\n')
    return out

def ready(timeout=180):return kubectl('rollout','status','deployment/hw11-api',f'--timeout={timeout}s',timeout=timeout+10)

def remote(code,client='client-0',timeout=90):return kubectl('exec',client,'--','python','-c',code,timeout=timeout)

def request(url='http://hw11-normal:8000',payload=None,client='client-0',path='/generate',method='POST'):
    payload=payload or {'prompt':'check','chunks':4,'chunk_delay':0.09,'request_id':str(uuid.uuid4()),'session_id':'check'}
    code="""import json,httpx,time
payload=PAYLOAD
start=time.monotonic()
with httpx.Client(trust_env=False,timeout=60) as c:
 r=c.request(METHOD,URL,json=payload if METHOD=='POST' else None)
 print(json.dumps({'status':r.status_code,'text':r.text,'headers':dict(r.headers),'duration':time.monotonic()-start}))
""".replace('PAYLOAD',repr(payload)).replace('METHOD',repr(method)).replace('URL',repr(url+path))
    return json.loads(remote(code,client=client))

def collect_logs(name):
    path=RESULTS/'logs'/name;path.mkdir(parents=True,exist_ok=True)
    for pod in api_pods():
        n=pod['metadata']['name'];(path/(n+'.jsonl')).write_text(kubectl('logs',n,check=False))

def reset_caches():
    for p in api_pods():
        ip=p['status'].get('podIP')
        if ip:
            response=request('http://'+ip+':8000',path='/control/reset-cache',payload={'unused':True})
            assert response['status']==200,response

@contextlib.contextmanager
def watch(name):
    stop=threading.Event();path=RESULTS/(name+'-timeline.jsonl')
    def worker():
        with path.open('w') as stream:
            while not stop.is_set():
                try:
                    raw=kubectl('get','pods,endpointslices,hpa','-o','json',timeout=15)
                    row={'unix':time.time(),'mono':time.monotonic(),'objects':json.loads(raw)}
                    stream.write(json.dumps(row)+'\n');stream.flush()
                    logs=RESULTS/'logs'/name;logs.mkdir(parents=True,exist_ok=True)
                    for pod in row['objects']['items']:
                        if pod.get('kind')=='Pod' and pod['metadata'].get('labels',{}).get('app')=='hw11-api':
                            podname=pod['metadata']['name'];text=kubectl('logs',podname,check=False,timeout=5)
                            if text.strip():(logs/(podname+'.jsonl')).write_text(text)
                except Exception as exc:stream.write(json.dumps({'unix':time.time(),'error':str(exc)})+'\n')
                stop.wait(2)
    t=threading.Thread(target=worker,daemon=True);t.start()
    try:yield
    finally:stop.set();t.join(timeout=20)

def schedule(name,duration,rps,traffic='uniform',chunks=4,delay=.09,prefixes=4):
    rows=[]
    for i in range(int(duration*rps)):
        client=i%4 if traffic=='uniform' else (0 if i%10<8 else 1+(i//10)%3)
        rows.append({'index':i,'client':client,'offset':i/rps,
                     'payload':{'prompt':f'Question {i:05d} '+'x'*48,'prefix':f'prefix-{i%prefixes}',
                                'chunks':chunks,'chunk_delay':float(delay)}})
    plan={'name':name,'duration':duration,'rps':rps,'traffic':traffic,'cache_initial':'not_reset_by_schedule; see scenario','requests':rows}
    path=ROOT/'results/schedules'/(name+'.json');path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(plan))
    return path

def start_load(name,plan,service='hw11-normal',clients=4,lead=4):
    start=time.time()+lead;processes=[]
    for i in range(clients):
        kubectl('cp',str(plan),f'client-{i}:/work/plan-{name}.json')
    start=max(start,time.time()+3)
    for i in range(clients):
        args=['kubectl','-n','hw11','exec',f'client-{i}','--','python','/app/client.py','--url',f'http://{service}:8000',
              '--schedule',f'/work/plan-{name}.json','--output',f'/work/{name}.jsonl','--start',str(start),
              '--client',str(i),'--run-id',name]
        log=(ROOT/'.runtime'/f'{name}-client-{i}.log').open('w')
        processes.append((i,subprocess.Popen(args,cwd=ROOT,env=ENV,stdout=log,stderr=subprocess.STDOUT),log))
    return {'name':name,'start':start,'plan':str(plan.relative_to(ROOT)),'service':service,'processes':processes}

def finish_load(job,timeout=240):
    rows=[]
    for i,p,log in job['processes']:
        p.wait(timeout=timeout);log.close()
        if p.returncode:raise RuntimeError(f'Клиент {i}: '+(ROOT/'.runtime'/f'{job["name"]}-client-{i}.log').read_text())
        text=kubectl('exec',f'client-{i}','--','cat',f'/work/{job["name"]}.jsonl')
        rows.extend(json.loads(line) for line in text.splitlines())
    path=RESULTS/'runs'/(job['name']+'.jsonl');path.parent.mkdir(exist_ok=True)
    path.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in sorted(rows,key=lambda r:r['sent_unix'])))
    meta={k:v for k,v in job.items() if k!='processes'};meta.update(end=time.time(),attempts=len(rows))
    save('runs/'+job['name']+'-meta.json',meta)
    with (RESULTS/'requests.jsonl').open('a') as stream:
        for row in rows:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    return rows

def summarize(rows):
    from collections import Counter
    def percentile(values,q):
        values=sorted(x for x in values if x is not None)
        if not values:return None
        x=(len(values)-1)*q;i=int(x);return values[i]+(values[min(i+1,len(values)-1)]-values[i])*(x-i)
    ok=[r for r in rows if r['outcome']=='completed']
    per_pod={}
    for pod in sorted({r['pod'] for r in rows if r['pod']}):
        selected=[r for r in rows if r['pod']==pod];success=[r for r in selected if r['outcome']=='completed']
        per_pod[pod]={'sent':len(selected),'completed':len(success),
                      'ttfc_p95':percentile([r['ttfc_seconds'] for r in success],.95),
                      'queue_p95':percentile([r['queue_seconds'] for r in success],.95)}
    return {'per_pod':per_pod,'cache_hit_rate':sum(r['cache_hit'] is True for r in ok)/len(ok) if ok else None,
            'sent':len(rows),'completed':len(ok),'outcomes':dict(Counter(r['outcome'] for r in rows)),
            'pods':dict(Counter(r['pod'] for r in rows)),'error_rate':1-len(ok)/len(rows) if rows else None,
            'ttfc_p50':percentile([r['ttfc_seconds'] for r in ok],.5),'ttfc_p95':percentile([r['ttfc_seconds'] for r in ok],.95),
            'response_p50':percentile([r['duration_seconds'] for r in ok],.5),
            'response_p95':percentile([r['duration_seconds'] for r in ok],.95),
            'send_lag_p95':percentile([r['send_lag_seconds'] for r in rows],.95)}
