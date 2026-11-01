"""Каждая HTTP-попытка сохраняется, включая ошибки; JSON измеряет полную задержку."""
import argparse,csv,json,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8091')
    parser.add_argument('--n',type=int,choices=[4,8],default=8)
    args=parser.parse_args()
    rows=[json.loads(x) for x in (ROOT/'.runtime/real/hw67-evidence/data/eval/golden.jsonl').read_text().splitlines()][:args.n]
    output=ROOT/'evidence/requests.jsonl';summaries=[]
    with output.open('w') as stream:
        for concurrency in (1,2):
            def call(row):
                started=time.perf_counter();item={'id':row['id'],'concurrency':concurrency,'max_new_tokens':32,'error':None,
                    'model_id':None,'generation_seconds':None,'queue_seconds':None,'output_tokens':None,'request_id':None}
                try:
                    req=Request(args.url+'/generate',data=json.dumps({'prompt':row['input'],'max_new_tokens':32}).encode(),
                                headers={'Content-Type':'application/json'})
                    try:r=urlopen(req,timeout=180)
                    except HTTPError as exc:r=exc
                    with r:status,body=r.status,json.load(r)
                    item.update(status=status,response=body,model_id=body.get('model_id'),
                        generation_seconds=body.get('generation_seconds'),queue_seconds=body.get('queue_seconds'),
                        output_tokens=body.get('output_tokens'),request_id=body.get('request_id'))
                    if status!=200:item['error']=str(body)
                except Exception as exc:item.update(status=None,error=f'{type(exc).__name__}: {exc}')
                item['client_seconds']=time.perf_counter()-started
                return item
            started=time.perf_counter();results=[]
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                for future in as_completed([pool.submit(call,row) for row in rows]):
                    result=future.result();results.append(result)
                    stream.write(json.dumps(result,ensure_ascii=False,allow_nan=False)+'\n');stream.flush()
            wall=time.perf_counter()-started;success=[r for r in results if r['status']==200 and r['error'] is None]
            errors=[r for r in results if r not in success]
            summary={'concurrency':concurrency,'n':len(results),'success':len(success),'errors':len(errors),
                'batch_seconds':wall,'successful_requests_per_second':len(success)/wall,
                'mean_success_seconds':sum(r['client_seconds'] for r in success)/len(success) if success else None,
                'max_success_seconds':max((r['client_seconds'] for r in success),default=None),
                'mean_error_seconds':sum(r['client_seconds'] for r in errors)/len(errors) if errors else None,
                'max_error_seconds':max((r['client_seconds'] for r in errors),default=None),
                'output_tokens':sum(r.get('output_tokens',0) or 0 for r in success)}
            summaries.append(summary)
    (ROOT/'evidence/benchmark.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2)+'\n')
    with (ROOT/'evidence/benchmark.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(summaries[0]));writer.writeheader();writer.writerows(summaries)
    print(json.dumps(summaries,ensure_ascii=False,indent=2))
    if any(s['errors'] for s in summaries):raise SystemExit(1)

if __name__=='__main__':main()
