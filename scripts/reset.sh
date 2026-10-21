#!/bin/sh
# Очистка базы перед передачей бота в работу. Что удаляется и что остаётся — в scripts/reset_data.sql.
# Запуск на сервере:  cd ~/parts_bot && sh scripts/reset.sh
# Сначала делается резервная копия в backups/ — из неё всё можно вернуть (README «Восстановление из backup»).
set -eu
cd "$(dirname "$0")/.."

echo "Будут удалены: клиенты бота, заказы, чат с клиентами, корзины, дилеры, каталог, списки запчастей,"
echo "переводы и правки деталей, история синхронизаций и рассылок, журнал действий."
echo "Останутся: сотрудники веб-панели, сотрудники дилеров, администраторы (ADMIN_IDS), регионы, контакты менеджера."
printf "Чтобы продолжить, напишите yes и нажмите Enter: "
read -r answer
[ "$answer" = "yes" ] || { echo "Отменено — ничего не изменено."; exit 1; }

# Telegram ID администраторов из .env — только цифры и запятые (их не удаляем)
ids=$(sed -n 's/^ADMIN_IDS=//p' .env 2>/dev/null | tr -c '0-9' ',' | tr -s ',' | sed 's/^,//; s/,$//')
[ -n "$ids" ] || ids=0

name="jac_parts_$(date +%Y-%m-%d_%H%M)_before_reset.sql.gz"
echo "1/4 Резервная копия: backups/$name"
docker compose exec -T backup sh -c "PGPASSWORD=\"\$POSTGRES_PASSWORD\" pg_dump -h postgres -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" --no-owner | gzip > /backups/$name && gunzip -c /backups/$name | tail -n 5 | grep -q 'dump complete' || { rm -f /backups/$name; exit 1; }" \
  || { echo "Резервная копия НЕ получилась — очистку не делаю. Проверьте: docker compose ps"; exit 1; }
ls -lh "backups/$name" 2>/dev/null || true

echo "2/4 Останавливаю бота, панель и синхронизацию"
docker compose stop bot web sync

echo "3/4 Очищаю базу"
if ! docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < scripts/reset_data.sql; then
  echo "Ошибка — база не изменена (всё или ничего). Запускаю бота обратно."
  docker compose start bot web sync
  exit 1
fi
echo "    Удаляю клиентов (сотрудники остаются)"
if ! docker compose exec -T postgres sh -c "psql -v ON_ERROR_STOP=1 -v admin_ids=$ids -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\"" < scripts/delete_clients.sql; then
  echo "Ошибка при удалении клиентов — клиенты остались, остальная очистка сделана. Повторить: sh scripts/delete_clients.sh"
fi

echo "4/4 Запускаю бота, панель и синхронизацию"
docker compose start bot web sync
echo
echo "Готово. Дальше в веб-панели → «📥 Загрузка Excel»: справочник дилеров, затем списки запчастей завода;"
echo "потом «🔄 CarSale» → «Синхронизировать сейчас». Сотрудников дилеров вернёт команда:"
echo "  docker compose exec -T postgres sh -c 'psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\"' < scripts/restore_dealer_staff.sql"
