"""Четыре графика и HTML-отчёт только из фактических журналов."""
import collections,html,json,math,statistics,subprocess,sys
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from common import ROOT,RESULTS,save,summarize
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'figure.dpi':140})
PLOTS=RESULTS/'plots';PLOTS.mkdir(exist_ok=True)
def read(name):return json.loads((RESULTS/name).read_text())
def rows(name):return [json.loads(x) for x in (RESULTS/'runs'/(name+'.jsonl')).read_text().splitlines()]
def timeline(name):return [json.loads(x) for x in (RESULTS/(name+'-timeline.jsonl')).read_text().splitlines() if 'objects' in json.loads(x)]
def ready_count(row):
 return sum(o['kind']=='Pod' and not o['metadata'].get('deletionTimestamp') and o['metadata'].get('labels',{}).get('app')=='hw11-api' and any(c['type']=='Ready' and c['status']=='True' for c in o.get('status',{}).get('conditions',[])) for o in row['objects']['items'])
def plot_a():
 fig,axes=plt.subplots(3,1,figsize=(12,10),constrained_layout=True)
 for ax,name,title in zip(axes,['a-warmup-before','a-warmup-after','a-rollout'],['До исправления: ложная готовность','После исправления: готовность после прогрева','Обновление A → B под запросами']):
  ts=timeline(name);rs=rows(name);start=min(t['unix'] for t in ts)
  ax.step([t['unix']-start for t in ts],[ready_count(t) for t in ts],where='post',label='Ready Pod')
  twin=ax.twinx()
  for outcome,color in [('completed','tab:green'),('http_error','tab:red'),('interrupted','tab:orange')]:
   rr=[r for r in rs if r['outcome']==outcome]
   if rr:twin.scatter([r['sent_unix']-start for r in rr],[r['duration_seconds'] for r in rr],s=13,color=color,label=outcome)
  if name=='a-rollout':
   rr=rows('a-long-stream')[0];ax.axvline(read('a-rollout-summary.json')['update_started']-start,color='black',linestyle='--',alpha=.6,label='Начало обновления');ax.axvspan(rr['sent_unix']-start,rr['sent_unix']-start+rr['duration_seconds'],alpha=.1,color='purple',label='Длительный поток A')
  ax.set(title=title,xlabel='Время от начала опыта, с',ylabel='Готовых Pod');ax.set_ylim(-.2,max(3,max(ready_count(t) for t in ts))+.3)
  twin.set_ylabel('Полный ответ клиента, с');ax.legend(loc='upper left');twin.legend(loc='upper right');ax.grid(alpha=.2)
 fig.suptitle('Опыт A • simulated CPU • прогрев 20 с • grace period 60 с');fig.savefig(PLOTS/'1-warmup-rollout.png');plt.close(fig)

def plot_b_pods():
 fig,axes=plt.subplots(2,2,figsize=(13,8),constrained_layout=True)
 for col,policy in enumerate(['sticky','normal']):
  name=f'b-{policy}-hot-3';rs=rows(name);start=min(r['sent_unix'] for r in rs)
  for pod in sorted({r['pod'] for r in rs if r['pod']}):
   rr=[r for r in rs if r['pod']==pod and r['outcome']=='completed']
   axes[0,col].scatter([r['sent_unix']-start for r in rr],[r['ttfc_seconds'] for r in rr],s=9,label=pod[-11:])
  data=read('prometheus/'+name+'.json')
  for series in data['waiting']['response']['data']['result']:
   vv=series['values'];axes[1,col].plot([float(v[0])-start for v in vv],[float(v[1]) for v in vv],label=series['metric'].get('pod','')[-11:])
  axes[0,col].set(title=policy+' • 80% от одного клиента • повтор 3',ylabel='TTFC успешного ответа, с')
  axes[1,col].set(ylabel='Запросов в очереди',xlabel='Время от начала нагрузки, с')
  for ax in axes[:,col]:ax.grid(alpha=.2);ax.legend()
 fig.suptitle('Опыт B • 4 запроса/с • 4 части × 0,09 с • concurrency=1');fig.savefig(PLOTS/'2-queue-by-pod.png');plt.close(fig)

