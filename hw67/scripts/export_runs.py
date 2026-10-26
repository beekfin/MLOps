"""Экспортировать измерения и ссылки MLflow без весов моделей."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mlflow
from mlflow import MlflowClient
from src.common import connect, load_params, save_json


def main():
    params=load_params();connect(params);client=MlflowClient()
    summary=json.loads(Path('metrics/sweep.json').read_text())
    runs=[]
    for item in summary['rows']:
        run=client.get_run(item['run_id'])
        if run.info.status!='FINISHED':raise ValueError('Незавершённый кандидат')
        runs.append(dict(name=item['name'],run_id=run.info.run_id,status=run.info.status,
                         url=f"{mlflow.get_tracking_uri()}/#/experiments/{run.info.experiment_id}/runs/{run.info.run_id}",
                         params=run.data.params,tags=run.data.tags,metrics=run.data.metrics,
                         history={key:[dict(step=m.step,value=m.value,timestamp=m.timestamp) for m in client.get_metric_history(run.info.run_id,key)] for key in ['train_loss','val_loss']}))
    model=client.get_registered_model(params['registry']['name'])
    parent=client.get_run(summary['parent_id'])
    result=dict(parent_run_id=summary['parent_id'],parent_status=parent.info.status,
                parent_start_time=parent.info.start_time,parent_end_time=parent.info.end_time,
                parent_seconds=(parent.info.end_time-parent.info.start_time)/1000,runs=runs,
                registered_model=dict(name=model.name,aliases=model.aliases))
    save_json('metrics/runs-export.json',result)
    print('Exported',len(runs),'finished runs;',model.aliases)


if __name__=='__main__':main()
