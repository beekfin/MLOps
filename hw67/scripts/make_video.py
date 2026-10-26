"""Видео по сохранённым реальным результатам; 4K, статичные кадры, малый расход RAM."""
from pathlib import Path
import csv,json,re,subprocess
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'submission/video-frames'
OUT.mkdir(parents=True,exist_ok=True)
F='/usr/share/fonts/TTF/DejaVuSans.ttf';B='/usr/share/fonts/TTF/DejaVuSans-Bold.ttf';M='/usr/share/fonts/TTF/DejaVuSansMono.ttf'
BG='#0c1523';FG='#edf3fc';GRAY='#99a9c1';CYAN='#47c8ea';GREEN='#43d39b';AMBER='#ffba69';PANEL='#182539'
font=lambda n,bold=False,mono=False:ImageFont.truetype(M if mono else B if bold else F,n*2)
def text(im,x,y,s,n=27,color=FG,bold=False,mono=False):
 ImageDraw.Draw(im).text((x*2,y*2),str(s),font=font(n,bold,mono),fill=color)
def paragraph(im,x,y,s,width=1490,n=27,color=FG):
 d=ImageDraw.Draw(im);f=font(n);line=''
 for word in str(s).split():
  test=(line+' '+word).strip()
  if d.textlength(test,font=f)>width*2 and line:
   text(im,x,y,line,n,color);y+=n+12;line=word
  else:line=test
 if line:text(im,x,y,line,n,color);y+=n+12
 return y

def box(im,x,y,w,h):
 ImageDraw.Draw(im).rounded_rectangle((x*2,y*2,(x+w)*2,(y+h)*2),radius=28,fill=PANEL,outline='#2d405a',width=3)
def base(title,sub,active):
 im=Image.new('RGB',(3840,2160),BG);d=ImageDraw.Draw(im)
 d.rectangle((0,0,3840,118),fill='#080f19');d.line((556,118,556,2160),fill='#2c3d54',width=4)
 for x,c in [(28,'#ff605c'),(56,'#ffbd44'),(84,'#00ca4e')]:d.ellipse(((x-7)*2,44,(x+7)*2,72),fill=c)
 text(im,125,17,'MLOps / Homework 6 + 7',20,GRAY)
 text(im,1460,17,'Ask Ubuntu  •  Qwen3-0.6B',19,CYAN)
 text(im,24,90,'EXPLORER',17,GRAY);text(im,24,135,'hw67',23,CYAN,True)
 names=['Данные','Исправления','6 конфигураций','MLflow','Кандидат','Оценка ответов','Допуск','Проверки','Вывод']
 for i,name in enumerate(names):
  y=210+i*69
  if name==active:d.rounded_rectangle((24,(y-8)*2,530,(y+38)*2),radius=12,fill='#20334b')
  text(im,34,y,name,21,FG if name==active else GRAY)
 text(im,328,92,sub.upper(),18,CYAN);text(im,328,132,title,40,FG,True)
 d.line((656,382,3730,382),fill='#2c3d54',width=3)
 text(im,328,1030,'HW67 / ЭКСПЕРИМЕНТЫ И КАЧЕСТВО ОТВЕТОВ',17,GRAY)
 return im

def image_panel(im,path):
 picture=Image.open(path).convert('RGB');factor=min(3050/picture.width,1460/picture.height);picture=picture.resize((int(picture.width*factor),int(picture.height*factor)),Image.Resampling.LANCZOS)
 im.paste(picture,(656,450))

