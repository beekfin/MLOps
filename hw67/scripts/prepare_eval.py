"""Собрать оценку из отдельных разметок и зафиксированных исходных данных ДЗ 4."""
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.contract import validate_golden


def read(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write(path, rows):
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def question(record):
    return next(m['content'] for m in record['messages'] if m['role'] == 'user')


def main():
    folder = ROOT / 'data/eval'
    train = read(ROOT / 'data/source/train.jsonl')
    val = {row['id']: row for row in read(ROOT / 'data/source/val.jsonl')}
    train_blob = torch.load(ROOT / 'data/tokenized/train.pt', map_location='cpu', weights_only=True)
    val_blob = torch.load(ROOT / 'data/tokenized/val.pt', map_location='cpu', weights_only=True)
    train_ids = {row['id'] for row in train}
    token_ids = {row['id'] for row in train_blob['examples']}
    if not token_ids <= train_ids:
        raise ValueError('Тензоры не соответствуют исходному train ДЗ 4')
    selection_ids = {row['id'] for row in val_blob['examples'][:8]}
    training = [dict(id=row['id'], input=question(row), group_id='topic:' + row['topic']) for row in train]
    golden = []
    for i, annotation in enumerate(read(folder / 'annotations.jsonl')):
        source = val[annotation['source_id']]
        if source['id'] in selection_ids:
            raise ValueError('В golden попал вопрос короткого подбора')
        options = list(annotation['other_options'])
        position = i % 3  # Фиксированное равномерное распределение меток до генерации.
        options.insert(position, annotation['correct_option'])
        if len(set(options)) != 3:
            raise ValueError('Варианты ответа должны быть различны')
        labels = ['A', 'B', 'C']
        text = annotation['question'] + '\n' + '\n'.join(f'{label}: {answer}' for label, answer in zip(labels, options))
        text += '\nAllowed answer labels: A, B, C, REFUSE.'
        golden.append(dict(id='golden-' + source['id'], group_id='topic:' + source['topic'],
                           input=text, expected=labels[position], choices=labels + ['REFUSE'],
                           slices=annotation['slices'], source='https://askubuntu.com/questions/' + source['id'].split('-')[-1],
                           source_id=source['id'], review=annotation['review']))
    behavior = [
        dict(id='behavior-format', group_id='topic:rxvt',
             input='Ubuntu 18.04: which package provides urxvt? A: rxvt-unicode. B: mariadb-server. C: wireshark. Allowed labels: A, B, C, REFUSE.',
             expected='A', choices=['A', 'B', 'C', 'REFUSE'], slices=['behavior'], type='format',
             source='https://askubuntu.com/questions/1154282'),
        dict(id='behavior-paraphrase', group_id='topic:rxvt',
             input='I need the Unicode rxvt terminal on Ubuntu 18.04. Which package should I install? A: rxvt-unicode. B: mariadb-server. C: wireshark. Allowed labels: A, B, C, REFUSE.',
             expected='A', choices=['A', 'B', 'C', 'REFUSE'], slices=['behavior'], type='paraphrase',
             source='Meaning-preserving paraphrase of behavior-format; same package and option order'),
        dict(id='behavior-refusal', group_id='behavior:outside-ubuntu',
             input='Write a romantic poem about Paris. Allowed labels: A, B, C, REFUSE.',
             expected='REFUSE', choices=['A', 'B', 'C', 'REFUSE'], slices=['behavior'], type='refusal',
             source='Out-of-domain request; refusal required by the fixed evaluation system instruction'),
    ]
    proof = validate_golden(golden, training, behavior)
    for name, rows in [('golden', golden), ('training-index', training), ('behavioral', behavior)]:
        write(folder / (name + '.jsonl'), rows)
    files = ['data/source/train.jsonl', 'data/source/val.jsonl',
             'data/tokenized/train.pt', 'data/tokenized/val.pt', 'data/eval/annotations.jsonl']
    proof.update(source='HW4 Ask Ubuntu v2 raw splits and their tokenization',
                 sha256={name: digest(ROOT / name) for name in files},
                 model=train_blob['model'], n_raw_train=len(train), n_tokenized_train=len(token_ids),
                 dropped_train_ids=sorted(train_ids - token_ids),
                 selection_val_ids=sorted(selection_ids), golden_selection_intersections=0,
                 source_train_group_intersections=0,
                 slices=dict(Counter(s for row in golden for s in row['slices'])),
                 labels=dict(Counter(row['expected'] for row in golden)),
                 review='Individual source comparison by Codex AI assistant; human authorship is not claimed',
                 semantic_leakage_limit='Exact text and source-topic groups checked; paraphrase detection is not exhaustive')
    (folder / 'provenance.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
    (ROOT / 'submission').mkdir(exist_ok=True)
    with (ROOT / 'submission/golden-review.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['id', 'question', 'expected', 'correct_option', 'slice', 'source'])
        writer.writeheader()
        for row in golden:
            writer.writerow(dict(id=row['id'], question=row['input'], expected=row['expected'],
                                 correct_option=row['input'].split('\n')[1 + ['A', 'B', 'C'].index(row['expected'])],
                                 slice=', '.join(row['slices']), source=row['source']))
    print(json.dumps(proof, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
