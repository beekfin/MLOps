"""Опыты на временных копиях: старый допуск и сохранность принятой модели.

Нужны история Git и отдельно полученный артефакт; генерация не запускается.
"""
from pathlib import Path
import importlib.util,json,tempfile,shutil,subprocess,sys
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from src import model_release as current, release
original_source=current.SOURCE
results=[]
with tempfile.TemporaryDirectory() as tmp:
 tmp=Path(tmp)
 source=subprocess.check_output(['git','show','9399f12:hw8910/hw8910-broken/model_release.py'],cwd=root)
 oldpath=tmp/'old_release.py';oldpath.write_bytes(source)
 spec=importlib.util.spec_from_file_location('old_release',oldpath);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
 for case in ['changed_artifact_dtype','different_json_generation_type']:
  r=tmp/case;shutil.copytree(root/'.runtime/real',r)
  m=current.read(r/'manifest-model.json')
  if case=='changed_artifact_dtype':
   cfg=current.read(r/'artifact/manifest.json');cfg['model']['dtype']='float16'
   release.write_json(r/'artifact/manifest.json',cfg)
   m['file_hashes']['manifest.json']=current.file_hash(r/'artifact/manifest.json')
   m['model_sha256']=current.fingerprint(m['file_hashes']);m['runtime']['dtype']='float16'
  else:m['runtime']['generation']['do_sample']=0
  m['runtime_sha256']=current.fingerprint(m['runtime'])
  outcome=old.create_report(r,m,'old-report.json')
  assert outcome['passed'] is True
  try:current.create_report(r,m,'new-report.json')
  except ValueError as exc:reason=str(exc)
  else:raise AssertionError('Несовместимое изменение принято')
  assert current.read(r/'new-report.json')['passed'] is False
  results.append({'case':case,'old_commit':'9399f12','old_passed':outcome['passed'],'fixed_rejected':True,'reason':reason,
     'note':'Только временная копия; исходные веса, оценка и принятая модель не изменены'})
(root/'metrics/audit-binding-regressions.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(results,ensure_ascii=False,indent=2))
# Проверить, что неудачная подготовка не уничтожает файлы уже принятой модели.
preparation=[]
with tempfile.TemporaryDirectory() as tmp:
 for label in ['old','fixed']:
  project=Path(tmp)/label;target=project/'.runtime/real';target.parent.mkdir(parents=True)
  shutil.copytree(root/'.runtime/real',target)
  incoming=project/'.runtime/import/model/artifacts/adapter';incoming.parent.mkdir(parents=True)
  shutil.copytree(root/'.runtime/real/artifact',incoming)
  record_directory=project/('evidence' if label=='old' else 'metrics')
  record_directory.mkdir();shutil.copy2(root/'metrics/model-source.json',record_directory/'model-source.json')
  shutil.copy2(root/'lab.py',project/'lab.py')
  cfg=current.read(incoming/'manifest.json');cfg['model']['dtype']='float16';release.write_json(incoming/'manifest.json',cfg)
  pointer=(target/'accepted.json').read_bytes()
  before={p.name:current.file_hash(p) for p in (target/'artifact').iterdir() if p.is_file()}
  module=old if label=='old' else current
  module.PROJECT=project;module.SOURCE=original_source
  rejected=False
  try:module.prepare(target)
  except ValueError:rejected=True
  after={p.name:current.file_hash(p) for p in (target/'artifact').iterdir() if p.is_file()}
  assert (before==after)==(label=='fixed')
  assert (target/'accepted.json').read_bytes()==pointer
  if label=='fixed':assert rejected
  preparation.append({'implementation':label,'rejected':rejected,'pointer_unchanged':True,'all_accepted_files_unchanged':before==after})
(root/'metrics/audit-prepare-preserves-accepted.json').write_text(json.dumps(preparation,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(preparation,ensure_ascii=False,indent=2))
