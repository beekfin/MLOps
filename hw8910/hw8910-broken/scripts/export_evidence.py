"""Сохранить маленькие описания и исходные отчёты; веса не копируются в сдачу."""
import json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    real=ROOT/'.runtime/real';out=ROOT/'evidence'
    for name,target in [('manifest-model.json','manifest.json'),('release-report.json','release-report.json'),
                        ('accepted.json','accepted.json'),('release-state.json','real-release-state.json'),
                        ('attempts.jsonl','real-attempts.jsonl')]:
        shutil.copy2(real/name,out/target)
    shutil.copytree(real/'hw67-evidence',out/'hw67',dirs_exist_ok=True)
    # Весь набор — только JSON/JSONL и чистые функции оценки, без тензоров.
    for path in (out/'hw67').rglob('*'):
        if path.suffix=='.pyc':path.unlink()
    for path in (out/'hw67').rglob('__pycache__'):
        if path.is_dir():path.rmdir()
    print('Manifest, принятый указатель, полный eval и сырые ответы сохранены в evidence/.')

if __name__=='__main__':main()
