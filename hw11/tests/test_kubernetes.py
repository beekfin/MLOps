"""Пять собственных проверок: все выполняют HTTP из настоящих клиентских Pod."""
import os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import experiments_a as a

@unittest.skipUnless(os.environ.get('HW11_K8S')=='1','Запустить make check-k8s после make up')
class KubernetesContract(unittest.TestCase):
    def test_01_warmup_excluded_from_traffic(self):a.warmup()
    def test_02_actual_version_after_rollback(self):a.rollout()
    def test_03_replacement_keeps_version_and_dialog(self):a.replacement()
    def test_04_rejections_and_interrupted_stream_counted(self):a.accounting()
    def test_05_two_dialogs_are_isolated(self):a.isolation()

if __name__=='__main__':unittest.main()
