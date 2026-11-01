"""Воспроизводимые опыты с настоящими процессами, файлами и локальным Prefect."""
import hashlib,json,os,subprocess,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src import release


def main():
    out=ROOT/'metrics';out.mkdir(exist_ok=True)
    experiments=ROOT/'.runtime/experiments'/uuid.uuid4().hex[:8];experiments.mkdir(parents=True,exist_ok=True)
    traces=[]
    def run(name,args,expected=0):
        command=[sys.executable,*args]
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=180)
        (out/(name+'.log')).write_text(f'$ {command}\nexit={result.returncode}\n'+result.stdout+result.stderr)
        traces.append({'experiment':name,'command':command,'exit_code':result.returncode})
        assert (result.returncode==0)==(expected==0),(name,result.stdout,result.stderr)
        return result
    def init(name):
        p=experiments/name
        if p.exists():raise FileExistsError(f'Для повторения выберите новый каталог или удалите только {p}')
        run(name+'-init',['lab.py','--workspace',str(p),'init']);return p
    def flow(name,p,*flags,expected=0):
        return run(name,['-m','src.pipeline','--workspace',str(p),*flags],expected)
    p=init('cache')
    flow('flow-failed-after-prepare',p,'--fail-after-prepare',expected=1)
    recovered=flow('flow-recovered',p)
    assert 'Cached(type=COMPLETED)' in recovered.stdout+recovered.stderr
    flow('flow-identical-repeat',p)
    (p/'input.txt').write_text('Изменённый вход по прежнему пути\n')
    changed=flow('flow-changed-input',p)
    assert 'PREPARED' in changed.stdout+changed.stderr
    config=json.loads((p/'config.json').read_text());config['template_sha256']='f'*64
    release.write_json(p/'config.json',config)
    changed=flow('flow-changed-template',p)
    assert 'PREPARED' in changed.stdout+changed.stderr
    events=(p/'publications.jsonl').read_text().splitlines();assert len(events)==1
    p=init('refusals');before=hashlib.sha256((p/'accepted.json').read_bytes()).hexdigest()
    negative=[]
    nan=json.loads((p/'report-B.json').read_text());nan['metrics']['accuracy']=float('nan')
    (p/'report-nan.json').write_text(json.dumps(nan))
    for report in ['report-incomplete.json','report-A.json','report-reject.json','report-nan.json']:
        run('refuse-'+report,['lab.py','--workspace',str(p),'run','--report',report],expected=1)
        after=hashlib.sha256((p/'accepted.json').read_bytes()).hexdigest()
        assert before==after
        negative.append({'report':report,'before_sha256':before,'after_sha256':after,'unchanged':True})
    # Ошибка атомарной замены внесена через mock, а не заполнением диска.
    from unittest.mock import patch
    from src import lab
    try:
        with patch('os.replace',side_effect=OSError('controlled disk failure')):
            release.publish(lab.read(p/'manifest-B.json'),lab.read(p/'report-B.json'),p/'accepted.json')
    except OSError:pass
    else:raise AssertionError('Ошибка записи не вышла наружу')
    assert hashlib.sha256((p/'accepted.json').read_bytes()).hexdigest()==before
    negative.append({'report':'os.replace failure','before_sha256':before,'after_sha256':before,'unchanged':True})
    release.write_json(out/'negative-publication.json',negative)
    p=init('pointer-crash')
    run('crash-after-pointer',['lab.py','--workspace',str(p),'run','--fail-after-pointer'],expected=1)
    assert json.loads((p/'accepted.json').read_text())['model_id']=='fixture-B'
    run('recover-pointer-journal',['lab.py','--workspace',str(p),'run'])
    run('repeat-after-recovery',['lab.py','--workspace',str(p),'run'])
    assert len((p/'publications.jsonl').read_text().splitlines())==1
    release.write_json(out/'publication-recovery.json',{'accepted':json.loads((p/'accepted.json').read_text()),
        'journal':json.loads((p/'release-state.json').read_text()),'events':1})
    release.write_json(out/'process-experiments.json',traces)
    print('Опыты восстановления, кеша, отказа и повторной публикации завершены.')

if __name__=='__main__':main()
