"""Настоящие процессы, HTTP и файлы; один интерфейс для исходника и исправления."""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib import request, error

PROJECT = Path(os.environ.get('HW8910_PROJECT', Path(__file__).resolve().parents[1])).resolve()


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'workspace'
        self.trace = []
        self.addCleanup(self.save_trace)
        self.cli('init')

    def save_trace(self):
        if os.environ.get('HW8910_EVIDENCE'):
            directory = Path(os.environ['HW8910_EVIDENCE'])
            directory.mkdir(parents=True, exist_ok=True)
            (directory / (self._testMethodName + '.log')).write_text('\n'.join(self.trace))

    def cli(self, *args):
        command = [sys.executable, str(PROJECT / 'lab.py'), '--workspace', str(self.root), *args]
        result = subprocess.run(command, cwd=PROJECT, text=True, capture_output=True, timeout=30)
        self.trace.append(f'$ {command}\nexit={result.returncode}\n{result.stdout}{result.stderr}')
        return result

    def read(self, name):
        return json.loads((self.root / name).read_text())

    @contextlib.contextmanager
    def server(self, warmup=0):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        log = tempfile.TemporaryFile(mode='w+')
        process = subprocess.Popen([sys.executable, str(PROJECT / 'service.py'), '--workspace',
            str(self.root), '--port', str(port), '--warmup-seconds', str(warmup)],
            cwd=PROJECT, stdout=log, stderr=log)
        url = f'http://127.0.0.1:{port}'
        try:
            for _ in range(200):
                if process.poll() is not None:
                    log.seek(0); self.fail('Сервер завершился: ' + log.read())
                try:
                    self.http(url, '/health'); break
                except (OSError, error.URLError): time.sleep(.025)
            else: self.fail('Сервер не начал принимать HTTP')
            yield url
        finally:
            process.terminate()
            try: process.wait(timeout=8)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
            log.seek(0); self.trace.append(log.read()); log.close()

    def http(self, url, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = request.Request(url + path, data=data, headers={'Content-Type': 'application/json'})
        try: response = request.urlopen(req, timeout=10)
        except error.HTTPError as exc: response = exc
        with response:
            status, body = response.status, json.load(response)
        self.trace.append(f'HTTP {path} {payload} -> {status} {body}')
        return status, body

    def ready(self, url):
        for _ in range(200):
            status, _ = self.http(url, '/ready')
            if status == 200: return
            time.sleep(.025)
        self.fail('Не завершён прогрев')

    def test_cache_recovery_and_changed_input(self):
        before = (self.root / 'accepted.json').read_bytes()
        self.assertNotEqual(self.cli('run', '--fail-after-prepare').returncode, 0)
        self.assertEqual((self.root / 'accepted.json').read_bytes(), before)
        repeat = self.cli('run')
        self.assertEqual(repeat.returncode, 0, repeat.stderr)
        self.assertIn('CACHE_HIT', repeat.stdout)
        (self.root / 'input.txt').write_text('Новые байты по прежнему пути\n')
        changed = self.cli('run')
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertIn('PREPARED', changed.stdout)
        self.assertNotIn('CACHE_HIT', changed.stdout)

    def test_incomplete_foreign_and_rejected_reports(self):
        before = (self.root / 'accepted.json').read_bytes()
        for report in ['report-incomplete.json', 'report-A.json', 'report-reject.json']:
            with self.subTest(report=report):
                result = self.cli('run', '--report', report)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.root / 'accepted.json').read_bytes(), before)

    def test_repeated_release_in_new_process(self):
        self.assertEqual(self.cli('run').returncode, 0)
        first = (self.root / 'accepted.json').read_bytes()
        self.assertEqual(self.cli('run').returncode, 0)
        self.assertEqual((self.root / 'accepted.json').read_bytes(), first)
        events = [json.loads(s) for s in (self.root / 'publications.jsonl').read_text().splitlines()]
        self.assertEqual(len(events), 1, events)

    def test_atomic_write_error_preserves_pointer(self):
        spec = importlib.util.spec_from_file_location('release_subject', PROJECT / 'release.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        before = (self.root / 'accepted.json').read_bytes()
        with patch('os.replace', side_effect=OSError('controlled replace failure')):
            with self.assertRaises(OSError):
                module.publish(self.read('manifest-B.json'), self.read('report-B.json'), self.root / 'accepted.json')
        self.assertEqual((self.root / 'accepted.json').read_bytes(), before)
        self.assertEqual(list(self.root.glob('*.tmp')), [])
        self.trace.append('os.replace failure: old bytes retained; no temporary files')

    def test_http_readiness_waits_for_warmup(self):
        with self.server(warmup=2) as url:
            self.assertEqual(self.http(url, '/health')[0], 200)
            self.assertEqual(self.http(url, '/ready')[0], 503)
            self.assertEqual(self.http(url, '/generate', {'prompt': 'Hello'})[0], 503)
            self.ready(url)
            self.assertEqual(self.http(url, '/generate', {'prompt': 'Hello'})[0], 200)

    def test_http_loaded_version_restart_and_rollback(self):
        with self.server() as url:
            self.ready(url)
            self.assertEqual(self.http(url, '/generate', {'prompt': 'Before'})[1]['model_id'], 'fixture-A')
            self.assertEqual(self.cli('run').returncode, 0)
            status, response = self.http(url, '/generate', {'prompt': 'After publication'})
            self.assertEqual(status, 200)
            self.assertIn('fixture-A', response['answer'])
            self.assertEqual(response['model_id'], 'fixture-A')
        with self.server() as url:
            self.ready(url)
            self.assertEqual(self.http(url, '/generate', {'prompt': 'Restarted'})[1]['model_id'], 'fixture-B')
        # Совместимо с исходным прототипом: откат через публичную функцию publish.
        command = [sys.executable, '-c',
            'import json,sys;from pathlib import Path;import release;'
            'p=Path(sys.argv[1]);release.publish(json.loads((p/"manifest-A.json").read_text()),'
            'json.loads((p/"report-A.json").read_text()),p/"accepted.json")', str(self.root)]
        result = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.server() as url:
            self.ready(url)
            self.assertEqual(self.http(url, '/generate', {'prompt': 'Rollback'})[1]['model_id'], 'fixture-A')

    def test_http_invalid_request_does_not_call_backend(self):
        with self.server() as url:
            self.ready(url)
            before = self.http(url, '/debug')[1]['calls']
            for payload in [{'prompt': 'Hi', 'max_new_tokens': 100000},
                            {'prompt': 'Hi', 'max_new_tokens': True}, {'prompt': ' '},
                            {'prompt': 12}, {'prompt': 'x' * 9000}, {'prompt': 'Hi', 'surprise': 1}]:
                with self.subTest(payload=str(payload)[:70]):
                    status, _ = self.http(url, '/generate', payload)
                    self.assertTrue(400 <= status < 500)
            self.assertEqual(self.http(url, '/debug')[1]['calls'], before)

    def test_tampered_artifact_is_not_published(self):
        before = (self.root / 'accepted.json').read_bytes()
        (self.root / 'model-B.txt').write_text('STUB ONLY: altered file\n')
        self.assertNotEqual(self.cli('run').returncode, 0)
        self.assertEqual((self.root / 'accepted.json').read_bytes(), before)

    def test_fixture_name_does_not_bypass_real_evaluation(self):
        import hashlib
        before = (self.root / 'accepted.json').read_bytes()
        manifest = self.read('manifest-B.json')
        report = self.read('report-B.json')
        # Даже с именем fixture-B настоящий артефакт требует полного eval.
        manifest['synthetic'] = False
        report['synthetic'] = False
        (self.root / 'manifest-B.json').write_text(json.dumps(manifest))
        (self.root / 'report-B.json').write_text(json.dumps(report))
        result = self.cli('run')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.root / 'accepted.json').read_bytes(), before)

        # Объявление каталога весов фикстурой также не разрешает выпуск.
        folder = self.root / 'pretend-adapter'; folder.mkdir()
        for name in ['adapter_model.safetensors','adapter_config.json','manifest.json']:
            (folder / name).write_text('Synthetic negative fixture, not model weights')
        manifest['synthetic'] = report['synthetic'] = True
        manifest['artifact_uri'] = folder.name
        manifest['file_hashes'] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
        canonical = json.dumps(manifest['file_hashes'],sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
        manifest['model_sha256'] = report['model_sha256'] = hashlib.sha256(canonical).hexdigest()
        (self.root / 'manifest-B.json').write_text(json.dumps(manifest))
        (self.root / 'report-B.json').write_text(json.dumps(report))
        result = self.cli('run')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.root / 'accepted.json').read_bytes(), before)


if __name__ == '__main__': unittest.main(verbosity=2)
