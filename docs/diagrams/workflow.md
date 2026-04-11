# Workflow Diagram — Пошаговое выполнение запроса

Включает все ветки: нормальный путь, ошибки, retry, force-finalize.

```mermaid
flowchart TD
    START([Пользователь: topic + style_hint]) --> CLI

    CLI[CLI: парсинг аргументов\nсоздание run_id] --> CHECK_ASSETS

    CHECK_ASSETS{assets/ не пусты?}
    CHECK_ASSETS -- Нет --> ABORT_ASSETS([ABORT: нет фоновых видео\nили фото персонажей])
    CHECK_ASSETS -- Да --> ORCH

    ORCH[PipelineOrchestrator.run\nинициализация Memory, CostTracker, Logger] --> REACT_START

    subgraph REACT["ReAct Loop (max 3 шага)"]
        REACT_START([Шаг N]) --> BUILD_PROMPT
        BUILD_PROMPT[PromptBuilder:\nsystem + topic + history] --> CHECK_BUDGET

        CHECK_BUDGET{Токены > 8000?}
        CHECK_BUDGET -- Да --> TRUNCATE[memory.truncate:\nудалить старые action+obs пары]
        TRUNCATE --> CHECK_BUDGET
        CHECK_BUDGET -- Нет --> CHECK_COST

        CHECK_COST{Стоимость > $2?}
        CHECK_COST -- Да --> FORCE_FINALIZE
        CHECK_COST -- Нет --> LLM_CALL

        LLM_CALL[LLMClient.call\nrouterai.ru\ntimeout=30с] --> LLM_OK

        LLM_OK{Ответ получен?}
        LLM_OK -- Нет / 5xx --> LLM_RETRY{retry_count ≤ 3?}
        LLM_RETRY -- Да --> LLM_CALL
        LLM_RETRY -- Нет --> ABORT_LLM([ABORT: LLM недоступен])

        LLM_OK -- Да --> TRACK_COST
        TRACK_COST[CostTracker:\nучёт токенов + стоимости] --> PARSE

        PARSE[ResponseParser:\nопределить action] --> PARSE_OK

        PARSE_OK{Формат корректен?}
        PARSE_OK -- Нет --> PARSE_RETRY{parse_retry ≤ 2?}
        PARSE_RETRY -- Да --> BUILD_CORRECTION[добавить correction_hint в prompt] --> LLM_CALL
        PARSE_RETRY -- Нет --> FORCE_FINALIZE

        PARSE_OK -- action=search --> SEARCH
        PARSE_OK -- action=finalize --> VALIDATE_JSON

        SEARCH[SearchTool.query\ntimeout=10с] --> SEARCH_OK
        SEARCH_OK{Поиск успешен?}
        SEARCH_OK -- Нет --> SEARCH_RETRY{retry ≤ 3?}
        SEARCH_RETRY -- Да --> SEARCH
        SEARCH_RETRY -- Нет --> OBS_EMPTY[observation: "search unavailable"]
        OBS_EMPTY --> MEM_ADD

        SEARCH_OK -- Да --> MEM_ADD
        MEM_ADD[memory.add_step\nthought + action + observation] --> CHECK_ITER

        CHECK_ITER{N < 3?}
        CHECK_ITER -- Да --> REACT_START
        CHECK_ITER -- Нет --> FORCE_FINALIZE[Force Finalize:\nLLM генерирует диалог\nна основе имеющейся истории]

        FORCE_FINALIZE --> VALIDATE_JSON

        VALIDATE_JSON[DialogueValidator:\nпроверка JSON-схемы\n≥2 реплик, поля speaker+text] --> VAL_OK

        VAL_OK{Схема валидна?}
        VAL_OK -- Нет --> VAL_RETRY{val_retry ≤ 2?}
        VAL_RETRY -- Да --> BUILD_CORRECTION2[добавить пример схемы в prompt] --> LLM_CALL
        VAL_RETRY -- Нет --> FALLBACK_DIALOGUE[Fallback Dialogue:\nшаблонный диалог с topic]
        FALLBACK_DIALOGUE --> DIALOGUE_READY

        VAL_OK -- Да --> DIALOGUE_READY([DialogueModel готов])
    end

    DIALOGUE_READY --> SCRIPT[ScriptGenerator:\nподготовка реплик для TTS]

    SCRIPT --> TTS_LOOP

    subgraph TTS["TTS Pipeline (ElevenLabs)"]
        TTS_LOOP[Для каждой реплики] --> TTS_CALL[ElevenLabs.synthesize\ntimeout=20с]
        TTS_CALL --> TTS_OK{Успех?}
        TTS_OK -- Нет --> TTS_RETRY{retry ≤ 3?}
        TTS_RETRY -- Да --> TTS_CALL
        TTS_RETRY -- Нет --> TTS_SKIP[Пропустить реплику\nWARN в логе]
        TTS_OK -- Да --> TTS_SAVE[сохранить temp/<run_id>/line_N.mp3]
        TTS_SKIP --> TTS_NEXT
        TTS_SAVE --> TTS_NEXT{ещё реплики?}
        TTS_NEXT -- Да --> TTS_LOOP
        TTS_NEXT -- Нет --> CONCAT[ffmpeg/moviepy:\nконкатенация MP3]
    end

    CONCAT --> ASSETS[AssetSelector:\nслучайный фон + фото персонажей]
    ASSETS --> COMPOSE[VideoComposer:\nMoviePy: фон + фото + аудио → MP4]
    COMPOSE --> CLEANUP[Cleanup: удалить temp/<run_id>/]
    CLEANUP --> OUTPUT([output/video_<run_id>.mp4\nВывод пути пользователю])
```

## Ветки завершения

| Ветка | Условие | Результат |
|---|---|---|
| **Успех** | Все шаги выполнены | MP4 в output/ |
| **ABORT: assets** | Пустая папка assets/ | Ошибка до старта pipeline |
| **ABORT: LLM** | LLM недоступен после 3 retry | Нет видео, exit code 1 |
| **Force Finalize** | Исчерпаны итерации или бюджет | Диалог из имеющегося контекста |
| **Fallback Dialogue** | JSON невалиден после 2 retry | Шаблонный диалог |
| **TTS Skip** | ElevenLabs не отвечает | Реплика пропускается, видео создаётся |
