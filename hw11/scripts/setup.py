"""Только собственный kind-кластер hw11; остальные контейнеры не затрагиваются."""
import hashlib,json,os,subprocess,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];os.chdir(ROOT)
ENV={**os.environ,'KUBECONFIG':str(ROOT/'.runtime/kubeconfig'),'PATH':str(ROOT/'.tools')+':'+os.environ['PATH']}
def run(*args):
 print('$',' '.join(args),flush=True);return subprocess.check_output(args,env=ENV,text=True,stderr=subprocess.STDOUT)
def pull(image):
 print(run('docker','pull',image),flush=True)
 return json.loads(run('docker','image','inspect',image))[0]['RepoDigests'][0]
def main():
 locks={}
 for name,image in [('node','kindest/node:v1.34.0'),('python','python:3.12.11-slim-bookworm'),('prometheus','prom/prometheus:v3.5.0'),('grafana','grafana/grafana:12.1.1'),('metrics','registry.k8s.io/metrics-server/metrics-server:v0.8.0')]:
  locks[name]=pull(image)
 (ROOT/'source/images-lock.json').write_text(json.dumps(locks,indent=2)+'\n')
 digest=hashlib.sha256(b''.join(p.read_bytes() for p in sorted((ROOT/'src').glob('*.py')))+(ROOT/'scripts/client.py').read_bytes()+(ROOT/'requirements.txt').read_bytes()).hexdigest()[:12]
 image='hw11-service:'+digest
 print(run('docker','build','--build-arg','BASE_IMAGE='+locks['python'],'-t',image,'.'),flush=True)
 cfg={'kind':'Cluster','apiVersion':'kind.x-k8s.io/v1alpha4','name':'hw11','nodes':[{'role':'control-plane','image':locks['node']}], 'networking':{'kubeProxyMode':'iptables'}}
 (ROOT/'.runtime/kind.json').write_text(json.dumps(cfg))
 if 'hw11' not in run('kind','get','clusters').split():
  print(run('kind','create','cluster','--config',str(ROOT/'.runtime/kind.json'),'--kubeconfig',ENV['KUBECONFIG'],'--wait','180s'),flush=True)
 print(run('docker','update','--memory','3g','--memory-swap','3g','--cpus','4','hw11-control-plane'),flush=True)
 print(run('kind','load','docker-image',image,'--name','hw11'),flush=True)
 # Docker 29 экспортирует многоархитектурный index с отсутствующими платформами.
 # Закреплённые сторонние образы kubelet получает прямо по digest через CRI.
 for img in [locks['prometheus'],locks['grafana'],locks['metrics']]:
  print(run('docker','exec','hw11-control-plane','crictl','pull',img),flush=True)
 values={'image':image,'monitoring':{'prometheusImage':locks['prometheus'],'grafanaImage':locks['grafana']}}
 old_values=ROOT/'source/installed-values.json'
 if old_values.exists() and json.loads(old_values.read_text()).get('image')!=image:
  print(run('kubectl','-n','hw11','delete','pod','-l','app=hw11-client','--ignore-not-found=true'),flush=True)
 (ROOT/'source/installed-values.json').write_text(json.dumps(values,indent=2)+'\n')
 print(run('helm','upgrade','--install','hw11','charts/hw11','-n','hw11','--create-namespace','-f','source/installed-values.json','--wait','--timeout','180s'),flush=True)
 url='https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.8.0/components.yaml'
 import yaml
 raw=urllib.request.urlopen(url).read().decode();(ROOT/'source/metrics-server-original.yaml').write_text(raw)
 docs=list(yaml.safe_load_all(raw))
 for obj in docs:
  if obj and obj['kind']=='Deployment':
   c=obj['spec']['template']['spec']['containers'][0];c['image']=locks['metrics']
   c['args'].extend(['--kubelet-insecure-tls','--metric-resolution=10s','--kubelet-request-timeout=5s'])
   c['resources']={'requests':{'cpu':'30m','memory':'64Mi'},'limits':{'cpu':'300m','memory':'160Mi'}}
 path=ROOT/'monitoring/metrics-server.yaml';path.write_text(yaml.safe_dump_all(docs))
 print(run('kubectl','apply','-f',str(path)),flush=True)
 print(run('kubectl','-n','kube-system','rollout','status','deployment/metrics-server','--timeout=120s'),flush=True)
 versions={name:run(*args) for name,args in {'kubectl':['kubectl','version','-o','json'],'kind':['kind','version'],'helm':['helm','version','--short']}.items()}
 versions['image']=json.loads(run('docker','image','inspect',image))[0];versions['node']=json.loads(run('docker','inspect','hw11-control-plane'))[0]
 (ROOT/'results/versions.json').write_text(json.dumps(versions,indent=2)+'\n')
 print('SETUP COMPLETE',flush=True)
if __name__=='__main__':main()
