"""4K-видео по реальным файлам: редкие статичные кадры, один поток ffmpeg."""
import csv,json,re,subprocess,textwrap
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1];E=ROOT/'evidence';OUT=ROOT/'submission/video-frames'
BG='#0b1421';PANEL='#142337';FG='#ebf1f8';CYAN='#57ceef';GREEN='#48d7a7';AMBER='#ffbc74';GRAY='#94a5bb'
F='/usr/share/fonts/TTF/DejaVuSans.ttf';M='/usr/share/fonts/TTF/DejaVuSansMono.ttf';B='/usr/share/fonts/TTF/DejaVuSans-Bold.ttf'
def font(n,mono=False,bold=False):return ImageFont.truetype(M if mono else B if bold else F,n*2)
def text(im,x,y,value,n=24,color=FG,mono=False,bold=False):ImageDraw.Draw(im).text((x*2,y*2),str(value),font=font(n,mono,bold),fill=color)
def read(name):return json.loads((E/name).read_text())
def log(name):return re.sub(r'\x1b\[[0-9;]*m','',(E/name).read_text())
def normalized(s):return str(s).replace(str(ROOT),'PROJECT').replace(str(ROOT.parents[1]),'REPO')

def scene(title,source,index,total):
 im=Image.new('RGB',(3840,2160),BG);d=ImageDraw.Draw(im)
 d.rectangle((0,0,3840,110),fill='#070d16')
 text(im,34,15,'MLOps / ДЗ 8 + 9 + 10',22,CYAN)
 text(im,1250,18,'Ask Ubuntu · Qwen3-0.6B',20,GRAY)
 text(im,60,91,source,19,CYAN)
 title_size=41
 while d.textlength(title,font=font(title_size,bold=True))>3600:title_size-=1
 text(im,60,137,title,title_size,FG,bold=True)
 d.rounded_rectangle((100,438,3740,1980),radius=20,fill=PANEL,outline='#30455e',width=2)
 text(im,60,1025,'ВИДЕООТЧЁТ ПО СОХРАНЁННЫМ ФАЙЛАМ И ЖУРНАЛАМ',16,GRAY)
 text(im,1730,1025,f'{index+1}/{total}',19,GRAY)
 return im

