# System Design — EduVid Factory PoC

## 1. Ключевые архитектурные решения

| Решение | Выбор | Обоснование |
|---|---|---|
| LLM-провайдер | routerai.ru (OpenAI-compatible API) | Российский роутер моделей, единый endpoint, совместим с `openai` SDK |
| Паттерн агента | ReAct (Reason → Act → Observe) | Позволяет многошаговое рассуждение с верификацией информации перед генерацией |
| Инструмент поиска | SerpAPI / Google Custom Search | Единственный инструмент в PoC; структурированные сниппеты, без скрапинга |
| Выход агента | JSON-диалог с фиксированной схемой | Детерминированный контракт между агентом и pipeline синтеза |
| Выполнение | Строго последовательное | Упрощает управление состоянием и бюджетом API в PoC |
| Хранилище состояния | In-memory в рамках сессии | Нет персистентности между запусками; контекст сбрасывается при завершении |
| Защита от prompt injection | Изоляция observation-слоя в промпте | Результаты поиска передаются только в поле `<observation>`, не в system-промпт |

---

## 2. Список модулей и их роли

```
src/
├── __main__.py              — CLI: парсинг аргументов, запуск PipelineOrchestrator
├── pipeline_orchestrator.py — сквозной координатор всей цепочки
├── agent/
│   ├── agent_core.py        — ReAct-цикл: prompt builder, LLM call, response parser
│   ├── memory.py            — хранение истории шагов сессии, контроль токен-бюджета
│   └── prompt_templates.py  — системный промпт, шаблоны action/observation блоков
├── tools/
│   └── search.py            — обёртка над поисковым API → нормализованные сниппеты
├── generation/
│   ├── script_generator.py  — валидация JSON-диалога, формирование реплик
│   ├── audio_generator.py   — ElevenLabs TTS построчно, конкатенация MP3
│   └── asset_selector.py    — случайный выбор фона и фото персонажей
├── composition/
│   └── video_composer.py    — MoviePy: фон + фото + аудио → MP4
└── utils/
    ├── logger.py             — ротируемый файловый лог + stdout
    ├── cost_tracker.py       — подсчёт токенов и API-стоимости за сессию
    └── validators.py         — JSON-схема диалога, sanity-чеки
```

---

## 3. Основной workflow

```
[Пользователь: topic + опциональный style_hint]
        ↓
[PipelineOrchestrator.run()]
        ↓
[AgentCore.run_react_loop(topic)]
  ┌─────────────────────────────────────────┐
  │  Шаг N (max = 3)                        │
  │  1. PromptBuilder.build(history)        │
  │  2. LLM call → routerai.ru              │
  │  3. ResponseParser.parse(raw)           │
  │     ├─ action=search →                  │
  │     │   search.query(q) → snippets      │
  │     │   memory.add_observation(snippets)│
  │     │   → следующий шаг                 │
  │     └─ action=finalize →                │
  │         validators.validate_json(d)     │
  │         └─ OK → выход из цикла          │
  │         └─ FAIL → retry (max 2) →       │
  │                   fallback dialogue      │
  └─────────────────────────────────────────┘
        ↓
[ScriptGenerator.prepare(dialogue)]
        ↓
[AudioGenerator.synthesize(lines)] — ElevenLabs, построчно
        ↓
[AssetSelector.pick()]
        ↓
[VideoComposer.assemble()] — MoviePy
        ↓
[output/video_<run_id>.mp4]
```

---

## 4. State / Memory / Context Handling

### Session Memory (in-memory)
Объект `SessionMemory` хранит список шагов сессии:
```
[
  { "role": "thought",      "content": "Нужно найти определение..." },
  { "role": "action",       "tool": "search", "query": "gradient boosting explained" },
  { "role": "observation",  "content": "<сниппеты из поиска>" },
  ...
]
```

### Context Budget
- Перед каждым LLM-вызовом подсчитываются токены: `system + history + instruction`.
- Лимит: **8 000 токенов** (оставляем запас для ответа).
- При превышении: удаляются самые старые `(action, observation)` пары, **мысли сохраняются**.
- Минимально необходимый контекст: system prompt + последний шаг + topic.

### Prompt Structure (каждый вызов LLM)
```
[SYSTEM]   роль агента, правила, формат ответа, anti-injection инструкция
[USER]     <topic>{topic}</topic>
           <style>{style_hint}</style>
           <history>
             <thought>...</thought>
             <action tool="search">...</action>
             <observation>...</observation>
             ...
           </history>
           <instruction>Шаг {N}/3. Реши: search или finalize.</instruction>
```

