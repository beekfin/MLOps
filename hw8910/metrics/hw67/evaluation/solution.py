"""Подсчёт качества ответов и проверка допуска по EVALUATION.md."""

import json
import math


def _by_id(records, name):
    """Построить словарь по id; пропуски и повторы — ошибка входных данных."""
    if not isinstance(records, list):
        raise ValueError(f'{name}: нужен список записей')
    result = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError(f'{name}: запись должна быть словарём')
        item_id = record.get('id')
        if not isinstance(item_id, str) or not item_id.strip() or item_id in result:
            raise ValueError(f'{name}: пустой или повторяющийся id')
        result[item_id] = record
    return result


def _summary(items):
    """Считать доли от всех вопросов, включая неправильные ответы и ошибки."""
    n = len(items)
    correct = sum(item['correct'] for item in items)
    valid = sum(item['valid'] for item in items)
    return dict(n=n, correct=correct, valid=valid,
                errors=sum(item['error'] is not None for item in items),
                accuracy=correct / n if n else 0.0,
                format_rate=valid / n if n else 0.0)


def _slice_summaries(items):
    groups = {}
    for item in items:
        for name in item['slices']:
            groups.setdefault(name, []).append(item)
    return {name: _summary(group) for name, group in sorted(groups.items())}


def score(rows, outputs):
    """Верните overall, slices и per_item. Не удаляйте плохие ответы из знаменателя.

    Строгий ответ: JSON с единственным строковым полем answer из choices.
    outputs: [{id, raw, error, latency_seconds}, ...].
    В overall и каждом срезе: n, correct, valid, errors, accuracy, format_rate.
    В per_item: id, raw, parsed, valid, correct, error, slices.
    Несовпадающие/дублирующиеся id и пустой набор должны вызвать ValueError.
    """
    questions = _by_id(rows, 'Вопросы')
    answers = _by_id(outputs, 'Ответы')
    if not questions or questions.keys() != answers.keys():
        raise ValueError('Нужен непустой набор с одинаковыми id вопросов и ответов')

    def unique_object(pairs):
        # Обычный json.loads молча заменяет повторное поле последним значением.
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Повторяющееся поле JSON')
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(f'{value} не является допустимым числом JSON')

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('Число JSON выходит за допустимый диапазон')
        return number

    per_item = []
    for item_id, row in questions.items():
        choices, slices = row.get('choices'), row.get('slices')
        if (not isinstance(choices, list) or not choices
                or any(not isinstance(label, str) for label in choices)
                or not isinstance(row.get('expected'), str)
                or row['expected'] not in choices):
            raise ValueError(f'{item_id}: некорректные choices или expected')
        if (not isinstance(slices, list) or not slices
                or any(not isinstance(name, str) or not name for name in slices)):
            raise ValueError(f'{item_id}: нужны именованные срезы')

        output = answers[item_id]
        raw, error = output.get('raw', ''), output.get('error')
        if error is not None and not isinstance(error, str):
            raise ValueError(f'{item_id}: error должен быть строкой или None')
        parsed, valid = None, False
        if error is None and isinstance(raw, str):
            try:
                parsed = json.loads(raw, object_pairs_hook=unique_object,
                                    parse_constant=reject_constant, parse_float=finite_float)
            except (ValueError, RecursionError):
                pass  # Плохой ответ остаётся в per_item и в знаменателе.
            else:
                valid = (isinstance(parsed, dict) and set(parsed) == {'answer'}
                         and isinstance(parsed['answer'], str)
                         and parsed['answer'] in choices)

        per_item.append(dict(id=item_id, raw=raw, parsed=parsed, valid=valid,
                             correct=valid and parsed['answer'] == row['expected'],
                             error=error, slices=list(dict.fromkeys(slices))))

    return dict(overall=_summary(per_item), slices=_slice_summaries(per_item),
                per_item=per_item)


