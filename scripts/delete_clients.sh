#!/bin/sh
# Удалить клиентов бота, оставив сотрудников (веб-панель, дилеры, ADMIN_IDS). Каталог и дилеров НЕ трогает.
# Нужен, если scripts/reset.sh уже запускали раньше, а клиентов не удаляли.
# Запуск на сервере:  cd ~/parts_bot && sh scripts/delete_clients.sh
set -eu
cd "$(dirname "$0")/.."

echo "Будут удалены все клиенты бота вместе с их заказами, корзинами и чатом."
echo "Останутся: сотрудники веб-панели, сотрудники дилеров, администраторы (ADMIN_IDS), каталог, дилеры."
printf "Чтобы продолжить, напишите yes и нажмите Enter: "
read -r answer
[ "$answer" = "yes" ] || { echo "Отменено — ничего не изменено."; exit 1; }

# Telegram ID администраторов из .env — только цифры и запятые
ids=$(sed -n 's/^ADMIN_IDS=//p' .env 2>/dev/null | tr -c '0-9' ',' | tr -s ',' | sed 's/^,//; s/,$//')
[ -n "$ids" ] || ids=0

name="jac_parts_$(date +%Y-%m-%d_%H%M)_before_delete_clients.sql.gz"
echo "1/2 Резервная копия: backups/$name"
docker compose exec -T backup sh -c "PGPASSWORD=\"\$POSTGRES_PASSWORD\" pg_dump -h postgres -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" --no-owner | gzip > /backups/$name && gunzip -c /backups/$name | tail -n 5 | grep -q 'dump complete' || { rm -f /backups/$name; exit 1; }" \
  || { echo "Резервная копия НЕ получилась — ничего не удаляю. Проверьте: docker compose ps"; exit 1; }

echo "2/2 Удаляю клиентов"
docker compose exec -T postgres sh -c "psql -v ON_ERROR_STOP=1 -v admin_ids=$ids -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\"" < scripts/delete_clients.sql \
  || { echo "Ошибка — ничего не удалено."; exit 1; }
echo "Готово."
