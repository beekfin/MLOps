"""Контракты выпуска; не зависят от сервера, фреймворка и весов."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def cache_key(data_path: Path, config: dict) -> str:
    return digest(canonical({'data_sha256': digest(Path(data_path).read_bytes()), 'config': config}))


def validate_release(manifest: dict, report: dict) -> None:
    if not isinstance(manifest, dict) or not isinstance(report, dict):
        raise ValueError('Manifest и отчёт должны быть объектами')
    if type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        raise ValueError('Неверная версия схемы')
    for key in ['model_id', 'artifact_uri']:
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ValueError('Отсутствует ' + key)
    hashes = ['model_sha256', 'protocol_sha256', 'golden_sha256', 'runtime_sha256']
    for key in hashes:
        if not isinstance(manifest.get(key), str) or not re.fullmatch('[0-9a-f]{64}', manifest[key]):
            raise ValueError('Некорректный SHA256: ' + key)
    runtime = manifest.get('runtime')
    try:
        valid_runtime = isinstance(runtime, dict) and bool(runtime) and digest(canonical(runtime)) == manifest['runtime_sha256']
    except (ValueError, TypeError):
        valid_runtime = False
    if not valid_runtime:
        raise ValueError('Runtime изменён или не указан')
    if report.get('status') != 'complete' or report.get('passed') is not True:
        raise ValueError('Неполный отчёт или отказ по качеству')
    if not isinstance(report.get('evaluation_run_id'), str) or not report['evaluation_run_id'].strip():
        raise ValueError('Отсутствует evaluation_run_id')
    for key in ['model_id', *hashes]:
        if report.get(key) != manifest[key]:
            raise ValueError('Несовместимый отчёт: ' + key)
    metrics = report.get('metrics')
    if not isinstance(metrics, dict):
        raise ValueError('Нет метрик')
    for key in ['accuracy', 'format_rate']:
        value = metrics.get(key)
        if type(value) not in (float, int) or not 0 <= value <= 1 or not math.isfinite(value):
            raise ValueError('Некорректная метрика ' + key)


def atomic_bytes(target, payload):
    """Ошибка до os.replace оставляет прежний файл; один писатель."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(target, value):
    atomic_bytes(target, canonical(value) + b'\n')


def verify_files(manifest, workspace):
    """Пересчитать реальные байты артефакта, не доверяя одному manifest."""
    files = manifest.get('file_hashes')
    if not isinstance(files, dict) or not files:
        raise ValueError('Нет закреплённого списка файлов')
    root = Path(workspace).resolve()
    artifact = (root / manifest.get('artifact_path', manifest['artifact_uri'])).resolve()
    if not artifact.is_relative_to(root):
        raise ValueError('Артефакт должен находиться в workspace')
    if manifest.get('synthetic') is True:
        if (not artifact.is_file() or set(files) != {artifact.name}
                or not artifact.read_bytes().startswith(b'STUB ONLY')):
            raise ValueError('Тестовый артефакт должен быть одним текстовым файлом STUB ONLY')
    elif manifest.get('synthetic') is not False or not artifact.is_dir():
        raise ValueError('Нужна явно указанная настоящая модель или тестовая фикстура')
    elif not {'adapter_model.safetensors', 'adapter_config.json', 'manifest.json'} <= set(files):
        raise ValueError('Не закреплены обязательные файлы адаптера')
    base = artifact if artifact.is_dir() else artifact.parent
    actual = {}
    for name, expected in files.items():
        path = (base / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(base) or not path.is_file():
            raise ValueError('Недопустимый файл: ' + name)
        actual[name] = digest(path.read_bytes())
        if actual[name] != expected:
            raise ValueError('Изменены байты артефакта: ' + name)
    if digest(canonical(actual)) != manifest['model_sha256']:
        raise ValueError('Не совпадает общий хеш модели')
    if manifest['synthetic'] is False:
        for name, expected in manifest.get('runtime_file_hashes', {}).items():
            path = (artifact / name).resolve()
            if not path.is_relative_to(artifact) or digest(path.read_bytes()) != expected:
                raise ValueError('Изменён токенизатор/шаблон: ' + name)
    return artifact


def publish(manifest: dict, report: dict, target: Path) -> None:
    validate_release(manifest, report)
    write_json(target, manifest)
