# WHOOP × Telegram Coach — Development Tasks

## Stage 0: Каркас (Skeleton)
- [x] Создать структуру проекта (папки, pyproject.toml, .env.example)
- [x] Настроить SQLAlchemy + Alembic (модели, миграции)
- [x] Реализовать Telegram бот: `/start`, `/help`, `/gear`, `/plan` (заглушка)
- [x] Настроить FastAPI для OAuth callback + webhooks
- [x] Конфигурация через Pydantic Settings
- [x] Добавить Docker / Railway конфигурацию

## Stage 1: WHOOP авторизация + чтение данных
- [x] WHOOP OAuth flow: авторизация, токены, refresh
- [x] Хранение токенов в БД (шифрование)
- [x] `/last` — показать последние workouts/cycles

## Stage 2: Логирование ролика + матчинг workout
- [x] Парсинг YouTube URL из сообщения
- [x] Создание pending_log с timestamp
- [x] Матчинг к WHOOP workout по времени
- [x] Выбор кандидата при неоднозначности
- [x] RPE 1–5 после матча
- [x] `/retry`, `/undo` команды

## Stage 3: "Умные вопросы" по unattributed
- [x] NeedMoreInfoScore расчёт
- [x] Авто-уточнение для ski/hike
- [x] Утренний soreness/pain опрос

## Stage 4: Утренний план по вебхуку recovery
- [x] WHOOP webhook обработка
- [x] Генерация плана на 3 дня
- [x] Hard constraints (боль, soreness, Z4 лимиты)
- [/] Soft scoring (benefit/cost) — базовый MVP


## Stage 5: YouTube пул + рекомендации
- [ ] Хранение videos/channels
- [ ] Отказ с причиной
- [ ] Ранжирование роликов

## Stage 6: VO₂max estimation
- [ ] VO₂max_est_submax из бега
- [ ] Weekly агрегирование
- [ ] Вторничный запрос manual VO₂max
