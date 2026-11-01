"""Связь сохранённой оценки ДЗ67 с конкретными файлами выпуска ДЗ8–10."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import release

PROJECT = Path(__file__).resolve().parent
SOURCE = PROJECT.parents[1] / 'hw67'
if not (SOURCE/'data/eval/golden.jsonl').is_file():
    SOURCE = PROJECT/'evidence/hw67'
EVAL_LIBRARIES = {'torch':'2.14.0','transformers':'5.17.0','peft':'0.21.0',
                  'tokenizers':'0.23.2','numpy':'2.5.3','accelerate':'1.15.0',
                  'safetensors':'0.8.0','huggingface-hub':'1.33.0'}


def read(path):
    return json.loads(Path(path).read_text())


def file_hash(path):
    return release.digest(Path(path).read_bytes())


def load_evaluation(root):
    source = Path(root) / 'hw67-evidence'
    # Две чистые функции загружаются из сохранённых исходников, без весов/MLflow.
    spec = importlib.util.spec_from_file_location('hw67_solution', source/'evaluation/solution.py')
    solution = importlib.util.module_from_spec(spec); spec.loader.exec_module(solution)
    return source, solution


def fingerprint(value):
    return release.digest(release.canonical(value))


def evaluation_fingerprint(value):
    # ДЗ67 использует JSON с пробелами; не меняем исторический протокол.
    return release.digest(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode())


def verify_evaluation(root, manifest, report=None):
    source, solution = load_evaluation(root)
    refs = manifest['evaluation_files']
    for name, expected in refs.items():
        if file_hash(source/name) != expected:
            raise ValueError('Изменён исходный отчёт/протокол: ' + name)
    config = read(source/'evaluation/params.json')
    rows = [json.loads(s) for s in (source/'data/eval/golden.jsonl').read_text().splitlines()]
    behavior = [json.loads(s) for s in (source/'data/eval/behavioral.jsonl').read_text().splitlines()]
    training = [json.loads(s) for s in (source/'data/eval/training-index.jsonl').read_text().splitlines()]
    baseline_spec = read(source/'evaluation/baseline.json')
    protocol = evaluation_fingerprint({'config': config, 'golden': rows, 'behavioral': behavior, 'training_index': training,
        'evaluation_code': {p.name: p.read_text() for p in sorted((source/'evaluation').glob('*.py'))}})
    reports = []
    for role in ['baseline', 'candidate']:
        result = read(source/f'metrics/{role}-eval.json')
        outputs = read(source/f'metrics/{role}-outputs.json')
        if result['protocol_sha256'] != protocol or result['golden_sha256'] != evaluation_fingerprint(rows) or result['baseline_spec_sha256'] != evaluation_fingerprint(baseline_spec):
            raise ValueError('Несовместимые данные/протокол оценки')
        if result['outputs_sha256'] != evaluation_fingerprint(outputs):
            raise ValueError('Изменены сырые ответы')
        by_id = {r['id']: r for r in outputs}
        if len(by_id) != len(outputs) or set(by_id) != {r['id'] for r in rows + behavior}:
            raise ValueError('Неверные ID ответов')
        computed = solution.score(rows, [by_id[r['id']] for r in rows])
        if any(result[k] != computed[k] for k in ['overall','slices','per_item']):
            raise ValueError('Неверно подсчитаны метрики')
        if result['behavioral'] != solution.score(behavior, [by_id[r['id']] for r in behavior]):
            raise ValueError('Неверный отчёт поведения')
        reports.append(result)
    base, candidate = reports
    if base['model'] != baseline_spec or candidate['model']['run_id'] != manifest['training_run_id'] or candidate['model']['uri'] != manifest['artifact_uri']:
        raise ValueError('Оценена другая модель')
    if manifest['protocol_sha256'] != protocol or manifest['golden_sha256'] != evaluation_fingerprint(rows):
        raise ValueError('Manifest связан с другим протоколом')
    runtime = manifest['runtime']
    if runtime.get('libraries') != EVAL_LIBRARIES:
        raise ValueError('Библиотеки генерации отличаются от среды оценки ДЗ67')
    g = runtime['generation']
    expected_g = {key: config[key] for key in ['system','seed','max_new_tokens','enable_thinking']}
    expected_g['do_sample'] = False
    if g != expected_g:
        raise ValueError('Изменены условия генерации')
    adapter = release.verify_files(manifest, root)
    original = read(adapter/'manifest.json')['model']
    if (runtime['base_name'],runtime['base_revision'],runtime['device'],runtime['dtype']) != (original['name'],original['revision'],original['device'],original['dtype']):
        raise ValueError('База, устройство или dtype отличаются от оценки')
    token_files = {name: file_hash(adapter/name) for name in ['tokenizer.json','tokenizer_config.json']}
    if runtime['tokenizer_sha256'] != fingerprint(token_files) or runtime['template_sha256'] != file_hash(adapter/'chat_template.jinja'):
        raise ValueError('Изменён токенизатор или шаблон')
    outcome = solution.quality_gate(base, candidate, config['critical_slices'])
    if outcome.get('passed') is not True:
        raise ValueError('Правило качества не подтвердило допуск')
    if report is not None:
        if report.get('evaluation_files') != refs or report['evaluation_run_id'] != candidate['evaluation_run_id'] or report['metrics'] != {k:candidate['overall'][k] for k in ['accuracy','format_rate']}:
            raise ValueError('Отчёт выпуска не соответствует полной оценке')
    return candidate


def create_report(root, manifest, report_name='release-report.json'):
    result = {key: manifest[key] for key in ['model_id','model_sha256','protocol_sha256','golden_sha256','runtime_sha256']}
    try:
        candidate = verify_evaluation(root, manifest)
        result.update(status='complete', passed=True, evaluation_run_id=candidate['evaluation_run_id'],
                      metrics={k:candidate['overall'][k] for k in ['accuracy','format_rate']},
                      evaluation_files=manifest['evaluation_files'], synthetic=False)
    except Exception as exc:
        result.update(status='failed',passed=False,error=f'{type(exc).__name__}: {exc}')
        release.write_json(Path(root)/report_name,result)
        raise
    release.write_json(Path(root)/report_name,result)
    return result


def prepare(root):
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    source_adapter = PROJECT/'.runtime/import/model/artifacts/adapter'
    artifact = root/'artifact'
    shutil.copytree(source_adapter, artifact, dirs_exist_ok=True)
    evidence = root/'hw67-evidence'
    names = ['evaluation/params.json','evaluation/baseline.json',
             'data/eval/golden.jsonl','data/eval/behavioral.jsonl','data/eval/training-index.jsonl',
             'metrics/baseline-eval.json','metrics/candidate-eval.json',
             'metrics/baseline-outputs.json','metrics/candidate-outputs.json','metrics/runs-export.json',
             'metrics/environment.json','metrics/candidate-model.json']
    names += [str(p.relative_to(SOURCE)) for p in (SOURCE/'evaluation').glob('*.py')]
    for name in names:
        target = evidence/name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE/name, target)
    candidate = read(evidence/'metrics/candidate-eval.json')
    original = read(artifact/'manifest.json')['model']
    config = read(evidence/'evaluation/params.json')
    generation = {key:config[key] for key in ['system','seed','max_new_tokens','enable_thinking']}
    generation['do_sample'] = False
    token_files = {name:file_hash(artifact/name) for name in ['tokenizer.json','tokenizer_config.json']}
    runtime = {'base_name':original['name'],'base_revision':original['revision'],
               'device':original['device'],'dtype':original['dtype'],
               'tokenizer_sha256':fingerprint(token_files),
               'template_sha256':file_hash(artifact/'chat_template.jinja'),'generation':generation,
               'libraries':EVAL_LIBRARIES}
    files = {name:file_hash(artifact/name) for name in ['adapter_config.json','adapter_model.safetensors','manifest.json']}
    manifest = {'schema_version':1,'model_id':'my-qwen-adapter/1@'+candidate['model']['run_id'],
        'artifact_uri':candidate['model']['uri'],'artifact_path':'artifact', 'synthetic':False,
        'training_run_id':candidate['model']['run_id'],'registry_version':'1',
        'model_sha256':fingerprint(files),'file_hashes':files,
        'runtime_file_hashes':{**token_files,'chat_template.jinja':runtime['template_sha256']},
        'protocol_sha256':candidate['protocol_sha256'],'golden_sha256':candidate['golden_sha256'],
        'runtime':runtime,'runtime_sha256':fingerprint(runtime),
        'evaluation_files':{name:file_hash(evidence/name) for name in names}}
    release.write_json(root/'manifest-model.json',manifest)
    shutil.copy2(evidence/'data/eval/golden.jsonl',root/'input.txt')
    release.write_json(root/'config.json',{'format':'golden-jsonl',
        'tokenizer_revision':runtime['base_revision'],'tokenizer_sha256':runtime['tokenizer_sha256'],
        'template_sha256':runtime['template_sha256'],'max_length':2048,
        'code_revision':file_hash(PROJECT/'lab.py')})
    print('Готовый артефакт ДЗ67; повторного обучения нет:',root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('command',choices=['prepare','gate'])
    parser.add_argument('--workspace',type=Path,default=PROJECT/'.runtime/real')
    args=parser.parse_args()
    if args.command=='prepare':prepare(args.workspace)
    else:create_report(args.workspace,read(args.workspace/'manifest-model.json'))
