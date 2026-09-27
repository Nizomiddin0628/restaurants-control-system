#!/usr/bin/env bash
# RestoPOS — serverga o'rnatish / yangilash (Ubuntu 24.04, root).
#   Birinchi marta ham, yangilash uchun ham bir xil buyruq:
#   curl -fsSL https://raw.githubusercontent.com/Nizomiddin0628/restaurants-control-system/main/deploy/install.sh | bash
# Domen: BASE=restopos.uz bilan bering (standart — IP asosidagi bepul nip.io manzili).
# Serverdagi boshqa saytlarga (Caddy'dagi eski loyihalar) tegmaydi: faqat o'z bloki import qilinadi.
set -euo pipefail

IP="$(curl -fsS4 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
BASE="${BASE:-${IP//./-}.nip.io}"
APP=/srv/restopos
REPO=https://github.com/Nizomiddin0628/restaurants-control-system.git
PORT=8010
USR=restopos
ENVF=$APP/.env

say() { echo -e "\n\033[1;32m==> $*\033[0m"; }
die() { echo -e "\n\033[1;31mXATO: $*\033[0m"; exit 1; }
[ "$(id -u)" = 0 ] || die "root sifatida ishga tushiring"
export DEBIAN_FRONTEND=noninteractive

say "1/9 Kerakli dasturlar (PostgreSQL, Redis, Python, Node)"
apt-get update -qq
apt-get install -y -qq postgresql redis-server python3-venv python3-dev build-essential libpq-dev git curl nodejs npm >/dev/null
systemctl enable --now postgresql redis-server >/dev/null
command -v pnpm >/dev/null || npm i -g pnpm@9.15.9 >/dev/null 2>&1
id -u $USR >/dev/null 2>&1 || useradd --system --home $APP --shell /usr/sbin/nologin $USR

git config --global --add safe.directory $APP 2>/dev/null || true
say "2/9 Kod (GitHub)"
if [ -d $APP/.git ]; then
  git -C $APP fetch -q origin main && git -C $APP reset -q --hard origin/main
else
  mkdir -p $APP && GIT_TERMINAL_PROMPT=0 git clone -q $REPO $APP.tmp && cp -a $APP.tmp/. $APP/ && rm -rf $APP.tmp
fi
echo "   versiya: $(git -C $APP log --oneline -1)"

say "3/9 Sozlamalar (.env) va baza"
if [ ! -f $ENVF ]; then
  rnd() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }
  cat > $ENVF <<ENV
DJANGO_SETTINGS_MODULE=config.settings.prod
DJANGO_SECRET_KEY=$(rnd 50)
JWT_SECRET=$(rnd 48)
POSTGRES_DB=restopos
POSTGRES_USER=restopos
POSTGRES_PASSWORD=$(rnd 24 | tr -dc 'A-Za-z0-9')
POSTGRES_HOST=localhost
REDIS_URL=redis://localhost:6379/3
PLATFORM_DOMAIN=$BASE
ALLOWED_HOSTS=*
OTP_DEV_ECHO=1
HTTPS=0
ENV
  chmod 600 $ENVF
fi
sed -i "s/^PLATFORM_DOMAIN=.*/PLATFORM_DOMAIN=$BASE/" $ENVF
set -a; . $ENVF; set +a
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$POSTGRES_USER'" | grep -q 1 \
  || sudo -u postgres psql -qc "CREATE ROLE $POSTGRES_USER LOGIN PASSWORD '$POSTGRES_PASSWORD'"
sudo -u postgres psql -qc "ALTER ROLE $POSTGRES_USER PASSWORD '$POSTGRES_PASSWORD'"
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$POSTGRES_DB'" | grep -q 1 \
  || sudo -u postgres createdb -O $POSTGRES_USER $POSTGRES_DB

say "4/9 Python kutubxonalari"
[ -d $APP/.venv ] || python3 -m venv $APP/.venv
$APP/.venv/bin/pip install -q --upgrade pip
$APP/.venv/bin/pip install -q -r $APP/backend/requirements.txt

