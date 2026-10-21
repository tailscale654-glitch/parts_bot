-- Возвращает сотрудников дилеров после очистки (scripts/reset_data.sql).
-- Запускать, когда дилеры снова появились: после загрузки справочника дилеров или синхронизации с CarSale.
-- Дилер ищется по названию. Можно запускать несколько раз: кто уже вернулся — не дублируется.
\set ON_ERROR_STOP on

SELECT to_regclass('restore_dealer_staff') IS NOT NULL AS has_backup \gset
\if :has_backup

INSERT INTO dealer_staff (dealer_id, user_id)
SELECT d.id, r.user_id
FROM restore_dealer_staff r
JOIN dealers d ON d.name_key = r.name_key
JOIN users u ON u.id = r.user_id
ON CONFLICT (user_id) DO NOTHING;

SELECT r.dealer_name AS "Дилер",
       concat_ws(' ', u.first_name, u.last_name) AS "Сотрудник",
       u.phone AS "Телефон",
       CASE WHEN s.id IS NULL THEN 'нет — дилера ещё нет в базе' ELSE 'вернулся' END AS "Результат"
FROM restore_dealer_staff r
JOIN users u ON u.id = r.user_id
LEFT JOIN dealer_staff s ON s.user_id = r.user_id
ORDER BY 1, 2;

-- все вернулись — временная таблица больше не нужна
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM restore_dealer_staff r
                   LEFT JOIN dealer_staff s ON s.user_id = r.user_id WHERE s.id IS NULL) THEN
        DROP TABLE restore_dealer_staff;
        RAISE NOTICE 'Все сотрудники дилеров вернулись.';
    END IF;
END $$;

\else
\echo 'Восстанавливать нечего: все сотрудники дилеров уже вернулись (или очистка не запускалась).'
\endif
