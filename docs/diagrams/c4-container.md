# C4 Level 2 — Container Diagram

Показывает внутренние контейнеры (исполняемые процессы / модули) и их взаимодействие.

```mermaid
graph TB
    user(["Контент-мейкер"])

    subgraph evf["EduVid Factory"]
        cli["__main__.py — CLI Entry Point\nПарсинг аргументов\nЗапуск PipelineOrchestrator"]
        orch["PipelineOrchestrator\nКоординирует цепочку\nагент → script → audio → video\nУправляет run_id, cleanup temp/"]
        agent["AgentCore + Memory\nReAct-цикл до 3 шагов\nPrompt Builder, Response Parser\nКонтроль токен-бюджета"]
        tools["SearchTool\nОбёртка над Search API\nНормализация, retry, таймаут 10 с"]
        validators["Validators + CostTracker\nВалидация JSON-схемы диалога\nHard stop при превышении 2 USD"]
        script["ScriptGenerator\nФинализация диалога\nПодготовка реплик для TTS"]
        audio["AudioGenerator\nTTS через ElevenLabs SDK\nКонкатенация MP3, retry 3x"]
        assets["AssetSelector\nСлучайный выбор фона\nи фото персонажей из assets/"]
        video["VideoComposer\nMoviePy: фон + фото + аудио\nЗапись MP4 в output/"]
        logger["Logger\nRotating log pipeline.log\nНет API ключей в логах"]
    end

    router["routerai.ru"]
    search_api["Search API"]
    tts_api["ElevenLabs"]
    fs["Local FS\nassets/ output/ temp/"]

    user -->|"CLI args"| cli
    cli -->|"run(topic, style_hint)"| orch
    orch -->|"run_react_loop(topic)"| agent
    agent -->|"search.query(q)"| tools
    agent -->|"validate / track_cost"| validators
    orch -->|"prepare(dialogue)"| script
    orch -->|"synthesize(lines)"| audio
    orch -->|"pick()"| assets
    orch -->|"assemble(audio, assets)"| video
    agent -->|"HTTPS LLM"| router
    tools -->|"HTTPS search"| search_api
    audio -->|"HTTPS TTS"| tts_api
    video -->|"write MP4"| fs
    assets -->|"read"| fs
    logger -->|"write logs"| fs
    orch -->|"log all events"| logger
    agent -->|"log thoughts/actions"| logger
    cli -->|"output path / error"| user

    classDef person fill:#08427b,color:#fff,stroke:#073b6f
    classDef container fill:#1168bd,color:#fff,stroke:#0e5fab
    classDef external fill:#6b6b6b,color:#fff,stroke:#555

    class user person
    class cli,orch,agent,tools,validators,script,audio,assets,video,logger container
    class router,search_api,tts_api,fs external
```

## Ключевые потоки данных между контейнерами

1. **CLI → Orchestrator → AgentCore**: передаётся `topic` (строка) и опциональный `style_hint`
2. **AgentCore → SearchTool**: поисковый запрос (строка), возврат — список сниппетов
3. **AgentCore → routerai.ru**: полный prompt (system + history), возврат — structured text с `action` или `finalize + dialogue_json`
4. **AgentCore → Validators**: JSON строка диалога, возврат — `DialogueModel` или `ValidationError`
5. **Orchestrator → AudioGenerator**: список реплик `[{speaker, text}]`, возврат — путь к объединённому MP3
6. **Orchestrator → VideoComposer**: пути к аудио, фону и фото, возврат — путь к MP4
