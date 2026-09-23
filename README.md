# RestoPOS — restoran/kafe/fast-food uchun yagona boshqaruv platformasi

Bitta kod bazasi, har restoran uchun alohida ma'lumotlar bazasi sxemasi, yoqib-o'chiriladigan modullar,
telefon/planshet/kompyuter/TV uchun moslashuvchan sayt va "qora oynasiz" boshqaruv paneli.

**Operatsion zanjir (hammasi ulangan):** taomnoma → tex-karta (gramm/ml) → **tannarx** (bozorlik narxidan avtomatik) →
**kassa** (savdo, smena, Payme/Click) → **ombor** kamayadi → **P&L** (daromad − tannarx − oylik − chiqim = sof foyda) →
**oylik** (HR: smena, davomat, hisob) → **vazifalar** (muammo → dalil → tasdiq) → Telegram bildirishnomalar.

```
restopos/
├── backend/                 Django 5 + Django Ninja + django-tenants + Celery
│   ├── config/              sozlamalar (base/dev/prod), urls (tenant) + urls_public (platforma)
│   ├── public/              public sxema: Tenant, Domain, Plan; create_tenant, bootstrap_dev buyruqlari
│   ├── core/                User (telefon+OTP, PIN), Role/ruxsatlar, Branch, Membership, AuditLog, Device,
│   │                        modul registri (core/modules.py), hodisa shinasi (core/events.py), presetlar
│   ├── modules/
│   │   ├── catalog/         taomnoma: kategoriya, taom (uz/ru/en), narx/tannarx/marja, modifikatorlar,
│   │   │                    filial narxlari, Excel import, qoralama → e'lon (MenuVersion snapshot)
│   │   ├── cms/             sayt: SiteSettings (tema, yetkazish, tillar, SEO), SiteSection (bo'limlar), Media
│   │   ├── tasks/           vazifalar va muammolar: Kanban, muammo turlari (SLA, dalil, tasdiq), bosqichlar, tarix, takroriy
│   │   ├── inventory/       ombor va tannarx: xomashyo (kg/l/dona), kirim (o'rtacha/oxirgi narx), tex-karta (g/ml, chiqindi %),
│   │   │                    tannarx → Product.cost avtomatik, savdoda kamayish, inventarizatsiya, kam qoldiq hodisasi
│   │   ├── pos/             kassa: menyu, savat, chegirma, to'lov usullari, smena (naqd farqi), bugungi cheklar, chek chop etish
│   │   ├── payments/        Payme Merchant API (JSON-RPC) + Click SHOP API (Prepare/Complete) — restoran o'z kalitlari bilan
│   │   ├── hr/              xodimlar: lavozim, maosh turi (oylik/soat/smena/%), smena jadvali, davomat, oylik (qoralama→tasdiq→to'landi)
│   │   └── finance/         P&L, kunlik/soatlik savdo, top taomlar, menyu muhandisligi, to'lov usullari, chiqimlar, Excel eksport, MB kurslari
│   ├── api/                 /api/v1 (tenant) va public API (tariflar, presetlar, ro'yxatdan o'tish)
│   ├── integrations/        sms (console | eskiz), telegram (Bot API: xabar, webhook, /vazifalar /keldim /ketdim), currency (cbu.uz)
│   ├── website/             restoran sayti (Django shablon + HTMX), TV menyu-taxtasi, PWA manifest,
│   │                        platforma landing + signup, /admin/ (Vue SPA build shu yerdan beriladi)
│   └── tests/               pytest: izolyatsiya, token, modul o'chirish, catalog, sayt, signup
├── frontend/                pnpm workspace
│   ├── packages/tokens      dizayn-tokenlar (light/dark × telefon/planshet/kompyuter/TV)
│   ├── packages/ui          UI komponentlar (Button, Input, Table inline-tahrir, Drawer, Dropzone, Toast …)
│   ├── packages/api         API mijoz (JWT, Idempotency-Key, 401 → login)
│   └── apps/admin           boshqaruv paneli: Vue 3 + Vite + Pinia + vue-router (+ vuedraggable)
├── infra/                   Dockerfile.backend, nginx.conf
├── docker-compose.yml       db, redis, backend, worker, beat (+ minio, frontend profillari)
├── Makefile · .env.example · .github/workflows/ci.yml
```

## Tez boshlash (5 daqiqa)

### A) Docker bilan (eng oson)

```bash
cp .env.example .env
docker compose up -d            # db + redis + backend + worker + beat
# birinchi ishga tushishda bootstrap_dev avtomatik: tariflar, platforma, demo restoran "Lazzat"
```

Ochish:

