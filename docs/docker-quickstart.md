# Запуск smeta-checker в Docker — инструкция для чайника

Эта инструкция поднимет **весь проект одной командой**: API, два интерфейса
(Nuxt), PostgreSQL, Redis и фоновых воркеров. Подходит для Windows,
macOS и Linux.

## Шаг 0. Что нужно установить

1. **Docker Desktop** — https://www.docker.com/products/docker-desktop/
   (на Linux — Docker Engine + Compose plugin).
2. **Git** — https://git-scm.com/downloads.

Больше ничего не нужно: Python, Node и PostgreSQL живут внутри контейнеров.

Проверьте, что Docker работает:

```powershell
docker --version
docker compose version
```

Обе команды должны напечатать версии без ошибок. Если Docker Desktop только
что установлен — запустите его и дождитесь статуса «Running».

## Шаг 1. Скачать проект

```powershell
git clone https://github.com/koden585/smeta-checker.git
cd smeta-checker
git checkout dev
```

## Шаг 2. Создать файл с секретами

```powershell
Copy-Item .env.example .env   # Windows PowerShell
# cp .env.example .env        # macOS / Linux
```

Откройте `.env` в блокноте и заполните **минимум два значения**:

| Переменная | Что вписать |
|---|---|
| `POSTGRES_PASSWORD` | Любой длинный пароль, например `smeta-2026-secret-pw` |
| `AUDIT_API_TOKEN` | Любой длинный случайный токен, например `smeta-api-token-2026-xyz` |

Без этих двух строк запуск остановится с понятной ошибкой — это защита,
а не баг.

> **Хотите настоящие проверки LLM?** Дополнительно заполните Yandex Cloud
> (`YANDEX_CLOUD_API_KEY`, `YANDEX_CLOUD_FOLDER`) или AnyModel
> (`ANYMODEL_API_KEY`, `ANYMODEL_MODEL`). Без них загрузка, история,
> просмотр и проверка оформления работают, а запуск аудита честно отвечает
> «модель не подключена».

## Шаг 3. Запустить всё одной командой

```powershell
docker compose up -d --build
```

Первый запуск занимает 5–15 минут: скачиваются образы Python/Node/PostgreSQL
и собираются два наших образа. Следующие запуски — секунды.

Проверьте статус:

```powershell
docker compose ps
```

Все сервисы должны быть `running` (у `migrate` — `exited (0)`, это нормально:
он один раз применил миграции и завершился).

## Шаг 4. Открыть в браузере

| Что | Адрес |
|---|---|
| **Nuxt-интерфейс (основной)** | http://127.0.0.1:3000 |
| API health | http://localhost:8000/healthz → `{"status":"ok"}` |

Откройте Nuxt, загрузите ВОР (XLSX/CSV) и PDF, нажмите «Проверить»,
откройте позицию и скачайте Word-отчёт.

## Шаг 5 (необязательно). Проверить, что всё работает

Живая проверка стека без расхода LLM-квоты:

```powershell
# Windows PowerShell:
Get-Content .env | Where-Object { $_ -match '^\w+=' } | ForEach-Object { $k,$v = $_ -split '=',2; Set-Item "env:$k" $v }
bash backend/scripts/verify.sh

# macOS / Linux:
set -a; . ./.env; set +a; ./backend/scripts/verify.sh
```

В конце должно быть `ALL VERIFY CHECKS PASSED`.

## Доступ из локальной сети (интранет)

По умолчанию Nuxt слушает только localhost сервера. Чтобы открыть его
с других машин компании:

1. В `.env` укажите адрес сервера и откройте порт наружу:

```env
NUXT_PUBLIC_HOST=192.168.1.10
WORKSPACE_BIND=0.0.0.0
```

2. Перезапустите: `docker compose up -d`.
3. Откройте `http://192.168.1.10:3000` с любой машины сети.

BFF принимает только точный Host — подмена адреса даст 403. Пароль в этом
режиме не требуется: доступ есть у всех, кто знает адрес в вашем сегменте.

## Доступ из интернета (мировая сеть)

1. В `.env` укажите домен, общий пароль и откройте порт:

```env
NUXT_PUBLIC_HOST=audit.example.com
WORKSPACE_PASSWORD=длинный-случайный-пароль
WORKSPACE_BIND=0.0.0.0
```

2. Перед контейнером поставьте reverse proxy с TLS (nginx/Caddy/Traefik),
   терминирующий HTTPS и проксирующий на `127.0.0.1:3000`.
3. Перезапустите: `docker compose up -d`.
4. Откройте `https://audit.example.com` — сначала экран входа с паролем.

Без TLS пароль и документы летят открытым текстом — так разворачивать
запрещено. Сессия живёт сутки, cookie HttpOnly + SameSite=strict.

## Частые действия

```powershell
docker compose logs -f api          # смотреть лог API (Ctrl+C — выйти)
docker compose logs -f workspace    # смотреть лог Nuxt
docker compose restart worker-llm   # мягкий рестарт воркера
docker compose down                 # остановить всё (данные сохранятся)
docker compose up -d                # запустить снова
```

## Если что-то пошло не так

| Симптом | Что делать |
|---|---|
| `Set POSTGRES_PASSWORD in .env` | Вы пропустили шаг 2: заполните `.env` |
| Порт занят (`port is already allocated`) | Закройте программу на порту 3000/8000, либо задайте `WORKSPACE_PORT`/`API_PORT` в `.env` |
| `workspace` отвечает 403 | Открывайте через адрес из `NUXT_PUBLIC_HOST` (или `http://127.0.0.1:3000`, если хост не задан). Подмена Host запрещена |
| Контейнер `unhealthy` дольше 2 минут | `docker compose logs <имя>` — там причина; чаще всего не дождались первой сборки |
| Всё сломалось и хотите с нуля | `docker compose down -v` (**сотрёт данные БД!**), затем шаг 3 |

## Как это устроено (кратко)

```text
Браузер → workspace (Nuxt, :3000) → api (FastAPI, :8000) → db (PostgreSQL)
                                                          → redis → worker-pdf / worker-llm
```

Данные живут в Docker volumes (`pgdata`, `blobs`, `pdfcache`, `redisdata`)
и переживают перезапуск. Бэкап: `./backend/scripts/backup.sh`.
