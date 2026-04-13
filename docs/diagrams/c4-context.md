# C4 Level 1 — Context Diagram

Показывает систему целиком, её пользователей и внешние зависимости.

```mermaid
graph TB
    user(["Контент-мейкер\nЗадаёт тему через CLI\nПолучает готовый MP4"])

    subgraph evf["EduVid Factory"]
        core["Агентная система создания\nобразовательных видео\nReAct-цикл: поиск → рассуждение\n→ генерация диалога → TTS → видео"]
    end

    router["routerai.ru\nLLM API Gateway\nOpenAI-compatible\nМаршрутизирует к языковым моделям"]
    search["DuckDuckGo\nddgs (без API-ключа)\nВеб-поиск, текстовые сниппеты"]
    tts["Silero TTS / edge-tts\nЛокальный TTS (torch.hub)\nFallback: Microsoft Edge TTS"]
    fs["Local File System\nХранение assets, temp, output"]

    user -->|"CLI: topic, style_hint"| core
    core -->|"HTTPS / OpenAI API"| router
    core -->|"ddgs (HTTPS)"| search
    core -->|"локально / HTTPS fallback"| tts
    core -->|"Read assets / Write output"| fs
    core -->|"output/video_id.mp4"| user

    classDef person fill:#08427b,color:#fff,stroke:#073b6f
    classDef system fill:#1168bd,color:#fff,stroke:#0e5fab
    classDef external fill:#6b6b6b,color:#fff,stroke:#555

    class user person
    class core system
    class router,search,tts,fs external
```

## Границы системы

| Внутри границы | Вне границы |
|---|---|
| ReAct-агент, pipeline синтеза, логика сборки видео | Языковые модели (routerai.ru) |
| Валидация диалога, управление состоянием | Поисковый индекс (DuckDuckGo) |
| Логирование и cost-трекинг | Синтез речи (Silero / edge-tts) |
| | Публикация в соцсети (вне scope PoC) |
