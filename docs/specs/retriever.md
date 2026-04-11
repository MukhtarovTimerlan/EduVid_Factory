# Spec: Retriever (SearchTool)

## Модуль: `tools/search.py`

### Ответственность
Единственный инструмент агента. Принимает поисковый запрос от AgentCore, вызывает внешний Search API, нормализует ответ в список текстовых сниппетов.

### Интерфейс

```python
class SearchTool:
    def query(self, q: str, n: int = 5) -> list[str]:
        """
        Возвращает список из n сниппетов вида "Title: ... | Snippet: ...".
        При ошибке после 3 retry возвращает ["search unavailable"].
        Никогда не выбрасывает исключение — агент всегда получает observation.
        """
```

### Источники (в порядке приоритета)

| Провайдер | Endpoint | Параметры |
|---|---|---|
| SerpAPI | `https://serpapi.com/search` | `engine=google`, `num=n`, `api_key` |
| Google Custom Search | `https://www.googleapis.com/customsearch/v1` | `cx=SEARCH_ENGINE_ID`, `num=n`, `key` |

Выбор провайдера через `SEARCH_PROVIDER` env var (`serpapi` / `google_cse`).

### Нормализация ответа

Из ответа API извлекаются только:
```python
f"Title: {item['title']} | Snippet: {item['snippet']}"
```
URL, ссылки, HTML — **отбрасываются**. Это снижает объём контекста и убирает потенциальные injection-векторы через URL-подобные конструкции.

### Лимиты и защиты

```python
MAX_QUERY_LEN = 100        # символов — обрезается если длиннее
MAX_SNIPPETS = 5           # количество результатов
MAX_SNIPPET_LEN = 500      # символов на один сниппет
TIMEOUT = 10               # секунд
RETRY_COUNT = 3
RETRY_BACKOFF = (1, 2, 4)  # секунды
```

### Sanitization запроса

Перед отправкой в API:
- Trim whitespace
- Удалить управляющие символы (`\n`, `\r`, `\t`)
- Обрезать до `MAX_QUERY_LEN`
- **Не экранировать** и не изменять семантику — это задача Search API

### Failure Modes

| Ситуация | Поведение |
|---|---|
| HTTP 4xx (неверный ключ) | Raise `SearchConfigError` (не retry — ошибка конфигурации) |
| HTTP 429 | Retry после `Retry-After` или 30 с |
| HTTP 5xx / Timeout | Retry 3×, затем return `["search unavailable"]` |
| Пустой список результатов | Return `["no results found for this query"]` |
| Результаты нерелевантны | Агент решает сам на следующем шаге рассуждения |

### Ограничения PoC

- Только веб-поиск, нет индексирования локальных документов
- Нет reranking — порядок результатов определяет Search API
- Нет кэширования запросов между запусками
- Нет дедупликации сниппетов из разных источников

### Логирование

```
INFO  search query: "{q}" (step={n})
INFO  search results: {count} snippets, {total_chars} chars
WARN  search retry {attempt}/3: {error}
ERROR search unavailable after 3 retries
```
API-ключ **никогда** не попадает в лог.