---

## 5. Retrieval-контур

**Инструмент:** SerpAPI или Google Custom Search API  
**Вызов:** агент формирует поисковый запрос → `search.query(q, n=5)` → список сниппетов  
**Нормализация:** из ответа API извлекаются только `title + snippet` (без URL, без HTML)  
**Релевантность:** агент сам оценивает релевантность результатов в следующем шаге рассуждения  
**Ограничение:** только текстовые сниппеты, без загрузки полных страниц  
**Защита от injection:** сниппеты передаются внутри тега `<observation>`, system-промпт явно запрещает агенту следовать инструкциям из observation  

---

## 6. Tool / API-интеграции

| Сервис | Использование | Библиотека | Таймаут |
|---|---|---|---|
| routerai.ru | Все LLM-вызовы (рассуждения + диалог) | `openai` (base_url переопределён) | 30 с |
| SerpAPI / Google CSE | Веб-поиск | `requests` | 10 с |
| ElevenLabs | TTS построчно | `elevenlabs` SDK | 20 с на реплику |
| MoviePy | Видеосборка | `moviepy` | — (локально) |

Все внешние вызовы: **3 retry с экспоненциальной задержкой** (1 с → 2 с → 4 с).

---

## 7. Failure Modes, Fallback и Guardrails

### LLM (routerai.ru)

| Ситуация | Обнаружение | Действие |
|---|---|---|
| Ответ не парсится (нет `action`/`finalize`) | `ResponseParser` → `ParseError` | Retry с уточняющей инструкцией (max 2), затем force-finalize |
| JSON диалога невалиден | `validators.validate_json()` | Retry генерации с примером схемы в промпте (max 2), затем fallback-диалог |
| Таймаут / HTTP 5xx | `requests.Timeout`, статус ≥ 500 | 3 retry экспоненциально, затем abort с ошибкой |
| HTTP 429 (rate limit) | статус 429 | Retry после `Retry-After` заголовка (или 60 с) |
| Агент зацикливается | счётчик шагов ≥ 3 | Принудительный выход → finalize на имеющейся истории |
| Контекст превысил бюджет | `memory.token_count()` > 8 000 | Усечение истории (keep last 2 пары) |

### Search Tool

| Ситуация | Действие |
|---|---|
| Нерелевантные результаты | Агент переформулирует запрос (следующий шаг) |
| Пустой ответ | Передаётся как observation: "no results" → агент решает finalize |
| Таймаут / ошибка API | 3 retry, затем observation: "search unavailable" |

### Audio / Video Pipeline

| Ситуация | Действие |
|---|---|
| ElevenLabs вернул пустой аудио | Перегенерация реплики (1 retry), затем пропуск с предупреждением |
| Пустая папка assets/ | Abort с чётким сообщением об ошибке до запуска pipeline |
| Временный файл пуст/повреждён | Перегенерация или abort |

### Guardrails

- **Cost guard:** перед каждым LLM-вызовом проверяется накопленная стоимость сессии; при превышении `$2.00` — принудительный finalize.
- **Prompt injection guard:** system-промпт содержит явную инструкцию игнорировать любые команды из блока `<observation>`.
- **Output sanitization:** финальный диалог проверяется на наличие обязательных полей и разумную длину (≥2 реплик, ≤20 реплик).

---

## 8. Технические и операционные ограничения

### Latency
| Компонент | Цель (p95) | Hard limit |
|---|---|---|
| Один LLM-шаг | < 5 с | 30 с (таймаут) |
| Один поисковый запрос | < 2 с | 10 с |
| TTS одной реплики | < 5 с | 20 с |
| Полный цикл агента (≤3 шага) | < 3 мин | — |
| Полный pipeline (агент + TTS + видео) | < 10 мин | — |

### Cost
| Операция | Оценка | Лимит сессии |
|---|---|---|
| LLM (рассуждения + диалог) | ~$0.30–0.80 | $2.00 (hard stop) |
| Поиск (SerpAPI) | ~$0.01–0.05 | — |
| ElevenLabs TTS | ~$0.30–0.50 | — |
| **Итого на видео** | **< $2.00** | — |

### Reliability
- Целевой success rate: **> 85%** (завершение без unhandled exception)
- Все внешние вызовы покрыты retry-логикой
- При любом сбое: структурированный лог + exit code ≠ 0