| Nima | Manzil |
|---|---|
| Demo restoran sayti | http://lazzat.localhost:8000 |
| Boshqaruv paneli | http://lazzat.localhost:8000/admin/ |
| TV menyu-taxtasi | http://lazzat.localhost:8000/tv/menu-board/ |
| Platforma sayti + ro'yxatdan o'tish | http://localhost:8000 → /signup/ |
| API hujjati (Swagger) | http://lazzat.localhost:8000/api/v1/docs |
| Django admin (texnik) | http://lazzat.localhost:8000/django-admin/ |

> `*.localhost` subdomenlari Chrome/Firefox/Edge'da avtomatik 127.0.0.1 ga boradi. Safari yoki curl uchun
> `/etc/hosts` ga `127.0.0.1 lazzat.localhost` qatorini qo'shing.

**Kirish:** telefon `+998901234567` → "Kod olish" → dev rejimda kod javobning o'zida (`dev_code`) va ekranda
ko'rsatiladi (SMS_PROVIDER=console). Prod'da Eskiz orqali SMS ketadi.

### B) Docker'siz (lokal Python + Node)

```bash
# talab: Python 3.11+, Node 20+, PostgreSQL 16, Redis
make setup                       # .venv, pip, pnpm, .env
source .venv/bin/activate
make bootstrap                   # migrate_schemas + tariflar + demo restoran
make build                       # admin panelni yig'ish (frontend → backend/website/static/admin)
make run                         # http://lazzat.localhost:8000
```

Frontend'ni jonli (hot reload) o'zgartirish: `.env` ga `VITE_DEV=1` yozing, `make web` (5173) va `make run`.
`/admin/` endi Vite dev-serverdan yuklanadi; API so'rovlari :8000 ga proxy qilinadi.

## Yangi restoran qo'shish

```bash
make tenant NAME="Chopar" SLUG=chopar PHONE=+998901112233 PRESET=fast_food
# → chopar.localhost, alohida PostgreSQL sxemasi, egasi (owner) roli, 1-filial, preset bo'yicha modullar va sayt bo'limlari
```
Yoki brauzerda: http://localhost:8000/signup/ (public API `POST /api/v1/signup`).

Presetlar: `fast_food`, `cafe`, `restaurant`, `cloud_kitchen` (`core/presets.py`) — modullar to'plami, tema, sayt bo'limlari.

## Arxitektura qisqacha

- **Multi-tenant:** `django-tenants`. `public` sxemada Tenant/Domain/Plan; har restoran o'z sxemasida
  (`Tenant.auto_create_schema`). Domen → sxema `TenantMainMiddleware` orqali. Keyinchalik bitta restoranni
  alohida serverga ko'chirish — `pg_dump -n <schema>` bilan.
- **Modullar:** `backend/modules/<code>/module.json` (kod, nom uz/ru/en, versiya, bog'liqliklar, ruxsatlar, nav,
  sozlama sxemasi). `Tenant.enabled_modules` — o'chirilgan modul: API 404 + nav'da ko'rinmaydi + hodisalari
  o'tkazib yuboriladi. Rejalashtirilgan (hali yozilmagan) modullar `core/modules.py:PLANNED_MODULES` da —
  panelning "Modullar" sahifasida "tez kunda" sifatida ko'rinadi.
- **Hodisa shinasi:** `core/events.py` — `emit("tenant.created", …)`, `@on("catalog.published")`. Modullar bir-birini
  import qilmaydi, faqat hodisa orqali gaplashadi.
- **Ruxsatlar:** `modul.amal` kodlari, `modul.*` va `*` (egasi). 7 tizim roli har restoranda avtomatik.
- **Auth:** telefon + OTP → JWT (`sch` claim = sxema; boshqa restoran tokeni ishlamaydi). PIN kassaga (2-bosqich).
- **Yuklamaga bardosh:** Redis kesh (tenant-aware kalitlar), `Idempotency-Key` (takroriy POST xavfsiz),
  `X-Request-Id`, Celery navbatlari `critical / default / bulk`, `tenant_task` dekoratori.
- **Sayt:** 4 ekran sinfi (≤600 telefon · 601–1024 planshet · 1025–1920 kompyuter · ≥1921 yoki `[data-density=tv]` TV),
  light/dark tokenlar, HTMX menyu filtri, TV taxtasi avtomatik aylanadi (pult shart emas), PWA manifest.
- **Kelajak:** Capacitor (iOS/Android) va Telegram bot shu API'ni ishlatadi — `packages/api` mijoz tayyor.

## API (asosiylari)

