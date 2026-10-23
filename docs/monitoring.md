# Мониторинг smeta-checker через Grafana

Опциональный стек: Grafana + Prometheus + Loki + exporters. Основной
`compose.yaml` его не поднимает, чтобы не нагружать CPU-only сервер.

## Запуск

```bash
docker compose -f compose.yaml -f compose.monitoring.yaml up -d
```

Grafana: `http://127.0.0.1:3001` (логин/пароль из `.env`: `GRAFANA_ADMIN_USER` /
`GRAFANA_ADMIN_PASSWORD`, по умолчанию `admin` / `admin`).

Остановить только мониторинг:

```bash
docker compose -f compose.yaml -f compose.monitoring.yaml stop grafana prometheus loki promtail
```

## Что отслеживать

### Инфраструктура
- CPU, RAM, диск, сеть хоста (node-exporter).
- Контейнеры: CPU/RAM/рестарты (cAdvisor).
- PostgreSQL: подключения, транзакции, размер БД, медленные запросы (postgres-exporter; в БД уже включён `log_min_duration_statement=1000`).
- Redis: память, ключи, hit/miss, подключённые клиенты (redis-exporter).
- Доступность API и Nuxt: HTTP 2xx/пробы (blackbox-exporter на `/healthz` и `/`).

### Приложение
- Логи всех контейнеров через Loki/Promtail (фильтр по `container`).
- Ошибки 4xx/5xx в логах API/Nuxt.
- Время ответа healthcheck (blackbox probe duration).
- LLM-трейсинг и стоимость — через Langfuse (уже настроен в compose через `LANGFUSE_*`), Grafana его не дублирует.

### Очереди и воркеры
- Живость `worker-pdf` / `worker-llm` (pidfile healthcheck в compose).
- Длина очередей Celery в Redis (метрика `redis_db_keys`/`redis_key_size` или ручной `LLEN`).
- Повторы/сбои задач — в логах воркеров.

### Аудиты (бизнес-метрики)
- Количество запусков и их статусы (`running`/`done`/`failed`) — SQL по таблице `runs`.
- Длительность подготовки PDF и позиций — логи `audit_tasks`.
- Ошибки LLM/OCR — логи воркеров и Langfuse.

### Безопасность и вход (AD)
- Неудачные попытки входа (401/403) в логах Nuxt.
- Блокировки по rate limit (3 попытки на учётную запись / 20 с IP за 15 минут).
- Отзывы сессий при недоступности AD.
- TLS/STARTTLS ошибки LDAP.
- Доступ к Grafana: рекомендуется включить LDAP-аутентификацию Grafana (см. ниже).

## Grafana и Active Directory

Grafana поддерживает LDAP. Пример конфигурации — `monitoring/grafana/ldap.toml.example`.
Чтобы включить:
1. Скопируйте пример в `monitoring/grafana/ldap.toml`.
2. Заполните параметры AD (сервер, base DN, bind DN).
3. Добавьте в `compose.monitoring.yaml` для сервиса `grafana`:
   - env `GF_AUTH_LDAP_ENABLED=true`
   - env `GF_AUTH_LDAP_CONFIG_FILE=/etc/grafana/ldap.toml`
   - volume `./monitoring/grafana/ldap.toml:/etc/grafana/ldap.toml:ro`
4. Перезапустите Grafana.

Пока AD для Grafana не настроен, используйте локального admin и ограничьте доступ к порту (bind на `127.0.0.1`).

## Рекомендуемые дашборды

- Node Exporter Full (id 1860) — CPU/RAM/диск.
- PostgreSQL (id 9628) — БД.
- Redis (id 11835) — кэш/брокер.
- cAdvisor (id 14282) — контейнеры.
- Blackbox (id 7587) — доступность.
