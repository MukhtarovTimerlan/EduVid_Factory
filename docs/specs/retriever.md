# Spec: Retriever (SearchTool)

## Модуль: `tools/search.py`

### Ответственность
Единственный инструмент агента. Принимает поисковый запрос от AgentCore, выполняет поиск через DuckDuckGo (бесплатно, без API-ключа), нормализует ответ в список текстовых сниппетов.

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

### Провайдер

| Провайдер | Библиотека | API-ключ |
|---|---|---|
| DuckDuckGo | `ddgs` (Python package) | Не нужен |

```python
from ddgs import DDGS

with DDGS() as ddgs:
    results = list(ddgs.text(query, max_results=n))
```

### Нормализация ответа

Из ответа DuckDuckGo извлекаются только:
```python
f"Title: {item['title']} | Snippet: {item['body']}"
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
| Ошибка сети / таймаут | Retry 3×, затем return `["search unavailable"]` |
| Rate limit DuckDuckGo | Retry с задержкой (1→2→4 с) |
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
