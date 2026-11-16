"""Опыты A и пять проверок с реальными запросами из клиентских Pod."""
import json,time,uuid
from pathlib import Path
from common import *


def warmup():
    results={}
    for broken in [True,False]:
        name='a-warmup-'+('before' if broken else 'after')
        plan=schedule(name,35,2)
        with watch(name):
            job=start_load(name,plan)
            upgrade(brokenProbes=broken,warmupSeconds=20,modelVersion='A')
            ready();rows=finish_load(job)
        collect_logs(name);results[name]=summarize(rows)
        results[name]['rows']=len(rows)
    assert results['a-warmup-before']['outcomes'].get('http_error',0)>0,results
    assert results['a-warmup-after']['completed']==results['a-warmup-after']['sent'],results
    save('a-warmup-summary.json',results)
    return results


def rollout():
    name='a-rollout';plan=schedule(name,65,1)
    # Длительный поток начинается на старой A до запроса на замену.
    longplan=schedule('a-long-stream',1,1,chunks=70,delay=.4)
    with watch(name):
        longjob=start_load('a-long-stream',longplan,clients=1,lead=2)
        time.sleep(max(0,longjob['start']+2-time.time()))
        start=time.time();job=start_load(name,plan)
        upgrade(modelVersion='B',warmupSeconds=20);ready()
        rows=finish_load(job);longrows=finish_load(longjob)
    collect_logs(name)
    assert all(r['outcome']=='completed' for r in rows+longrows),(summarize(rows),longrows)
    assert longrows[0]['model_id']=='A' and longrows[0]['finished_mono']-longrows[0]['sent_mono']>25,longrows
    assert request()['headers']['x-model-id']=='B'
    save('a-rollout-summary.json',{'update_started':start,'short':summarize(rows),'long':longrows,'zero_5xx_and_unfinished':True})
    # Неготовая B: новая ревизия не получает рабочих запросов.
    with watch('a-bad-version'):
        upgrade(modelVersion='B',failWarmup=True,warmupSeconds=20)
        time.sleep(26)
        pods=api_pods();responses=[request() for _ in range(4)]
        assert all(r['status']==200 for r in responses)
        save('a-bad-version.json',{'pods':pods,'responses':responses,'endpoints':objects('endpointslices')})
        # Управляемый возврат к A; --wait отдельно сохраняет исходные состояния.
        upgrade(modelVersion='A',failWarmup=False,warmupSeconds=20);ready()
        returned=request();assert returned['headers']['x-model-id']=='A',returned
        save('a-rollback.json',{'response':returned,'pods':api_pods(),'endpoints':objects('endpointslices')})
    collect_logs('a-rollback')
    return returned


def replacement():
    first=request(payload={'prompt':'FIRST_CONTROL','history':[{'role':'user','content':'DIALOG_PERSIST_42'}],'session_id':'persist'})
    before_pods=api_pods();before_names={p['metadata']['name'] for p in before_pods}
    old=first['headers']['x-pod'];old_ip=next(p['status']['podIP'] for p in before_pods if p['metadata']['name']==old)
    with watch('a-replacement'):
        kubectl('delete','pod',old,'--wait=false')
        kubectl('wait','--for=delete','pod/'+old,'--timeout=90s')
        time.sleep(2);kubectl('wait','--for=condition=Ready','pods','-l','app=hw11-api','--timeout=150s')
        ready();new=next(p for p in api_pods() if p['metadata']['name'] not in before_names)
        history=[{'role':'user','content':'DIALOG_PERSIST_42'},{'role':'assistant','content':'FIRST_CONTROL'}]
        after=request('http://'+new['status']['podIP']+':8000',payload={'prompt':'CONTINUE','history':history,'session_id':'persist'})
        assert after['headers']['x-pod']==new['metadata']['name']
    assert old not in [p['metadata']['name'] for p in api_pods()]
    assert after['status']==200 and after['headers']['x-model-id']==first['headers']['x-model-id']=='A'
    assert 'DIALOG_PERSIST_42' in after['text']
    save('a-replacement.json',{'old_pod':old,'old_ip':old_ip,'first':first,'after':after,'pods':api_pods()})
    collect_logs('a-replacement');return after


def accounting():
    # Контролируемый избыток нагрузки; каждый отказ — отдельная строка клиента.
    plan=schedule('a-overload',8,35,chunks=8,delay=.15)
    job=start_load('a-overload',plan);rows=finish_load(job)
    assert any(r['outcome']=='rejected' for r in rows),summarize(rows)
    assert len(rows)==len(json.loads(plan.read_text())['requests'])
    collect_logs('a-overload')
    # Принудительное удаление: grace=0, поток обрывается; штатный drain не успевает.
    target=api_pods()[0];pod=target['metadata']['name'];ip=target['status']['podIP']
    plan=schedule('a-force-kill',1,1,chunks=70,delay=.4)
    with watch('a-force-kill'):
        kubectl('cp',str(plan),'client-0:/work/plan-a-force-kill.json')
        job={'name':'a-force-kill','plan':str(plan.relative_to(ROOT)),'service':'direct-pod'}
        start=time.time()+2
        args=['kubectl','-n','hw11','exec','client-0','--','python','/app/client.py','--url',f'http://{ip}:8000',
              '--schedule','/work/plan-a-force-kill.json','--output','/work/a-force-kill.jsonl','--start',str(start),'--client','0','--run-id','a-force-kill']
        log=(ROOT/'.runtime/a-force-kill-client-0.log').open('w')
        import subprocess
        process=subprocess.Popen(args,cwd=ROOT,env=ENV,stdout=log,stderr=subprocess.STDOUT)
        job['processes']=[(0,process,log)];job['start']=start
        time.sleep(max(0,start+3-time.time()))
        before_logs=kubectl('logs',pod,check=False)
        (RESULTS/'logs/force-before.jsonl').write_text(before_logs)
        crash_at=time.time()
        kubectl('delete','pod',pod,'--grace-period=0','--force','--wait=false')
        killed=finish_load(job)
        assert killed[0]['outcome']=='interrupted' and killed[0]['chunks']>0,killed
        # ReplicaSet создаёт замену, она проходит прогрев и возвращается в endpoints.
        time.sleep(3);ready()
        recovered=request();assert recovered['status']==200
    save('a-accounting.json',{'overload':summarize(rows),'force_kill':killed,'crash_unix':crash_at,'recovered':recovered,'recovered_unix':time.time()})
    (RESULTS/'logs/force-previous.jsonl').write_text(kubectl('logs',pod,'--previous',check=False))
    collect_logs('a-after-crash')
    return rows,killed


def isolation():
    results=[]
    for tag,foreign in [('ALPHA_ONLY_731','BETA_ONLY_948'),('BETA_ONLY_948','ALPHA_ONLY_731')]:
        response=request(payload={'prompt':'Продолжи мой диалог','history':[{'role':'user','content':tag}], 'session_id':tag})
        assert response['status']==200 and tag in response['text'] and foreign not in response['text'],response
        results.append(response)
    save('dialog-isolation.json',results);return results

if __name__=='__main__':
    for name,fn in [('warmup',warmup),('rollout',rollout),('replacement',replacement),('accounting',accounting),('isolation',isolation)]:
        print('START',name,flush=True);fn();print('PASS',name,flush=True)
