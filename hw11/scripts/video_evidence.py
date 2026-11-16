"""Кадры с извлечениями из сохранённых доказательств; без повторного запуска стенда."""
import hashlib,json,statistics
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];R=ROOT/'results'
def read(name):return json.loads((R/name).read_text())
def rows(name):return [json.loads(s) for s in (R/name).read_text().splitlines() if s.strip()]
def stamp(t):return datetime.fromtimestamp(t,timezone.utc).isoformat(timespec='seconds')
def response(r):
 first=json.loads(r['text'].splitlines()[0]);last=json.loads(r['text'].splitlines()[-1])
 return {k:first[k] for k in ['request_id','pod','model_id','artifact_sha256','session_id','text']}|{'http_status':r['status'],'done':last['done']}
def pretty(value):return json.dumps(value,ensure_ascii=False,indent=2).splitlines()
def make(title,source,values,duration=24):return {'title':title,'source':source,'values':values,'duration':duration,'evidence':True}
def enrich(scenes):
 inserts={};replace={}
 probes=(ROOT/'charts/hw11/templates/service.yaml').read_text();start=probes.index('          startupProbe:');end=probes.index('          lifecycle:',start)
 # Дословные строки исходного Helm-шаблона, без имитации терминала.
 inserts['Состав стенда и ограничения']=[make('Проверки запуска, готовности и жизни','charts/hw11/templates/service.yaml · дословный фрагмент',
  [s[10:] for s in probes[start:end].splitlines()]+['','Startup разрешает запуск остальных проверок после прогрева.', 'Readiness управляет трафиком; liveness проверяет жизнь процесса.'],28)]
 artifact=(ROOT/'charts/hw11/files/model-A.json').read_bytes();digest=hashlib.sha256(artifact).hexdigest()
 replacement=read('a-replacement.json');old=response(replacement['first']);new=response(replacement['after'])
 assert old['artifact_sha256']==new['artifact_sha256']==digest and old['pod']!=new['pod']
 inserts['Проверки запуска, готовности и жизни']=[make('Источник и проверка артефакта','charts/hw11/files/model-A.json · src/backend.py · a-replacement.json',[
  'Файл ConfigMap model-A.json:',*pretty(json.loads(artifact)), '', 'SHA256 фактических байтов:',digest,
  'При загрузке: digest(raw) == ARTIFACT_SHA256; иначе ValueError.',
  'До замены Pod: '+old['pod'],'После замены Pod: '+new['pod'],
  'Версия A и полный SHA256 в обоих HTTP-ответах совпали.'
 ],25)]
 # Реальный запрос до прогрева и два снимка исправленного EndpointSlice.
 early=None
 for p in sorted((R/'logs/a-warmup-before').glob('*.jsonl')):
  for line in p.read_text().splitlines():
   try:x=json.loads(line)
   except ValueError:continue
   if x.get('event')=='request_arrived' and x.get('ready') is False and x.get('request_id','').startswith('a-warmup-before'):
    early=x;break
  if early:break
 assert early is not None
 timeline=rows('a-warmup-after-timeline.jsonl');initial={p['metadata']['name'] for p in timeline[0]['objects']['items'] if p.get('kind')=='Pod'}
 samples=[];selected=None
 for sample in timeline:
  items=sample['objects']['items'];pods=[p for p in items if p.get('kind')=='Pod' and p['metadata'].get('labels',{}).get('app')=='hw11-api' and p['metadata']['name'] not in initial]
  for pod in pods:
   name=pod['metadata']['name'];ready=any(c['type']=='Ready' and c['status']=='True' for c in pod.get('status',{}).get('conditions',[]))
   if selected is None and not ready:selected=name
   if name!=selected or any(s['ready']==ready for s in samples):continue
   endpoints=[e for obj in items if obj.get('kind')=='EndpointSlice' and obj['metadata'].get('labels',{}).get('kubernetes.io/service-name')=='hw11-normal' for e in obj['endpoints'] if e.get('targetRef',{}).get('name')==name]
   samples.append({'time_utc':stamp(sample['unix']),'pod':name,'ready':ready,'endpoint_ready':[e.get('conditions',{}).get('ready') for e in endpoints]})
 assert len(samples)==2
 inserts['Прогрев: исходный дефект и исправление']=[make('Журнал запроса и фактические endpoints','logs/a-warmup-before/ · a-warmup-after-timeline.jsonl · выборка',[
  'До исправления: реальный request_arrived при ready=false',
  'UTC: '+stamp(early['unix']),'request_id: '+early['request_id'],'pod: '+early['pod'],
  'model_id: '+str(early['model_id'])+'; ready: false','',
  'После исправления, одна и та же новая копия:',*['UTC '+s['time_utc']+' | Ready='+str(s['ready'])+' | endpoint.ready='+str(s['endpoint_ready']) for s in samples],
  'pod: '+selected,'Непрогретая копия исключена из рабочих адресов.'
 ],27)]
 bad=read('a-bad-version.json');bad_names={p['metadata']['name'] for p in bad['pods'] if not any(c['type']=='Ready' and c['status']=='True' for c in p['status'].get('conditions',[]))}
 served={r['headers']['x-pod'] for r in bad['responses']};assert bad_names and not bad_names&served
 rollback=response(read('a-rollback.json')['response']);assert rollback['model_id']=='A'
 inserts['Активный ответ пережил начало обновления']=[make('Неготовая B и настоящий ответ после отката','a-bad-version.json · a-rollback.json · выбранные поля HTTP-ответа',[
  'Неготовый Pod B, Ready=False:',*sorted(bad_names),'Он отсутствует среди Pod, обслуживших контрольные запросы.',
  'После возврата к A:',*pretty(rollback)
 ],27)]
 inserts['Отказ и восстановление проверены отдельно']=[make('Продолжение диалога на новой копии','a-replacement.json · выбранные поля сохранённого HTTP-ответа',[
  'До удаления: '+old['pod'],'history: DIALOG_PERSIST_42 | FIRST_CONTROL',
  'Реальный ответ новой копии:',*pretty(new)
 ],26)]
 iso=read('dialog-isolation.json');ir=[response(x) for x in iso]
 assert 'BETA_ONLY_948' not in ir[0]['text'] and 'ALPHA_ONLY_731' not in ir[1]['text']
 inserts['Продолжение диалога на новой копии']=[make('Два диалога и оборванный ответ','dialog-isolation.json · a-accounting.json · выбранные фактические поля',[
  *['session_id: '+r['session_id']+' | HTTP '+str(r['http_status'])+' | done='+str(r['done'])+'\nrequest_id: '+r['request_id']+'\ntext: '+r['text'] for r in ir],
  '', 'Принудительное завершение:',*pretty({k:read('a-accounting.json')['force_kill'][0][k] for k in ['request_id','pod','model_id','status','outcome','chunks','done']}),
  'done=false при HTTP 200 учитывается как обрыв, а не успех.'
 ],27)]
 # Полная таблица: 12 отдельных прогонов, без усреднения p50/p95 между ними.
 for traffic in ['uniform','hot']:
  table=['политика / повтор    n_OK / sent   p50, с   p95, с   ошибки   timeout']
  for row in read('b-summary.json'):
   if row['traffic']!=traffic:continue
   table.append(f"{row['policy']:>6} / {row['repeat']}          {row['completed']:3}/{row['sent']}      {row['ttfc_p50']:5.2f}    {row['ttfc_p95']:5.2f}    {row['error_rate']:5.1%}      {row['outcomes'].get('timeout',0)}")
  table+=['','p50/p95: время до первого фрагмента, только полные успешные ответы.',
          'n_OK — число наблюдений; ошибки — доля от всех отправленных попыток.',
          '4 запроса/с; каждый прогон 120 с; одинаковое расписание между политиками.']
  inserts.setdefault('Все три повтора, включая удачные случаи',[]).append(make('Все прогоны: '+('равномерный трафик' if traffic=='uniform' else '80% от одного клиента'),'results/b-summary.json · отдельные строки каждого прогона',table,26))
 # Разделить время создания Pod и наблюдения решения HPA.
 c=read('c-summary.json');created=[]
 for row in rows('c-hpa-timeline.jsonl'):
  for obj in row.get('objects',{}).get('items',[]):
   if obj.get('kind')=='Pod' and obj['metadata'].get('labels',{}).get('app')=='hw11-api':
    timestamp=datetime.fromisoformat(obj['metadata']['creationTimestamp'].replace('Z','+00:00')).timestamp()
    if c['load_start']<=timestamp<=c['three_ready']:created.append(timestamp)
 assert created
 for scene in scenes:
  if scene['title']=='Опыт C: масштабирование 2 → 3 → 2':
   scene['values'][1]=f"Создание Pod: +{min(created)-c['load_start']:.1f} с; наблюдение HPA: +{c['observed_three']-c['load_start']:.1f} с."
   scene['values'].insert(2,f"Все три готовы: +{c['three_ready']-c['load_start']:.1f} с от начала нагрузки.")
 transitions={}
 for path in [R/'b-alerts.jsonl',R/'c-alerts.jsonl']:
  for sample in rows(str(path.relative_to(R))):
   for group in sample.get('rules',{}).get('data',{}).get('groups',[]):
    for rule in group.get('rules',[]):
     if rule.get('type')=='alerting':transitions.setdefault(rule['name'],[]).append((sample['unix'],rule['state']))
 values=['UTC из сохранённых ответов Prometheus /api/v1/rules:']
 for name,obs in sorted(transitions.items()):
  obs.sort();wanted=['inactive','pending','firing','inactive'];chosen=[]
  for t,state in obs:
   if wanted and state==wanted[0]:chosen.append((t,state));wanted.pop(0)
  assert not wanted,(name,wanted)
  values += ['',name,*[stamp(t)+'  '+s for t,s in chosen]]
 inserts['Два алерта прошли полный цикл']=[make('Фактические переходы обоих алертов','results/b-alerts.jsonl · c-alerts.jsonl · последовательная выборка',values,27)]
 comparison=read('prometheus/b-normal-uniform-1-histogram-comparison.json');start=comparison['start'];end=comparison['end']
 inserts['Клиент и Prometheus сопоставлены']=[make('Точный запрос PromQL и границы сравнения','results/prometheus/b-normal-uniform-1-histogram-comparison.json',[
  'histogram_quantile(0.95,',f'  sum by (le) (hw11_ttfc_seconds_bucket @ {end:.3f})',f'  - sum by (le) (hw11_ttfc_seconds_bucket @ {start:.3f})',')',
  'Оба снимка — в паузах без запросов; Pod между ними не менялись.',
  'bucket +Inf: '+next(x['value'][1] for x in comparison['buckets'] if x['metric']['le']=='+Inf')+' успешных ответов; клиент: '+str(comparison['client']['completed']),
  'TTFC = first_mono - sent_mono; полный ответ = finished_mono - sent_mono.',
  'Маркер done не считается частью; интервалы — между соседними частями.',
  'Prometheus интерполирует внутри bucket; клиент дополнительно измеряет сеть.'
 ],27)]
 testlog=(R/'kubernetes-tests.log').read_text().splitlines();assert 'OK' in testlog
 replace['Проверки прошли']=make('Реальный вывод пяти проверок Kubernetes','results/kubernetes-tests.log · дословный вывод, без повторного запуска',[
  'Команда из README: make check-k8s','',*testlog,'','Локально: Ran 3 tests / OK; Helm: 1 chart(s) linted, 0 failed.'
 ],30)
 dashboard=json.loads((ROOT/'monitoring/grafana/export.json').read_text())
 inserts['Реальный вывод пяти проверок Kubernetes']=[make('Сохранённый экспорт установленной Grafana','monitoring/grafana/export.json · HTTP /api/dashboards/uid/hw11',[
  'uid: '+dashboard['uid'],'title: '+dashboard['title'],
  'Панели фактического экспорта:',*[f"  {p['id']}: {p['title']}" for p in dashboard['panels']],
  'Источник Prometheus: discovery каждого Pod, а не одного Service.',
  'Это извлечение JSON, не скриншот интерфейса Grafana.'
 ],24)]
 foot=read('footprint.json');env=read('environment-before.json')
 inserts['Сохранённый экспорт установленной Grafana']=[make('Ресурсы и удаление собственного стенда','environment-before.json · footprint.json · README.md',[
  f"Свободно до запуска: {env['disk']['free']/1e9:.1f} ГБ.",
  f"Сумма образов (верхняя оценка): {foot['images_sum_bytes_unshared_upper_bound']/1e9:.2f} ГБ.",
  f"Отдельный том узла /var: {foot['node_volumes_allocated_bytes']/1e9:.2f} ГБ.",
  f"hw11 вместе с инструментами и окружением: {foot['hw11_directory_logical_bytes_includes_tools_and_venv']/1e9:.2f} ГБ на момент замера.",
  'Prometheus: 2 часа / 128 МБ; том до 256 МиБ. Grafana: до 128 МиБ.',
  'Команды для повторения и удаления (не запускались при сборке видео):',
  '  cd hw11 && make up','  make down    # удалить только кластер kind с именем hw11',
  'Общие Docker-образы других проектов не удаляются.'
 ],25)]
 for scene in scenes:
  if scene['title']=='Ревью: очередь важнее жёсткой привязки':
   scene['values'][-1]=json.loads((ROOT/'source/references.json').read_text())['primary_case']
   scene['duration']=32
 result=[]
 def append(scene):
  s=replace.get(scene['title'],scene);result.append(s)
  for child in inserts.get(s['title'],[]):append(child)
 for scene in scenes:append(scene)
 return result
