# C4 Level 3 — Component Diagram (AgentCore)

Показывает внутреннее устройство ядра системы — модуля `AgentCore`.  
Это наиболее сложный и критичный контейнер: всё взаимодействие с LLM происходит здесь.

```mermaid
graph TB
    orch(["PipelineOrchestrator"])
    logger_c(["Logger"])
    router(["routerai.ru LLM API"])
    search_tool(["SearchTool"])

    subgraph agent["AgentCore — agent/agent_core.py"]
        loop["ReActLoop\nГлавный управляющий цикл\nИтерирует шаги max=3\nОтслеживает счётчик и сигналы остановки"]
        pb["PromptBuilder\nСобирает prompt:\nsystem + topic + style_hint + history\nУсечение при превышении 8000 токенов"]
        llm["LLMClient\nВызов routerai.ru\nBase URL и API key из env\nRetry 3x backoff, таймаут 30 с"]
        rp["ResponseParser\nПарсит raw text LLM\nОпределяет action=search или finalize\nВыбрасывает ParseError"]
        mem["SessionMemory\nagent/memory.py\nadd_step(), get_history()\ntoken_count(), truncate()"]
        pt["PromptTemplates\nagent/prompt_templates.py\nSystem prompt агента\nАнти-injection инструкция"]
        ct["CostTracker\nutils/cost_tracker.py\nПодсчёт токенов и стоимости\nHard limit 2 USD, BudgetExceededError"]
        val["DialogueValidator\nutils/validators.py\nPydantic: min 2 реплики, max 20\nRetry 2x с примером схемы"]
    end

    orch -->|"run_react_loop(topic, style_hint)"| loop
    loop -->|"build_prompt(memory, step_n)"| pb
    pb -->|"get_system_prompt()"| pt
    pb -->|"get_history(), token_count()"| mem
    loop -->|"call(prompt)"| llm
    llm -->|"POST /chat/completions"| router
    llm -->|"track(tokens)"| ct
    ct -->|"BudgetExceededError"| loop
    loop -->|"parse(raw_response)"| rp
    rp -->|"StepResult(action, query/dialogue)"| loop
    loop -->|"query(q) при action=search"| search_tool
    loop -->|"add_step(thought/action/obs)"| mem
    loop -->|"validate(dialogue_json)"| val
    val -->|"ValidationError — retry"| loop
    loop -->|"DialogueModel"| orch
    loop -->|"log каждый шаг"| logger_c

    classDef external fill:#6b6b6b,color:#fff,stroke:#555
    classDef component fill:#1168bd,color:#fff,stroke:#0e5fab

    class orch,logger_c,router,search_tool external
    class loop,pb,llm,rp,mem,pt,ct,val component
```

## Критические пути в AgentCore

### Нормальный путь (1 итерация)
```
loop.step(1)
  → pb.build() [system + topic + empty history]
  → llm.call() → routerai.ru
  → rp.parse() → action=search, query="..."
  → search_tool.query()
  → mem.add_step(thought, action, observation)

loop.step(2)
  → pb.build() [system + topic + history(step1)]
  → llm.call() → routerai.ru
  → rp.parse() → action=finalize, dialogue_json={...}
  → val.validate() → OK
  → return DialogueModel
```

### Путь с ParseError
```
rp.parse() → ParseError
  → retry_count += 1
  → если retry_count ≤ 2:
      pb.add_correction_hint("Respond strictly in format: ...")
      → llm.call() снова
  → если retry_count > 2:
      force_finalize(mem.get_history())  ← генерирует диалог на базе имеющегося
```

### Путь с превышением бюджета
```
ct.track(tokens) → total_cost > $2.00
  → BudgetExceededError
  → loop.force_finalize() [без нового LLM-вызова на поиск]
  → val.validate() → ...
```

### Путь с исчерпанием итераций
```
loop.step(3) → action=search  ← агент всё ещё хочет искать
  → iteration_count = MAX (3)
  → force_finalize(mem.get_history())
  → val.validate() → ...
```
