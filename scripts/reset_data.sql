-- Очистка тестовых данных перед передачей бота в работу.
-- Запускать через scripts/reset.sh (он сначала делает резервную копию и останавливает бота).
--
-- УДАЛЯЕТ: заказы и переписку по заказам, корзины, чат с клиентами (веб-панель «Чат»), очередь продаж в CarSale,
--          дилеров и ссылки-приглашения, каталог (модели, категории, детали, остатки), списки запчастей завода,
--          переводы и правки деталей из панели, историю синхронизаций и рассылок, журнал действий,
--          неиспользованные приглашения в веб-панель.
-- ОСТАВЛЯЕТ: всех пользователей бота (имя, телефон, язык, регион, автомобиль), сотрудников веб-панели
--             с логинами, паролями и ролями, регионы, контакты менеджера («⚙️ Настройки»).
--
-- Привязку сотрудников к дилерам сохраняет в таблицу restore_dealer_staff: дилеры удаляются,
-- а после загрузки справочника дилеров (или синхронизации CarSale) scripts/restore_dealer_staff.sql вернёт её.
\set ON_ERROR_STOP on

BEGIN;
DROP TABLE IF EXISTS restore_dealer_staff;
CREATE TABLE restore_dealer_staff AS
    SELECT s.user_id, d.name_key, d.name AS dealer_name
    FROM dealer_staff s JOIN dealers d ON d.id = s.dealer_id;

TRUNCATE order_messages, order_items, carsale_ops, orders, cart_items,
         support_messages, support_chats,
         stocks, parts, models, nodes, part_catalog, part_overrides, part_translations,
         dealer_staff, dealer_invites, dealers, panel_invites,
         sync_runs, broadcasts, audit_log
         RESTART IDENTITY;
ALTER SEQUENCE orders_id_seq RESTART WITH 10001;  -- номера заказов снова с 10001
DELETE FROM bot_settings WHERE key IN ('carsale_sync_request', 'untranslated_notified');
COMMIT;

SELECT 'Заказы' AS "Что", count(*) AS "Осталось" FROM orders
UNION ALL SELECT 'Сообщения в чате', count(*) FROM support_messages
UNION ALL SELECT 'Дилеры', count(*) FROM dealers
UNION ALL SELECT 'Детали', count(*) FROM parts
UNION ALL SELECT 'Пользователи бота (остаются)', count(*) FROM users
UNION ALL SELECT 'Сотрудники веб-панели (остаются)', count(*) FROM web_users
UNION ALL SELECT 'Сотрудники дилеров — вернутся после загрузки дилеров', count(*) FROM restore_dealer_staff;
