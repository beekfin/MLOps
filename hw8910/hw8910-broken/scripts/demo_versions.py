"""Управляемый опыт A→B→A только с лёгкими явно помеченными STUB-артефактами."""
import json,socket,subprocess,sys,time,uuid
from pathlib import Path
from urllib import request,error
ROOT=Path(__file__).resolve().parents[1]


def main():
    root=ROOT/'.runtime'/('versions-'+uuid.uuid4().hex[:8]);observations=[];process=None;url=''
    def cli(*args):
        result=subprocess.run([sys.executable,str(ROOT/'lab.py'),'--workspace',str(root),*args],
            cwd=ROOT,capture_output=True,text=True)
        observations.append({'command':['lab.py',*args],'exit_code':result.returncode,
                             'stdout':result.stdout,'stderr':result.stderr})
        assert result.returncode==0,result.stderr
    def call(path,payload=None):
        data=None if payload is None else json.dumps(payload).encode()
        req=request.Request(url+path,data=data,headers={'Content-Type':'application/json'})
        try:r=request.urlopen(req,timeout=5)
        except error.HTTPError as exc:r=exc
        with r:status,body=r.status,json.load(r)
        observations.append({'path':path,'status':status,'body':body})
        return status,body
    def start():
        nonlocal process,url
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
        process=subprocess.Popen([sys.executable,str(ROOT/'service.py'),'--workspace',str(root),
            '--port',str(port),'--warmup-seconds','1'],cwd=ROOT,stdout=log,stderr=log)
        for _ in range(200):
            try:
                if call('/health')[0]==200:break
            except OSError:time.sleep(.03)
        else:raise RuntimeError('Нет HTTP-сервера')
        for _ in range(200):
            if call('/ready')[0]==200:break
            time.sleep(.03)
        else:raise RuntimeError('Нет готовности')
    def stop():
        if process and process.poll() is None:
            process.terminate();process.wait(timeout=10)
    def observe(label,expected):
        status,body=call('/generate',{'prompt':'Which model is loaded?'})
        assert status==200 and body['model_id']==expected and expected in body['answer']
        observations.append({'phase':label,'model_id':body['model_id'],'runtime_sha256':body['runtime_sha256']})
    cli('init')
    with (ROOT/'evidence/stub-versions-server.log').open('w') as log:
        try:
            start();observe('initial A','fixture-A')
            cli('run');observe('B published; A still loaded','fixture-A');stop()
            start();observe('B loaded after restart','fixture-B')
            cli('run','--manifest','manifest-A.json','--report','report-A.json')
            observe('rollback pointer A; B still loaded','fixture-B');stop()
            start();observe('A loaded after rollback restart','fixture-A')
        finally:stop()
    (ROOT/'evidence/stub-versions.json').write_text(json.dumps(observations,ensure_ascii=False,indent=2)+'\n')
    print('STUB ONLY: A → publish B / still A → restart B → rollback A / still B → restart A')

if __name__=='__main__':main()