def plot_b_comparison():
 summary=read('b-summary.json');fig,axes=plt.subplots(1,2,figsize=(13,5),constrained_layout=True)
 groups=[(p,t) for t in ['uniform','hot'] for p in ['normal','sticky']]
 for i,(policy,traffic) in enumerate(groups):
  rr=[r for r in summary if r['policy']==policy and r['traffic']==traffic]
  for ax,key,factor in [(axes[0],'ttfc_p95',1),(axes[1],'error_rate',100)]:
   vv=[r[key]*factor for r in rr];ax.bar(i,statistics.mean(vv),alpha=.5,color='tab:blue' if policy=='normal' else 'tab:orange')
   ax.scatter([i-.12,i,i+.12],vv,color='black',s=20)
 for ax in axes:
  ax.set_xticks(range(4),[p+'\n'+t for p,t in groups]);ax.grid(axis='y',alpha=.2)
 axes[0].set_ylabel('TTFC p95 успешных ответов, с');axes[1].set_ylabel('Доля неуспешных попыток, %')
 fig.suptitle('Опыт B • каждый столбец: среднее 3 прогонов по 120 с; точки — отдельные прогоны');fig.savefig(PLOTS/'3-policy-comparison.png');plt.close(fig)

def plot_c():
 events=read('c-summary.json');ts=timeline('c-hpa');start=events['start'];fig,axes=plt.subplots(3,1,figsize=(13,9),constrained_layout=True)
 desired=[]
 for t in ts:
  h=[o for o in t['objects']['items'] if o['kind']=='HorizontalPodAutoscaler']
  desired.append(h[0].get('status',{}).get('desiredReplicas',2) if h else 2)
 axes[0].step([t['unix']-start for t in ts],desired,where='post',label='HPA desired')
 axes[0].step([t['unix']-start for t in ts],[ready_count(t) for t in ts],where='post',label='Ready',alpha=.75)
 axes[0].set_ylabel('Число реплик');axes[0].set_yticks([0,1,2,3]);axes[0].legend()
 all_rows=[]
 for name in ['c-cpu','c-hot','c-alerts']:all_rows+=rows(name)
 bins=collections.Counter(int(r['sent_unix']-start)//5*5 for r in all_rows)
 xs=list(range(0,int(events['end']-start)+6,5))
 axes[1].step(xs,[bins.get(x,0)/5 for x in xs],where='post');axes[1].set_ylabel('Отправлено запросов/с')
 data=read('prometheus/c.json')
 for series in data['cpu']['response']['data']['result']:
  vv=series['values'];axes[2].plot([float(v[0])-start for v in vv],[float(v[1]) for v in vv],label=series['metric'].get('pod','')[-11:])
 axes[2].set(ylabel='CPU, ядер',xlabel='Время от начала опыта, с');axes[2].legend()
 for ax in axes:ax.grid(alpha=.2)
 fig.suptitle('Опыт C • HPA CPU 60% от request=100m • min=2, max=3 • стабилизация 45 с');fig.savefig(PLOTS/'4-hpa-load.png');plt.close(fig)

def table(items,keys):
 return '<table><thead><tr>'+''.join('<th>'+html.escape(k)+'</th>' for k in keys)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(row.get(k,'')))+'</td>' for k in keys)+'</tr>' for row in items)+'</tbody></table>'