```
POST /api/v1/auth/otp            {phone}            → dev: {dev_code}
POST /api/v1/auth/verify         {phone, code}      → {token, me}
GET  /api/v1/me · PATCH /api/v1/me
GET/PUT /api/v1/modules · GET /api/v1/permissions · PUT /api/v1/tenant
GET/POST/PUT/DELETE /api/v1/branches · /roles · /users · GET /api/v1/audit · GET /api/v1/dashboard/summary
GET/POST/PUT/PATCH/DELETE /api/v1/catalog/categories · /products · /modifier-groups
POST /api/v1/catalog/products/bulk · /reorder · /{id}/image · /{id}/branch-price
POST /api/v1/catalog/import (Excel) · POST /api/v1/catalog/publish · GET /api/v1/catalog/versions
GET  /api/v1/catalog/published   (ommaviy, kesh)
GET/PUT /api/v1/cms/settings · /sections · /media · GET /api/v1/cms/public
GET  /api/v1/tasks/meta · /board · /tasks · /stats
POST /api/v1/tasks/tasks · /tasks/{id}/move · /submit · /approve · /reject · /archive
POST /api/v1/tasks/tasks/{id}/attachments?kind=photo|proof · /comments · /steps · PATCH /tasks/steps/{id}
GET  /api/v1/tasks/tasks/{id}/activity · CRUD /tasks/columns · /categories · /recurrences (+ /recurrences/run)
GET  /api/v1/inventory/summary · /ingredients · /recipes · /recipes/{product_id} (PUT — tannarx qayta hisoblanadi) · /movements
POST /api/v1/inventory/purchases (kirim → narx va qoldiq) · /ingredients/{id}/adjust (inventarizatsiya) · /recipes/recompute
GET  /api/v1/pos/menu · /summary · /orders · /shift · POST /pos/orders · /orders/{id}/pay · /cancel · /shift/open · /shift/{id}/close
POST /api/v1/payments/payme (Payme Merchant API) · /payments/click/prepare · /click/complete · /payments/link · GET/PUT /payments/settings
GET  /api/v1/hr/meta · /employees · /employees/{id}/card · /shifts · /attendance · /payroll
POST /api/v1/hr/employees · /shifts · /shifts/copy-week · /attendance/check-in · /check-out · /payroll/compute · /payroll/{id}/status
GET  /api/v1/finance/pnl · /dashboard · /export.xlsx · /expenses · /categories · /rates (cbu.uz) · POST /finance/expenses
POST /api/v1/telegram/set-webhook · /telegram/webhook (Bot API)
public: GET /api/v1/plans · /presets · /modules · POST /api/v1/signup
```
Excel import ustunlari: `kategoriya | nom_uz | nom_ru | nom_en | narx | tannarx | tavsif_uz | og'irlik | kkal | sku`.

## Vazifalar va muammolar (boshqaruv markazi)

Bitta joyda: **muammo → vazifa → bajaruvchi → dalil → nazoratchi tasdig'i → arxiv**. Xalqaro amaliyotdan olingan:
Andon (har xodim muammoni ko'tara oladi), Kanban + WIP chegarasi, HACCP/CAPA (tuzatuvchi chora + dalil),
SLA va eskalatsiya, "definition of done" — foto-dalilsiz yopilmaydi.

* **Muammo ochish:** ofitsiant telefonda singan stulni suratga oladi → tur ("Mebel / Jihoz") tanlanadi →
  tizim SLA bo'yicha muddat, standart bosqichlar va bo'lim boshlig'ini nazoratchi qilib qo'yadi.
* **Kanban:** Yangi · Jarayonda · Tekshiruvda · Bajarildi. Ustunlarni egasi o'zi qo'shadi/nomlaydi/ko'chiradi
  (WIP chegarasi bilan). Kartani sudrab ko'chirish — qoidalar buzilsa tizim ruxsat bermaydi.
* **Dalil (majburiy):** `requires_proof` bo'lsa, bajarilgan ish rasmisiz "Tekshiruvda"ga o'tmaydi.
* **Tasdiq:** `requires_approval` bo'lsa, "Bajarildi" holatini faqat nazoratchi (yoki `tasks.approve` ruxsati bor
  xodim) qo'ya oladi — bajaruvchi o'z ishini o'zi yopolmaydi. Rad etish sabab bilan qaytaradi va `rework_count` oshadi.
* **Tarix:** har harakat (kim, qachon, nimadan nimaga) yoziladi — bahs uchun joy qolmaydi.
* **Takroriy ishlar:** kunlik sanitariya, haftalik inventarizatsiya — Celery beat har kuni 06:00 da ochadi;
  kechikkanlar har soatda nazoratchiga eskalatsiya bo'ladi (`tasks.overdue` hodisasi).
