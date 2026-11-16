"""Размер собственного стенда без удаления общих Docker-образов."""
import json,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
locks=json.loads((ROOT/'source/images-lock.json').read_text());values=json.loads((ROOT/'source/installed-values.json').read_text())
images={}
for image in [*locks.values(),values['image']]:
 info=json.loads(subprocess.check_output(['docker','image','inspect',image]))[0]
 images[image]={'id':info['Id'],'bytes':info['Size']}
node=json.loads(subprocess.check_output(['docker','container','inspect','--size','hw11-control-plane']))[0]
volumes={}
for mount in node['Mounts']:
 if mount['Type']=='volume':
  value=subprocess.check_output(['docker','exec','hw11-control-plane','du','-s','-B1',mount['Destination']],text=True)
  volumes[mount['Destination']]={'volume_name':mount['Name'],'allocated_bytes':int(value.split()[0])}
bytes_files=sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file())
size={'unix':time.time(),'images':images,'images_sum_bytes_unshared_upper_bound':sum(x['bytes'] for x in images.values()),
      'node_writable_bytes':node.get('SizeRw'),'node_volumes':volumes,'node_volumes_allocated_bytes':sum(x['allocated_bytes'] for x in volumes.values()),
      'node_limits':{'memory_bytes':node['HostConfig']['Memory'],'nano_cpus':node['HostConfig']['NanoCpus']},
      'hw11_directory_logical_bytes_includes_tools_and_venv':bytes_files,
      'note':'Сумма размеров образов — верхняя оценка без вычитания общих слоёв. Внутренние образы containerd находятся в отдельном Docker-томе /var, его размер учтён отдельно; SizeRw контейнера не включает этот том. Это оценка занятого диска, а не RAM.',
      'docker_system_df':subprocess.check_output(['docker','system','df'],text=True)}
(ROOT/'results/footprint.json').write_text(json.dumps(size,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(size,ensure_ascii=False,indent=2))
