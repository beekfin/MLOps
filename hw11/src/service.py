"""FastAPI из ДЗ8–10: прогрев, очередь, поток, версия и метрики каждого Pod."""
import asyncio,json,os,time,uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request,Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,ConfigDict,Field
from prometheus_client import CollectorRegistry,Counter,Gauge,Histogram,ProcessCollector,generate_latest,CONTENT_TYPE_LATEST
from .backend import SimulatedBackend

POD=os.environ.get('POD_NAME','local');ROOT=Path(os.environ.get('HW11_CONFIG','/config'))

def env(name,default,kind=float):return kind(os.environ.get(name,default))
def emit(event,**fields):
    row={'event':event,'unix':time.time(),'mono':time.monotonic(),'pod':POD,**fields}
    print(json.dumps(row,ensure_ascii=False),flush=True)

class Message(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    role:str
    content:str=Field(max_length=8192)

class GenerateRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    prompt:str=Field(min_length=1,max_length=8192)
    prefix:str=Field(default='common-prefix',max_length=2048)
    history:list[Message]=Field(default_factory=list,max_length=30)
    session_id:str=Field(default='anonymous',max_length=120)
    request_id:str=Field(default_factory=lambda:str(uuid.uuid4()),max_length=120)
    chunks:int=Field(default=4,ge=1,le=80)
    chunk_delay:float=Field(default=0.09,ge=0,le=0.5)

class ServiceState:
    def __init__(self):
        self.ready=False;self.draining=False;self.backend=None;self.error=None
        self.running=0;self.waiting=0;self.active=0
        self.capacity=env('CONCURRENCY',1,int);self.max_waiting=env('MAX_WAITING',16,int)
        self.sem=asyncio.Semaphore(self.capacity)
        self.registry=CollectorRegistry();ProcessCollector(registry=self.registry)
        buckets=(.01,.025,.05,.1,.2,.4,.6,.8,1,1.5,2,3,5,8,12,20,30,60)
        self.requests=Counter('hw11_requests','Итог попытки',['outcome'],registry=self.registry)
        for outcome in ['completed','rejected','interrupted','not_ready']:self.requests.labels(outcome)
        self.arrivals=Counter('hw11_arrivals','Поступившие HTTP-запросы',registry=self.registry)
        self.ttfc=Histogram('hw11_ttfc_seconds','До первого фрагмента успешного ответа',buckets=buckets,registry=self.registry)
        self.duration=Histogram('hw11_response_seconds','Полный успешный ответ',buckets=buckets,registry=self.registry)
        self.queue=Histogram('hw11_queue_seconds','Ожидание обработки',buckets=buckets,registry=self.registry)
        self.busy=Gauge('hw11_running','Обрабатываемые запросы',registry=self.registry)
        self.queued=Gauge('hw11_waiting','Запросы в очереди',registry=self.registry)
        self.is_ready=Gauge('hw11_ready','Готовность backend',registry=self.registry)
        self.cache_hits=Counter('hw11_cache','Имитация кеша',['result'],registry=self.registry)
        self.version=Gauge('hw11_model_info','Загруженный артефакт',['model_id'],registry=self.registry)

    async def load(self):
        emit('load_start',warmup_seconds=env('WARMUP_SECONDS',20))
        try:
            self.backend=SimulatedBackend(ROOT/'model.json',os.environ['ARTIFACT_SHA256'],env('CACHE_SIZE',8,int),env('CACHE_HIT_MS',40),env('CACHE_MISS_MS',160),env('CHUNK_CPU_MS',3))
            await asyncio.sleep(env('WARMUP_SECONDS',20))
            if os.environ.get('FAIL_WARMUP','false')=='true':raise ValueError('Контролируемый отказ прогрева')
            self.ready=True;self.is_ready.set(1);self.version.labels(self.backend.loaded_id).set(1)
            emit('warmup_complete',model_id=self.backend.loaded_id,artifact_sha256=self.backend.artifact_sha256)
        except Exception as exc:self.error=str(exc);emit('load_failed',error=self.error)

    def metadata(self,payload=None):
        return {'backend_mode':'simulated','pod':POD,'model_id':self.backend.loaded_id if self.backend else None,
                'artifact_sha256':self.backend.artifact_sha256 if self.backend else None,
                **({'request_id':payload.request_id,'session_id':payload.session_id} if payload else {})}


def create_app():
    state=ServiceState()
    @asynccontextmanager
    async def lifespan(app):
        loader=asyncio.create_task(state.load())
        yield
        state.draining=True;state.is_ready.set(0)
        if not loader.done():loader.cancel()
        await asyncio.gather(loader,return_exceptions=True)
    app=FastAPI(lifespan=lifespan);app.state.service=state

    @app.get('/health')
    async def health():return {'alive':True,**state.metadata()}

    @app.get('/startup')
    async def startup():
        if os.environ.get('BROKEN_PROBES','false')!='true' and not state.ready:raise HTTPException(503,'Прогрев')
        return {'started':True,**state.metadata()}

    @app.get('/ready')
    async def ready():
        broken=os.environ.get('BROKEN_PROBES','false')=='true'
        if state.draining or (not broken and not state.ready):raise HTTPException(503,state.error or 'Прогрев')
        return {'ready':True,**state.metadata()}

    @app.post('/drain')
    async def drain():
        emit('drain_started',active=state.active)
        # EndpointSlice уже помечает удаляемый Pod terminating. Пока изменения
        # доходят до kube-proxy, обслуживаем последние поступающие соединения.
        await asyncio.sleep(3)
        state.draining=True;state.is_ready.set(0)
        return {'draining':True,'active':state.active}

    @app.post('/control/reset-cache',include_in_schema=False)
    async def reset_cache():
        if state.active:raise HTTPException(409,'Сначала завершите запросы')
        state.backend.cache.clear();emit('cache_reset');return {'cache_size':0}

    @app.get('/debug')
    async def debug():return {**state.metadata(),'warmup_finished':state.ready,'draining':state.draining,'running':state.running,'waiting':state.waiting,'active':state.active}

    @app.get('/metrics')
    async def metrics():return Response(generate_latest(state.registry),headers={'Content-Type':CONTENT_TYPE_LATEST})

    @app.post('/generate')
    async def generate(payload:GenerateRequest,request:Request):
        started=time.monotonic();state.arrivals.inc()
        meta=state.metadata(payload)
        emit('request_arrived',**{k:v for k,v in meta.items() if k!='pod'},peer_ip=request.client.host,ready=state.ready,
             running=state.running,waiting=state.waiting,prefix=payload.prefix)
        if not state.ready or state.draining:
            state.requests.labels('not_ready').inc();emit('request_rejected',request_id=payload.request_id,reason='not_ready')
            return Response(json.dumps({**meta,'error':'not_ready'}),status_code=503,media_type='application/json')
        if state.active>=state.capacity+state.max_waiting:
            state.requests.labels('rejected').inc();emit('request_rejected',request_id=payload.request_id,reason='queue_full')
            return Response(json.dumps({**meta,'error':'queue_full'}),status_code=429,media_type='application/json')
        state.active+=1;state.waiting+=1;state.queued.set(state.waiting)
        acquired=False
        try:
            await asyncio.wait_for(state.sem.acquire(),timeout=env('QUEUE_TIMEOUT_SECONDS',15))
            acquired=True
        except (TimeoutError,asyncio.CancelledError) as exc:
            state.active-=1;state.waiting-=1;state.queued.set(state.waiting)
            state.requests.labels('rejected' if isinstance(exc,TimeoutError) else 'interrupted').inc()
            if isinstance(exc,asyncio.CancelledError):raise
            return Response(json.dumps({**meta,'error':'queue_timeout'}),status_code=429,media_type='application/json')
        state.waiting-=1;state.running+=1;state.queued.set(state.waiting);state.busy.set(state.running)
        queue_seconds=time.monotonic()-started;state.queue.observe(queue_seconds)
        async def stream():
            completed=False;first=None;count=0
            try:
                hit=await state.backend.prepare(payload.prefix);state.cache_hits.labels('hit' if hit else 'miss').inc()
                history=[m.content for m in payload.history];text=' | '.join([*history,payload.prompt])
                for index in range(payload.chunks):
                    await asyncio.sleep(payload.chunk_delay)
                    await state.backend.chunk()
                    now=time.monotonic()
                    if first is None:first=now
                    count+=1
                    yield (json.dumps({**meta,'index':index,'text':text if index==0 else f'part-{index}',
                                      'queue_seconds':queue_seconds,'cache_hit':hit},ensure_ascii=False)+'\n').encode()
                elapsed=time.monotonic()-started
                completed=True;state.requests.labels('completed').inc();state.ttfc.observe(first-started);state.duration.observe(elapsed)
                emit('request_completed',request_id=payload.request_id,session_id=payload.session_id,model_id=state.backend.loaded_id,
                     ttfc=first-started,queue_seconds=queue_seconds,duration=elapsed,chunks=count,cache_hit=hit)
                yield (json.dumps({**meta,'done':True,'chunks':count})+'\n').encode()
            finally:
                if not completed:
                    state.requests.labels('interrupted').inc();emit('request_interrupted',request_id=payload.request_id,chunks=count)
                state.running-=1;state.active-=1;state.busy.set(state.running);state.sem.release()
        return StreamingResponse(stream(),media_type='application/x-ndjson',headers={'X-Pod':POD,'X-Model-ID':state.backend.loaded_id,'X-Request-ID':payload.request_id})
    return app

if __name__=='__main__':
    import uvicorn
    uvicorn.run(create_app(),host='0.0.0.0',port=8000,timeout_graceful_shutdown=45,access_log=False)
