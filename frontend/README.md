# КДФП · Nuxt workspace для smeta-checker

Nuxt 4 / Vue 3 / TypeScript / Nuxt UI. Этот интерфейс работает с `backend/api.py` в этом же репозитории: `/api/v1`, постоянные проекты/версии/audit runs, Celery либо существующий fallback.

## Запуск

Единственный поддерживаемый запуск — Docker Compose из корня проекта
(см. [инструкцию для чайника](../docs/docker-quickstart.md)):

```powershell
Copy-Item .env.example .env   # заполнить POSTGRES_PASSWORD, AUDIT_API_TOKEN
docker compose up -d --build
```

Интерфейс: **http://127.0.0.1:3000**, API: **http://localhost:8000**.
Нативный запуск без Docker не поддерживается.

Development frontend: задайте серверные `NUXT_BACKEND_URL` и `NUXT_BACKEND_TOKEN`,
затем `pnpm --dir frontend dev`. Токен нельзя переносить в `runtimeConfig.public`,
браузерное хранилище или `NUXT_PUBLIC_*`.

## Пользовательский цикл

1. На странице загрузки сохраните XLSX/CSV и PDF в выбранном проекте. Повторная загрузка тех же байтов использует существующую версию.
2. Выберите одну версию каждого документа, проверьте привязки. При проблемах приложение требует явного решения выполнить только доступные проверки.
3. Каждая выбранная ВОР создаёт свой аудит. Страница показывает стадию и число завершённых позиций; её можно закрыть и открыть через историю.
4. После завершения доступны очереди, поиск/пагинация, Excel/Word и окно сверки. Результат привязан к `run_id`, а не к текущему состоянию проекта.
5. В окне сверки — точный лист/ячейки ВОР, PDF, физическая/печатная страницы, цитаты, дерево разделов и поиск. Переход на другую страницу не подтверждает позицию. Выделение появляется только при однозначной локализации цитаты в текстовом слое.

Проверка оформления вызывается отдельно для выбранного листа XLSX, без LLM. CSV не выдаётся за редактируемую книгу Excel. ONLYOFFICE, сохранение редакторских ревизий и PDF-заметки в этой версии интеграции ещё не подключены.

## Контракты и проверки

```powershell
cd backend; python -m scripts.export_frontend_openapi; cd ..
pnpm --dir frontend run api:generate
pnpm --dir frontend run api:check
pnpm --dir frontend run fmt:check
pnpm --dir frontend run lint
pnpm --dir frontend run typecheck
pnpm --dir frontend run test:unit
pnpm --dir frontend run build
```

Источник схем — реальные Pydantic DTO в `backend/workspace_models.py`, `backend/audit_models.py` и `backend/api.py`. Сгенерированный SDK/TS/Zod находится в `app/generated/`; вручную его не редактируют. Экспорт OpenAPI не открывает БД и не запускает OCR/LLM.

Для E2E используется отдельная PostgreSQL `smeta_test_ui`, `backend/tests/workspace_server.py`, синтетические файлы и явно подменный тестовый LLM-клиент. Это испытание интеграции, не живой прогон модели. Начальный запуск требует пустую БД и новый `--root`; `--resume` использует уже созданный тестовый комплект без удаления данных. Обычный production entry point тестовый клиент не подключает.

После запуска fixture API на 8116 и built Nuxt на 3016 задайте `FRONTEND_URL=http://127.0.0.1:3016` и `E2E_FIXTURE_ROOT=<полный путь fixture>`, затем `pnpm --dir frontend run test:e2e`. GitHub Actions содержит эти шаги с отдельной тестовой БД.

## Как устроен запуск в Compose

Nuxt входит в общий `compose.yaml` как сервис `workspace`. Порт публикуется только
на host loopback (`127.0.0.1:3000`), внутри контейнера BFF доверяет Docker-шлюзу
(`NUXT_TRUST_PROXY=1`), сохраняя Host allowlist, same-origin и сессию.
`AUDIT_API_TOKEN` берётся из серверного `.env`.

BFF рассчитан на локальную работу и не является публичным многопользовательским входом.
