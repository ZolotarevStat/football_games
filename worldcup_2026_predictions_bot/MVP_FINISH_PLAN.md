# MVP Finish Plan

Дата обновления: 2026-06-08.

## Текущее решение

Продовый MVP работает в режиме polling-worker на Yandex Cloud Compute VM:

```text
Telegram Bot API getUpdates -> YC Compute VM systemd worker -> Google Sheets
```

Webhook отключен. Это осознанный MVP-выбор после нестабильных timeout на связке Telegram -> Yandex Cloud Functions и исходящих вызовах Cloud Functions к `api.telegram.org`.

Текущий статус:

- VM: `wc-predictions-bot-worker`, external IP хранится вне репозитория.
- Service: `wc-predictions-bot`, `systemd`, enabled + active.
- Durable state: Google Sheets.
- Локальный ноутбук не является production runtime.
- Cloud Functions/API Gateway оставлены как артефакты эксперимента, но не являются текущим runtime.

## Что уже входит в MVP

- Привязка участника по invite/PIN через `/start`.
- Тестовый доступ по списку `ALLOWED_USERNAMES`, если включен `OPEN_REGISTRATION_ENABLED=true`.
- Приватный ввод прогнозов в личке боту.
- Интерактивный сценарий `/predict`: матч -> 7 счетов -> автор команды 1 -> автор команды 2 -> подтверждение.
- Быстрая команда `/submit MATCH_ID scores | Автор1 | Автор2`.
- Быстрая команда `/authors MATCH_ID | Автор1 | Автор2` для замены только авторов до дедлайна.
- Компактный список ближайших открытых матчей через `/matches`.
- Подробные правила через `/rules`.
- Просмотр своих прогнозов через `/my`.
- Server-side deadline: новые прогнозы и правки после дедлайна блокируются.
- Server-side проверка 7 уникальных счетов.
- Server-side проверка авторов из активной заявки команды.
- Подсказки по ближайшим игрокам из заявки при ручной ошибке в `/submit`.
- Запрет повтора авторов Г+П внутри одного прогноза.
- Запрет повторного автора в актуальных прогнозах участника.
- Админские команды `/status MATCH_ID`, `/publish MATCH_ID`, `/score MATCH_ID`, `/score all` и `/leaderboard`.

## Работа в группе участников

Основное правило: прогнозы не принимаются в группе, только в личке боту.

Режим Telegram:

- У BotFather желательно оставить `Privacy Mode = ENABLED`.
- Тогда бот в группе видит только команды, ответы на свои сообщения и упоминания, а не весь поток чата.

Кодовая защита:

- В группах обычный текст игнорируется.
- В группах прогнозные команды `/start`, `/predict`, `/submit`, `/authors`, `/my`, `/cancel` не выполняются; бот отвечает коротким сообщением, что прогнозы принимаются в личке.
- В группах разрешены только явные команды из allowlist: `/help`, `/rules`, `/matches`, `/status`, `/publish`, `/score`, `/leaderboard`, а также forecast-команды только как redirect в личку.
- Команды с упоминанием бота нормализуются: `/my@tii_wc_predictions_2026_bot` работает так же, как `/my`.

Практика для участников:

- В общем чате можно закрепить инструкцию: "Прогнозы отправлять в личку @tii_wc_predictions_2026_bot. В группе бот нужен только для публикации закрытых прогнозов и таблицы".
- Организаторы используют `/publish MATCH_ID` после дедлайна и `/leaderboard` после обновления таблицы.

## Следующие шаги

### P0 - стабилизация runtime

1. Убрать/архивировать webhook Cloud Function как не-prod путь, чтобы не путать эксплуатацию.
2. Описать runbook для YC worker:
   - `systemctl status wc-predictions-bot`
   - `journalctl -u wc-predictions-bot`
   - restart/deploy/update.
3. Настроить минимальный мониторинг:
   - cron/automation или health script, который проверяет `systemctl is-active`;
   - алерт или ручной чек перед игровым днем.
4. Перенести секреты с VM filesystem в более аккуратный механизм, если останемся на VM дольше MVP:
   - минимум `chmod 600`;
   - лучше Lockbox + deploy script.

### P0 - данные турнира

1. Проверить часовой пояс и дедлайны на первых матчах после каждого импорта workbook.
   - Правило MVP: `deadline_msk = kickoff_msk - 5 минут`.
   - Проверено 2026-06-08: `MexSAf` 21:55, `SKoCze` 04:55, `CanBiH` 21:55.
2. Поддерживать реальные матчи ЧМ-2026 в листе `matches`.
3. Поддерживать полные заявки игроков по каждой команде с сортировкой по priority.
4. Финализировать участников:
   - не P0 для открытого теста с `OPEN_REGISTRATION_ENABLED=true`;
   - P0 перед закрытым боевым запуском, если нужен allowlist, invite/PIN и корректный `/status MATCH_ID` по списку ожидаемых участников.

### P1 - UX перед запуском

1. Сообщение после `/start`: явный пример `/submit`.
2. Убрать test labels из пользовательских сообщений.
3. Дальше упрощать UX только по фактическим фидбэкам тестеров.

### P1 - админский контур

1. `/remind MATCH_ID`: список/сообщение для напоминания несдавшим.
2. `/publish MATCH_ID` smoke на тестовом закрытом матче.
3. Проверить, что `TOURNAMENT_CHAT_ID` указывает на правильный общий чат.

### P2 - scoring

1. Зафиксировать правила расчета очков в листе `scoring_rules`.
2. Сделать скрипт пересчета `scoring` и `leaderboard`.
3. Smoke: один матч -> results -> scoring -> leaderboard -> `/leaderboard`.
4. Отменённые матчи и технические результаты помечать в `results.status` как `cancelled` / `technical`; они не учитываются.

## Stop-rules

- Не расширять MVP до веб-интерфейса.
- Не добавлять базу данных, пока Google Sheets хватает.
- Не делать сложную авторизацию: invite/PIN + telegram_id достаточно для MVP.
- Не возвращаться к webhook, пока polling worker стабилен и работает на YC.
