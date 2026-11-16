"""Две реальные Service × два трафика × три повтора, каждый >=120 секунд."""
import hashlib,json,time
from common import *
from metrics import forward,alerts,export,histogram_comparison

def main():
    ready();upgrade(modelVersion='A',warmupSeconds=20);ready()
    summary=[]
    previous={x['run']:x for x in json.loads((RESULTS/'b-summary.json').read_text())} if (RESULTS/'b-summary.json').exists() else {}
    save('b-network.json',{'services':objects('services'),'pods':objects('pods'),'nodes':json.loads(command('kubectl','get','nodes','-o','json')),
                           'kube_proxy':command('kubectl','-n','kube-system','get','cm','kube-proxy','-o','yaml'),
                           'keep_alive':'httpx max_keepalive_connections=0; новое TCP-соединение на каждый запрос',
                           'cache':{'size':8,'hit_ms':40,'miss_ms':160,'concurrency':1,'queue_capacity':16,'queue_timeout_seconds':45,'chunk_cpu_ms':3}})
    with forward(),alerts('b'):
        for repeat in range(1,4):
            for traffic in ['uniform','hot']:
                plan=schedule('b-'+traffic,120,4,traffic=traffic)
                plan_data=json.loads(plan.read_text());plan_data['cache_initial']='empty'
                plan.write_text(json.dumps(plan_data))
                for policy in ['normal','sticky']:
                    name=f'b-{policy}-{traffic}-{repeat}'
                    if (RESULTS/'runs'/(name+'.jsonl')).exists():
                        rows=[json.loads(x) for x in (RESULTS/'runs'/(name+'.jsonl')).read_text().splitlines()]
                        summary.append(previous.get(name,{'run':name,'policy':policy,'traffic':traffic,'repeat':repeat,'measurement_seconds':120,'schedule_sha256':hashlib.sha256(plan.read_bytes()).hexdigest(),**summarize(rows)}))
                        print('RESUME saved',name,flush=True);continue
                    reset_caches();time.sleep(4);start=time.time()
                    print('START',name,'120 seconds',flush=True)
                    with watch(name):
                        job=start_load(name,plan,service='hw11-'+policy);rows=finish_load(job)
                    time.sleep(4);end=time.time()
                    assert len(rows)==480,(name,len(rows))
                    assert len({r['client_id'] for r in rows})==4
                    collect_logs(name);export(name,start,end)
                    histogram_comparison(name,start,end,rows)
                    info={'run':name,'policy':policy,'traffic':traffic,'repeat':repeat,'measurement_seconds':120,
                          'schedule_sha256':hashlib.sha256(plan.read_bytes()).hexdigest(),**summarize(rows)}
                    summary.append(info);save('b-summary.json',summary)
                    print('DONE',name,json.dumps(info),flush=True)
        # Выбранное исправление: убрать ClientIP. Оно уже представлено normal
        # с тем же расписанием, backend и тремя полными повторами обоих трафиков.
        save('b-fix.json',{'before':'sticky','after':'normal','change':'sessionAffinity: ClientIP -> None',
                           'matching_schedule':True,'backend_unchanged':True,'keep_alive_unchanged':True,
                           'evidence':'b-summary.json: три повтора каждой политики и трафика'})
        print('Waiting for alerts to return to inactive',flush=True);time.sleep(45)
    print('EXPERIMENT B COMPLETE',flush=True)

if __name__=='__main__':main()
