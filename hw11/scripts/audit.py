"""Проверка полноты сдачи по сырым данным; не заменяет HTTP-тесты."""
import collections,hashlib,json,math,re
from pathlib import Path
from common import ROOT,RESULTS,save

def read(name):return json.loads((RESULTS/name).read_text())
def lines(path):return [json.loads(s) for s in path.read_text().splitlines() if s.strip()]
def main():
    checks=[]
    def check(name,condition,detail=None):
        checks.append({'requirement':name,'passed':bool(condition),'detail':detail})
        if not condition:print('FAIL',name,detail)
    b=read('b-summary.json');check('12 полных прогонов B',len(b)==12)
    for traffic in ['uniform','hot']:
        selected=[x for x in b if x['traffic']==traffic]
        check('Одинаковое расписание '+traffic,len({x['schedule_sha256'] for x in selected})==1)
        for policy in ['normal','sticky']:
            rr=[x for x in selected if x['policy']==policy];check(f'{policy}/{traffic}: 3 повтора',len(rr)==3)
    for row in b:
        rr=lines(RESULTS/'runs'/(row['run']+'.jsonl'));plan=json.loads((RESULTS/'schedules'/('b-'+row['traffic']+'.json')).read_text())
        check(row['run']+': 120 с, 480 попыток',row['measurement_seconds']>=120 and len(rr)==len(plan['requests'])==480)
        check(row['run']+': 4 клиента',len({x['client_id'] for x in rr})==4)
        check(row['run']+': завершённые имеют done',all(x['done'] and x['chunks']==4 for x in rr if x['outcome']=='completed'))
        meta=read('runs/'+row['run']+'-meta.json');reset_pods=set()
        for path in (RESULTS/'logs'/row['run']).glob('*.jsonl'):
            for text in path.read_text().splitlines():
                try:event=json.loads(text)
                except ValueError:continue
                if event.get('event')=='cache_reset' and meta['start']-20<=event['unix']<=meta['start']:
                    reset_pods.add(event['pod'])
        check(row['run']+': кеш сброшен на двух Pod',len(reset_pods)==2,sorted(reset_pods))
        compare=read('prometheus/'+row['run']+'-histogram-comparison.json')
        inf=[x for x in compare['buckets'] if x['metric']['le']=='+Inf']
        count=float(inf[0]['value'][1]) if inf else None
        check(row['run']+': тот же набор успехов в Histogram',count==row['completed'],{'client':row['completed'],'prometheus':count})
    a=read('a-warmup-summary.json')
    check('Дефект прогрева воспроизведён',a['a-warmup-before']['outcomes'].get('http_error',0)>0)
    check('Прогрев исправлен',a['a-warmup-after']['completed']==a['a-warmup-after']['sent'])
    rollout=read('a-rollout-summary.json');check('Штатное обновление без 5xx/обрывов',rollout['zero_5xx_and_unfinished'])
    rollback=read('a-rollback.json');check('Фактическая версия после отката A',rollback['response']['headers']['x-model-id']=='A')
    account=read('a-accounting.json');check('Принудительный обрыв записан',account['force_kill'][0]['outcome']=='interrupted' and account['force_kill'][0]['chunks']>0)
    isolation=read('dialog-isolation.json');check('Два изолированных диалога',len(isolation)==2 and 'BETA_ONLY_948' not in isolation[0]['text'] and 'ALPHA_ONLY_731' not in isolation[1]['text'])
    log=(RESULTS/'kubernetes-tests.log').read_text();check('5 собственных Kubernetes-проверок прошли',bool(re.search(r'Ran 5 tests',log) and re.search(r'\nOK\s*$',log)))
    c=read('c-summary.json');check('HPA 2→3→2',c['observed_three']<c['observed_two'] and c['downscale_delay_seconds']>=0)
    states=collections.defaultdict(set);observations=collections.defaultdict(list)
    for path in RESULTS.glob('*-alerts.jsonl'):
        for sample in lines(path):
            for group in sample.get('rules',{}).get('data',{}).get('groups',[]):
                for rule in group.get('rules',[]):
                    if rule.get('type')=='alerting':
                        states[rule['name']].add(rule['state']);observations[rule['name']].append((sample['unix'],rule['state']))
    for name in ['HighFirstChunkLatency','HighRejectionRate']:
        check(name+': inactive/pending/firing',{'inactive','pending','firing'}<=states[name],sorted(states[name]))
        ordered=sorted(observations[name]);check(name+': вернулся в inactive после firing',bool(ordered and ordered[-1][1]=='inactive' and any(s=='firing' for _,s in ordered)))
    peers=collections.defaultdict(set)
    for path in (RESULTS/'logs').rglob('*.jsonl'):
        for text in path.read_text().splitlines():
            try:r=json.loads(text)
            except ValueError:continue
            if r.get('event')=='request_arrived' and str(r.get('request_id','')).startswith('b-'):
                peers[r['request_id']].add(r.get('peer_ip'))
    ips=sorted({ip for pp in peers.values() for ip in pp if ip})
    save('b-source-ips.json',{'observed_ips':ips,'requests_with_peer':len(peers)})
    check('Service видит >=4 разных клиентских IP',len(ips)>=4,ips)
    for i,name in enumerate(['1-warmup-rollout','2-queue-by-pod','3-policy-comparison','4-hpa-load'],1):
        check('График '+str(i),(RESULTS/'plots'/(name+'.png')).is_file())
    check('HTML-отчёт',(ROOT/'report.html').is_file())
    save('audit.json',{'checks':checks,'passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks)})
    print(f"Проверено: {len(checks)}; провалено: {sum(not x['passed'] for x in checks)}")
    if any(not x['passed'] for x in checks):raise SystemExit(1)
if __name__=='__main__':main()
