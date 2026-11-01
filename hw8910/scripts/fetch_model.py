"""Получить конкретную версию MLflow без установки MLflow в быстрый контур."""
import argparse,json,sys,time
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import quote,urlencode
from urllib.error import URLError,HTTPError
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));from src import release


def get(url):
    for attempt in range(3):
        try:
            with urlopen(url,timeout=60) as r:return r.read()
        except HTTPError as exc:
            if exc.code<500 or attempt==2:raise
        except (URLError,TimeoutError):
            if attempt==2:raise
        time.sleep(.3*(attempt+1))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--tracking-uri',default='http://127.0.0.1:5006')
    args=parser.parse_args()
    source=ROOT.parent/'hw67'
    if not (source/'metrics/candidate-model.json').is_file():source=ROOT/'metrics/hw67'
    spec=json.loads((source/'metrics/candidate-model.json').read_text())
    query=urlencode({'name':spec['name'],'version':spec['version']})
    version=json.loads(get(args.tracking_uri+'/api/2.0/mlflow/model-versions/get?'+query))['model_version']
    if version['run_id']!=spec['run_id']:raise ValueError('В реестре другой training run')
    run=json.loads(get(args.tracking_uri+'/api/2.0/mlflow/runs/get?'+urlencode({'run_id':spec['run_id']})))['run']
    if run['info']['status']!='FINISHED':raise ValueError('Обучение не завершено')
    artifact_uri=run['info']['artifact_uri']
    if not artifact_uri.startswith('mlflow-artifacts:/'):raise ValueError('Нужен локальный MLflow artifact proxy')
    prefix=artifact_uri[len('mlflow-artifacts:/'):].strip('/')+'/model/artifacts/adapter/'
    target=ROOT/'.runtime/import/model/artifacts/adapter';target.mkdir(parents=True,exist_ok=True)
    hashes={};payloads={}
    for name in ['adapter_config.json','adapter_model.safetensors','manifest.json','tokenizer.json','tokenizer_config.json','chat_template.jinja']:
        payload=get(args.tracking_uri+'/api/2.0/mlflow-artifacts/artifacts/'+quote(prefix+name,safe='/'))
        payloads[name]=payload;hashes[name]=release.digest(payload)
    record=ROOT/'metrics/model-source.json'
    if record.is_file():
        previous=json.loads(record.read_text())
        if previous['run_id']==spec['run_id'] and previous['files']!=hashes:
            raise ValueError('Изменены файлы прежнего training run; старую оценку использовать нельзя')
    for name,payload in payloads.items():release.atomic_bytes(target/name,payload)
    release.write_json(ROOT/'metrics/model-source.json',{'registry':version,'run_id':spec['run_id'],
        'artifact_uri':artifact_uri,'files':hashes,'operation':'read existing completed run; no training'})
    print('Артефакт получен:',target)

if __name__=='__main__':main()
