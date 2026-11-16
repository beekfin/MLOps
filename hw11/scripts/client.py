"""Открытое расписание запросов: ожидание ответа не задерживает отправку новых."""
import argparse,asyncio,json,time,uuid
from pathlib import Path
import httpx

async def attempt(client,url,item,start_unix,run_id,client_id,timeout=45):
    planned=float(item['offset']);await asyncio.sleep(max(0,start_unix+planned-time.time()))
    sent=time.monotonic();unix=time.time();first=None;parts=[];done=False;pod=None;version=None;status=None;queue=None;hit=None
    request_id=f'{run_id}-{client_id}-{item["index"]}'
    payload={**item['payload'],'request_id':request_id,'session_id':f'session-{client_id}'}
    row={'run_id':run_id,'client_id':client_id,'request_id':request_id,'scheduled_offset':planned,
         'scheduled_unix':start_unix+planned,'sent_unix':unix,'sent_mono':sent,'send_lag_seconds':unix-(start_unix+planned),
         'input_length':len(payload['prompt']),'output_limit':payload['chunks']}
    try:
        async with client.stream('POST',url+'/generate',json=payload,timeout=timeout) as response:
            status=response.status_code;pod=response.headers.get('x-pod');version=response.headers.get('x-model-id')
            if status!=200:
                body=await response.aread()
                try:meta=json.loads(body);pod=meta.get('pod');version=meta.get('model_id')
                except ValueError:pass
                row['error']=body.decode()[:250]
            else:
                async for line in response.aiter_lines():
                    if not line:continue
                    event=json.loads(line)
                    if event.get('done'):done=True;continue
                    now=time.monotonic()
                    if first is None:first=now
                    parts.append(now);pod=event['pod'];version=event['model_id'];queue=event['queue_seconds'];hit=event['cache_hit']
        outcome='completed' if status==200 and done else 'rejected' if status==429 else 'interrupted' if status==200 else 'http_error'
    except httpx.TimeoutException as exc:outcome='timeout';row['error']=str(exc)
    except Exception as exc:outcome='interrupted' if status==200 else 'transport_error';row['error']=f'{type(exc).__name__}: {exc}'
    finished=time.monotonic()
    row.update(status=status,outcome=outcome,pod=pod,model_id=version,first_mono=first,finished_mono=finished,
               ttfc_seconds=first-sent if first is not None else None,duration_seconds=finished-sent,
               chunks=len(parts),done=done,queue_seconds=queue,cache_hit=hit,
               inter_chunk_seconds=[b-a for a,b in zip(parts,parts[1:])])
    return row

async def run(args):
    plan=json.loads(Path(args.schedule).read_text());items=[x for x in plan['requests'] if x['client']==args.client]
    limits=httpx.Limits(max_connections=256,max_keepalive_connections=0)
    async with httpx.AsyncClient(limits=limits,trust_env=False) as client:
        tasks=[asyncio.create_task(attempt(client,args.url,item,args.start,args.run_id,args.client,args.timeout)) for item in items]
        with Path(args.output).open('w') as stream:
            for future in asyncio.as_completed(tasks):
                row=await future;stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush()
    print(json.dumps({'run_id':args.run_id,'client':args.client,'planned':len(items),'finished':len(tasks)}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--schedule',required=True)
    p.add_argument('--output',required=True);p.add_argument('--start',type=float,required=True)
    p.add_argument('--client',type=int,required=True);p.add_argument('--run-id',required=True);p.add_argument('--timeout',type=float,default=45)
    asyncio.run(run(p.parse_args()))
