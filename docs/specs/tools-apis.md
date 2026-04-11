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

## 2. ElevenLabs TTS (`generation/audio_generator.py`)

### Контракт

```python
class AudioGenerator:
    def synthesize(self, lines: list[DialogueLine], output_dir: Path) -> Path:
        """
        Для каждой реплики создаёт MP3.
        Конкатенирует в один файл.
        Возвращает путь к итоговому audio.mp3.
        При ошибке отдельной реплики — пропускает с WARN.
        """
```

### Параметры ElevenLabs

```python
VOICE_A = os.environ.get("ELEVENLABS_VOICE_A", "default_voice_id")
VOICE_B = os.environ.get("ELEVENLABS_VOICE_B", "default_voice_b_id")
STABILITY = 0.5
SIMILARITY_BOOST = 0.75
TIMEOUT = 20  # секунд на реплику
```

### Маппинг speaker → voice

```python
VOICE_MAP = {"A": VOICE_A, "B": VOICE_B}
```

### Failure Modes

| Ситуация | Действие |
|---|---|
| HTTP 5xx / Timeout | Retry 3×, затем пропустить реплику (WARN) |
| Пустой MP3 (0 байт) | Повтор 1 раз, при повторной неудаче — пропустить |
| Все реплики пропущены | `AudioError` — невозможно создать видео без звука |
| HTTP 401 | `AudioConfigError` — ошибка ключа, без retry |

### Side Effects

- Временные файлы: `temp/<run_id>/line_N.mp3`
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
ROUTERAI_BASE_URL=https://api.routerai.ru/v1
ROUTERAI_API_KEY=...
LLM_MODEL=gpt-4o-mini

SEARCH_PROVIDER=serpapi           # или google_cse
SEARCH_API_KEY=...
SEARCH_ENGINE_ID=...              # только для google_cse

ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_A=...
ELEVENLABS_VOICE_B=...
```

### Startup validation

При запуске `PipelineOrchestrator` проверяет наличие всех обязательных env vars.  
Если отсутствует хотя бы одна — `ConfigurationError` до первого API-вызова.

### Таймауты (итог)

| API | Connect timeout | Read timeout |
|---|---|---|
| routerai.ru | 5 с | 30 с |
| Search API | 5 с | 10 с |
| ElevenLabs | 5 с | 20 с |
