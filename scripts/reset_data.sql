-- Очистка тестовых данных перед запуском в работу.
-- УДАЛЯЕТ: заказы и переписку, корзины, каталог (модели, категории, детали, остатки), дилеров,
--          сотрудников дилеров и приглашения, историю синхронизаций и рассылок.
-- ОСТАВЛЯЕТ: клиентов бота, сотрудников веб-панели и их роли, регионы, настройки (контакты менеджера),
--            переводы названий деталей из панели, журнал действий.
-- Перед запуском обязательно сделайте резервную копию (см. README «Очистка перед запуском»).
BEGIN;
TRUNCATE order_messages, order_items, orders, cart_items, stocks, parts, models, nodes,
         dealer_staff, dealer_invites, dealers, sync_runs, broadcasts RESTART IDENTITY;
ALTER SEQUENCE orders_id_seq RESTART WITH 10001;  -- номера заказов снова с 10001
DELETE FROM bot_settings WHERE key = 'carsale_sync_request';
COMMIT;

SELECT 'orders' AS table, count(*) FROM orders
UNION ALL SELECT 'parts', count(*) FROM parts
UNION ALL SELECT 'dealers', count(*) FROM dealers
UNION ALL SELECT 'users (остаются)', count(*) FROM users
UNION ALL SELECT 'web_users (остаются)', count(*) FROM web_users;
