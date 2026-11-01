"""Исполняемый прототип для расследования. Только синтетические данные, без модели.

Запускайте в отдельном каталоге .lab. Этот последовательный прототип надо
превратить в корректный Prefect-flow; его зелёный статус не доказывает корректность.
"""
import argparse
import hashlib
import json
from pathlib import Path
from src import release
import uuid


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path,value):
    release.write_json(path,value)


def initialize(root):
    if root.exists():
        raise FileExistsError('Рабочий каталог уже существует. Выберите новый --workspace.')
    root.mkdir(parents=True)
    runtime={'base_revision':'fixture-only','tokenizer_sha256':'a'*64,
             'template_sha256':'b'*64,'generation':{'max_new_tokens':32,'do_sample':False},'dtype':'float32'}
    for version in ['A','B']:
        artifact=root/f'model-{version}.txt';artifact.write_text(f'STUB ONLY — version {version}\n')
        files={artifact.name:digest(artifact.read_bytes())}
        m={'schema_version':1,'model_id':f'fixture-{version}','synthetic':True,
           'artifact_uri':artifact.name,'model_sha256':digest(canonical(files)),
           'protocol_sha256':'d'*64,'golden_sha256':'e'*64,
           'runtime_sha256':digest(canonical(runtime)),'runtime':runtime,'file_hashes':files}
        report={k:m[k] for k in ['model_id','model_sha256','protocol_sha256','golden_sha256','runtime_sha256']}
        report.update(status='complete',passed=True,evaluation_run_id=f'fixture-eval-{version}',metrics={'accuracy':.8,'format_rate':1.0},synthetic=True)
        write(root/f'manifest-{version}.json',m);write(root/f'report-{version}.json',report)
    write(root/'accepted.json',read(root/'manifest-A.json'))
    report=read(root/'report-B.json');report['status']='running';report['passed']='false'
    write(root/'report-incomplete.json',report)
    report=read(root/'report-B.json');report['passed']=False
    write(root/'report-reject.json',report)
    write(root/'config.json',{'tokenizer_revision':'r1','template_sha256':'b'*64,'max_length':128,'code_revision':'prepare-v1'})
    (root/'input.txt').write_text('Первый пример\nВторой пример\n')
    print('Создан синтетический стенд:',root)


def preparation_config(root):
    return {**read(root/'config.json'), 'implementation_sha256': digest(Path(__file__).read_bytes())}


def prepare(root):
    config=preparation_config(root);key=release.cache_key(root/'input.txt',config)
    cache=root/'cache';cache.mkdir(exist_ok=True);entry=cache/(key+'.json')
    if entry.exists():
        result=read(entry);print('CACHE_HIT',result['input_sha256']);return result
    payload=(root/'input.txt').read_bytes()
    rows = payload.decode().splitlines()
    if config.get('format') == 'golden-jsonl':
        parsed = [json.loads(s) for s in rows if s.strip()]
        ids = [r['id'] for r in parsed]
        if len(ids) != len(set(ids)) or not ids:
            raise ValueError('Пустые/повторяющиеся ID данных')
        for row in parsed:
            if not isinstance(row.get('input'), str) or not row['input'].strip() or row.get('expected') not in row.get('choices', []):
                raise ValueError('Неверная схема вопроса')
    result={'input_sha256':digest(payload),'rows':len(rows),'config':config,
            'cache_key':key,'uri':str(entry.resolve())}
    write(entry,result);print('PREPARED',result['input_sha256']);return result


def artifact(root, manifest_name='manifest-B.json'):
    manifest = read(root / manifest_name)
    release.verify_files(manifest, root)
    return manifest


def validate_bound(root, manifest, report_name):
    report = read(root / report_name)
    return validate_bound_report(root, manifest, report)


def validate_bound_report(root, manifest, report):
    release.validate_release(manifest, report)
    release.verify_files(manifest, root)
    if manifest['synthetic'] is True:
        if report.get('synthetic') is not True:
            raise ValueError('Отчёт фикстуры должен быть явно помечен synthetic=True')
    else:
        from src.model_release import verify_evaluation
        verify_evaluation(root, manifest, report)
    return report


def publish_event(root, manifest, report, fail_after_pointer=False):
    validate_bound_report(root, manifest, report)
    state_path = root / 'release-state.json'
    state = read(state_path) if state_path.exists() else {'events': [], 'pending': None}
    target = root / 'accepted.json'
    def save_events():
        release.atomic_bytes(root / 'publications.jsonl', b''.join(canonical(e) + b'\n' for e in state['events']))
    def complete_pending():
        pending = state['pending']
        if pending and target.exists() and digest(target.read_bytes()) == pending['accepted_sha256']:
            if not any(e['release_id'] == pending['release_id'] for e in state['events']):
                state['events'].append(pending)
        state['pending'] = None
        write(state_path, state); save_events()
    # Журнал намерения восстанавливает сбой между указателем и событием.
    complete_pending()
    release_id = digest(canonical({'manifest': manifest, 'decision': report}))
    existing = any(e['release_id'] == release_id for e in state['events'])
    expected = canonical(manifest) + b'\n'
    if existing and target.exists() and target.read_bytes() == expected:
        print('ALREADY_PUBLISHED', manifest['model_id']); return release_id
    state['pending'] = {'release_id': release_id, 'model_id': manifest['model_id'],
                        'runtime_sha256': manifest['runtime_sha256'],
                        'evaluation_run_id': report['evaluation_run_id'],
                        'accepted_sha256': digest(expected)}
    write(state_path, state)
    release.publish(manifest, report, target)
    if fail_after_pointer:
        raise RuntimeError('Инъекция сбоя между accepted.json и журналом')
    complete_pending()
    print('PUBLISHED', manifest['model_id'])
    return release_id


def run(root,report_name,fail_after_prepare=False,manifest_name='manifest-B.json',fail_after_pointer=False):
    attempt = {'attempt_id': str(uuid.uuid4()), 'manifest': manifest_name, 'report': report_name}
    try:
        prepared=prepare(root)
        if fail_after_prepare:raise RuntimeError('Инъекция сбоя после подготовки')
        manifest=artifact(root,manifest_name)
        report=validate_bound(root,manifest,report_name)
        attempt['release_id']=publish_event(root,manifest,report,fail_after_pointer)
        attempt['status']='completed'
        return attempt
    except Exception as exc:
        attempt.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        with (root/'attempts.jsonl').open('a') as f:
            f.write(json.dumps(attempt,ensure_ascii=False)+'\n')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,default=Path('.lab'))
    sub=parser.add_subparsers(dest='command',required=True);sub.add_parser('init')
    run_parser=sub.add_parser('run');run_parser.add_argument('--report',default='report-B.json');run_parser.add_argument('--fail-after-prepare',action='store_true')
    run_parser.add_argument('--manifest',default='manifest-B.json')
    run_parser.add_argument('--fail-after-pointer',action='store_true')
    args=parser.parse_args()
    if args.command=='init':initialize(args.workspace)
    else:run(args.workspace,args.report,args.fail_after_prepare,args.manifest,args.fail_after_pointer)


if __name__=='__main__':main()
