"""Готовность, реальный ответ и 422 до backend; выполняется после старта сервера."""
import argparse,json,time
from pathlib import Path
from urllib import request,error
ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8091')
    parser.add_argument('--name',default='real-api');args=parser.parse_args();trace=[]
    def call(path,payload=None):
        data=None if payload is None else json.dumps(payload).encode()
        req=request.Request(args.url+path,data=data,headers={'Content-Type':'application/json'})
        try:r=request.urlopen(req,timeout=90 if path=='/generate' else 4)
        except error.HTTPError as exc:r=exc
        with r:status,body=r.status,json.load(r)
        entry={'path':path,'status':status,'body':body};trace.append(entry)
        return entry
    started=time.monotonic()
    try:
        while time.monotonic()-started < 240:
            try:
                health=call('/health');ready=call('/ready')
                if ready['status']==200:break
            except (OSError,error.URLError):pass
            time.sleep(.25)
        else:raise RuntimeError('Сервис не готов за 240 секунд')
        before=call('/debug')['body']['calls']
        bad=call('/generate',{'prompt':'Hello','max_new_tokens':100000})
        after=call('/debug')['body']['calls']
        assert bad['status']==422 and before==after
        source=ROOT/'.runtime/real/hw67-evidence'
        row=json.loads((source/'data/eval/golden.jsonl').read_text().splitlines()[0])
        actual=call('/generate',{'prompt':row['input'],'max_new_tokens':32})
        expected=json.loads((ROOT/'.runtime/real/accepted.json').read_text())
        assert actual['status']==200
        body=actual['body']
        assert body['model_id']==expected['model_id'] and body['runtime_sha256']==expected['runtime_sha256']
        assert 'STUB ONLY' not in body['answer']
        saved={r['id']:r for r in json.loads((source/'metrics/candidate-outputs.json').read_text())}
        assert body['answer']==saved[row['id']]['raw'],(body,saved[row['id']])
        summary={'ready':True,'loaded_model_id':body['model_id'],'runtime_sha256':body['runtime_sha256'],
            'invalid_status':bad['status'],'calls_before_invalid':before,'calls_after_invalid':after,
            'real_response':actual,'matches_saved_evaluation':True,'elapsed_seconds':time.monotonic()-started}
    finally:
        (ROOT/'metrics'/f'{args.name}-http.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'metrics'/f'{args.name}.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
