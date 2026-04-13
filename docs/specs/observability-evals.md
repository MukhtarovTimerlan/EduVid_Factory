# Spec: Observability / Evals

## Логирование

### Конфигурация

```python
# utils/logger.py
import logging
from logging.handlers import RotatingFileHandler

def setup_logger(name: str) -> logging.Logger:
    handler = RotatingFileHandler(
        "logs/pipeline.log",
        maxBytes=10 * 1024 * 1024,  # 10 МБ
        backupCount=5,
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    ))
    ...
```

### Структура событий

Каждый run идентифицируется `run_id` (UUID). Все события содержат его.

#### Pipeline-уровень

```
INFO  [run_id] Pipeline started | topic="{topic}" style="{style}"
INFO  [run_id] Pipeline finished | output={path} elapsed={s}s total_cost=${n}
ERROR [run_id] Pipeline failed at stage={stage} | error={msg}
```

#### Agent-уровень

```
INFO  [run_id] Agent step {n}/{max} started
INFO  [run_id] Prompt built | tokens={n} (history={h}, system={s})
INFO  [run_id] LLM call | model={model} temp={t}
INFO  [run_id] LLM response | action={search|finalize} prompt_tokens={n} completion_tokens={n} cost=${n} latency={ms}ms
WARN  [run_id] LLM retry {attempt}/3 | error={msg}
ERROR [run_id] LLM unavailable after 3 retries
INFO  [run_id] Agent thought: "{thought_text}"
INFO  [run_id] Agent action=search | query="{q}"
INFO  [run_id] Search results | count={n} total_chars={c}
WARN  [run_id] Search retry {attempt}/3
WARN  [run_id] Search unavailable, using fallback observation
INFO  [run_id] Agent action=finalize | dialogue_lines={n}
WARN  [run_id] ParseError retry {attempt}/2 | error={msg}
WARN  [run_id] ValidationError retry {attempt}/2 | error={msg}
WARN  [run_id] Force finalize triggered | reason={iteration_limit|budget_exceeded|parse_failed}
WARN  [run_id] Using fallback dialogue | reason=validation_failed_after_retry
INFO  [run_id] Memory truncated | removed_pairs={n} remaining_tokens={n}
INFO  [run_id] Cost guard check | session_cost=${n} limit=${limit}
WARN  [run_id] Cost guard triggered | cost=${n} > limit=${limit}
```

#### TTS / Video уровень

```
INFO  [run_id] TTS started | lines={n}
INFO  [run_id] TTS line {n}/{total} | speaker={s} chars={c}
WARN  [run_id] TTS line {n} skipped after retry | error={msg}
ERROR [run_id] TTS all lines failed — abort
INFO  [run_id] Video composition started
INFO  [run_id] Video composition done | size={bytes} duration={s}s
```

### Что НЕ логируется (явная политика)

```python
# utils/logger.py — sanitize_for_log()
SENSITIVE_KEYS = ["api_key", "authorization", "x-api-key", "bearer"]

def sanitize_for_log(data: dict) -> dict:
    """Заменяет значения sensitive keys на '***'"""
```

- API-ключи (ROUTERAI_API_KEY)
- HTTP Authorization заголовки
- Полный system prompt (только тип события)
- Персональные данные (не используются в PoC)

---

## Метрики (собираются в лог, агрегируются вручную в PoC)

| Метрика | Тип | Целевое значение |
|---|---|---|
| `pipeline.duration_seconds` | Histogram | p95 < 600 с |
| `agent.steps_count` | Counter | Среднее ~1.5 |
| `agent.llm_latency_ms` | Histogram | p95 < 5 000 мс |
| `agent.llm_tokens_total` | Counter | — |
| `agent.session_cost_usd` | Gauge | < $2.00 |
| `search.latency_ms` | Histogram | p95 < 2 000 мс |
| `search.retry_count` | Counter | — |
| `tts.lines_skipped` | Counter | Должно быть 0 |
| `pipeline.success_rate` | Rate | > 85% |
| `agent.force_finalize_count` | Counter | Должно быть минимальным |
| `agent.fallback_dialogue_count` | Counter | Должно быть 0 |

---

## Evals (качество диалога)

### Автоматические проверки (встроены в pipeline)

```python
# utils/validators.py — DialogueValidator

class DialogueValidator:
    def validate(self, raw_json: str) -> DialogueModel:
        # Структурные проверки (Pydantic):
        # - Поля: lines[].speaker, lines[].text
        # - Количество реплик: 2 ≤ n ≤ 20
        # - Непустые строки
        # - speaker ∈ {"A", "B"}

    def sanity_check(self, dialogue: DialogueModel, topic: str) -> list[str]:
        # Мягкие проверки (warnings, не abort):
        # - Хотя бы одно упоминание topic в тексте (fuzzy)
        # - Нет явных артефактов: "ACTION:", "QUERY:", "```"
        # - Средняя длина реплики в пределах [50, 300] символов
        # Возвращает список предупреждений для лога
```

### Ручная экспертная оценка (постфактум)

По шкале 1–5 на выборке видео:

| Критерий | Описание |
|---|---|
| Точность | Факты соответствуют поисковым результатам |
| Доступность | Объяснение понятно целевой аудитории |
| Структура | Логичная последовательность реплик |
| Полнота | Тема раскрыта достаточно для 1-минутного видео |
| Естественность | Диалог звучит живо, не шаблонно |

Целевой балл: ≥ 4.0 по каждому критерию.

### LLM-as-Judge (реализован: `utils/fact_checker.py`)

После генерации диалога `FactChecker` отправляет его на проверку фактов отдельным LLM-вызовом:
```
Проверь диалог по теме "{topic}" на фактические ошибки.
Если ошибок нет — ответь "OK". Если есть — перечисли, каждая строка "ERROR: ...".
```
Результат: предупреждения в лог. Никогда не прерывает pipeline.

---

## Трейсинг (PoC — через лог, продакшен — OpenTelemetry)

В PoC каждый `run_id` позволяет grep-нуть все события одного запуска:

```bash
grep "run_id=abc123" logs/pipeline.log
```

Структура событий позволяет восстановить полный trace:
```
Pipeline started → Agent step 1 → LLM call → Search → Agent step 2 → LLM call →
Finalize → Validate → TTS → Video → Pipeline finished
```
