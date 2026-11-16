"""4K-обзор сохранённых опытов ДЗ11; один поток ffmpeg и исходный трек автора."""
import argparse,hashlib,json,re,statistics,subprocess
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1];R=ROOT/'results';FRAMES=ROOT/'.runtime/video-frames'
BG='#0b1421';PANEL='#142337';FG='#ebf1f8';CYAN='#57ceef';GREEN='#48d7a7';GRAY='#94a5bb'
F=Path('/usr/share/fonts/TTF')
def font(size,bold=False,mono=False):return ImageFont.truetype(str(F/('DejaVuSansMono.ttf' if mono else 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')),size*2)
def text(im,x,y,value,size=25,color=FG,bold=False):ImageDraw.Draw(im).text((x*2,y*2),str(value),font=font(size,bold),fill=color)
def read(name):return json.loads((R/name).read_text())
def base(title,source,index,total):
 im=Image.new('RGB',(3840,2160),BG);d=ImageDraw.Draw(im);d.rectangle((0,0,3840,110),fill='#070d16')
 text(im,36,14,'MLOps / ДЗ 11',23,CYAN);text(im,1240,17,'Kubernetes · CPU · simulated',20,GRAY)
 text(im,60,90,source,18,CYAN)
 size=41
 while d.textlength(title,font=font(size,True))>3600:size-=1
 text(im,60,135,title,size,bold=True)
 text(im,60,1025,'ОБЗОР ВЫПОЛНЕННЫХ ОПЫТОВ ПО СОХРАНЁННЫМ ДАННЫМ',15,GRAY)
 text(im,1740,1025,f'{index+1}/{total}',19,GRAY)
 return im

def body(im,values,size=29):
 d=ImageDraw.Draw(im)
 def wrap(s,n):
  out=[]
  while d.textlength(s,font=font(n))>3390:
   low,high=1,len(s)
   while low<high:
    mid=(low+high+1)//2
    if d.textlength(s[:mid],font=font(n))<=3390:low=mid
    else:high=mid-1
   cut=s.rfind(' ',0,low+1)
   if cut<low//2:cut=low
   out.append(s[:cut]);s=s[cut:].lstrip()
  return out+[s]
 while sum(len(wrap(s,size))*(size+15)+18 for s in values)>710:
  size-=1
  if size<20:raise ValueError('Переполнен кадр')
 d.rounded_rectangle((100,435,3740,1970),radius=22,fill=PANEL,outline='#30455e',width=2)
 y=245
 for s in values:
  for line in wrap(s,size):text(im,85,y,line,size,GREEN if 'PASS' in line or 'OK' in line else FG);y+=size+15
  y+=18

def plot(im,name,crop=None):
 chart=Image.open(R/'plots'/name).convert('RGB')
 if crop:
  w,h=chart.size;chart=chart.crop((0,int(h*crop[0]),w,int(h*crop[1])))
 chart.thumbnail((3580,1500),Image.Resampling.LANCZOS)
 # Масштабировать исходную научную фигуру в доступную область без обрезки текста.
 ratio=min(3580/chart.width,1500/chart.height)
 chart=chart.resize((round(chart.width*ratio),round(chart.height*ratio)),Image.Resampling.LANCZOS)
 im.paste(chart,((3840-chart.width)//2,440+(1500-chart.height)//2))

def main():
 p=argparse.ArgumentParser();p.add_argument('--music',type=Path,default=Path('/home/beekfin/Downloads/1-07_-haggstrom.mp3'));args=p.parse_args()
 if not args.music.is_file():raise FileNotFoundError('Передайте --music /путь/к/треку.mp3')
 audit=read('audit.json');assert audit['failed']==0
 for file,n in [('kubernetes-tests.log',5),('final-check.log',3)]:
  raw=(R/file).read_text();assert f'Ran {n} tests' in raw and re.search(r'\nOK',raw)
 b=read('b-summary.json');assert len(b)==12 and all(x['measurement_seconds']>=120 and x['sent']==480 for x in b)
 a=read('a-warmup-summary.json');roll=read('a-rollout-summary.json');acc=read('a-accounting.json');c=read('c-summary.json')
 scenes=[]
 def add(title,source,values,duration=20):scenes.append({'title':title,'source':source,'values':values,'duration':duration})
 def graph(title,source,name,duration=24,crop=None):scenes.append({'title':title,'source':source,'plot':name,'duration':duration,'crop':crop})
 add('Сервис под нагрузкой','продолжение ДЗ 8–10 · выполненные опыты A, B и C',[
  'Две копии сервиса → прогрев и обновление → балансировка → масштабирование.',
  'Настоящий Kubernetes, HTTP-запросы, Prometheus и Grafana.',
  'backend_mode=simulated: управляемый имитатор на процессоре.',
  'Показатели относятся к фрагментам ответа, а не к токенам LLM.'
 ],16)
 add('Состав стенда и ограничения','source/images-lock.json · charts/hw11/ · results/versions.json',[
  'Kubernetes 1.34.0 / kind 0.30.0 / Helm 3.19.0.',
  'Deployment, два Service, ConfigMap, четыре клиента с разными IP.',
  'Узел: предел 3 ГиБ RAM и 4 CPU. У API: CPU 100m → 800m, RAM 64 → 192 МиБ.',
  'Образы закреплены digest, Python-зависимости — uv.lock и хешами.',
  'Прогрев 20 с. Startup, readiness и liveness выполняют разные проверки.'
 ],23)
 before=a['a-warmup-before'];after=a['a-warmup-after']
 add('Опыт A: ранняя готовность воспроизведена','results/a-warmup-summary.json · logs/a-warmup-before/',[
  'Исходный дефект: startup/readiness принимают запуск HTTP за готовность.',
  f"До исправления: {before['sent']} запросов, {before['completed']} успешных, {before['sent']-before['completed']} отказа.",
  'Журнал показывает получение запросов до завершения прогрева.',
  f"После исправления: {after['completed']} из {after['sent']} успешны.",
  'Сохранены Ready, EndpointSlice и серверные журналы.'
 ],24)
 graph('Прогрев: исходный дефект и исправление','одинаковое расписание · Ready и ответы по времени','1-warmup-rollout.png',26,crop=(0,944/1400))
 add('Обновление A → B под запросами','results/a-rollout-summary.json · a-rollback.json',[
  f"Завершены {roll['short']['completed']} коротких запросов и один длительный поток A.",
  f"Длительный ответ: {roll['long'][0]['duration_seconds']:.2f} с; он пересёк начало обновления.",
  'HTTP 5xx и незавершённых потоков в штатном повторе: 0.',
  'В пробном прогоне было два HTTP 429: очередь ждала дольше 15 с.',
  'Исходные данные сохранены. Ожидание увеличено до 45 с; повтор прошёл.',
  'Неготовая ревизия B исключена из трафика; выполнен возврат к A.'
 ],28)
 graph('Активный ответ пережил начало обновления','grace period 60 с · прогрев новой копии 20 с','1-warmup-rollout.png',23,crop=(944/1400,1))
 kill=acc['force_kill'][0]
 add('Отказ и восстановление проверены отдельно','results/a-accounting.json · a-replacement.json · dialog-isolation.json',[
  f"Принудительное удаление Pod: поток оборван после {kill['chunks']} частей, outcome={kill['outcome']}.",
  'Затем новая копия прогрелась, восстановила ту же версию и ответила.',
  'История передаётся в запросе; продолжение проверено именно на новом Pod.',
  'Два диалога с контрольными строками не смешались.',
  f"Проверка переполнения очереди: {acc['overload']['outcomes']['rejected']} отказов учтены клиентом."
 ],25)
 add('Опыт B: условия сравнения','results/schedules/ · b-network.json · b-source-ips.json',[
  'Обычный Service и Service с sessionAffinity: ClientIP — над теми же двумя Pod.',
  'Четыре клиентских Pod; сервис наблюдал четыре разных IP.',
  'Равномерный трафик и 80% запросов через одного клиента.',
  'Одинаковые входы, ограничения ответа и расписания; HTTP keep-alive выключен.',
  '12 полных прогонов: 2 политики × 2 режима × 3 повтора по 120 с.',
  'Всего 5760 попыток; перед каждым прогоном кеш пуст, процессы прогреты.'
 ],28)
 add('Управляемая очередь и локальный кеш','src/backend.py · charts/hw11/values.yaml',[
  'Одна обработка одновременно, очередь до 16 запросов, ожидание до 45 с.',
  'Кеш на 8 префиксов: попадание — 40 мс CPU, промах — 160 мс CPU.',
  'Четыре части ответа с паузой 0,09 с, каждая — ещё 3 мс CPU.',
  'Вычислительная работа действительно нагружает процессор.',
  'Числа описывают эту модель нагрузки; реальный движок потребует отдельной проверки.'
 ],24)
 graph('Горячая копия ждёт, соседняя простаивает','третий горячий прогон · TTFC и очередь отдельно по Pod','2-queue-by-pod.png',28)
 averages={}
 for policy in ['normal','sticky']:
  rr=[x for x in b if x['policy']==policy and x['traffic']=='hot']
  averages[policy]=(statistics.mean(x['ttfc_p95'] for x in rr),statistics.mean(x['error_rate'] for x in rr))
 add('Результат исправления привязки','results/b-summary.json · b-fix.json',[
  'Выбранное исправление: sessionAffinity: ClientIP → None.',
  f"Горячий трафик, среднее трёх p95: normal {averages['normal'][0]:.2f} с; sticky {averages['sticky'][0]:.2f} с.",
  f"Средняя доля ошибок: normal {averages['normal'][1]:.1%}; sticky {averages['sticky'][1]:.1%}.",
  'При удачном закреплении 240/240 привязка тоже дала ноль отказов; случай сохранён.',
  'Локальность кеша полезна, пока её выигрыш не перекрывается ожиданием очереди.'
 ],25)
 graph('Все три повтора, включая удачные случаи','точки — отдельные прогоны; столбцы — средние · p95 только успешных ответов','3-policy-comparison.png',25)
 add('Опыт C: масштабирование 2 → 3 → 2','results/c-summary.json · c-hpa-timeline.jsonl',[
  'HPA autoscaling/v2: CPU 60% от request=100m, минимум 2 и максимум 3.',
  f"Третья копия создана/запрошена через {c['observed_three']-c['load_start']:.1f} с; три готовы через {c['three_ready']-c['load_start']:.1f} с.",
  f"Возврат к двум: {c['downscale_delay_seconds']:.1f} с после завершения нагрузки; окно стабилизации — 45 с.",
  'В горячем повторе третья копия почти не получила запросов: прежние IP остались закреплены.',
  'Масштабирование по средней CPU-метрике само по себе не устраняет привязку.'
 ],26)
 graph('Масштабирование вместе с реальной нагрузкой','паузы имеют нулевую нагрузку · Ready, отправленные запросы/с и CPU','4-hpa-load.png',28)
 add('Два алерта прошли полный цикл','results/b-alerts.jsonl · c-alerts.jsonl · monitoring/rules.yml',[
  'Задержка: p95 TTFC > 0,5 с при минимум 10 успешных ответах за 30 с.',
  'Отказы: доля >10% при минимум 10 исходах за 30 с.',
  'Условие удерживается 8 с; управляемая перегрузка вызвала срабатывание.',
  'Оба алерта: inactive → pending → firing → inactive.',
  'Идентификаторы запросов и диалогов — в журнале, а не в метках метрик.'
 ],24)
 comparison=read('prometheus/b-normal-uniform-1-histogram-comparison.json');pq=float(comparison['prometheus_p95'][0]['value'][1])
 add('Клиент и Prometheus сопоставлены','monitoring/promql.md · results/prometheus/*-histogram-comparison.json',[
  'Монотонные часы клиента: отправка → первый фрагмент → завершение.',
  'Отдельно учтены успехи, отказы, обрывы и тайм-ауты; скрытых повторов нет.',
  f"Пример: p95 клиента {comparison['client']['ttfc_p95']:.2f} с, Histogram {pq:.2f} с; успешных ответов — 480.",
  'Сначала складываются bucket-счётчики с le, затем histogram_quantile.',
  'Для всех 12 прогонов число успехов в Histogram совпало с журналом клиента.',
  'Разница задержек объясняется сетью и интерполяцией внутри интервалов.'
 ],28)
 add('Проверки прошли','results/kubernetes-tests.log · final-check.log · audit.json',[
  'PASS — прогрев и исключение раннего трафика.',
  'PASS — фактически загруженная версия после отката.',
  'PASS — замена Pod, сохранение версии и продолжение диалога.',
  'PASS — учёт отказов и оборванного потока; изоляция двух диалогов.',
  'Пять проверок в Kubernetes и три локальные — OK. Helm lint — OK.',
  f"Сверка полноты по сохранённым данным: {audit['passed']} успешно, {audit['failed']} провалено."
 ],26)
 add('Ревью: очередь важнее жёсткой привязки','report.html, раздел 6 · кейс Google Cloud из лекции',[
  'У A очередь 3 с, B свободна и пересчитает префикс за 0,8 с: новый запрос — на B.',
  'Нужны измерения очереди, hit/miss, длин входов и ответов, ошибок и доступной ёмкости.',
  'История хранится вне Pod; уже начатый поток остаётся на A до завершения.',
  'При обрыве — отдельная учтённая попытка, без склейки частей разных ответов.',
  'Кейс Google / Vertex AI: учитывать одновременно кеш, очередь и допуск к обработке.',
  'Прямая ссылка на первоисточник приложена к письменному ревью.'
 ],27)
 commit=subprocess.check_output(['git','rev-parse','--short','HEAD'],cwd=ROOT,text=True).strip()
 add('Материалы для сдачи','hw11/report.html · README.md · results/ · monitoring/',[
  f'Репозиторий: github.com/beekfin/MLOps · результаты ДЗ11: {commit}.',
  'Код и Helm-чарт, исходные журналы, четыре графика, настройки и экспорт Grafana.',
  'Инструкция запуска и удаления, ресурсы и фактический размер стенда.',
  'Видео — обзор выполненных опытов по сохранённым данным.',
  'Музыка: C418 — Haggstrom. Без голосовой озвучки.'
 ],18)
 FRAMES.mkdir(parents=True,exist_ok=True);out=ROOT/'submission';out.mkdir(exist_ok=True)
 concat=[];metadata=[';FFMETADATA1','title=ДЗ11 — Kubernetes под нагрузкой'];elapsed=0
 for i,s in enumerate(scenes):
  im=base(s['title'],s['source'],i,len(scenes))
  if 'plot' in s:plot(im,s['plot'],s.get('crop'))
  else:body(im,s['values'])
  path=FRAMES/f'{i:02d}.png';im.save(path);im.close()
  concat += [f"file '{path}'",f"duration {s['duration']}"]
  metadata += ['[CHAPTER]','TIMEBASE=1/1000',f'START={elapsed*1000}',f"END={(elapsed+s['duration'])*1000}",'title='+s['title']]
  elapsed+=s['duration']
 concat += [f"file '{path}'"]
 (FRAMES/'concat.txt').write_text('\n'.join(concat)+'\n');(FRAMES/'chapters.txt').write_text('\n'.join(metadata)+'\n')
 target=out/'hw11_beekfin_4k_music.mp4'
 cmd=['prlimit','--as=1610612736','--','nice','-n','10','ffmpeg','-v','error','-y','-threads','1','-f','concat','-safe','0','-i',str(FRAMES/'concat.txt'),
      '-stream_loop','-1','-i',str(args.music),'-f','ffmetadata','-i',str(FRAMES/'chapters.txt'),'-map','0:v:0','-map','1:a:0','-map_metadata','2','-map_chapters','2',
      '-filter_threads','1','-vf','format=yuv420p','-fps_mode','vfr','-c:v','libx264','-preset','veryfast','-crf','18','-threads','1','-g','1',
      '-c:a','aac','-b:a','192k','-af',f'volume=0.4,afade=t=in:st=0:d=1,afade=t=out:st={elapsed-3}:d=3','-t',str(elapsed+.04),'-movflags','+faststart',str(target)]
 subprocess.run(cmd,check=True)
 facts={'file':str(target.relative_to(ROOT)),'duration_seconds':elapsed,'resolution':[3840,2160],'chapters':len(scenes),'music':'C418 — Haggstrom',
        'music_sha256':hashlib.sha256(args.music.read_bytes()).hexdigest(),'video_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'results_commit':commit,
        'presentation':'Обзор сохранённых результатов, не запись повторного запуска'}
 (out/'video-info.json').write_text(json.dumps(facts,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(facts,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
