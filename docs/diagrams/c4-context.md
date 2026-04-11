# C4 Level 1 — Context Diagram

Показывает систему целиком, её пользователей и внешние зависимости.

```mermaid
C4Context
  title EduVid Factory — System Context

  Person(user, "Контент-мейкер", "Задаёт тему через CLI;\nполучает готовый MP4")

  System(evf, "EduVid Factory", "Агентная система создания\nобразовательных видео.\nReAct-цикл: поиск → рассуждение\n→ генерация диалога → TTS → видео")

  System_Ext(router, "routerai.ru", "LLM API Gateway.\nOpenAI-compatible.\nМаршрутизирует вызовы\nк языковым моделям")

  System_Ext(search, "Search API\n(SerpAPI / Google CSE)", "Веб-поиск.\nВозвращает текстовые сниппеты\nпо запросу агента")

  System_Ext(tts, "ElevenLabs", "Text-to-Speech API.\nСинтез реплик диалога\nв MP3-аудио")

  System_Ext(fs, "Local File System", "Хранение assets (фоны, фото),\nвременных файлов и\nфинального MP4")

  Rel(user, evf, "CLI: topic, style_hint")
  Rel(evf, router, "HTTPS / OpenAI API\n(рассуждения + диалог)")
  Rel(evf, search, "HTTPS / REST\n(поисковые запросы)")
  Rel(evf, tts, "HTTPS / SDK\n(TTS построчно)")
  Rel(evf, fs, "Read assets\nWrite output & logs")
  Rel(evf, user, "output/video_<id>.mp4")
```

## Границы системы

| Внутри границы | Вне границы |
|---|---|
| ReAct-агент, pipeline синтеза, логика сборки видео | Языковые модели (routerai.ru) |
| Валидация диалога, управление состоянием | Поисковый индекс (Search API) |
| Логирование и cost-трекинг | Синтез речи (ElevenLabs) |
| | Публикация в соцсети (вне scope PoC) |
