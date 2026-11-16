"""Управляемый имитатор. Числа относятся к модели нагрузки, не к LLM."""
import asyncio,hashlib,json,time
from collections import OrderedDict
from pathlib import Path
from .release import digest


def cpu_work(seconds):
    end=time.thread_time()+seconds
    value=b'hw11-simulated'
    while time.thread_time()<end:
        value=hashlib.pbkdf2_hmac('sha256',value,b'hw11',1000)
    return value.hex()[:8]


class SimulatedBackend:
    mode='simulated'
    def __init__(self,path,expected_hash,cache_size,hit_ms,miss_ms,chunk_cpu_ms):
        raw=Path(path).read_bytes()
        if digest(raw)!=expected_hash:raise ValueError('SHA256 артефакта не совпадает')
        artifact=json.loads(raw)
        if artifact.get('backend_mode')!='simulated':raise ValueError('Требуется явный имитатор')
        self.loaded_id=artifact['model_id'];self.artifact_sha256=digest(raw)
        self.cache=OrderedDict();self.cache_size=cache_size
        self.hit_ms=hit_ms;self.miss_ms=miss_ms;self.chunk_cpu_ms=chunk_cpu_ms

    async def prepare(self,prefix):
        key=digest(prefix.encode());hit=key in self.cache
        await asyncio.to_thread(cpu_work,(self.hit_ms if hit else self.miss_ms)/1000)
        self.cache[key]=True;self.cache.move_to_end(key)
        while len(self.cache)>self.cache_size:self.cache.popitem(last=False)
        return hit

    async def chunk(self):
        return await asyncio.to_thread(cpu_work,self.chunk_cpu_ms/1000)
