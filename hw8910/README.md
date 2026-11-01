# ДЗ 8+9+10: выпуск принятой модели и локальный сервис

Проект продолжает ДЗ67 с вопросами Ask Ubuntu. Используется готовый адаптер
`my-qwen-adapter/1` из training run `0381294b884b46ea90076356c9e8db4f`.
Повторного обучения нет. Подробный результат — [REPORT.md](docs/REPORT.md), семь
причин ошибок — [defects.csv](docs/defects.csv), реальные журналы — `metrics/`.
Код — в `src/`, отчёт и разбор ошибок — в `docs/`, результаты — в `metrics/`.
Методичка и исходные инструкции — в `source/`; [условие задания](source/homework8-9-10.html).

Из этого каталога:

```bash
uv sync --frozen                         # быстрые проверки, без загрузки весов
make check                              # 13 исходных + 9 собственных + 24 из ДЗ67
make check-negative                     # намеренная поломка во временной копии
make prove                              # те же 9 собственных тестов: исходник/исправление
make experiments                        # Prefect: сбой, кеш, инвалидация; отказы и восстановление
.venv/bin/python scripts/demo_versions.py # STUB ONLY: A → B → A, реальные HTTP и перезапуски
```

Для `make prove` нужен Git-репозиторий с исходным коммитом `e4cf8ad`.
Быстрые тесты используют настоящие процессы и HTTP, но подставляют лёгкий
генератор `StubBackend`. Они не измеряют качество настоящей модели.

Настоящая модель запускается отдельно:

```bash
uv sync --frozen --extra model
# Если MLflow из ДЗ67 ещё не запущен:
(cd ../hw67 && make up)
make fetch-model
# Если базы нет в кеше Hugging Face, скачать её один раз:
.venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-0.6B', revision='c1899de289a04d12100db370d81485cdf75e47ca')"
make prepare-real
make release
make release                              # тот же выпуск: второго события нет
make serve                                # фоновая служба, предел памяти 3900 МиБ
curl -i http://127.0.0.1:8091/ready
.venv/bin/python scripts/probe_real.py
make benchmark                            # 8 одинаковых запросов при 1 и 2 клиентах
make stop
```

При загрузке `/health` возвращает 200, `/ready` — 503; после прогрева
`/ready` возвращает 200 с загруженной версией. Для генерации:

```bash
curl http://127.0.0.1:8091/generate \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Which Ubuntu package provides urxvt? A: rxvt-unicode. B: mariadb-server. C: urxvt-server-only.","max_new_tokens":32}'
```

Ответ содержит `answer`, `request_id`, фактически загруженный `model_id`,
`runtime_sha256`, `output_tokens`, время ожидания и генерации. Лимит ответа
фиксирован: 32 новых токена, как в ДЗ67. Вход — до 8192 символов и 2048
токенов с системной инструкцией; одна генерация одновременно.

Принятый workspace сохраняется целиком. Для другого кандидата используйте
отдельный `--workspace`: ошибочная подготовка не должна перезаписать
файлы уже принятой модели.

После получения и полной оценки другого кандидата пример команд:

```bash
.venv/bin/python -m src.model_release prepare --workspace .runtime/next
.venv/bin/python -m src.pipeline --workspace .runtime/next --manifest manifest-model.json --report release-report.json
# После остановки прежнего API запустить сервис с тем же --workspace .runtime/next.
```

После смены `accepted.json` нужен явный перезапуск:

```bash
systemctl --user restart mlops-hw8910-serving.service
curl -i http://127.0.0.1:8091/ready
```

Без systemd можно запустить `.venv/bin/python service.py --workspace .runtime/real
--backend transformers --port 8091 --warmup-seconds 1` в одном терминале.
При этом отдельного ограничения памяти нет. Для модели нужен запас около
4 ГиБ плюс память системы и остальных приложений. `make serve` проверяет,
что перед загрузкой доступно не менее 5 ГиБ RAM; при недостатке закройте
ненужные приложения и повторите запуск.

`src/pipeline.py` запускает локальный Prefect с четырьмя задачами. Результаты
подготовки сохраняются в workspace, состояния Prefect — в `.prefect/`.
Код сервиса и зависимостей закреплён Git/`uv.lock`; параметры модели берутся
из принятого manifest. Полное правило ДЗ67 вызывается по сохранённым
исходным ответам и отчётам. Автоматического обучения, обновления baseline
или смены реестрового `champion` здесь нет.

Для сдачи после выполнения опытов:

```bash
.venv/bin/python scripts/export_evidence.py
.venv/bin/python scripts/make_video.py    # uv sync --frozen --all-extras; нужен ffmpeg
.venv/bin/python scripts/package_submission.py
```

`submission/project.zip` содержит код и отчёты, `submission/evidence.zip` —
машинные результаты и полную исходную оценку. Видео —
`submission/hw8910_beekfin_4k_music.mp4`. Веса, окружения и кеши исключены.
Порядок отдельной передачи артефакта описан в `submission/ARTIFACTS.txt`.
На другом компьютере нужны базовая модель с точной ревизией и папка
адаптера; один manifest без файлов не позволяет запустить генерацию.

Удалённый GitHub Actions не запускался. `source/ci.example.yml` — выданный
преподавателем шаблон; выполненный `make check` является локальной проверкой.

Для запуска команд: `cd hw8910` из корня репозитория.
