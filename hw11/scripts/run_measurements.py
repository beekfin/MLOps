"""Последовательный запуск измерений; состояние и каждый вывод сохраняются."""
import json,os,re,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];os.chdir(ROOT)
def state(phase,**fields):
 value={'phase':phase,'unix':time.time(),**fields};(ROOT/'.runtime/status.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');print(json.dumps(value,ensure_ascii=False),flush=True)
def run(phase,args,log,env=None):
 state(phase)
 with (ROOT/log).open('w') as stream:subprocess.run(args,stdout=stream,stderr=subprocess.STDOUT,check=True,env=env)
try:
 state('waiting_for_kubernetes_tests')
 deadline=time.time()+600
 while time.time()<deadline:
  text=(ROOT/'results/kubernetes-tests.log').read_text()
  if '\nFAILED ' in text:raise RuntimeError('Kubernetes tests failed')
  if re.search(r'Ran 5 tests',text) and re.search(r'\nOK\s*$',text):break
  time.sleep(2)
 else:raise TimeoutError('Kubernetes tests не завершились за 10 минут')
 env={**os.environ,'HW11_K8S':'1'}
 run('verify_new_pod', [sys.executable,'-m','unittest','discover','-s','tests','-p','test_kubernetes.py','-k','test_03','-v'],'results/replacement-validation.log',env)
 run('experiment_b',[sys.executable,'-u','scripts/experiments_b.py'],'results/experiment-b.log')
 run('experiment_c',[sys.executable,'-u','scripts/experiments_c.py'],'results/experiment-c.log')
 run('footprint',[sys.executable,'scripts/footprint.py'],'results/footprint.log')
 run('report',[sys.executable,'scripts/report.py'],'results/report-build.log')
 run('audit',[sys.executable,'scripts/audit.py'],'results/audit.log')
 state('complete')
except Exception as exc:
 state('failed',error=f'{type(exc).__name__}: {exc}');raise
