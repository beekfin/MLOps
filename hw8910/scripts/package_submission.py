"""Код и доказательства отдельно от весов; контрольные суммы комплекта сдачи."""
import hashlib,json,subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent


def main():
    out=ROOT/'submission';out.mkdir(exist_ok=True)
    tracked=subprocess.check_output(['git','ls-files','-z','--','hw8910','hw67'],cwd=REPO).decode().split('\0')
    with zipfile.ZipFile(out/'project.zip','w',zipfile.ZIP_DEFLATED) as z:
        for name in tracked:
            if not name or name.startswith('hw8910/metrics/'):continue
            p=REPO/name
            if not p.is_file():continue
            if p.suffix in ['.pt','.bin','.safetensors'] or any(x in p.parts for x in ['.venv','.cache','.runtime','.prefect']):
                raise ValueError('Недопустимый файл в Git: '+name)
            z.write(p,name)
    with zipfile.ZipFile(out/'evidence.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted((ROOT/'metrics').rglob('*')):
            if p.is_file():
                if p.suffix not in ['.json','.jsonl','.txt','.log','.csv','.py','.png','.jpg']:
                    raise ValueError('Неожиданный файл доказательств: '+str(p))
                z.write(p,str(p.relative_to(REPO)))
    m=json.loads((ROOT/'metrics/manifest.json').read_text())
    artifact=ROOT/'.runtime/real/artifact'
    instructions=f'''Артефакты модели передаются отдельно от Git и архивов сдачи.

Готовая папка для передачи преподавателю: {artifact}
Обязательные файлы: adapter_model.safetensors, adapter_config.json, manifest.json,
tokenizer.json, tokenizer_config.json, chat_template.jinja.

Это существующий результат training run {m['training_run_id']}.
URI реестра: {m['artifact_uri']}. Контрольные суммы — metrics/manifest.json.
База: {m['runtime']['base_name']}, revision {m['runtime']['base_revision']}.
Её публичные файлы доступны в Hugging Face по этой точной ревизии.

Вариант 1: преподаватель получает папку адаптера отдельными файлами от автора,
кладёт её в hw8910/.runtime/import/model/artifacts/adapter/,
затем выполняет make prepare-real, make release, make serve.
Исходная оценка приложена в metrics/hw67/ и используется без сервера MLflow.
Базовую модель нужно один раз скачать в кеш huggingface_hub по точной ревизии.

Вариант 2: при доступе к авторскому локальному MLflow запустить make fetch-model.
Адрес по умолчанию http://127.0.0.1:5006 относится к компьютеру автора;
он НЕ является общедоступной ссылкой. Параметр --tracking-uri задаётся в fetch_model.py.
Сервис в публичную сеть не выставлялся.

Вариант 3: прикрепить шесть файлов адаптера отдельными файлами в разделе
GitHub Releases репозитория beekfin/MLOps и передать ссылку на релиз.
Это отдельные вложения релиза, не файлы Git и не архив с весами.
Публикация релиза ещё не выполнялась; не считать эту инструкцию ссылкой доступа.

Архив project.zip распаковать в корень проекта, затем evidence.zip туда же.
Быстрый make check не требует весов. Для make prove нужен исходный Git-репозиторий
с коммитом e4cf8ad; архив не подменяет историю Git.
'''
    (out/'ARTIFACTS.txt').write_text(instructions)
    manifest={'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        'original_commit':'e4cf8ad','initial_fix_commit':'f402799','original_tests_fingerprint':'09bd65e6b886',
        'hw67_tests_fingerprint':'c42ac7788026','checks':{'provided':13,'own':9,'hw67':24},
        'training_run_id':m['training_run_id'],'model_id':m['model_id'],'runtime_sha256':m['runtime_sha256'],
        'benchmark':json.loads((ROOT/'metrics/benchmark.json').read_text()),'video':'hw8910_beekfin_4k_music.mp4'}
    (out/'SUBMISSION.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    checks={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.suffix in ['.zip','.mp4']}
    (out/'SHA256.json').write_text(json.dumps(checks,indent=2)+'\n')
    print(json.dumps(checks,indent=2))

if __name__=='__main__':main()
