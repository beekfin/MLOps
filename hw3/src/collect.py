"""Стадия collect: снимок Ask Ubuntu -> chat JSONL.

Из согласованного источника берутся вопросы по управлению пакетами и их
принятые ответы. HTML преобразуется в обычный текст, каждому примеру
назначается тематическая группа по тегам, а системная инструкция выбирается
детерминированно по id.
"""

import hashlib
import html
import json
import re
import time
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

from src.config import load_params, source_files


class TextExtractor(HTMLParser):
    """Преобразовать HTML сообщения Stack Exchange в читаемый текст."""

    BREAK_TAGS = {"p", "div", "br", "li", "pre", "blockquote", "h1", "h2", "h3", "h4"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        elif not self.hidden_depth and tag in self.BREAK_TAGS:
            self.parts.append("\n")
        if not self.hidden_depth and tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1
        elif not self.hidden_depth and tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def plain_text(value: str) -> str:
    parser = TextExtractor()
    parser.feed(value)
    text = html.unescape("".join(parser.parts)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def pick_prompt(example_id: str, variants: list[str]) -> str:
    digest = hashlib.sha1(example_id.encode("utf-8")).hexdigest()
    return variants[int(digest, 16) % len(variants)]


def rank(example_id: str) -> str:
    """Стабильный порядок выборки: v1 остаётся подмножеством v2."""
    return hashlib.sha1(example_id.encode("utf-8")).hexdigest()


def choose_topic(tags: list[str], frequencies: Counter[str]) -> str:
    """Выбрать наиболее конкретный тег, не создавая доминирующую группу."""
    return min(tags, key=lambda tag: (frequencies[tag], tag))


def read_source(paths: list[Path]) -> list[dict]:
    rows: dict[int, dict] = {}
    for path in paths:
        with path.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"{path}:{lineno}: битый JSON — {exc.msg}") from exc
                required = {
                    "question_id", "answer_id", "tags", "title_html",
                    "question_html", "answer_html", "source_url",
                }
                missing = required - row.keys()
                if missing:
                    raise SystemExit(f"{path}:{lineno}: нет полей {sorted(missing)}")
                rows[int(row["question_id"])] = row
    return list(rows.values())


def main() -> None:
    params = load_params()
    cfg = params["collect"]
    paths = params["paths"]
    version = cfg["version"]
    variants = cfg["system_prompts"]
    if not variants:
        raise SystemExit("collect.system_prompts пуст: инструкцию брать неоткуда")

    started = time.perf_counter()
    source_rows = read_source(source_files(params))
    limit = int(cfg["n_rows"][version])
    selected = sorted(
        source_rows,
        key=lambda row: rank(f"askubuntu-{row['question_id']}"),
    )[:limit]
    # Частоты считаются по фиксированному источнику, а не по срезу версии:
    # при расширении v1 -> v2 тема уже существующего примера не меняется.
    frequencies = Counter(tag for row in source_rows for tag in row["tags"])

    out = Path(paths["raw"])
    out.parent.mkdir(parents=True, exist_ok=True)
    prompts_used: set[str] = set()
    groups: Counter[str] = Counter()
    with out.open("w", encoding="utf-8") as fh:
        for row in selected:
            example_id = f"askubuntu-{row['question_id']}"
            prompt = pick_prompt(example_id, variants)
            topic = choose_topic(row["tags"], frequencies)
            user = f"{plain_text(row['title_html'])}\n\n{plain_text(row['question_html'])}"
            assistant = plain_text(row["answer_html"])
            prompts_used.add(prompt)
            groups[topic] += 1
            record = {
                "id": example_id,
                "topic": topic,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": assistant},
                ],
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    metrics = {
        "version": version,
        "source_files": len(source_files(params)),
        "source_rows": len(source_rows),
        "rows_written": len(selected),
        "groups": len(groups),
        "largest_group_share": round(max(groups.values()) / len(selected), 4),
        "system_prompt_variants": len(prompts_used),
        "seconds": round(time.perf_counter() - started, 2),
    }
    mpath = Path(paths["metrics_collect"])
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"collect: {version}, источник {len(source_rows)} строк -> {len(selected)}, "
        f"групп {len(groups)}, вариантов инструкции {len(prompts_used)}, "
        f"{metrics['seconds']} с -> {out}"
    )


if __name__ == "__main__":
    main()
