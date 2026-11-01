"""Одни и те же собственные проверки запускаются против двух версий проекта."""
from pathlib import Path
import json,os,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parent
ORIGINAL='e4cf8ad'

def main():
    evidence=ROOT/'metrics';evidence.mkdir(exist_ok=True)
    summary={}
    with tempfile.TemporaryDirectory(prefix='hw8910-original-') as tmp:
        subject=Path(tmp)
        for name in ['release.py','lab.py','service.py']:
            data=subprocess.check_output(['git','show',f'{ORIGINAL}:hw8910/hw8910-broken/{name}'],cwd=REPO)
            (subject/name).write_bytes(data)
        for label,project in [('before',subject),('after',ROOT)]:
            env={**os.environ,'HW8910_PROJECT':str(project),'HW8910_EVIDENCE':str(evidence/label)}
            command=[sys.executable,'-m','unittest','discover','-s','tests','-p','test_integration.py','-v']
            result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True)
            (evidence/f'{label}-integration.log').write_text(result.stdout+result.stderr)
            summary[label]={'command':command,'exit_code':result.returncode,'subject':ORIGINAL if label=='before' else 'working tree'}
            if (label=='before' and result.returncode==0) or (label=='after' and result.returncode!=0):
                raise RuntimeError(f'Неожиданный результат {label}: {result.stdout}{result.stderr}')
    (evidence/'regression-proof.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