* **Ko'rinishlar:** Kanban · Ro'yxat · Kalendar · Mening vazifalarim · Muammolar · Arxiv; statistika: holat donuti,
  bo'limlar va ustuvorlik kesimi, o'rtacha bajarish vaqti, qaytarilgan ishlar ulushi (sifat ko'rsatkichi).
* **Ruxsatlar:** `tasks.view` (o'ziniki) · `tasks.view_all` · `tasks.create` (har bir xodimda bor — Andon) ·
  `tasks.edit` · `tasks.assign` · `tasks.approve` · `tasks.admin` · `tasks.delete`.

## Tannarx qanday hisoblanadi (food cost)

1. **Xomashyo** bazaviy birlikda: kg / l / dona, narx — so'm/birlik (masalan, go'sht 95 000 so'm/kg).
2. **Kirim (bozorlik)** kiritilganda narx yangilanadi (sozlama: *o'rtacha tortilgan* yoki *oxirgi*), qoldiq oshadi.
3. **Tex-karta**: taomga nechta **gramm / ml / dona** ketadi + chiqindi % (tozalash, pishirish) + necha porsiya chiqadi.
4. Tannarx = Σ(miqdor × narx × (1 + chiqindi%)) / porsiya → **Product.cost** avtomatik yoziladi; marja va food cost % ko'rinadi.
5. Xomashyo narxi o'zgarsa — shu xomashyo bor **barcha taomlar** darhol qayta hisoblanadi.
6. Kassada sotilganda tex-karta bo'yicha ombordan yechiladi; qoldiq minimaldan tushsa — `inventory.low_stock` → vazifa ochiladi.

## Sof foyda qanday hisoblanadi (P&L)

Daromad (to'langan cheklar) − Tannarx (chek qatorlaridagi tannarx snapshoti) = **Yalpi foyda**
− Mehnat (HR oyliklari, davrga proporsional) − Chiqimlar (ijara, kommunal, marketing…) = **Sof foyda**.
Ko'rsatkichlar: food cost % (maqsad ≤ 32), mehnat % (≤ 25), prime cost % (≤ 60), zararsizlik nuqtasi.
Menyu muhandisligi: har taom Yulduz / Ot / Jumboq / It — aniq tavsiya bilan.

## Real integratsiyalar

| Xizmat | Qanday ishlaydi | Kerak |
|---|---|---|
| **Payme** | Merchant API (JSON-RPC 2.0): Check/Create/Perform/Cancel/CheckTransaction/GetStatement, Basic auth | merchant ID + key (Hisobotlar → To'lov API) |
| **Click** | SHOP API: Prepare/Complete, md5 imzo tekshiruvi | service_id, merchant_id, secret key |
| **Telegram** | Bot API: xodim /start → telefon ulashadi → vazifa/tasdiq/kechikish xabarlari; /vazifalar, /keldim, /ketdim | `TELEGRAM_BOT_TOKEN`, `POST /api/v1/telegram/set-webhook` |
| **Eskiz SMS** | OTP kirish | `SMS_PROVIDER=eskiz`, `ESKIZ_*` |
| **MB kurslari** | cbu.uz ochiq JSON, 6 soat kesh | kalit shart emas |

Kalit kiritilmaguncha tizim to'xtab qolmaydi: Telegram xabarlari logga yoziladi, Payme/Click havolasi "kalit kiritilmagan" deb aytadi.

## Test va sifat

```bash
make test        # pytest (PostgreSQL kerak; POSTGRES_* .env dan)
make lint        # ruff + vue-tsc
```
CI (`.github/workflows/ci.yml`): backend testlari Postgres xizmati bilan, frontend typecheck + build.

## Prod'ga chiqarish (qisqa)

1. `.env`: `DJANGO_SETTINGS_MODULE=config.settings.prod`, kuchli `DJANGO_SECRET_KEY`/`JWT_SECRET`,
   `PLATFORM_DOMAIN=restopos.uz`, `ALLOWED_HOSTS=.restopos.uz`, `SMS_PROVIDER=eskiz` + `ESKIZ_*`, S3/MinIO `AWS_*`.
2. DNS: `restopos.uz` va `*.restopos.uz` → server. Wildcard TLS (`certbot`, DNS-01).
3. `docker compose -f docker-compose.yml up -d` + `infra/nginx.conf`. Backend `gunicorn`, worker, beat.
4. `python manage.py migrate_schemas` har relizda; yangi modul → `module.json` + `TENANT_APPS` + migratsiya.

## Hali yo'q (halol ro'yxat)

- **Fiskal chek (Soliq onlayn-kassa)** — `fiscal` moduli: `pos.order_paid` hodisasini tinglab, ishonchli fiskal provayder API'siga
  yuboradi (IKPU kodi `Product.ikpu_code` da tayyor). Provayder shartnomasi kerak.
- **KDS (oshxona ekrani)**, stollar/bron, yetkazib berish (kuryer ilovasi), CRM/bonus (mijoz telefoni kassada allaqachon yig'iladi),
  o'qitish (video/test), Telegram Mini App buyurtma, Capacitor ilova — reja bo'yicha keyingi bosqichlar.
- Uzum to'lov API (Payme/Click namunasi bo'yicha qo'shiladi).