def main():
 def read(name):return json.loads((ROOT/name).read_text())
 sweep=read('metrics/sweep.json');a=read('metrics/baseline-eval.json');b=read('metrics/candidate-eval.json')
 gate=read('metrics/quality-gate.json');negative=read('metrics/negative-gate.json');storage=read('metrics/storage-check.json')
 diff=read('metrics/eval-diff.json');candidate=read('metrics/candidate-model.json')
 rawlog=re.sub(r'\x1b\[[0-9;]*m','',(ROOT/'metrics/check-all.log').read_text())
 if 'Итог: 9/9' not in rawlog or not re.search(r'Ran 24 tests',rawlog):raise SystemExit('Нет подтверждённого полного результата тестов')
 rows=list(csv.DictReader((ROOT/'docs/comparison.csv').open()))
 golden={r['id']:r for r in map(json.loads,(ROOT/'data/eval/golden.jsonl').read_text().splitlines())}
 scenes=[]
 def add(im,duration):scenes.append((im,duration))
 im=base('От эксперимента до проверенного адаптера','единая работа к лекциям 6 и 7','Вывод')
 paragraph(im,328,250,'Шесть LoRA-конфигураций → один кандидат → реальные ответы → решение о выпуске.',n=35)
 for x,value,label in [(328,'6','законченных конфигураций'),(850,'50 + 3','вопросов и проверок поведения'),(1370,'9 / 9','проверок части A')]:
  box(im,x,440,495,210);text(im,x+24,463,value,56,GREEN,True);paragraph(im,x+24,555,label,width=450,n=25)
 paragraph(im,328,735,'Собственный датасет Ask Ubuntu, Qwen/Qwen3-0.6B, CPU/float32. Видео построено по реальным сохранённым запускам, отчётам и интерфейсу MLflow.',n=29)
 add(im,18)
 im=base('Происхождение данных и отсутствие пересечений','data.dvc • data/eval/provenance.json','Данные')
 items=['2211 исходных train-вопросов → 2197 токенизированных примеров ДЗ 4.','Полный training-index используется для проверки пересечений.','Golden: 50 разных вопросов из исходного val, вне train и восьми вопросов подбора.','Точных совпадений и пересечений исходных тематических групп: 0.','Метки A/B/C: 17 / 17 / 16. Разметка и исходные принятые ответы сохранены через DVC.']
 y=245
 for s in items:y=paragraph(im,328,y,s,n=30)+37
 paragraph(im,328,855,'Сверка ассистентом выполнена. Проверка человеком: '+('подтверждена автором.' if (ROOT/'docs/golden-human-review.md').exists() else 'пока не подтверждена; таблица golden-review.csv подготовлена.'),n=25,color=AMBER)
 add(im,24)
 im=base('Четыре дефекта исправлены','docs/defects.md','Исправления')
 fixes=[('Общая запись для всех моделей','Каждой конфигурации — собственный дочерний run.'),('Файлы внутри заменяемого контейнера','artifacts:/mlartifacts → постоянное хранилище.'),('Исключённые версии train/val','SHA256 обоих файлов сохраняется у каждого кандидата.'),('Регистрация без проверки порога','gate(run, threshold) выполняется до записи в реестр.')]
 for i,(cause,fix) in enumerate(fixes):
  y=240+i*175;box(im,328,y,1538,150);text(im,350,y+17,f'{i+1}. {cause}',28,FG,True);text(im,350,y+81,fix,26,GREEN)
 add(im,28)
 im=base('Одинаковые условия шести обучений','params.yaml • фиксированный вычислительный бюджет','6 конфигураций')
 for i,s in enumerate(['База и её ревизия, train/val и seed 42 одинаковы.','4 шага на конфигурацию, train-пул 32, val 8.','Микробатч 1 × накопление 2. Проверка val на шагах 0, 2, 4.','Меняются только lr, ранг r и набор проекций LoRA; alpha/r = 2.','Словарь считается порциями по 32 токена; правило loss сохранено.','Последовательное выполнение, отдельная служба с пределом RAM.']):paragraph(im,328,245+i*108,s,n=29)
 add(im,24)
 im=base('Шесть запусков в MLflow','интерфейс сервера • снимок настоящих результатов','MLflow')
 image_panel(im,ROOT/'docs/mlflow-runs.jpg');add(im,30)
 im=base('Сравнение конфигураций','docs/comparison.csv • числа получены из MLflow','6 конфигураций')
 xs=[328,570,670,840,1080,1320,1540]
 for x,s in zip(xs,['Конфигурация','r','lr','Проекции','Val до','Val после','Время, с']):text(im,x,240,s,23,CYAN,True)
 for i,row in enumerate(rows):
  values=[row['name'],row['r'],row['lr'],'q,v' if row['name'].startswith('qv') else 'все 7',f"{float(row['base_val_loss']):.4f}",f"{float(row['final_val_loss']):.4f}",f"{float(row['seconds']):.1f}"]
  for x,s in zip(xs,values):text(im,x,315+i*82,s,25,GREEN if i==0 else FG)
 paragraph(im,328,855,'Время включает обучение и замеры val. Это четыре шага, а не полная эпоха. Таблица относится только к одному завершённому sweep.',n=27,color=GRAY)
 add(im,28)
 im=base('Кандидат зарегистрирован по порогу loss','models:/my-qwen-adapter@candidate','Кандидат')
 image_panel(im,ROOT/'docs/mlflow-model.jpg');add(im,24)
 im=base('Протокол оценки закреплён заранее','evaluation/params.json • evaluation/baseline.json','Оценка ответов')
 lines=['Первый baseline — исходная база с точной commit-ревизией.','Оцениваются база и один кандидат, а не все шесть моделей.','Одна system-инструкция, жадная генерация, seed 42, до 32 новых токенов.','Строго JSON: {"answer":"A"}, без лишних полей и пояснений.','Ошибки, пустые и невалидные ответы остаются в знаменателе.','Все ответы, показатели и исправленные/потерянные id сохранены.']
 for i,s in enumerate(lines):paragraph(im,328,240+i*112,s,n=28)
 add(im,22)
 im=base('Общие показатели и три среза','baseline-eval.json • candidate-eval.json','Оценка ответов')
 text(im,328,235,'Группа',28,CYAN,True);text(im,1010,235,'База',28,CYAN,True);text(im,1430,235,'Кандидат',28,CYAN,True)
 groups=[('Все вопросы',a['overall'],b['overall'])]+[(s,a['slices'][s],b['slices'][s]) for s in sorted(a['slices'])]
 for i,(name,left,right) in enumerate(groups):
  y=315+i*115;text(im,328,y,name,27)
  for x,v in [(1010,left),(1430,right)]:text(im,x,y,f"{v['correct']}/{v['n']} = {v['accuracy']:.1%}",28)
 text(im,328,810,'Правильный формат:',28,CYAN)
 text(im,1010,810,f"{a['overall']['valid']}/50",28);text(im,1430,810,f"{b['overall']['valid']}/50",28)
 paragraph(im,328,905,'Критические срезы: installation и troubleshooting. Улучшено ответов: '+str(len(diff['improved']))+'; потеряно: '+str(len(diff['regressed']))+'.',n=25,color=AMBER)
 add(im,28)
 im=base('Что исправили и что потеряли','сырые ответы и ожидаемые метки • два примера','Оценка ответов')
 selected=list(dict.fromkeys(diff['regressed'][:1]+diff['improved'][:1]+list(golden)))[:2]
 pa={r['id']:r for r in a['per_item']};pb={r['id']:r for r in b['per_item']}
 y=225
 for item_id in selected:
  row=golden[item_id];y=paragraph(im,328,y,row['input'],n=24)+12
  y=paragraph(im,328,y,'Ожидается: '+row['expected']+' | База: '+str(pa[item_id]['raw'])+' | Кандидат: '+str(pb[item_id]['raw']),n=25,color=CYAN)+35
 paragraph(im,328,940,'Подробный ручной разбор 3–5 пар — в docs/conclusion.md.',n=25,color=GRAY)
 add(im,36)
 im=base('Три обязательные проверки поведения','формат • перефраз • корректный отказ','Оценка ответов')
 kinds=['Соблюдение JSON-формата','Перефраз без изменения ответа','Отказ на запрос вне темы Ubuntu']
 left=a['behavioral']['per_item'];right=b['behavioral']['per_item']
 for i,(name,x,z) in enumerate(zip(kinds,left,right)):
  y=245+i*220;text(im,328,y,name,30,CYAN,True)
  paragraph(im,328,y+65,'База: '+str(x['raw']),n=26)
  paragraph(im,328,y+125,'Кандидат: '+str(z['raw']),n=26,color=GREEN if z['correct'] else AMBER)
 add(im,22)
 im=base('Решение о выпуске','metrics/quality-gate.json • автоматическое правило','Допуск')
 passed=gate.get('passed') is True
 text(im,328,255,'PASS' if passed else 'ОТКАЗ В ВЫПУСКЕ',62,GREEN if passed else AMBER,True)
 paragraph(im,328,385,'Причина: '+gate.get('reason','Проверки совместимости, общих показателей, критических срезов и поведения пройдены.'),n=31)
 paragraph(im,328,595,'champion назначен проверенной версии.' if passed else 'candidate остаётся доступным. champion не назначается; baseline не подменяется. Отказ разрешён заданием.',n=31,color=CYAN)
 paragraph(im,328,810,'Пороги и критические срезы не менялись после просмотра ответов.',n=27,color=GRAY)
 add(im,24)
 im=base('Отрицательная проверка и сохранность файлов','negative-gate.json • storage-check.json','Проверки')
 paragraph(im,328,245,'Испорченная копия ответов отклонена: '+str(negative['rejected'])+'. Настоящие веса, ответы и указатели не изменялись.',n=30,color=GREEN)
 paragraph(im,328,430,'Проверка хранения действительно пересоздала контейнер MLflow через --force-recreate. Контрольный файл скачан заново; SHA256 совпал.',n=30)
 text(im,328,645,'SHA256 probe.txt:',26,CYAN)
 paragraph(im,328,700,storage['sha256'],n=27)
 paragraph(im,328,850,'Отдельно проверен отказ регистрации при нулевом пороге loss.',n=27,color=GRAY)
 add(im,28)
 im=base('Итоговые проверки','сохранённый настоящий лог make check-all','Проверки')
 y=228
 for line in rawlog.splitlines():
  if line.startswith('PASS '):text(im,328,y,line,23,GREEN);y+=49
 text(im,328,760,'Итог: 9/9',42,GREEN,True)
 text(im,328,835,'Тесты оценки: 24 / 24 • OK',30,GREEN)
 text(im,328,910,'Отпечаток tests/: c42ac7788026',28,CYAN,mono=True)
 add(im,26)
 im=base('Единый комплект сдачи','репозиторий • отчёты • данные • одно видео','Вывод')
 for i,s in enumerate(['Код, конфиг, версии данных и исходные тесты сохранены.','Шесть сопоставимых запусков и одна реальная оценка двух версий.','CSV, четыре дефекта и единый вывод с разбором ответов.','Отдельные архивы отчётов и данных оценки без весов и тензоров.']):paragraph(im,328,245+i*125,s,n=31)
 paragraph(im,328,810,'Ограничения: короткое обучение, 50 вопросов, исторические ответы и простые варианты выбора. Это учебная проверка, а не доказательство общего превосходства модели.',n=27,color=AMBER)
 add(im,18)
 timeline=[]
 for index,(im,duration) in enumerate(scenes):
  text(im,1750,1030,f'{index+1}/{len(scenes)}',20,GRAY)
  path=OUT/f'{index:02d}.png';im.save(path)
  timeline.extend([f"file '{path}'",f'duration {duration}'])
 timeline.append(f"file '{OUT/f'{len(scenes)-1:02d}.png'}'")
 (OUT/'concat.txt').write_text('\n'.join(timeline)+'\n')
 total=sum(d for _,d in scenes)
 target=ROOT/'submission/hw67_beekfin_4k_music.mp4'
 command=['prlimit','--as=1610612736','--','nice','-n','10','ffmpeg','-v','error','-y','-threads','1','-f','concat','-safe','0','-i',str(OUT/'concat.txt'),'-stream_loop','-1','-i','/home/beekfin/Downloads/1-07_-haggstrom.mp3','-map','0:v:0','-map','1:a:0','-filter_threads','1','-vf','format=yuv420p','-fps_mode','vfr','-c:v','libx264','-preset','veryfast','-crf','18','-threads','1','-g','1','-c:a','aac','-b:a','192k','-af',f'afade=t=in:st=0:d=1,afade=t=out:st={total-3}:d=3','-t',str(total+0.04),'-movflags','+faststart',str(target)]
 subprocess.run(command,check=True)
 print('Video:',target,'duration',total,'seconds')

if __name__=='__main__':main()