def lines(im,values,n=23,mono=False,start=245):
 y=start;max_width=1740;d=ImageDraw.Draw(im)
 def wrap(value,size):
  value=normalized(value);chunks=[];f=font(size,mono)
  while d.textlength(value,font=f)>max_width*2:
   low,high=1,len(value)
   while low<high:
    middle=(low+high+1)//2
    if d.textlength(value[:middle],font=f)<=max_width*2:low=middle
    else:high=middle-1
   cut=value.rfind(' ',0,low+1)
   if cut<low//2:cut=low
   chunks.append(value[:cut]);value=value[cut:].lstrip()
  chunks.append(value)
  return chunks
 while sum(len(wrap(v,n))*(n+11)+9 for v in values)>978-start:
  n-=1
  if n<17:raise ValueError('Слишком много текста в кадре')
 for value in values:
  chunks=wrap(value,n)
  for part in chunks:
   if y+n>978:raise ValueError('Кадр переполнен: '+value)
   color=GREEN if any(t in part for t in ['PASS','Cached(','200','ALREADY_PUBLISHED','OK']) else AMBER if any(t in part for t in ['FAIL','503','422','exit=1']) else FG
   text(im,85,y,part,n,color,mono);y+=n+11
  y+=9
 return y

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 proof=read('regression-proof.json');m=read('manifest.json');gate=read('release-report.json')
 api=read('real-api.json');restart=read('real-api-restart.json');bench=read('benchmark.json')
 raw=log('check.log')
 assert re.search(r'Ran 21 tests',raw) and re.search(r'Ran 24 tests',raw)
 assert proof['before']['exit_code']!=0 and proof['after']['exit_code']==0
 assert gate['passed'] is True and api['matches_saved_evaluation'] and restart['matches_saved_evaluation']
 assert len([json.loads(s) for s in (E/'requests.jsonl').read_text().splitlines()])==16
 scenes=[]
 def add(title,source,values,duration,n=23,mono=False):scenes.append((title,source,values,duration,n,mono))
 add('От принятой модели до работающего API','единая работа по методичке к лекциям 8–9–10',[
  'Готовая модель ДЗ67 → полный допуск → accepted.json → загрузка и прогрев → ответы API.',
  'Семь причин ошибок исправлены. Восемь собственных проверок показаны до и после.',
  'Prefect выполняет четыре стадии. FastAPI обслуживает настоящую модель.',
  'Нового обучения нет: используется сохранённый адаптер Qwen3-0.6B.',
  'CPU / float32. После прогрева: 8 запросов при одном клиенте и 8 при двух.'
 ],18,n=30)
 defects=list(csv.DictReader((ROOT/'defects.csv').open()))
 add('Семь независимых причин ошибок','defects.csv · исходник e4cf8ad → исправления',[
  f"{r['id']}. {r['root_cause']} → {r['fix']}" for r in defects],32,n=23)
 before=log('before-integration.log')
 names=[]
 for line in before.splitlines():
  if line.startswith('test_') and 'subTest' not in line:
   name=line.split(' ')[0]
   if name not in names:names.append(name)
 add('Собственные проверки обнаруживают дефекты','make prove · один файл тестов для обеих версий',[
  'Исходный прототип: exit='+str(proof['before']['exit_code']),*names,
  'Восемь тестов не проходят по нарушениям поведения, без ошибок импорта.',
  'Три — реальный HTTP. Четыре — выпуск через отдельные процессы.',
  'Подробные команды и ответы: evidence/before/.'
 ],24,n=21,mono=True)
 add('Быстрые проверки проходят','make check · веса не загружаются',[
  'Исходные тесты ДЗ8–10: 09bd65e6b886',
  'Сохранённые тесты ДЗ67: c42ac7788026',
  *[line for line in raw.splitlines() if re.match(r'Ran (21|24) tests',line)],
  '13 исходных + 8 собственных + 24 из ДЗ67 = 45 проверок.',
  'Результаты двух наборов: OK.',
  'make check-negative: намеренно сломанный ключ кеша → exit=1.',
  'Поломка выполнялась во временной копии; рабочий код восстановлен.'
 ],24,n=27)
 fail=[x for x in log('flow-failed-after-prepare.log').splitlines() if 'PREPARED' in x or 'Finished in state Failed' in x][:3]
 recovered=[x for x in log('flow-recovered.log').splitlines() if 'Cached(' in x or 'PUBLISHED' in x or "Beginning flow run" in x]
 add('Сбой и восстановление в новом процессе','pipeline.py · настоящий локальный Prefect',[
  'Проверка данных → готовый артефакт → полный допуск → публикация.',
  'Сначала — управляемый сбой после подготовки, exit=1:',*fail,
  'Следующий процесс, exit=0:',*recovered,
  'Передаются пути, хеши и ID. Веса не становятся результатом задачи.'
 ],32,n=21,mono=True)
 changed=[]
 for name in ['flow-changed-input.log','flow-changed-template.log']:
  changed.append(name)
  changed += [x for x in log(name).splitlines() if 'PREPARED' in x]
 add('Кеш зависит от содержимого и обработки','persist_result + cache_key_fn · файлы читаются после завершения процесса',[
  'Ключ: байты входа + токенизатор + шаблон + max_length + версия и хеш кода.',
  'Изменены байты input.txt по прежнему пути: новая подготовка.',
  'Изменён шаблон: новая подготовка.',*changed,
  'Настоящий выпуск сверяет подготовленные данные с golden и runtime.',
  'Потерянный или изменённый сохранённый результат блокирует продолжение.'
 ],28,n=24)
 selected={k:gate[k] for k in ['status','passed','evaluation_run_id','metrics']}
 add('Выпуск связан с полной оценкой ДЗ67','model_release.py · quality_gate вызывается повторно по сохранённым ответам',[
  'Training run: '+m['training_run_id'],
  'Модель: '+m['artifact_uri'],
  'База: '+m['runtime']['base_revision'],
  'CPU / float32; тот же токенизатор, шаблон и библиотеки.',
  'Одна system-инструкция, seed 42, do_sample=False, max_new_tokens=32.',
  *json.dumps(selected,ensure_ascii=False,indent=2).splitlines(),
  'Хеши файлов пересчитываются до публикации и перед загрузкой.'
 ],32,n=22,mono=True)
 neg=read('negative-publication.json')
 add('Отказ сохраняет прежнюю принятую версию','неполный / чужой / отклонённый отчёт, NaN и ошибка замены',[
  *[f"{r['report']}: accepted.json unchanged={r['unchanged']}" for r in neg],
  'SHA256 до и после каждого опыта:',neg[0]['before_sha256'],
  'Все коды отказов и индивидуальные хеши: negative-publication.json.',
  'Оценка синтетических фикстур не выдаётся за оценку настоящей модели.'
 ],28,n=25,mono=True)
 recovery=read('publication-recovery.json')
 add('Повтор и восстановление журнала','attempts.jsonl отдельно от publications.jsonl',[
  'ID выпуска учитывает manifest, runtime и связанное решение оценки.',
  'Сбой внесён между заменой accepted.json и записью события.',
  'Следующий процесс восстановил согласованность.',
  'Событий после восстановления и повтора: '+str(recovery['events']),
  'Намерение и события сохраняются атомарно; JSONL журнала восстанавливается.',
  'Гарантии рассчитаны на одного писателя.',
  *[x for x in log('real-flow-repeat.log').splitlines() if 'ALREADY_PUBLISHED' in x]
 ],28,n=26)
 switches=[x for x in read('stub-versions.json') if 'phase' in x]
 add('Публикация, перезапуск и откат A → B → A','STUB ONLY · два лёгких артефакта, настоящие процессы и HTTP',[
  *[f"{x['phase']} → {x['model_id']}" for x in switches],
  'Изменение accepted.json не заменяет объект модели в памяти.',
  'Метаданные ответа берутся из фактически загруженного backend.',
  'Фикстуры не являются вторым обученным адаптером.'
 ],28,n=25,mono=True)
 response=api['real_response']['body']
 add('Настоящий ответ Qwen через FastAPI','real-api.json · transformers + peft',[
  *json.dumps(response,ensure_ascii=False,indent=2).splitlines(),
  'Ответ совпал с сохранённым ответом ДЗ67 на этот же вопрос.',
  'На вопросе об urxvt модель ошибается: A при эталоне B.',
  'Работа HTTP не означает правильность каждого ответа модели.'
 ],34,n=23,mono=True)
 statuses=[x for x in read('real-api-http.json') if x['path']=='/ready']
 assert any(x['status']==503 for x in statuses) and statuses[-1]['status']==200
 add('Готовность, ограничения и повторная загрузка','реальная модель · health / ready / generate',[
  'Пока идут загрузка и прогрев: health=200, ready=503.',
  'После прогрева: ready=200.',
  'Чрезмерный max_new_tokens: HTTP '+str(api['invalid_status']),
  f"Calls до/после неверного запроса: {api['calls_before_invalid']} / {api['calls_after_invalid']}",
  'После настоящего перезапуска снова загружен тот же manifest.',
  'Совпадение с сохранённой оценкой после перезапуска: '+str(restart['matches_saved_evaluation']),
  'До 8192 символов / 2048 токенов входа; 32 новых токена.',
  'Предел памяти службы: 3900 МиБ. После замера служба остановлена.'
 ],28,n=26)
 add('Одинаковые восемь запросов при 1 и 2 клиентах','benchmark.csv · requests.jsonl · после прогрева',[
  'Клиенты | n | успех/ошибка | пакет, с | успехов/с | средняя, с | максимум, с',
  *[f"{b['concurrency']} | {b['n']} | {b['success']}/{b['errors']} | {b['batch_seconds']:.3f} | {b['successful_requests_per_second']:.4f} | {b['mean_success_seconds']:.3f} | {b['max_success_seconds']:.3f}" for b in bench],
  'В каждом режиме: 64 выходных токена, лимит одинаков — 32.',
  'Два клиента в основном ждут блокировку одной модели.',
  'Все 16 попыток сохранены. Ошибок нет; задержки ошибок — null.',
  'Выборка мала. Устойчивый p95 и ускорение движка не заявляются.',
  'Измерена полная задержка. TTFT и ITL здесь не измерялись.'
 ],32,n=24,mono=True)
 add('Единый комплект сдачи','REPORT.md · defects.csv · evidence/ · submission/',[
  'Код и два этапа Git-истории: исходник и исправления.',
  'Семь причин ошибок, собственные красные и зелёные доказательства.',
  'Настоящий manifest, полный допуск, ответы API и сырые измерения.',
  'Код и отчёты упакованы; веса, окружения и кеши исключены.',
  'Адаптер передаётся отдельно по инструкции ARTIFACTS.txt.',
  'Локальные проверки выполнены. Удалённый Actions не запускался.',
  'Методичка, все 15 слайдов и 45 минут лекции учтены.'
 ],24,n=28)
 timeline=[]
 for index,(title,source,values,duration,n,mono) in enumerate(scenes):
  im=scene(title,source,index,len(scenes));lines(im,values,n,mono)
  path=OUT/f'{index:02d}.png';im.save(path);im.close()
  timeline += [f"file '{path}'",f'duration {duration}']
 timeline += [f"file '{OUT/f'{len(scenes)-1:02d}.png'}'"]
 (OUT/'concat.txt').write_text('\n'.join(timeline)+'\n')
 total=sum(s[3] for s in scenes);target=ROOT/'submission/hw8910_beekfin_4k_music.mp4'
 cmd=['prlimit','--as=1610612736','--','nice','-n','10','ffmpeg','-v','error','-y','-threads','1',
      '-f','concat','-safe','0','-i',str(OUT/'concat.txt'),'-stream_loop','-1','-i','/home/beekfin/Downloads/1-07_-haggstrom.mp3',
      '-map','0:v:0','-map','1:a:0','-filter_threads','1','-vf','format=yuv420p','-fps_mode','vfr',
      '-c:v','libx264','-preset','veryfast','-crf','18','-threads','1','-g','1',
      '-c:a','aac','-b:a','192k','-af',f'volume=0.4,afade=t=in:st=0:d=1,afade=t=out:st={total-3}:d=3',
      '-t',str(total+.04),'-movflags','+faststart',str(target)]
 subprocess.run(cmd,check=True)
 print('Готово:',target, 'длительность',total,'с')

if __name__=='__main__':main()