def main():
 b=read('b-summary.json');a=read('a-warmup-summary.json');c=read('c-summary.json');roll=read('a-rollout-summary.json');footprint=read('footprint.json')
 for row in b:row.update(summarize(rows(row['run'])))
 balanced=[x for x in b if x['policy']=='sticky' and max(x['pods'].values())/x['sent']<=.55]
 balanced_note='; '.join(x['run']+': '+str(x['pods']) for x in balanced) or 'В этой серии равномерного закрепления не наблюдалось; все исходы сохранены.'
 averages={}
 for policy in ['normal','sticky']:
  group=[x for x in b if x['policy']==policy and x['traffic']=='hot']
  averages[policy]={'ttfc':statistics.mean(x['ttfc_p95'] for x in group),'errors':statistics.mean(x['error_rate'] for x in group)}
 assert len(b)==12 and all(x['sent']==480 for x in b)
 plot_a();plot_b_pods();plot_b_comparison();plot_c()
 # Единый журнал собирается заново, повторный запуск не дублирует попытки.
 allrows=[]
 for p in sorted((RESULTS/'runs').glob('*.jsonl')):allrows += [json.loads(s) for s in p.read_text().splitlines()]
 (RESULTS/'requests.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in allrows))
 summary={'requests':summarize(allrows),'b':b,'c':c};save('summary.json',summary)
 case='https://cloud.google.com/blog/products/containers-kubernetes/how-gke-inference-gateway-improved-latency-for-vertex-ai'
 comparisons=[]
 for row in b:
  value=read('prometheus/'+row['run']+'-histogram-comparison.json')
  q=value['prometheus_p95'];comparisons.append({'run':row['run'],'client p95, с':round(row['ttfc_p95'],3),'Prometheus p95, с':q[0]['value'][1] if q else None,'n':row['completed']})
 body=f'''<!doctype html><html lang="ru"><meta charset="utf-8"><title>ДЗ11 — Kubernetes под нагрузкой</title>
<style>body{{font:17px/1.55 system-ui;max-width:1400px;margin:40px auto;padding:0 24px;color:#172339}}h1,h2{{line-height:1.2}}table{{border-collapse:collapse;font-size:13px;width:100%}}td,th{{border:1px solid #ccd4df;padding:6px;text-align:left;overflow-wrap:anywhere}}img{{max-width:100%}}code{{background:#edf1f6;padding:2px 4px}}.note{{background:#edf6fc;padding:16px}}@media print{{body{{font-size:11pt}}h2{{break-after:avoid}}img{{break-inside:avoid}}}}</style>
<h1>ДЗ11. Сервис работает, пользователи ждут</h1>
<p>Продолжение сервиса ДЗ8–10. Стенд: Kubernetes в kind, две реплики FastAPI, Prometheus, Grafana и четыре клиентских Pod. Все HTTP-запросы и измерения выполнены в этом стенде.</p>
<p class="note"><b>backend_mode=simulated.</b> Используется управляемый CPU-имитатор, разрешённый методичкой для всех 10 баллов. Веса LLM не загружались. Измерены время до первого фрагмента ответа (TTFC) и интервалы между фрагментами (inter-chunk latency). Результаты не являются скоростью реальной модели.</p>
<h2>1. Условия и воспроизведение</h2>
<p>Образы закреплены digest в <code>source/images-lock.json</code>, Python-зависимости — в <code>uv.lock</code> и requirements с хешами. Версии запуска и ресурсы сохранены в <code>results/versions.json</code>, свободное место до запуска — в <code>results/environment-before.json</code>. Инструкция запуска и удаления — README.md.</p>
<p>Узел kind ограничен 3 ГиБ RAM и 4 CPU. У каждой API-копии запрошены 100m CPU (0,1 ядра) и 64 МиБ памяти; пределы — 800m CPU и 192 МиБ. Прогрев 20 с, startup допускает 90 с, readiness проверяется каждую секунду, liveness раз в 5 с. Grace period 60 с, завершение активных ответов Uvicorn — до 45 с. Prometheus: хранение 2 часа/128 МБ, том до 256 МиБ; Grafana — том до 128 МиБ. Фактическая верхняя оценка размеров образов: {footprint['images_sum_bytes_unshared_upper_bound']/1e9:.2f} ГБ; отдельного тома узла /var с внутренним containerd: {footprint['node_volumes_allocated_bytes']/1e9:.2f} ГБ; записываемого слоя контейнера узла: {(footprint.get('node_writable_bytes') or 0)/1e9:.3f} ГБ; каталога hw11 с локальными инструментами и окружением: {footprint['hw11_directory_logical_bytes_includes_tools_and_venv']/1e9:.2f} ГБ. Общие слои в сумме образов не вычтены. Подробности — results/footprint.json.</p>
<p>Артефакты A и B — маленькие JSON-файлы в immutable ConfigMap. При старте процесс пересчитывает SHA256, сверяет ожидаемое значение и только потом проходит прогрев. Модель и хеш берутся из реально загруженного файла. История диалога передаётся клиентом, локальный кеш не является хранилищем истории.</p>
<p>Имитатор один во всех сравнениях: concurrency=1, очередь до 16 запросов, timeout очереди 45 с; локальный кеш на 8 префиксов с вытеснением давно неиспользованных записей: найденный префикс стоит 40 мс CPU, отсутствующий — 160 мс CPU, вычисление части=3 мс CPU. Между частями есть заданная пауза. CPU-работа действительно выполняет криптографические вычисления PBKDF2 до заданного времени потока; это измеряемая вычислительная нагрузка, а не один sleep.</p>
<h2>2. Опыт A — прогрев, обновление и отказ</h2>
<p><b>Гипотеза.</b> Если startup/readiness проверяют только доступность HTTP, новая копия начинает обслуживать пользователей до прогрева.</p>
<p><b>До изменения.</b> Режим BROKEN_PROBES=true оставляет именно этот дефект. Клиенты отправляли тот же набор запросов, что и после исправления. Сводка исходного и повторного опыта:</p>
{table([{'run':k,**v} for k,v in a.items()],['run','sent','completed','outcomes'])}
<p><b>Причина и изменение.</b> Запущенный HTTP-процесс ещё не означает готовую модель. startup/readiness теперь ждут завершения загрузки и прогрева, liveness проверяет только жизнь процесса. Подтверждения Ready, EndpointSlice и запросов сохранены в a-warmup-*-timeline.jsonl и logs/.</p>
<p>В первом пробном обновлении тайм-аут очереди 15 с привёл к двум HTTP 429 из 65 коротких запросов при занятом длинным ответом слоте. Сам длинный поток завершился. Исходные данные сохранены в results/initial-a/. Тайм-аут очереди увеличен до 45 с в пределах клиентского ожидания и grace period; ниже приведён полный повтор с тем же расписанием.</p>
<p><b>Штатное обновление.</b> До начала A→B запущен длинный поток A. Новая B прогревается; старый процесс принимает оставшиеся соединения в коротком периоде распространения EndpointSlice, затем завершает активные ответы. В полном прогоне: {roll['short']['sent']} коротких запросов и один длинный; HTTP 5xx и незавершённых потоков — 0. Длительный ответ занял {roll['long'][0]['duration_seconds']:.2f} с и пересёк начало обновления.</p>
<p>Неготовая ревизия B с контролируемым отказом прогрева не стала Ready и не вошла в рабочие endpoints. Затем выполнен управляемый возврат к A. Фактическая версия подтверждена ответами, а не только номером Helm-релиза. После замены Pod восстановились версия и диалог.</p>
<p><b>Принудительное завершение.</b> Отдельный запрос направлен в выбранный Pod; его удаление с grace=0 оборвало уже начатый поток. Отправленные части и незавершённость записаны клиентом. ReplicaSet создал замену, она прошла прогрев; восстановление проверено HTTP-запросом. Журнал a-accounting.json хранит этот опыт отдельно от корректного обновления.</p>
<img src="results/plots/1-warmup-rollout.png" alt="Готовность и запросы во время прогрева и обновления">
<h2>3. Опыт B — привязка и очередь</h2>
<p><b>Гипотеза.</b> Привязка к IP сохраняет локальный кеш, но при концентрации 80% запросов у одного клиента может перегрузить одну реплику. Обычная Service оставляет больше возможностей распределить работу.</p>
<p>Сравнивались Service normal (sessionAffinity=None) и sticky (ClientIP, timeout=30 с) над теми же Pod. Четыре клиента имеют разные IP; соединение создаётся заново для каждого запроса: keep-alive выключен в обеих политиках. Сеть kindnet, kube-proxy iptables. Фактические клиентские адреса, настройки и распределение — b-network.json и журналы request_arrived.</p>
<p>Два расписания: равномерное и 80% от client-0. В каждом 480 запросов за 120 с, одинаковые длины и 4 части с паузой 0,09 с. Кеш перед каждым прогоном пуст, backend уже прогрет. Для каждой комбинации выполнены три повтора. Плановое и фактическое время отправки записаны отдельно.</p>
{table([{**r,'ttfc_p50':round(r['ttfc_p50'],3),'ttfc_p95':round(r['ttfc_p95'],3),'response_p50':round(r['response_p50'],3),'response_p95':round(r['response_p95'],3),'timeouts':r['outcomes'].get('timeout',0),'error_rate':round(r['error_rate'],4),'send_lag_p95':round(r['send_lag_p95'],3)} for r in b],['run','sent','completed','ttfc_p50','ttfc_p95','response_p50','response_p95','error_rate','timeouts'])}
<p>p50 — медиана, p95 — значение, в которое укладываются 95% наблюдений. Все задержки в таблице указаны в секундах, error_rate — доля неуспешных отправленных попыток. Количество наблюдений для перцентилей — completed. Отклонённые, оборванные и просроченные попытки остаются в сырых данных и доле ошибок.</p>
<p>Для горячего трафика среднее по трём отдельным p95: normal={averages['normal']['ttfc']:.3f} с, sticky={averages['sticky']['ttfc']:.3f} с. Средняя доля ошибок: normal={averages['normal']['errors']:.2%}, sticky={averages['sticky']['errors']:.2%}. Это сводка трёх прогонов, не перцентиль объединённого потока.</p>
<p><b>Случай без перекоса.</b> {html.escape(balanced_note)}. Трасса показывает, какие клиентские IP закрепились за каждым Pod. Удачное закрепление может дать меньшую задержку, чем случайное распределение новых соединений, поэтому привязка не объявляется плохой при любом трафике.</p>
<p><b>Исправление.</b> Убрана обязательная привязка ClientIP. Результат исправления — те же полные прогоны normal для обоих режимов нагрузки и трёх повторов. Общий кеш не добавлялся; повторный расчёт префикса возможен, зато запрос не обязан ждать перегруженную копию. Выбор нужно оценивать одновременно по задержке, отказам и распределению, не по одному cache hit.</p>
<img src="results/plots/2-queue-by-pod.png" alt="TTFC и очередь каждой копии">
<img src="results/plots/3-policy-comparison.png" alt="Сравнение политик в трёх прогонах">
<p><b>Ограничения.</b> Kubernetes Service выбирает путь для соединения, а не гарантирует строгое чередование запросов. Четыре ClientIP могут случайно попасть на копии равномерно или неравномерно. Отсутствие перекоса в конкретном прогоне также сохранено в таблице и объясняется фактическими pod/peer_ip. Полученные числа относятся к заданным стоимости кеша и скорости имитатора; их нельзя переносить на движок реальной модели.</p>
<h2>4. Опыт C — HPA и алерты</h2>
<p><b>Гипотеза.</b> Вычислительная нагрузка поднимет CPU и вызовет рост с 2 до 3 копий. После снижения нагрузки HPA вернётся к минимуму. Само добавление копии не гарантирует перераспределения клиентов с ClientIP.</p>
<p>Первая фаза: 120 с, 10 запросов/с, 2 фрагмента с паузой 0,03 с. После возврата к двум копиям повторён горячий сценарий B: 120 с, 4 запроса/с, 4 фрагмента × 0,09 с, 80% запросов от одного клиента и пустой кеш. Для срабатывания алертов отдельно поданы 18 запросов/с в течение 45 с, по 8 фрагментов × 0,12 с, затем нагрузка снята.</p>
<p>HPA — механизм Kubernetes, меняющий число копий по метрикам нагрузки. Используется autoscaling/v2: CPU=60% от request=100m, min=2, max=3, окно стабилизации вниз 45 с. Доступность resource metrics API и CPU requests проверена. Наблюдаемое появление третьей копии: через {c['observed_three']-c['load_start']:.1f} с от старта нагрузки; все три готовы через {c['three_ready']-c['load_start']:.1f} с. Возврат к двум наблюдался через {c['downscale_delay_seconds']:.1f} с после окончания клиентского прогона. Это фактическое время, включающее цикл сбора метрик и управления; оно может превышать заданное окно.</p>
<p>Повторён горячий сценарий с ClientIP. Распределение отправленных запросов по обслужившим Pod: {html.escape(str(c['hot_summary']['pods']))}. Готовых/созданных копий в конце этой фазы — {len([p for p in c['hot_pods'] if not p['metadata'].get('deletionTimestamp')])}; все их имена и времена создания сохранены в c-summary.json, поэтому копия без запросов также видна. Средняя CPU-метрика реагирует, когда суммарная загрузка превышает целевое среднее; один занятый Pod при остальных простаивающих может как вызвать рост, так и остаться ниже порога. Уже закреплённые IP продолжают поступать прежним получателям, поэтому новая копия может получать мало работы. Трасса c-hot и HPA conditions приложены.</p>
<p>Два алерта: p95 TTFC выше 0,5 с и доля отказов выше 10%; окно 30 с, минимум 10 исходов соответствующего типа, удержание 8 с. Управляемая перегрузка и последующая пауза записаны в *-alerts.jsonl: состояния inactive, pending и firing, затем возврат в inactive.</p>
<img src="results/plots/4-hpa-load.png" alt="HPA, готовность, нагрузка и CPU">
<h2>5. Методика измерений и собственные проверки</h2>
<p>Клиент измеряет время time.monotonic(): TTFC=t_first−t_sent, полный ответ=t_finish−t_sent; inter-chunk latency — разности времён соседних содержательных частей. Маркер done не считается частью. Отправленные, completed, rejected, interrupted, timeout, HTTP/transport error учитываются отдельно. Повторы скрыто не выполняются. Все запланированные запросы сохранены в schedules/, фактические — requests.jsonl; это позволяет видеть задержку самого генератора.</p>
<p>Перцентили на клиенте рассчитаны только для полностью успешных ответов, с линейной интерполяцией между порядковыми статистиками. Доля ошибок включает все отправленные попытки. Для Histogram складываются bucket-счётчики с сохранением le, затем применяется histogram_quantile; перцентили разных Pod не усредняются. Для одинакового набора ответов сравниваются снимки до и после прогона с паузой для сбора метрик:</p>
{table(comparisons,['run','n','client p95, с','Prometheus p95, с'])}
<p>Разница ожидаема: клиент включает доставку по сети; Prometheus интерполирует внутри bucket. Точные запросы, времена и исходные bucket-счётчики — results/prometheus/*-histogram-comparison.json; остальные PromQL — monitoring/promql.md.</p>
<p>Пять собственных проверок tests/test_kubernetes.py выполняют реальные HTTP-запросы из Kubernetes: прогрев; версия после отката; замена Pod с продолжением диалога; учёт отказов/обрыва; изоляция двух диалогов. Дополнительные локальные проверки проверяют SHA256, ограничение кеша и схему запросов. Полные результаты — results/kubernetes-tests.log и local-tests.log.</p>
<h2>6. Ревью: закреплять ли диалог за Pod навсегда</h2>
<p>При заданных условиях новый запрос направил бы на свободную B. У A ожидание очереди уже 3 секунды, а B пересчитает префикс за 0,8 секунды. При прочих равных экономия пересчёта на A не компенсирует ожидание. Постоянную связь session_id→pod_id не принимаю как общее правило: полезно учитывать локальный кеш, но решение должно также учитывать очередь и доступную ёмкость.</p>
<p>До принятия политики нужны распределения задержек, длительности входов и ответов, стоимость cache hit/miss, пределы памяти и параллелизма, актуальность сведений об очереди, ошибки и поведение при всплесках. Новый запрос можно допускать, только если выбранная копия готова и её очередь не превысила ограничение; при исчерпании ёмкости нужен явный отказ или ограниченное ожидание. Бесконечные повторы увеличат перегрузку.</p>
<p>История диалога передаётся в запросе или хранится вне Pod. После потери A новая копия восстанавливает контекст из этой истории, даже если локальный кеш утрачен. Уже начатый поток остаётся на A до завершения в пределах grace period; переносить его посередине ответа нельзя. При аварийном обрыве клиент получает признак незавершённости, а новая попытка учитывается отдельно.</p>
<p>Это связано с <a href="{case}">кейсом Google Cloud / Vertex AI из сцены 70 лекции</a>: маршрутизация сочетает повторное использование префикса с текущей очередью и ограничением допуска. Компания описывает настройку веса очереди, чтобы обходить горячие копии. Её показатели на реальных моделях — внешний пример, не результаты этого имитатора.</p>
<h2>7. Сдача и границы результата</h2>
<p>Репозиторий: <a href="https://github.com/beekfin/MLOps/tree/main/hw11">beekfin/MLOps/hw11</a>. Точный коммит сдачи определяется <code>git log -1 --format=%H -- hw11</code>. Условия задания и связь с предыдущим сервисом сохранены в source/. Все данные измерены локально; дополнительных опытов с GPU, SGLang или llm-d не заявляется.</p>
<p>Стенд одноузловой: проверена замена процессов/Pod, а не отказ физического узла. Нулевая доля обрывов относится к зафиксированному штатному обновлению и заданной нагрузке; принудительное завершение имеет отдельный журнал. Ограничения имитатора, TCP-балансировки и гистограмм учитываются при выводах.</p>
</html>'''
 (ROOT/'report.html').write_text(body)
 print('Четыре графика и report.html построены из фактических результатов.')
if __name__=='__main__':main()
