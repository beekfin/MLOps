"""Упаковать отчёты и доступные данные оценки без весов и обучающих тензоров."""
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / 'submission'
    out.mkdir(exist_ok=True)
    required = ['sweep.json', 'candidate-model.json', 'baseline-outputs.json',
                'candidate-outputs.json', 'baseline-eval.json', 'candidate-eval.json',
                'eval-diff.json', 'quality-gate.json', 'negative-gate.json',
                'storage-check.json', 'runs-export.json']
    for name in required:
        if not (ROOT / 'metrics' / name).is_file():
            raise SystemExit('Не хватает отчёта: ' + name)
    with zipfile.ZipFile(out / 'reports.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in required:
            archive.write(ROOT / 'metrics' / name, 'metrics/' + name)
        for name in ['released.json', 'environment.json']:
            path = ROOT / 'metrics' / name
            if path.is_file(): archive.write(path, 'metrics/' + name)
        for path in sorted((ROOT / 'metrics').glob('*.log')):
            archive.write(path, 'metrics/' + path.name)
    with zipfile.ZipFile(out / 'evaluation-data.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for directory in ['data/eval', 'data/source']:
            for path in sorted((ROOT / directory).glob('*.jsonl')):
                archive.write(path, str(path.relative_to(ROOT)))
        archive.write(ROOT / 'data/eval/provenance.json', 'data/eval/provenance.json')
        archive.write(out / 'golden-review.csv', 'golden-review.csv')
    tracked = subprocess.check_output(['git', 'ls-files', '-z', '--', '.'], cwd=ROOT).decode().split('\0')
    with zipfile.ZipFile(out / 'project.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in tracked:
            if not name:
                continue
            path = ROOT / name
            if not path.is_file():
                continue
            if path.suffix in {'.pt', '.safetensors', '.bin'} or '.venv' in path.parts:
                raise SystemExit('Недопустимый файл в Git: ' + name)
            archive.write(path, 'hw67/' + name)
    checksums = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in sorted(out.glob('*.zip'))}
    (out / 'SHA256.json').write_text(json.dumps(checksums, indent=2) + '\n')
    print(json.dumps(checksums, indent=2))


if __name__ == '__main__':
    main()
