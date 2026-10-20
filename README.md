# INVIX Catalog

Каталог товаров: администратор отправляет Telegram-боту фотографию с названием в подписи, бот сохраняет изображение в MinIO и товар в PostgreSQL. Каталог на Next.js App Router доступен в браузере и Telegram Mini App.

## Живой стенд

- Telegram-бот: [@godsdar_invix_catalog_bot](https://t.me/godsdar_invix_catalog_bot).
- Каталог / Mini App: https://policies-travis-ebony-decade.trycloudflare.com/.

Стенд запущен 20 октября 2026 на локальном компьютере через временный HTTPS-туннель. Доступен, пока работают компьютер, Docker и туннель. URL может измениться при пересоздании туннеля. В каталоге есть демонстрационный товар с тестовым изображением; новые товары добавляются администратором через `/create` и одно фото с названием в подписи.

Стек: **Next.js / React / TypeScript, FastAPI, aiogram 3, PostgreSQL 17, MinIO**. UI намеренно минимальный. Добавление товаров выполняется только через бота и только для `ADMIN_IDS`.

## Быстрый запуск каталога

Нужны Docker Engine и Docker Compose v2.

```sh
cp .env.example .env
docker compose up -d --build
```

Открыть [http://localhost:8080](http://localhost:8080). Без добавленных товаров отображается «Товаров пока нет». API: [http://localhost:8080/api/products](http://localhost:8080/api/products), OpenAPI: [http://localhost:8080/api/docs](http://localhost:8080/api/docs).

Сначала одноразовый контейнер `init` применит схему и создаст приватный bucket, затем запустятся API, Next.js и gateway. PostgreSQL и MinIO доступны только внутри Docker-сети. Данные сохраняются в именованных volumes. Локальные пароли из примера нужно заменить перед публичным развёртыванием.

## Telegram-бот и Mini App

1. Создать бота в BotFather, записать токен в `.env` как `BOT_TOKEN`.
2. Указать числовые Telegram user ID администраторов через запятую в `ADMIN_IDS`. ID проверяется по `message.from.id` из обновления Telegram, а не по параметрам браузера.
3. Сгенерировать `WEBHOOK_SECRET`: `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` и внести его в `.env`.
4. Настроить публичный HTTPS reverse proxy на gateway (локально слушает `127.0.0.1:8080`). Передать внешний URL в `MINI_APP_URL`, например `https://catalog.example.org`. Сохранить заголовок `X-Telegram-Bot-Api-Secret-Token` при проксировании `/telegram/webhook`. Для удалённого proxy изменить bind-адрес gateway только в закрытой сети.
5. Запустить сервисы и зарегистрировать webhook:

```sh
docker compose --profile telegram up -d --build \
  --scale api=2 --scale frontend=2 --scale bot=2 --scale worker=2
docker compose --profile telegram run --rm worker python -m catalog.register_webhook
```

Регистрация устанавливает команды `/start`, `/create`, `/cancel` и webhook. Long polling не используется. Команду регистрации выполняют один раз после изменения адреса или секрета, а не при старте каждой реплики. Ранее ожидающие обновления Telegram не удаляются.

В личном чате `/start` возвращает «У меня есть товар» и кнопку открытия каталога. Администратор также видит «Создать товар». `/create` или эта кнопка запрашивает одну фотографию с названием в caption. Диалог действует 30 минут; `/cancel` отменяет его. Название: 1–200 символов, фото: до 10 МБ / 20 мегапикселей. Альбомы отклоняются с подсказкой отправить одно фото. Неадминистратор не может создать товар.

Каталог публичный, одинаковый в браузере и Mini App: аутентификация через `initData` для чтения не требуется. Клиент не передаёт `user_id` для изменения данных, mutation API в вебе отсутствует. SDK вызывает `ready()` и `expand()`; отсутствие SDK не мешает обычному браузеру.

## Временный HTTPS-стенд на своём компьютере

```sh
./scripts/start-demo.sh
# Остановить стенд, сохранив данные:
./scripts/stop-demo.sh
```

Скрипт запускает две реплики каталога и официальный Cloudflare Quick Tunnel, записывает полученный HTTPS URL в локальный `.env`. Если заполнены `BOT_TOKEN` и `ADMIN_IDS`, также запускает по две реплики webhook и worker и регистрирует webhook. Секрет webhook генерируется локально; токен не выводится в терминал.

Публичный адрес работает, пока запущены компьютер, Docker и контейнер туннеля. При пересоздании туннеля URL меняется: нужно повторно выполнить `start-demo.sh`, чтобы обновить кнопку Mini App и webhook. Для длительного ревью лучше использовать сервер со стабильным доменом. Профиль временного стенда отключает автоматический перезапуск всех компонентов после перезапуска Docker/компьютера. Запланированное включение и пробуждение компьютера не настраиваются.

## Архитектура и несколько реплик

```text
Telegram → HTTPS gateway → bot webhook × N → PostgreSQL durable inbox
                                                   ↓
                                             worker × N
                                              ↓      ↓
                                            MinIO  products + outbox
                                                       ↓
                                                  Telegram reply
Browser / Mini App → gateway → Next.js × N → FastAPI × N → PostgreSQL / MinIO
```

- Webhook проверяет секрет, валидирует update и подтверждает приём только после commit в PostgreSQL. `update_id` является первичным ключом: повторная доставка безопасна.
- Воркеры выбирают задания через `FOR UPDATE SKIP LOCKED`. Ранее принятые незавершённые обновления того же чата блокируют следующие; другие чаты обрабатываются параллельно. Состояние добавления товара хранится в `admin_dialogs`, не в памяти aiogram FSM.
- Фото скачивается в ограниченный буфер, декодируется и повторно кодируется в JPEG; метаданные исходного файла не переносятся. Локальные пользовательские файлы не сохраняются. Объект в S3 приватный; API отдаёт ограниченное по размеру изображение по ID товара.
- S3 записывается до commit товара. Ключ `products/{update_id}.jpg` детерминирован. После сбоя между S3 и PostgreSQL update остаётся в inbox и повторно записывает тот же объект; товар появляется только после успешной транзакции. Это не распределённая транзакция: при длительном сбое в S3 может временно лежать объект без видимого товара.
- Товар, завершение update, удаление диалога и ответ в outbox фиксируются в одной транзакции. Savepoint позволяет после ошибки сохранить счётчик попыток и повторить update с задержкой 2–256 секунд. Повторы не ограничены: зависший чат требует наблюдения оператора.
- Отправка ответов также распределяется между воркерами через PostgreSQL. Telegram `retry_after` учитывается; блокировка бота пользователем завершает доставку с сохранением причины. Если Telegram принял `sendMessage`, но процесс умер до commit, ответ может повториться. Для внешнего API **exactly-once не обещается**; создание товара идемпотентно.
- API, webhook, worker и Next.js не содержат постоянного пользовательского состояния и не требуют sticky sessions. Nginx обновляет Docker DNS каждые 5 секунд. PostgreSQL и MinIO — внешние хранилища состояния. В Compose они одиночные: это демонстрация масштабирования приложения, а не кластер высокой доступности инфраструктуры. Gateway также одиночный; его можно вынести во внешний балансировщик.

Подробности: [ADR-001](docs/decisions/001-durable-telegram-processing.md).

## Проверки

```sh
# Реальные PostgreSQL и MinIO; отдельная БД catalog_test и bucket catalog-test.
docker compose --profile test build api tests minio
docker compose --profile test run --rm tests

# Next.js, включая TypeScript
docker compose build frontend

# Несколько реплик без Telegram credentials
docker compose up -d --scale api=2 --scale frontend=2
docker compose ps
curl -f http://localhost:8080/api/health/ready
```

Тесты создают только тестовую БД с суффиксом `_test`, очищают только её таблицы и используют отдельный S3 bucket. Для проверки aiogram используется настоящий Dispatcher, для внешних вызовов Telegram — подставной gateway: токен и сеть Telegram не нужны. Сценарии: секрет webhook, пять параллельных повторов одного update, запрет записи неадминистратором, создание товара и чтение изображения через API, состояние диалога между обработчиками, валидация ввода, отмена/истечение диалога, повреждённое фото, отказ после записи в S3 до commit, восемь параллельных воркеров, повтор доставки ответа, keyset-пагинация.

Натурная проверка Telegram требует настоящего токена и публичного HTTPS URL. Они не входят в репозиторий. Автотесты не доказывают доставку сообщений реальным Telegram или поведение конкретного клиента Telegram.

## API

| Маршрут | Назначение |
| --- | --- |
| `GET /api/products?after=0&limit=50` | Товары в порядке ID, `items` и `next_cursor`; лимит до 100 |
| `GET /api/products/{id}/image` | JPEG из приватного MinIO; 404, если товара нет |
| `GET /api/health/live` | Процесс API запущен |
| `GET /api/health/ready` | PostgreSQL со схемой и MinIO доступны |
| `POST /telegram/webhook` | Только аутентифицированные Telegram updates |

Список не кэшируется в Next.js, поэтому новые товары видны после обновления страницы. Изображения кэшируются на час, так как после создания товар не редактируется. Пагинация по ID не выполняет дорогой `OFFSET`.

## Эксплуатация

```sh
docker compose logs --tail=100 api
docker compose --profile telegram logs --tail=100 worker bot
# Остановка сохраняет данные
docker compose --profile telegram down
```

Readiness API возвращает 503 при недоступности хранилищ. При недоступности PostgreSQL webhook не подтверждает запись; Telegram повторит доставку. Ошибки воркеров записываются по типу исключения и ID задания, без payload, URL скачивания и токенов. За очередями следует наблюдать, например:

```sql
SELECT update_id, attempts, last_error, received_at
FROM telegram_updates WHERE done_at IS NULL ORDER BY received_at;
SELECT id, attempts, last_error FROM telegram_outbox WHERE sent_at IS NULL;
```

Для постоянной эксплуатации нужны резервные копии PostgreSQL/MinIO, мониторинг задержки очереди и срока сертификата, ротация секретов и политика хранения старых Telegram updates/outbox. Автоматическое удаление не включено, чтобы не потерять историю идемпотентности. Текущая схема — версия 1, применяется отдельным init под advisory lock. Следующие изменения следует добавлять как последовательные миграции, а не менять существующую схему в работающей БД.

## Структура

- `backend/catalog/api.py` — FastAPI: каталог и фотографии.
- `backend/catalog/webhook.py` — сохранение Telegram updates.
- `backend/catalog/handlers.py` — сценарии бота на aiogram.
- `backend/catalog/worker.py` — конкурирующие воркеры inbox/outbox.
- `backend/catalog/storage.py` — MinIO и проверка фото.
- `backend/tests/` — интеграционные сценарии.
- `frontend/app/` — серверная страница Next.js и адаптация Mini App.
- `infra/nginx.conf`, `compose.yaml` — маршрутизация и запуск.

MinIO собирается из официального upstream commit `9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a` (релиз `RELEASE.2025-10-15T17-29-55Z`): публичные реестры образов могут не отдавать старые теги. Первая сборка MinIO требует сети и занимает больше времени; лицензия upstream включена в контейнер.

Версии Python-зависимостей зафиксированы в `uv.lock`, `requirements.txt`, `requirements-dev.txt`; JavaScript — в `package-lock.json`.
