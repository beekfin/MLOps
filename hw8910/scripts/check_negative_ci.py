"""Намеренная поломка в изолированной копии: тесты должны вернуть ненулевой код."""
from pathlib import Path
import json,shutil,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[1]

def main():
    with tempfile.TemporaryDirectory(prefix='hw8910-ci-negative-') as temp:
        root=Path(temp);shutil.copytree(ROOT/'tests',root/'tests')
        source=(ROOT/'src/release.py').read_text()
        old="return digest(canonical({'data_sha256': digest(Path(data_path).read_bytes()), 'config': config}))"
        assert old in source
        shutil.copytree(ROOT/'src',root/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copy2(ROOT/'release.py',root/'release.py')
        (root/'src/release.py').write_text(source.replace(old,"return '0' * 64  # намеренно сломанный ключ кеша"))
        result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_release.py','-v'],
                              cwd=root,capture_output=True,text=True)
        log=ROOT/'metrics/intentional-broken-check.log'
        log.write_text('Намеренная поломка cache_key только во временной копии.\n'
                       f'exit={result.returncode}\n'+result.stdout+result.stderr)
        assert result.returncode!=0 and 'AssertionError' in result.stderr
        (ROOT/'metrics/intentional-broken-check.json').write_text(json.dumps({
            'exit_code':result.returncode,'mutation':'cache_key always zero','isolated_copy':True,
            'working_code_unchanged':True},indent=2)+'\n')
    print('Отрицательный прогон завершился ожидаемой ошибкой; рабочий код сохранён.')

if __name__=='__main__':main()
