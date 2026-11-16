"""Загрузить закреплённые CLI в .tools без изменения системы."""
import hashlib,json,os,tarfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'.tools';out.mkdir(exist_ok=True)
records={}
def get(url,target):
 if not target.exists():
  print('Download',url,flush=True)
  with urllib.request.urlopen(url,timeout=90) as response:target.write_bytes(response.read())
 return target
for name,url,shaurl in [
 ('kind','https://kind.sigs.k8s.io/dl/v0.30.0/kind-linux-amd64','https://kind.sigs.k8s.io/dl/v0.30.0/kind-linux-amd64.sha256sum'),
 ('kubectl','https://dl.k8s.io/release/v1.34.0/bin/linux/amd64/kubectl','https://dl.k8s.io/release/v1.34.0/bin/linux/amd64/kubectl.sha256')]:
 p=get(url,out/name);sha=get(shaurl,out/(name+'.sha256')).read_text().split()[0]
 assert hashlib.sha256(p.read_bytes()).hexdigest()==sha,name
 p.chmod(0o755);records[name]={'url':url,'sha256':sha}
p=get('https://get.helm.sh/helm-v3.19.0-linux-amd64.tar.gz',out/'helm.tar.gz')
sha=get('https://get.helm.sh/helm-v3.19.0-linux-amd64.tar.gz.sha256sum',out/'helm.sha256').read_text().split()[0]
assert hashlib.sha256(p.read_bytes()).hexdigest()==sha
with tarfile.open(p) as tar:
 (out/'helm').write_bytes(tar.extractfile('linux-amd64/helm').read())
(out/'helm').chmod(0o755);records['helm']={'version':'v3.19.0','sha256':sha}
(ROOT/'source/tools-lock.json').write_text(json.dumps(records,indent=2)+'\n')
