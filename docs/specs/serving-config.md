# Spec: Serving / Config

## Запуск

### CLI

```bash
python -m src [OPTIONS] TOPIC

Arguments:
  TOPIC            Тема обучающего видео (строка)

Options:
  --style TEXT     Подсказка по стилю (например: "для детей", "технически")
  --model TEXT     Модель LLM (переопределяет LLM_MODEL из env)
  --output DIR     Директория для сохранения MP4 (по умолчанию: output/)
  --dry-run        Только запустить агента, не генерировать аудио/видео
  --log-level      DEBUG | INFO | WARNING (по умолчанию: INFO)

Example:
  python -m src "Градиентный бустинг" --style "для начинающих"
```

### Выход

| Код | Значение |
|---|---|
| 0 | Видео создано успешно |
| 1 | Ошибка (LLM недоступен, неверная конфигурация, ошибка сборки) |
| 2 | Неверные аргументы CLI |

---

## Конфигурация

### Обязательные переменные окружения

```bash
ROUTERAI_BASE_URL=https://api.routerai.ru/v1
ROUTERAI_API_KEY=<api_key>
SEARCH_API_KEY=<serpapi_or_google_key>
ELEVENLABS_API_KEY=<key>
```

### Опциональные переменные

```bash
# LLM
LLM_MODEL=gpt-4o-mini              # модель по умолчанию
LLM_TEMPERATURE=0.3
LLM_MAX_TOKENS=1024
LLM_TIMEOUT=30

# Agent
AGENT_MAX_STEPS=3
AGENT_TOKEN_BUDGET=8000
AGENT_COST_LIMIT_USD=2.0

# Search
SEARCH_PROVIDER=serpapi             # serpapi | google_cse
SEARCH_ENGINE_ID=                   # только для google_cse
SEARCH_N_RESULTS=5
SEARCH_TIMEOUT=10

# ElevenLabs
ELEVENLABS_VOICE_A=<voice_id>
ELEVENLABS_VOICE_B=<voice_id>
ELEVENLABS_STABILITY=0.5
ELEVENLABS_SIMILARITY=0.75
ELEVENLABS_TIMEOUT=20

# Paths
ASSETS_DIR=assets
OUTPUT_DIR=output
TEMP_DIR=temp
LOG_DIR=logs

# Logging
LOG_LEVEL=INFO
LOG_MAX_BYTES=10485760              # 10 МБ
LOG_BACKUP_COUNT=5
```

### Файл `.env`

```bash
# Скопировать из .env.example и заполнить
cp .env.example .env
```

`.env` добавлен в `.gitignore`. Никогда не коммитить.

---

## Startup Validation

При каждом запуске `PipelineOrchestrator` проверяет до первого API-вызова:

```python
REQUIRED_ENV_VARS = [
    "ROUTERAI_BASE_URL", "ROUTERAI_API_KEY",
    "SEARCH_API_KEY",
    "ELEVENLABS_API_KEY",
]

REQUIRED_DIRS = ["assets/backgrounds", "assets/characters"]

def validate_on_startup():
    # 1. Проверить наличие всех обязательных env vars
    # 2. Проверить что assets/ содержит хотя бы один файл в каждой подпапке
    # 3. Проверить что output/ и logs/ доступны для записи
    # При любой ошибке: ConfigurationError с точным указанием что отсутствует
```

---

## Зависимости (Python)

```toml
[tool.poetry.dependencies]
python = "^3.11"
openai = "^1.0"          # routerai.ru совместим с openai SDK
requests = "^2.31"       # Search API calls
elevenlabs = "^1.0"      # TTS SDK
moviepy = "^1.0"         # Video composition
pydantic = "^2.0"        # Dialogue JSON validation
python-dotenv = "^1.0"   # .env loading
tiktoken = "^0.5"        # Token counting (для OpenAI-совместимых моделей)
```

---

## Версии моделей

Версия LLM-модели фиксируется через `LLM_MODEL` env var.  
При изменении модели (например, переход с `gpt-4o-mini` на другую через routerai.ru) необходимо:
1. Проверить совместимость формата ответа с `ResponseParser`
2. Скорректировать `AGENT_TOKEN_BUDGET` если у новой модели другой context window
3. Пересчитать cost estimates в `CostTracker` (стоимость токенов отличается)

Текущая стоимость токенов задаётся в `utils/cost_tracker.py` как константы:
```python
COST_PER_1K_INPUT = float(os.environ.get("LLM_COST_INPUT_PER_1K", "0.00015"))
COST_PER_1K_OUTPUT = float(os.environ.get("LLM_COST_OUTPUT_PER_1K", "0.0006"))
```
