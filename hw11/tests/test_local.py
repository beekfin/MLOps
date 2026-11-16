import asyncio,hashlib,json,tempfile,unittest
from pathlib import Path
from src.backend import SimulatedBackend
from src.service import GenerateRequest

class Contract(unittest.TestCase):
    def test_artifact_changed_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'model.json';p.write_text(json.dumps({'backend_mode':'simulated','model_id':'A'}))
            digest=hashlib.sha256(p.read_bytes()).hexdigest();p.write_text('{}')
            with self.assertRaises(ValueError):SimulatedBackend(p,digest,2,1,2,1)

    def test_cache_is_local_bounded_and_real_work(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'model.json';p.write_text(json.dumps({'backend_mode':'simulated','model_id':'A'}));digest=hashlib.sha256(p.read_bytes()).hexdigest()
            a=SimulatedBackend(p,digest,1,1,2,1);b=SimulatedBackend(p,digest,1,1,2,1)
            async def check():
                self.assertFalse(await a.prepare('prefix'));self.assertTrue(await a.prepare('prefix'))
                self.assertFalse(await b.prepare('prefix'));await a.prepare('other')
                self.assertFalse(await a.prepare('prefix'));self.assertEqual(len(a.cache),1)
            asyncio.run(check())

    def test_dialog_history_explicit_and_input_bounded(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):GenerateRequest(prompt='x',chunks=0)
        with self.assertRaises(ValidationError):GenerateRequest(prompt='x',extra='forbidden')
        a=GenerateRequest(prompt='x',history=[{'role':'user','content':'A'}]);b=GenerateRequest(prompt='x')
        self.assertEqual(a.history[0].content,'A');self.assertEqual(b.history,[])

if __name__=='__main__':unittest.main()
