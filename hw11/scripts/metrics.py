"""Запросы Prometheus и экспорт метрик/алертов без потери сырых рядов."""
import contextlib,json,subprocess,threading,time
import httpx
from common import ROOT,RESULTS,ENV,save
BASE='http://127.0.0.1:19090'

@contextlib.contextmanager
def forward():
    log=(ROOT/'.runtime/prometheus-port-forward.log').open('a')
    p=subprocess.Popen(['kubectl','-n','hw11','port-forward','svc/prometheus','19090:9090'],env=ENV,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                if httpx.get(BASE+'/-/ready',timeout=2).status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.5)
        else:raise RuntimeError('Prometheus недоступен')
        yield
    finally:p.terminate();p.wait(timeout=10);log.close()

def query(expr,at=None):
    params={'query':expr}
    if at is not None:params['time']=str(at)
    value=httpx.get(BASE+'/api/v1/query',params=params,timeout=30).json()
    if value['status']!='success':raise RuntimeError(value)
    return value['data']['result']

@contextlib.contextmanager
def alerts(name):
    stop=threading.Event();path=RESULTS/(name+'-alerts.jsonl')
    def worker():
        with path.open('w') as stream:
            while not stop.is_set():
                try:
                    value=httpx.get(BASE+'/api/v1/rules',timeout=5).json()
                    stream.write(json.dumps({'unix':time.time(),'rules':value})+'\n');stream.flush()
                except Exception as exc:stream.write(json.dumps({'unix':time.time(),'error':str(exc)})+'\n')
                stop.wait(2)
    t=threading.Thread(target=worker,daemon=True);t.start()
    try:yield
    finally:stop.set();t.join(timeout=10)

def export(name,start,end):
    expressions={
        'ttfc_p95':'histogram_quantile(0.95, sum by (le,pod) (rate(hw11_ttfc_seconds_bucket[30s])))',
        'running':'hw11_running','waiting':'hw11_waiting','ready':'hw11_ready',
        'cpu':'sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="hw11",container="api"}[30s]))',
        'memory':'container_memory_working_set_bytes{namespace="hw11",container="api"}',
        'completion_rate':'sum by (pod) (rate(hw11_requests_total{outcome="completed"}[30s]))'}
    data={}
    for key,expr in expressions.items():
        response=httpx.get(BASE+'/api/v1/query_range',params={'query':expr,'start':start,'end':end,'step':2},timeout=30).json()
        data[key]={'promql':expr,'response':response}
    save('prometheus/'+name+'.json',data)
    return data

def histogram_comparison(name,start,end,rows):
    # Оба снимка сделаны в паузах без запросов, Pod не менялись между снимками.
    expr=f'sum by (le) (hw11_ttfc_seconds_bucket @ {end:.3f}) - sum by (le) (hw11_ttfc_seconds_bucket @ {start:.3f})'
    counts=query(expr);quantile=query('histogram_quantile(0.95, ('+expr+'))')
    from common import summarize
    result={'start':start,'end':end,'promql':'histogram_quantile(0.95, ('+expr+'))','buckets':counts,'prometheus_p95':quantile,'client':summarize(rows),
            'note':'Гистограмма наблюдает только полностью завершённые ответы. Клиент включает доставку по сети; Prometheus интерполирует внутри bucket.'}
    save('prometheus/'+name+'-histogram-comparison.json',result)
    return result