def _validate_result(result, name, minimum):
    """Проверить полноту отчёта и пересчитать его числа из per_item."""
    if not isinstance(result, dict):
        raise ValueError(f'{name}: нет отчёта')
    items = result.get('per_item')
    indexed = _by_id(items, name)
    if len(indexed) < minimum:
        raise ValueError(f'{name}: нужно минимум {minimum} примеров')
    for item in items:
        if not {'id', 'raw', 'parsed', 'valid', 'correct', 'error', 'slices'} <= item.keys():
            raise ValueError(f'{name}: неполная запись per_item')
        if type(item['valid']) is not bool or type(item['correct']) is not bool:
            raise ValueError(f'{name}: valid и correct должны быть логическими значениями')
        if item['correct'] and not item['valid']:
            raise ValueError(f'{name}: правильный ответ должен иметь валидный формат')
        if item['error'] is not None:
            raise ValueError(f'{name}: ошибка генерации на {item["id"]}')
        parsed = item['parsed']
        if item['valid'] and (not isinstance(parsed, dict) or set(parsed) != {'answer'}
                              or not isinstance(parsed['answer'], str)):
            raise ValueError(f'{name}: valid не соответствует разобранному ответу')
        slices = item['slices']
        if (not isinstance(slices, list) or not slices
                or any(not isinstance(s, str) or not s for s in slices)
                or len(slices) != len(set(slices))):
            raise ValueError(f'{name}: некорректные срезы у {item["id"]}')

    def check_counts(actual, expected):
        if not isinstance(actual, dict):
            raise ValueError(f'{name}: отсутствуют метрики')
        for key in ('n', 'correct', 'valid', 'errors'):
            if type(actual.get(key)) is not int or actual[key] != expected[key]:
                raise ValueError(f'{name}: {key} не соответствует per_item')
        for key in ('accuracy', 'format_rate'):
            value = actual.get(key)
            if (type(value) not in (int, float) or not 0 <= value <= 1
                    or not math.isfinite(value)
                    or not math.isclose(value, expected[key], rel_tol=0, abs_tol=1e-12)):
                raise ValueError(f'{name}: некорректное значение {key}')

    check_counts(result.get('overall'), _summary(items))
    slices = result.get('slices')
    expected = _slice_summaries(items)
    if not isinstance(slices, dict) or slices.keys() != expected.keys():
        raise ValueError(f'{name}: список срезов не соответствует per_item')
    for key in expected:
        check_counts(slices[key], expected[key])
    return indexed


def quality_gate(baseline, candidate, critical_slices):
    """Верните {passed: True, ...} или вызовите ValueError с причиной отказа.

    Проверьте совместимость протокола/набора/baseline, метрики и counts,
    все id и срезы, общую accuracy/format_rate, критические срезы и behavior.
    Missing, NaN, пустой набор и ошибки генерации означают отказ.
    Пороги задаются до измерения; учебный допуск регрессии равен нулю.
    """
    if (not isinstance(critical_slices, list) or not critical_slices
            or any(not isinstance(s, str) or not s for s in critical_slices)):
        raise ValueError('Нужно заранее указать критические срезы')

    indexes, behavior_indexes = [], []
    for name, report in [('Baseline', baseline), ('Кандидат', candidate)]:
        if not isinstance(report, dict) or report.get('status') != 'complete':
            raise ValueError(f'{name}: оценка не завершена')
        if not isinstance(report.get('model'), dict) or not report['model']:
            raise ValueError(f'{name}: не указана модель')
        for key in ('protocol_sha256', 'golden_sha256', 'baseline_spec_sha256'):
            if not isinstance(report.get(key), str) or not report[key]:
                raise ValueError(f'{name}: отсутствует {key}')
        indexes.append(_validate_result(report, name, minimum=50))
        if len(report['slices']) < 3:
            raise ValueError(f'{name}: нужно минимум три среза')
        behavior_indexes.append(_validate_result(report.get('behavioral'),
                                                f'{name}, проверки поведения', minimum=3))

    for key in ('protocol_sha256', 'golden_sha256', 'baseline_spec_sha256'):
        if baseline[key] != candidate[key]:
            raise ValueError(f'Отчёты несовместимы: различается {key}')
    for left, right in (indexes, behavior_indexes):
        if left.keys() != right.keys():
            raise ValueError('В отчётах разные id заданий')
        if any(set(left[i]['slices']) != set(right[i]['slices']) for i in left):
            raise ValueError('Состав срезов различается между отчётами')

    for key in ('accuracy', 'format_rate'):
        if candidate['overall'][key] < baseline['overall'][key]:
            raise ValueError(f'Кандидат ухудшил общую метрику {key}')
    for name in critical_slices:
        if name not in baseline['slices'] or name not in candidate['slices']:
            raise ValueError(f'Нет критического среза {name}')
        if candidate['slices'][name]['accuracy'] < baseline['slices'][name]['accuracy']:
            raise ValueError(f'Кандидат ухудшил критический срез {name}')
    behavior = candidate['behavioral']['overall']
    if behavior['correct'] != behavior['n']:
        raise ValueError('Кандидат не прошёл все обязательные проверки поведения')

    return {'passed': True}