say "5/9 Boshqaruv paneli (frontend) yig'ilmoqda — 2-5 daqiqa"
cd $APP/frontend
pnpm install --frozen-lockfile --reporter=silent
NODE_OPTIONS=--max-old-space-size=1024 pnpm --filter @restopos/admin exec vite build --logLevel warn

say "6/9 Migratsiya va demo ma'lumotlar"
cd $APP/backend
PY="$APP/.venv/bin/python manage.py"
if [ ! -f $APP/.seeded ]; then
  $PY bootstrap_dev
  $PY seed_showcase --domain "namuna.$BASE" || true
  $PY seed_hr --slug namuna || true
  touch $APP/.seeded
fi
$PY migrate_schemas --shared -v 0
$PY migrate_schemas -v 0
$PY set_platform_domain "$BASE"
$PY training_videos --all || true
$PY collectstatic --noinput -v 0
mkdir -p $APP/backend/media
chown -R $USR:$USR $APP
chmod 750 $APP; chmod o+x $APP $APP/backend; chmod -R o+rX $APP/backend/media

say "7/9 Xizmat (gunicorn, port $PORT)"
cat > /etc/systemd/system/restopos.service <<UNIT
[Unit]
Description=RestoPOS (gunicorn)
After=network.target postgresql.service redis-server.service

[Service]
User=$USR
Group=$USR
WorkingDirectory=$APP/backend
EnvironmentFile=$ENVF
ExecStart=$APP/.venv/bin/gunicorn config.wsgi:application -b 127.0.0.1:$PORT -w 2 --threads 2 --timeout 60 --max-requests 800 --max-requests-jitter 80 --access-logfile -
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable restopos >/dev/null
systemctl restart restopos

say "8/9 Caddy (eski saytlarga tegmaydi)"
if [ "${HTTPS_ON:-0}" = 1 ]; then SITE="$BASE, *.$BASE"; else SITE="http://$BASE, http://*.$BASE"; fi
cat > /etc/caddy/restopos.caddy <<CADDY
# RestoPOS — deploy/install.sh yaratgan
$SITE {
	encode gzip
	request_body {
		max_size 25MB
	}
	handle /media/* {
		root * $APP/backend
		file_server
	}
	handle {
		reverse_proxy 127.0.0.1:$PORT
	}
}
CADDY
cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-restopos
grep -q "import /etc/caddy/restopos.caddy" /etc/caddy/Caddyfile || printf '\nimport /etc/caddy/restopos.caddy\n' >> /etc/caddy/Caddyfile
if caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/tmp/caddy-check.log 2>&1; then
  systemctl reload caddy
else
  cp /etc/caddy/Caddyfile.bak-restopos /etc/caddy/Caddyfile
  cat /tmp/caddy-check.log | tail -5
  die "Caddy sozlamasi xato — eski holatga qaytarildi (eski saytlar ishlayapti)"
fi

say "9/9 Tekshiruv"
for i in $(seq 1 20); do curl -fs -o /dev/null -H "Host: $BASE" http://127.0.0.1:$PORT/healthz/ && break; sleep 1; done
curl -fs -o /dev/null -H "Host: $BASE" http://127.0.0.1:$PORT/healthz/ || { journalctl -u restopos -n 30 --no-pager; die "Sayt ishga tushmadi (yuqoridagi log)"; }
code=$(curl -s -o /dev/null -w "%{http_code}" "http://namuna.$BASE/admin/" || true)
echo "   namuna.$BASE/admin/ → HTTP $code"
cat <<DONE

$(printf '\033[1;32m')TAYYOR!$(printf '\033[0m')  Kirish telefoni: +998901234567 (kod ekranda chiqadi — SMS ulanmaguncha)
  Namuna restoran:  http://namuna.$BASE/admin/
  Lazzat:           http://lazzat.$BASE/admin/
  Sayt (mijozlar):  http://namuna.$BASE/
  Platforma (HQ):   http://$BASE/hq/
Yangilash (GitHub'ga push qilgandan keyin) — xuddi shu buyruq.
Log: journalctl -u restopos -f
DONE
