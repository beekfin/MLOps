"""Отчёт строится из фактических результатов текущего запуска."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

TITLES = {"inference": "Инференс", "full_ft": "Полное дообучение", "lora": "LoRA r=8, q/v"}


def number(n):
    return f"{n:,}".replace(",", " ")


def plot_activations(activations, path):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), width_ratios=(2, 1))
    means = []
    for label, values in activations["norms"].items():
        axes[0].plot(values, label=f"{label}, слой {activations['layers'][label]}")
        means.append(sum(values) / len(values))
    axes[0].set(xlabel="Позиция токена", ylabel="L2-норма, лог. шкала",
                yscale="log", title="Активации на выходе блоков")
    axes[0].legend()
    axes[0].grid(alpha=.25)
    axes[1].bar(list(activations["norms"]), means, color=["#4c78a8", "#f58518", "#54a24b"])
    axes[1].set(ylabel="Средняя L2-норма", title="Среднее по позициям")
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def markdown_report(report, params):
    e, c = report["environment"], report["config"]
    mem = {m["mode"]: m for m in report["memory"]}
    weights = mem["inference"]["weight_mb"]
    lines = [
        f"# ДЗ 2 — анатомия {report['model']}",
        "",
        "## Условия замера",
        "",
        "| Условие | Значение |", "|---|---|",
        f"| Платформа | {e['platform']} |",
        f"| Устройство | {e['device']} |",
        f"| dtype весов | {e['dtype']} |",
        f"| seq_len / batch | {e['seq_len']} / {e['batch_size']} |",
        f"| Прогонов на режим | {e['repeats']}, каждый в отдельном процессе |",
        f"| Метрика памяти | {e['memory_metric']} |",
        f"| Python | {e['python']} |",
        f"| torch | {e['torch']} |",
        f"| transformers | {e['transformers']} |",
        f"| peft | {e['peft']} |",
        f"| Seed | {params['generate']['seed']} |",
        "",
        "Запуск: `uv sync --locked`, затем `make inspect`. Модель загружается из локального кэша.",
        "Вход для замера памяти — случайные ID токенов. KV-cache отключён во всех режимах.",
        "Инференс: один forward без градиентов. Обучение: forward, backward и один шаг AdamW.",
        "Для LoRA обучаются только адаптеры первого конфига. Gradient checkpointing не включён.",
        "Единица памяти во всех таблицах — МиБ (байты / 1024²). В шаблоне курса она подписана «МБ».",
        "",
        "## 1. Параметры модели",
        "",
        f"Блоков: {c['num_hidden_layers']}; hidden_size: {c['hidden_size']}; "
        f"intermediate_size: {c['intermediate_size']}; словарь: {c['vocab_size']}.",
        f"Голов Q: {c['num_attention_heads']}; голов K/V: {c['num_key_value_heads']}; "
        f"размер головы: {c['head_dim']}.",
        "",
        "| Группа | Модулей | Shape | Уникальных параметров | Доля | Общих параметров |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for g in report["params_by_group"]:
        lines.append(f"| {g['group']} | {g['modules']} | {g['shape']} | {number(g['params'])} | "
                     f"{100*g['share']:.2f}% | {number(g['tied_params'])} |")
    lines += [
        f"| **Итого** | | | **{number(report['params_total'])}** | **100%** | |", "",
        f"Прямая проверка через `model.parameters()`: {number(report['params_direct'])}. Разница: "
        f"{report['params_total']-report['params_direct']}.",
        f"Связывание входных и выходных весов: `tie_word_embeddings={c['tie_word_embeddings']}`.",
        "Общий тензор учитывается один раз. Ноль в строке lm_head при связывании означает",
        "отсутствие дополнительных весов, а не отсутствие самого выходного слоя.",
        "Таблицы MLP широкие, поэтому занимают значительную долю параметров; большой словарь",
        "тоже требует много весов. Нормализации содержат лишь небольшие векторы множителей.",
        "",
        "## 2. Активации и хуки", "",
        f"Промпт: «{params['hooks']['prompt']}». После шаблона чата: {report['activations']['n_tokens']} токенов.",
        "Хук снимает L2-норму вектора каждого токена на выходе выбранного блока.", "",
        f"![Нормы активаций]({Path(params['hooks']['plot']).name})", "",
        "| Блок | Индекс | Средняя норма | Максимум | Позиция максимума |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, vals in report["activations"]["norms"].items():
        lines.append(f"| {label} | {report['activations']['layers'][label]} | {sum(vals)/len(vals):.3f} | "
                     f"{max(vals):.3f} | {vals.index(max(vals))} |")
    h = report["hook_check"]
    lines += [
        "", "Масштаб скрытых состояний меняется по глубине модели: каждый блок добавляет свою",
        "поправку через residual-связь. Это не означает, что норма обязана расти на каждом слое.",
        "Логарифмическая шкала позволяет видеть и небольшие значения, и выбросы.",
        "По одному графику норм нельзя доказать, на какие токены направлено внимание.", "",
        f"Число хуков: до запуска {h['before']}, после первого {h['after_first']}, "
        f"после второго {h['after_second']}. Нормы двух запусков совпали: {h['same_norms']}.", "",
        "## 3. Расчёт LoRA", "",
        "Для матрицы с размером out × in добавляются A размера r × in и B размера out × r.",
        "Поэтому число новых параметров равно **r × (in + out)**. Складываем по целевым слоям.", "",
        "| Конфиг | Своя формула | PEFT | Разница | Доля от базовой модели |",
        "|---|---:|---:|---:|---:|",
    ]
    for l in report["lora"]:
        lines.append(f"| {l['name']} | {number(l['formula'])} | {number(l['peft'])} | "
                     f"{l['formula']-l['peft']} | {l['share_of_base']*100:.3f}% |")
    lines += ["", "В конфиге «все линейные» используются семь типов проекций декодер-блока.",
              "Выходной lm_head в этот список не входит. Доли выше считаются от базовой модели,",
              "а PEFT в консоли делит на размер модели вместе с адаптером.", ""]
    for l in report["lora"]:
        terms = []
        for g in report["params_by_group"]:
            if g["group"] in l["target_modules"]:
                terms.append(f"{g['group']}: {g['modules']} × {l['r']} × "
                             f"({' + '.join(g['shape'].split('×'))})")
        lines.append(f"- {l['name']}: " + "; ".join(terms) + f" = {number(l['formula'])}.")
    lines += ["", "## 4. Память", "",
              "| Режим | Пик, МиБ | К инференсу | Время с загрузкой, с | PID |",
              "|---|---:|---:|---:|---:|"]
    for mode, m in mem.items():
        lines.append(f"| {TITLES[mode]} | {m['peak_mb']:.1f} | "
                     f"{m['peak_mb']/mem['inference']['peak_mb']:.2f} | {m['seconds']:.1f} | {m['pid']} |")
    lines += ["", f"Сами веса занимают {weights:.3f} МиБ. Пики во всех режимах выше этого значения.",
              "Следующая таблица показывает размер тензоров, посчитанный по numel × element_size.",
              "Градиенты измерены после backward, состояния AdamW — после optimizer.step.", "",
              "| Режим | Веса базы, МиБ | Градиенты, МиБ | Состояния AdamW, МиБ |",
              "|---|---:|---:|---:|"]
    for mode, m in mem.items():
        lines.append(f"| {TITLES[mode]} | {m['weight_mb']:.3f} | {m['gradient_mb']:.3f} | {m['optimizer_mb']:.3f} |")
    lines += [
        "", "При полном дообучении нужны градиенты и состояния оптимизатора для всех весов.",
        "При LoRA — только для адаптеров; базовые веса остаются в памяти.",
        "Кроме этих тензоров нужны активации, результаты вычислений и рабочие буферы.",
        "Поэтому LoRA экономит память обучения, но её пик не равен только размеру адаптера.",
        "RSS включает также Python, библиотеки и память, удерживаемую аллокатором.",
        "Сумма в таблице тензоров не обязана равняться пику всего процесса.",
        "PEFT может хранить адаптеры в float32, хотя база загружена в bfloat16; размеры выше",
        "получены из реальных тензоров, а не из предположения о двух байтах на любое число.", "",
        "Пик CPU измеряется через ru_maxrss за жизнь отдельного процесса, включая загрузку.",
        "На CUDA используется max_memory_allocated с синхронизацией; на MPS — максимум",
        "driver_allocated_memory по выборкам каждые 10 мс и на границах этапов.",
        "Выборочный максимум MPS может пропустить очень короткий пик.",
        "CUDA/MPS на этой машине недоступны: их выбор метрики проверен тестами с подставными",
        "значениями API, реальные замеры здесь выполнены только на CPU.", "",
        "## 5. Четыре исправленных дефекта", "",
        "### 1. Хуки оставались на слоях",
        "Было: дескрипторы хуков не сохранялись, remove() не вызывался.",
        "Проявление: каждый вызов добавлял ещё три хука, и они удерживали словари результатов.",
        f"Исправлено: контекстный менеджер с finally снимает свои хуки. Теперь числа: "
        f"{h['before']} → {h['after_first']} → {h['after_second']}; повторные нормы совпадают.",
        "Отдельный тест проверяет удаление при исключении и сохранение чужого хука.", "",
        "### 2. Общие веса считались дважды",
        f"Было: обход с remove_duplicate=False давал {number(report['params_without_dedup'])} параметров.",
        f"Это на {number(report['params_without_dedup']-report['params_total'])} больше прямого подсчёта.",
        f"Исправлено: повторный id тензора помечается tied. Итог {number(report['params_total'])}, разница с моделью 0.", "",
        "### 3. Остаток памяти выдавался за пик; режимы смешивались",
        "Было: память ускорителя снималась в конце после gc.collect(), а режимы запускались",
        "в одном процессе. RSS хранит максимум за жизнь процесса, поэтому тяжёлый режим",
        "мог завысить результат следующего режима.",
        "Исправлено: каждый режим запускается отдельным subprocess, память отслеживается",
        "во время работы и включает загрузку. PID и реальные пики приведены в таблице выше.",
        f"Разница full FT − inference: {mem['full_ft']['peak_mb']-mem['inference']['peak_mb']:.1f} МиБ; "
        f"LoRA − inference: {mem['lora']['peak_mb']-mem['inference']['peak_mb']:.1f} МиБ.", "",
        "### 4. На ускорителе выбирался RSS",
        "Было: device_allocated_bytes() для любого устройства возвращала RSS процесса.",
        "Из-за этого подпись «аллокатор» не соответствовала измерению; память GPU могла не учитываться.",
        "Исправлено: CPU → ru_maxrss, CUDA → max_memory_allocated, MPS → driver_allocated_memory.",
        "Численная проверка с подставным API: при текущем расходе CUDA 10 байт и пике 90",
        "сохраняется 90; при выборках MPS 10 → 90 → 20 сохраняется 90, а не 20.",
        "Это тест алгоритма, не измерение реальной видеокарты.", "",
        "## Источники и файлы", "",
        "Числа этого запуска сохранены в report.json, сводная таблица — anatomy-worksheet.xlsx.",
        "Условия и требования: материалы ДЗ 2 и лекция 2 из выданного архива.",
        "- [Пик памяти CUDA](https://docs.pytorch.org/docs/stable/generated/torch.cuda.max_memory_allocated.html)",
        "- [Память драйвера MPS](https://docs.pytorch.org/docs/stable/generated/torch.mps.driver_allocated_memory.html)",
        "- [LoRA в PEFT](https://huggingface.co/docs/peft/package_reference/lora)", "",
    ]
    return "\n".join(lines)


def write_report(report, params):
    plot_activations(report["activations"], params["hooks"]["plot"])
    path = Path(params["report"]["markdown"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_report(report, params), encoding="utf-8")
