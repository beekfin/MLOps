"""FastAPI: готовность после загрузки и прогрева; одна генерация одновременно."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from src import release


class StubBackend:
    """Только для управления процессами; не является ответом обученной модели."""
    def __init__(self, manifest, root=None):
        self.loaded_id = manifest['model_id']
        self.runtime_sha256 = manifest['runtime_sha256']
        self.calls = 0

    def generate(self, prompt, limit):
        self.calls += 1
        time.sleep(.01)
        return {'answer': f'STUB ONLY: {self.loaded_id}', 'output_tokens': 1}

    def warmup(self):
        self.generate('warmup', 32)


class GenerateRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    prompt: str = Field(min_length=1, max_length=8192)
    max_new_tokens: int | None = None


class ServiceState:
    def __init__(self, root, warmup_seconds, backend_factory=StubBackend):
        self.root = Path(root)
        self.ready = False
        self.error = None
        self.backend = None
        self.warmup_finished = threading.Event()
        self.lock = threading.Lock()
        self.warmup_seconds = warmup_seconds
        self.backend_factory = backend_factory
        self.manifest = None

    def load(self):
        try:
            manifest = json.loads((self.root / 'accepted.json').read_text())
            release.verify_files(manifest, self.root)
            if release.digest(release.canonical(manifest['runtime'])) != manifest['runtime_sha256']:
                raise ValueError('Не совпадает хеш runtime')
            if self.backend_factory is StubBackend and manifest['synthetic'] is not True:
                raise ValueError('Настоящая модель требует --backend transformers')
            if manifest['synthetic'] is False:
                from src import lab
                lab.validate_bound(self.root, manifest, 'release-report.json')
            self.manifest = manifest
            self.backend = self.backend_factory(manifest, self.root)
            time.sleep(self.warmup_seconds)
            self.backend.warmup()
            self.warmup_finished.set()
            self.ready = True
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
            print('LOAD_FAILED', self.error, flush=True)

    def generate(self, payload):
        if not self.ready:
            raise HTTPException(503, 'Модель ещё не готова')
        limit = self.manifest['runtime']['generation']['max_new_tokens']
        if not payload.prompt.strip() or (payload.max_new_tokens is not None and payload.max_new_tokens != limit):
            raise HTTPException(422, f'Нужен непустой prompt и закреплённый лимит {limit}')
        started = time.perf_counter()
        with self.lock:
            generation_started = time.perf_counter()
            try:
                result = self.backend.generate(payload.prompt, limit)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            generation_seconds = time.perf_counter() - generation_started
        result.update(model_id=self.backend.loaded_id, runtime_sha256=self.backend.runtime_sha256,
                      request_id=str(uuid.uuid4()), generation_seconds=generation_seconds,
                      queue_seconds=generation_started-started, server_seconds=time.perf_counter()-started)
        return result


def create_app(root, warmup_seconds=0, backend_factory=StubBackend):
    state = ServiceState(root, warmup_seconds, backend_factory)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(asyncio.to_thread(state.load))
        yield
        await task

    app = FastAPI(lifespan=lifespan)
    app.state.service = state

    @app.get('/health')
    async def health():
        return {'alive': True, 'backend': 'STUB ONLY' if backend_factory is StubBackend else 'transformers+peft'}

    @app.get('/ready')
    async def ready():
        if not state.ready:
            raise HTTPException(503, state.error or 'Загрузка или прогрев')
        return {'ready': True, 'model_id': state.backend.loaded_id,
                'runtime_sha256': state.backend.runtime_sha256}

    @app.get('/debug', include_in_schema=False)
    async def debug():
        return {'loaded_id': state.backend.loaded_id if state.backend else None,
                'calls': state.backend.calls if state.backend else 0,
                'warmup_finished': state.warmup_finished.is_set(), 'error': state.error}

    @app.post('/generate')
    def generate(payload: GenerateRequest):
        return state.generate(payload)

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, default=Path('.lab'))
    parser.add_argument('--port', type=int, default=8091)
    parser.add_argument('--warmup-seconds', type=float, default=5)
    parser.add_argument('--backend', choices=['stub','transformers'], default='stub')
    args = parser.parse_args()
    factory = StubBackend
    if args.backend == 'transformers':
        from src.backend import TransformersBackend
        factory = TransformersBackend
    import uvicorn
    uvicorn.run(create_app(args.workspace, args.warmup_seconds, factory), host='127.0.0.1', port=args.port)


if __name__ == '__main__': main()
