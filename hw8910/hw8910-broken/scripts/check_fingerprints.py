"""Исходные тесты преподавателя и ДЗ67 не ослаблены."""
import hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def fingerprint(paths):
    h=hashlib.sha256()
    for p in sorted(paths):h.update(p.name.encode());h.update(p.read_bytes())
    return h.hexdigest()[:12]

def main():
    actual=fingerprint([ROOT/'tests/test_release.py']);assert actual=='09bd65e6b886',actual
    old=ROOT.parents[1]/'hw67/tests'
    previous=fingerprint([p for p in old.iterdir() if p.is_file()]);assert previous=='c42ac7788026',previous
    print('Исходные тесты ДЗ8–10: '+actual+'; ДЗ67: '+previous)

if __name__=='__main__':main()
