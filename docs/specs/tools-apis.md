# Spec: Tools / API Integrations

## 1. LLMClient — routerai.ru (`agent/llm_client.py`)

### Контракт

```python
class LLMClient:
    def call(self, messages: list[dict], model: str, max_tokens: int = 1024) -> LLMResponse:
        """
        messages: [{"role": "system"|"user"|"assistant", "content": str}]
        Возвращает LLMResponse(content: str, prompt_tokens: int, completion_tokens: int)
        Raises: LLMUnavailableError после исчерпания retry
        """
```

### Конфигурация

```python
# Конфигурируется через env vars
base_url = os.environ["ROUTERAI_BASE_URL"]  # например: https://api.routerai.ru/v1
api_key  = os.environ["ROUTERAI_API_KEY"]
model    = os.environ.get("LLM_MODEL", "gpt-4o-mini")  # дефолтная модель

# Инициализация через openai SDK
client = openai.OpenAI(base_url=base_url, api_key=api_key)
```

### Параметры вызова

```python
response = client.chat.completions.create(
    model=model,
    messages=messages,
    max_tokens=1024,
    temperature=0.3,     # низкая температура для структурированных ответов
    timeout=30,
)
```

**Почему `temperature=0.3`:** агент должен следовать формату ответа строго; высокая температура увеличивает вероятность `ParseError`.

### Retry-логика

```
Attempt 1 → wait 1s → Attempt 2 → wait 2s → Attempt 3 → wait 4s → LLMUnavailableError
```

Retry применяется при: Timeout, HTTP 5xx, `openai.APIConnectionError`.  
**Не применяется** при: HTTP 4xx (ошибка конфигурации/аутентификации).

### Side Effects

- Каждый вызов тратит токены и деньги → `CostTracker.track()` вызывается **сразу после** каждого успешного response
- Вызовы логируются: `model`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `latency_ms`

### Защита от утечки данных

- API-ключ берётся только из `os.environ`, никогда не передаётся аргументом функции
- Ключ не включается в логи даже при ошибках авторизации

---

## 2. TTS (`generation/audio_generator.py`)

### Контракт

```python
class AudioGenerator:
    def synthesize(self, lines: list[DialogueLine], output_dir: Path) -> Path:
        """
        Для каждой реплики создаёт WAV (Silero) или MP3 (edge-tts).
        Конкатенирует в один файл audio.mp3.
        Возвращает путь к итоговому audio.mp3.
        При ошибке отдельной реплики — пропускает с WARN.
        """
```

### Стратегия (primary → fallback)

**Primary: Silero TTS** — локальная модель через `torch.hub`, не требует API-ключа.
```python
# Загружается один раз при первом вызове (~50 МБ)
model, _ = torch.hub.load("snakers4/silero-models", "silero_tts",
                           language="ru", speaker="v4_ru")

VOICE_A = os.environ.get("TTS_VOICE_A", "xenia")   # clear, energetic female
VOICE_B = os.environ.get("TTS_VOICE_B", "baya")    # warmer, softer female
# Другие варианты: kseniya, aidar (мужской), eugene (мужской)
```

**Fallback: edge-tts** — используется если `torch` не установлен.
```python
EDGE_VOICE = os.environ.get("EDGE_TTS_VOICE", "ru-RU-SvetlanaNeural")
# Дифференциация голосов через просодию:
PROSODY = {"A": {"rate": "+0%",  "pitch": "+0Hz"},
           "B": {"rate": "-15%", "pitch": "+12Hz"}}
```

### Failure Modes

| Ситуация | Действие |
|---|---|
| torch не установлен | Автоматический fallback на edge-tts |
| Silero: ошибка модели | Fallback на edge-tts, все последующие реплики тоже через edge-tts |
| edge-tts: пустой файл | `AudioError` |
| Все реплики пропущены | `AudioError` — невозможно создать видео без звука |
| Любая ошибка реплики | Retry 3×, затем пропустить с WARN |

### Side Effects

- Временные файлы: `temp/<run_id>/line_NNN.wav` (Silero) или `line_NNN.mp3` (edge-tts)
- Финальный файл: `temp/<run_id>/audio.mp3`
- Все temp-файлы удаляются `PipelineOrchestrator` после сборки видео

---

## 3. Search API (`tools/search.py`)

Подробная спецификация: [retriever.md](retriever.md)

Ключевые контрактные параметры для интеграции:

```python
# Side effects: нет (read-only запрос)
# Исключения: SearchConfigError (неверный ключ) — не перехватывается в AgentCore
# Все остальные ошибки: обрабатываются внутри SearchTool, агент получает fallback observation
```

---

## 4. Общие принципы для всех API-интеграций

### Конфигурация через env vars

```bash
# Обязательные
ROUTERAI_BASE_URL=https://routerai.ru/api/v1
ROUTERAI_API_KEY=...
LLM_MODEL=openai/gpt-5.4-mini

# TTS — Silero (без ключа, нужен torch)
TTS_VOICE_A=xenia
TTS_VOICE_B=baya
# TTS — edge-tts fallback (без ключа)
EDGE_TTS_VOICE=ru-RU-SvetlanaNeural

# Search — DuckDuckGo (без ключа)
SEARCH_N_RESULTS=5
```

### Startup validation

При запуске `PipelineOrchestrator` проверяет наличие обязательных env vars.  
Если отсутствует хотя бы одна — `ConfigurationError` до первого API-вызова.

### Таймауты (итог)

| Компонент | Connect timeout | Read timeout |
|---|---|---|
| routerai.ru | 5 с | 30 с |
| DuckDuckGo search | 5 с | 10 с |
| Silero TTS | — (локально) | — |
| edge-tts | — (HTTPS к MS Edge) | 30 с |
