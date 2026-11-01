"""Один локальный Prefect-flow. Получение артефакта читает готовое ДЗ67, не обучает."""
import argparse
import os
from pathlib import Path

# Только локальные метаданные и результаты; не используется Prefect Cloud.
HOME = Path(__file__).resolve().parent / '.prefect'
os.environ.setdefault('PREFECT_HOME', str(HOME))
os.environ.setdefault('PREFECT_SERVER_ANALYTICS_ENABLED', 'false')
os.environ.setdefault('PREFECT_LOGGING_LEVEL', 'INFO')
from prefect import flow, task, get_run_logger
from prefect.filesystems import LocalFileSystem
from prefect.runtime import flow_run
import uuid
import lab
import release


def input_key(context, parameters):
    root = Path(parameters['workspace'])
    return release.digest(release.canonical({'workspace': str(root.resolve()),
        'input_key': release.cache_key(root/'input.txt', lab.preparation_config(root)),
        'implementation': release.digest(Path(lab.__file__).read_bytes())}))


@task(persist_result=True, cache_key_fn=input_key, log_prints=True)
def prepare_input(workspace):
    return lab.prepare(Path(workspace))


@task(log_prints=True, persist_result=False)
def obtain_artifact(workspace, manifest_name, prepared, fail_after_prepare=False):
    if fail_after_prepare:
        raise RuntimeError('Инъекция сбоя после подготовки')
    root = Path(workspace)
    saved = Path(prepared['uri'])
    if not saved.is_file() or lab.read(saved) != prepared:
        raise ValueError('Сохранённый результат подготовки отсутствует или изменён')
    if prepared['cache_key'] != release.cache_key(root/'input.txt', lab.preparation_config(root)):
        raise ValueError('Подготовка не соответствует текущему входу')
    manifest = lab.artifact(root, manifest_name)
    if manifest['synthetic'] is False:
        if prepared['input_sha256'] != release.digest((root/'hw67-evidence/data/eval/golden.jsonl').read_bytes()):
            raise ValueError('Подготовленные данные изменились: нужна согласованная новая оценка')
        config = prepared['config']; runtime = manifest['runtime']
        if (config['tokenizer_revision'],config['tokenizer_sha256'],config['template_sha256'],config['max_length']) != (
                runtime['base_revision'],runtime['tokenizer_sha256'],runtime['template_sha256'],2048):
            raise ValueError('Подготовка использовала другие условия токенизации')
    get_run_logger().info('Читаем существующий training run %s; обучения здесь нет',
                          manifest.get('training_run_id', 'STUB ONLY'))
    return {'manifest': manifest_name, 'model_id': manifest['model_id'],
            'model_sha256': manifest['model_sha256'], 'input_sha256': prepared['input_sha256']}


@task(log_prints=True, persist_result=False)
def evaluate_admission(workspace, descriptor, report_name):
    root = Path(workspace)
    manifest = lab.read(root/descriptor['manifest'])
    if manifest['synthetic'] is False:
        from model_release import create_report
        create_report(root, manifest, report_name)
    report = lab.validate_bound(root, manifest, report_name)
    return {'manifest': descriptor['manifest'], 'report': report_name,
            'evaluation_run_id': report['evaluation_run_id'], 'passed': report['passed']}


@task(log_prints=True, persist_result=False)
def publish_accepted(workspace, decision, fail_after_pointer=False):
    root = Path(workspace)
    return lab.publish_event(root, lab.read(root/decision['manifest']),
                             lab.validate_bound(root, lab.read(root/decision['manifest']), decision['report']),
                             fail_after_pointer)


@flow(name='hw8910-release', log_prints=True, persist_result=False)
def release_flow(workspace, manifest_name='manifest-B.json', report_name='report-B.json',
                 fail_after_prepare=False, fail_after_pointer=False):
    root = Path(workspace).resolve()
    storage = LocalFileSystem(basepath=str(root/'prefect-results'))
    storage.save('hw8910-'+release.digest(str(root).encode())[:16], overwrite=True)
    attempt = {'attempt_id':str(uuid.uuid4()), 'flow_run_id':str(flow_run.id),
               'manifest':manifest_name, 'report':report_name}
    try:
        preparation = prepare_input.with_options(result_storage=storage, result_serializer='json')(str(root))
        descriptor = obtain_artifact(str(root), manifest_name, preparation, fail_after_prepare)
        decision = evaluate_admission(str(root), descriptor, report_name)
        result = publish_accepted(str(root), decision, fail_after_pointer)
        attempt.update(status='completed',release_id=result)
        return result
    except Exception as exc:
        attempt.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        with (root/'attempts.jsonl').open('ab') as stream:
            stream.write(release.canonical(attempt)+b'\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--workspace', type=Path, default=Path('.lab'))
    p.add_argument('--manifest', default='manifest-B.json')
    p.add_argument('--report', default='report-B.json')
    p.add_argument('--fail-after-prepare', action='store_true')
    p.add_argument('--fail-after-pointer', action='store_true')
    args = p.parse_args()
    release_flow(str(args.workspace), args.manifest, args.report,
                 args.fail_after_prepare, args.fail_after_pointer)
