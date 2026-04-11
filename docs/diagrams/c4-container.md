# C4 Level 2 — Container Diagram

Показывает внутренние контейнеры (исполняемые процессы / модули) и их взаимодействие.

```mermaid
C4Container
  title EduVid Factory — Containers

  Person(user, "Контент-мейкер")

  System_Boundary(evf, "EduVid Factory") {

    Container(cli, "__main__.py\nCLI Entry Point", "Python", "Парсинг аргументов (topic, style_hint).\nЗапуск PipelineOrchestrator.\nВывод итога / ошибки пользователю.")

    Container(orch, "PipelineOrchestrator", "Python", "Координирует полную цепочку:\nагент → script → audio → video.\nУправляет run_id, cleanup temp/.")

    Container(agent, "AgentCore + Memory", "Python", "ReAct-цикл (≤3 шага).\nPrompt Builder, Response Parser.\nСессионная история шагов.\nКонтроль токен-бюджета.")

    Container(tools, "SearchTool", "Python / requests", "Обёртка над Search API.\nНормализует ответ в сниппеты.\nRetry-логика, таймаут 10 с.")

    Container(validators, "Validators + CostTracker", "Python", "Валидация JSON-схемы диалога.\nПодсчёт токенов и стоимости.\nGuardrail: hard stop при > $2.")

    Container(script, "ScriptGenerator", "Python", "Финализация диалога из агента.\nПодготовка реплик для TTS.")

    Container(audio, "AudioGenerator", "Python / ElevenLabs SDK", "TTS построчно через ElevenLabs.\nКонкатенация MP3.\nRetry 3× на реплику.")

    Container(assets, "AssetSelector", "Python", "Случайный выбор фона и\nфото персонажей из assets/.")

    Container(video, "VideoComposer", "Python / MoviePy", "Сборка MP4:\nфон + фото персонажей + аудио.\nЗапись в output/.")

    Container(logger, "Logger + Logs", "Python / файловая система", "Ротируемый лог pipeline.log.\nВсе шаги агента, ошибки, стоимость.\nNO API keys в логах.")
  }

  System_Ext(router, "routerai.ru")
  System_Ext(search_api, "Search API")
  System_Ext(tts_api, "ElevenLabs")
  System_Ext(fs, "Local FS (assets/, output/, temp/)")

  Rel(user, cli, "CLI args")
  Rel(cli, orch, "run(topic, style_hint)")
  Rel(orch, agent, "run_react_loop(topic)")
  Rel(agent, tools, "search.query(q)")
  Rel(agent, validators, "validate_json(dialogue)\ntrack_cost(tokens)")
  Rel(orch, script, "prepare(dialogue)")
  Rel(orch, audio, "synthesize(lines)")
  Rel(orch, assets, "pick()")
  Rel(orch, video, "assemble(audio, assets)")
  Rel(agent, router, "HTTPS LLM calls")
  Rel(tools, search_api, "HTTPS search")
  Rel(audio, tts_api, "HTTPS TTS")
  Rel(video, fs, "write MP4")
  Rel(assets, fs, "read backgrounds, photos")
  Rel(logger, fs, "write logs/pipeline.log")
  Rel(orch, logger, "log all events")
  Rel(agent, logger, "log thoughts/actions/observations")
  Rel(cli, user, "output path / error message")
```

## Ключевые потоки данных между контейнерами

1. **CLI → Orchestrator → AgentCore**: передаётся `topic` (строка) и опциональный `style_hint`
2. **AgentCore → SearchTool**: поисковый запрос (строка), возврат — список сниппетов
3. **AgentCore → routerai.ru**: полный prompt (system + history), возврат — structured text с `action` или `finalize + dialogue_json`
4. **AgentCore → Validators**: JSON строка диалога, возврат — `DialogueModel` или `ValidationError`
5. **Orchestrator → AudioGenerator**: список реплик `[{speaker, text}]`, возврат — путь к объединённому MP3
6. **Orchestrator → VideoComposer**: пути к аудио, фону и фото, возврат — путь к MP4
