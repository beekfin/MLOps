"""Быстрые проверки дефектов, включая ошибки и недоступные здесь ускорители."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import torch

from src.inspect_model import (PeakMemory, device_metric_source, forward_hooks,
                               group_table, lora_params_formula, memory_profile,
                               parameter_rows)


class Regressions(unittest.TestCase):
    def test_tied_and_untied_parameters(self):
        model = torch.nn.Module()
        model.embed_tokens = torch.nn.Embedding(5, 3)
        model.lm_head = torch.nn.Linear(3, 5, bias=False)
        for tied in (False, True):
            if tied:
                model.lm_head.weight = model.embed_tokens.weight
            rows = parameter_rows(model)
            table = group_table(rows)
            self.assertEqual(sum(x['params'] for x in table),
                             sum(p.numel() for p in model.parameters()))
            self.assertEqual(table[-1]['params'], 0 if tied else 15)
            self.assertEqual(table[-1]['tied_params'], 15 if tied else 0)

    def test_hooks_cleanup_on_exception_and_preserve_existing(self):
        layer = torch.nn.Identity()
        handle = layer.register_forward_hook(lambda *args: None)
        try:
            with self.assertRaisesRegex(RuntimeError, 'forward failed'):
                with forward_hooks({'layer': layer}) as store:
                    layer(torch.ones(1, 2, 3))
                    self.assertEqual(len(store['layer']), 2)
                    raise RuntimeError('forward failed')
            self.assertEqual(len(layer._forward_hooks), 1)
        finally:
            handle.remove()

    def test_lora_formula_and_non_target(self):
        model = torch.nn.Module()
        model.q_proj = torch.nn.Linear(3, 5)
        model.v_proj = torch.nn.Linear(3, 2)
        model.other = torch.nn.Linear(3, 7)
        self.assertEqual(lora_params_formula(model, 2, ['q_proj', 'v_proj']), 26)

    def test_cuda_reads_peak_not_final_allocation(self):
        with patch('torch.cuda.synchronize'), patch('torch.cuda.reset_peak_memory_stats') as reset, \
             patch('torch.cuda.memory_allocated', return_value=10), \
             patch('torch.cuda.max_memory_allocated', return_value=90):
            with PeakMemory(torch.device('cuda')) as peak:
                pass
            self.assertEqual(peak.used, 90)
            reset.assert_called_once()
            self.assertEqual(device_metric_source(torch.device('cuda')),
                             'torch.cuda.max_memory_allocated')

    def test_mps_keeps_larger_sample(self):
        with patch('torch.mps.synchronize'), \
             patch('torch.mps.driver_allocated_memory', side_effect=[10, 90, 20]):
            with PeakMemory(torch.device('mps'), interval=60) as peak:
                peak.checkpoint()
            self.assertEqual(peak.used, 90)
            self.assertFalse(peak.worker.is_alive())

    def test_cpu_keeps_process_high_water_mark(self):
        with patch('src.inspect_model.peak_rss', return_value=(90 * 1024**2, 'ru_maxrss')):
            with PeakMemory(torch.device('cpu')) as peak:
                pass
            self.assertEqual(peak.result()['peak_mb'], 90)

    def test_every_mode_repeat_uses_subprocess_and_passes_config(self):
        count = 0
        def run(command, **kwargs):
            nonlocal count
            count += 1
            self.assertEqual(json.loads(command[-1])['memory']['repeats'], 2)
            return SimpleNamespace(returncode=0, stdout=json.dumps(
                {'peak_mb': count, 'pid': count}), stderr='')
        with patch('src.inspect_model.subprocess.run', side_effect=run) as runner:
            result = memory_profile({'memory': {'repeats': 2}})
        self.assertEqual(runner.call_count, 6)
        self.assertEqual([x['peak_mb'] for x in result], [2, 4, 6])
        self.assertEqual([x['pids'] for x in result], [[1, 2], [3, 4], [5, 6]])

    def test_probe_failure_is_visible(self):
        with patch('src.inspect_model.subprocess.run', return_value=SimpleNamespace(
                returncode=1, stdout='', stderr='out of memory')):
            with self.assertRaisesRegex(RuntimeError, 'out of memory'):
                memory_profile({'memory': {'repeats': 1}})


if __name__ == '__main__':
    unittest.main()
