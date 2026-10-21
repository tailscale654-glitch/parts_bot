-- Удаляет клиентов бота (всех, кто не сотрудник). Вместе с клиентом удаляются его заказы, корзина и чат.
-- ОСТАВЛЯЕТ: сотрудников веб-панели (логины, пароли, роли), сотрудников дилеров (в том числе сохранённых
--            для возврата после очистки) и администраторов из ADMIN_IDS.
-- Запуск: scripts/reset.sh (вместе с очисткой) или scripts/delete_clients.sh (только клиенты).
-- Переменная admin_ids — Telegram ID администраторов через запятую (скрипты берут её из .env).
\set ON_ERROR_STOP on
\if :{?admin_ids}
\else
\set admin_ids 0
\endif

BEGIN;
CREATE TEMP TABLE keep_users (id integer PRIMARY KEY, why text) ON COMMIT DROP;
INSERT INTO keep_users SELECT user_id, 'сотрудник веб-панели' FROM web_users ON CONFLICT DO NOTHING;
INSERT INTO keep_users SELECT user_id, 'сотрудник дилера' FROM dealer_staff ON CONFLICT DO NOTHING;
INSERT INTO keep_users SELECT id, 'администратор (ADMIN_IDS)' FROM users WHERE telegram_id IN (:admin_ids) ON CONFLICT DO NOTHING;
DO $$
BEGIN
    IF to_regclass('restore_dealer_staff') IS NOT NULL THEN  -- сотрудники дилеров, которые вернутся после загрузки дилеров
        INSERT INTO keep_users SELECT user_id, 'сотрудник дилера' FROM restore_dealer_staff ON CONFLICT DO NOTHING;
    END IF;
END $$;

DELETE FROM users WHERE id NOT IN (SELECT id FROM keep_users);

SELECT concat_ws(' ', u.first_name, u.last_name) AS "Остались", u.phone AS "Телефон", k.why AS "Почему"
FROM users u JOIN keep_users k ON k.id = u.id
ORDER BY k.why, 1;
COMMIT;

SELECT count(*) AS "Пользователей в боте теперь" FROM users;
