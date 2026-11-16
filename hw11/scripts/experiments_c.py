"""Вычислительная нагрузка, HPA 2→3→2, горячий клиент и переходы алертов."""
import time,json
from common import *
from metrics import forward,alerts,export

def replicas():return json.loads(kubectl('get','deployment/hw11-api','-o','json'))['spec']['replicas']
def wait_scale(number,timeout=240):
    deadline=time.time()+timeout
    while time.time()<deadline:
        if replicas()==number:return time.time()
        time.sleep(3)
    raise AssertionError(f'HPA не достиг {number}')

def main():
    ready();upgrade(**{'hpa.enabled':True,'hpa.targetCPU':60,'hpa.stabilizationSeconds':45})
    kubectl('scale','deployment/hw11-api','--replicas=2');ready()
    save('c-metrics-api.json',json.loads(command('kubectl','get','--raw','/apis/metrics.k8s.io/v1beta1/pods')))
    start=time.time();events={'start':start,'configured_stabilization_seconds':45}
    with forward(),alerts('c'),watch('c-hpa'):
        plan=schedule('c-cpu',120,10,chunks=2,delay=.03)
        job=start_load('c-cpu',plan);events['load_start']=job['start']
        events['observed_three']=wait_scale(3);ready();events['three_ready']=time.time()
        rows=finish_load(job);events['load_finished']=time.time();events['cpu_summary']=summarize(rows)
        events['observed_two']=wait_scale(2);ready();events['two_ready']=time.time()
        events['downscale_delay_seconds']=events['two_ready']-events['load_finished']
        events['hpa_after_low_load']=json.loads(kubectl('get','hpa/hw11-api','-o','json'))
        # Повторный перекос при существующей привязке IP и включённом HPA.
        time.sleep(5);reset_caches()
        plan=schedule('c-hot',120,4,traffic='hot',chunks=4,delay=.09)
        job=start_load('c-hot',plan,service='hw11-sticky');events['hot_start']=job['start'];hot=finish_load(job)
        events['hot_summary']=summarize(hot);events['hot_pods']=api_pods();events['hot_end']=time.time()
        # Перегрузка длинными потоками вызывает обе заданные тревоги.
        plan=schedule('c-alerts',45,18,traffic='hot',chunks=8,delay=.12)
        job=start_load('c-alerts',plan,service='hw11-sticky');bad=finish_load(job);events['alerts_summary']=summarize(bad)
        time.sleep(50)
        events['final_observed_two']=wait_scale(2);ready()
        export('c',start,time.time());events['end']=time.time()
        events['final_hpa']=json.loads(kubectl('get','hpa/hw11-api','-o','json'))
    save('c-summary.json',events);collect_logs('c-final')
    print('EXPERIMENT C COMPLETE',json.dumps(events,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
