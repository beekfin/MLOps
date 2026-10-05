"""Run in friend's hw5: uv run python /path/to/prepare_fast.py --device cpu."""
import argparse
import hashlib
import json
import math
import random
from pathlib import Path

import torch
import yaml


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select(blob, limit, max_len, seed):
    candidates = []
    for e in blob['examples']:
        ids, labels, mask = e['input_ids'], e['labels'], e['attention_mask']
        if not (len(ids) == len(labels) == len(mask)):
            raise ValueError('Несогласованные длины тензоров')
        if 1 < len(ids) <= max_len and any(x != -100 for x in labels[1:]):
            candidates.append(e)
    random.Random(seed).shuffle(candidates)
    picked = candidates[:limit]
    if not picked:
        raise ValueError('Нет подходящих примеров: увеличьте --max-len')
    result = dict(blob)
    result['examples'] = picked
    return result, {'source_examples': len(blob['examples']), 'eligible': len(candidates),
                    'selected': len(picked), 'tokens': sum(len(e['input_ids']) for e in picked),
                    'max_length': max(len(e['input_ids']) for e in picked)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', type=Path, default=Path('../hw4/data/tokenized'))
    ap.add_argument('--out', type=Path, default=Path('data/tokenized_fast'))
    ap.add_argument('--train-count', type=int, default=1000)
    ap.add_argument('--val-count', type=int, default=100)
    ap.add_argument('--max-len', type=int, default=512)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--device', choices=['cpu', 'mps', 'cuda'], default='cpu')
    a = ap.parse_args()
    if min(a.train_count, a.val_count, a.max_len) <= 0:
        ap.error('Количество примеров и длина должны быть положительными')
    config_path = Path('params.yaml')
    params = yaml.safe_load(config_path.read_text())
    targets = [a.out / 'train.pt', a.out / 'val.pt', Path('params.fast.yaml'), Path('fast_data_manifest.json')]
    if any(p.exists() for p in targets):
        raise SystemExit('Файлы результата уже существуют. Используйте новую папку/копию проекта.')
    results, report = {}, {'seed': a.seed, 'max_len_filter': a.max_len, 'method': 'shuffle eligible complete HW4 tensors; no truncation', 'splits': {}}
    for name, count in [('train', a.train_count), ('val', a.val_count)]:
        source = a.source / f'{name}.pt'
        blob = torch.load(source, map_location='cpu', weights_only=True)
        if blob['model'] != params['model']['name']:
            raise ValueError('Модель HW4 не совпадает с HW5')
        results[name], stats = select(blob, count, a.max_len, a.seed)
        stats.update(source=str(source), source_sha256=sha(source))
        report['splits'][name] = stats
    # All inputs are validated before writing anything.
    a.out.mkdir(parents=True, exist_ok=True)
    for name, blob in results.items():
        target = a.out / f'{name}.pt'
        torch.save(blob, target)
        report['splits'][name]['output_sha256'] = sha(target)
        params['data'][name] = target.as_posix()
    params['model']['device'] = a.device
    params['model']['dtype'] = 'float32' if a.device == 'cpu' else 'bfloat16'
    params['train'].update(epochs=1, batch_size=1, grad_accum=8, eval_batch_size=1,
                           eval_every=10, gradient_checkpointing=True, max_steps=None)
    Path('params.fast.yaml').write_text(yaml.safe_dump(params, allow_unicode=True, sort_keys=False))
    report['original_config_sha256'] = sha(config_path)
    report['optimizer_steps_per_variant'] = math.ceil(len(results['train']['examples']) / 8)
    Path('fast_data_manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('Готово. params.yaml не изменён. Смотрите инструкцию перед обучением.')


if __name__ == '__main__':
    main()
