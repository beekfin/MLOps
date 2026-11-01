"""Настоящий backend: те же шаблон и параметры, что в evaluation/cli.py ДЗ67."""
from pathlib import Path
import importlib.metadata
import json
from src import release


class TransformersBackend:
    def __init__(self, manifest, root):
        if manifest.get('synthetic') is not False:
            raise ValueError('Настоящий генератор не принимает тестовые фикстуры')
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed
        self.loaded_id = manifest['model_id']
        self.runtime_sha256 = manifest['runtime_sha256']
        self.calls = 0
        self.runtime = manifest['runtime']
        runtime = self.runtime
        for name, version in runtime['libraries'].items():
            if importlib.metadata.version(name) != version:
                raise ValueError(f'Версия {name} отличается от оценки')
        if runtime['dtype'] != 'float32' or runtime['device'] != 'cpu':
            raise ValueError('Этот допуск получен для CPU/float32')
        artifact = release.verify_files(manifest, root)
        self.tokenizer = AutoTokenizer.from_pretrained(artifact, local_files_only=True)
        if release.digest(self.tokenizer.chat_template.encode()) != runtime['template_sha256']:
            raise ValueError('В память загружен другой шаблон')
        set_seed(runtime['generation']['seed'])
        torch.set_num_threads(4)
        base = AutoModelForCausalLM.from_pretrained(runtime['base_name'],
            revision=runtime['base_revision'], dtype=torch.float32, local_files_only=True)
        self.model = PeftModel.from_pretrained(base, artifact).to('cpu').eval()
        self.torch = torch

    def generate(self, prompt, limit):
        g = self.runtime['generation']
        if limit != g['max_new_tokens']:
            raise ValueError('Лимит не соответствует оценке')
        text = self.tokenizer.apply_chat_template([
            {'role': 'system', 'content': g['system']}, {'role': 'user', 'content': prompt}],
            tokenize=False, add_generation_prompt=True, enable_thinking=g['enable_thinking'])
        batch = self.tokenizer(text, return_tensors='pt').to('cpu')
        if batch['input_ids'].shape[1] > 2048:
            raise ValueError('Вход превышает 2048 токенов с system-инструкцией')
        self.calls += 1
        with self.torch.inference_mode():
            output = self.model.generate(**batch, max_new_tokens=limit, do_sample=g['do_sample'],
                pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id)
        tokens = output[0, batch['input_ids'].shape[1]:]
        return {'answer': self.tokenizer.decode(tokens, skip_special_tokens=True),
                'output_tokens': int(len(tokens))}

    def warmup(self):
        self.generate('Which package provides urxvt? A: rxvt-unicode. B: mariadb-server. C: urxvt-server-only.',
                      self.runtime['generation']['max_new_tokens'])
