# Mirza Bot — Python Rewrite (`rewrite/python`)

Full rewrite of the PHP mirzabot platform: **aiogram 3 · SQLAlchemy 2 async ·
PostgreSQL (JSONB) · APScheduler · aiohttp** — plugin-first registry keyed
`(kind, name, revision)` so panels, gateways, jobs and future addons drop in
without touching core.

## Layout

```
src/mirza/
├── bot.py               dispatcher assembly, webhook/polling entry
├── server.py            production process: aiohttp + scheduler
├── config/              pydantic-settings (.env)
├── contracts.py         typed plugin contracts (PanelAdapter, PaymentGateway, Job)
├── registry/            plugin-first registry (kind,name,revision)
├── models/              all legacy tables as ORM models (+JSONB upgrades)
├── db/                  async engine/session
├── panels/              12 backend adapters + ManagePanel-equivalent service
├── payments/            7 gateways + wallet ledger + order lifecycle
├── jobs/                16+1 APScheduler jobs (legacy cronbot/*.php)
├── handlers/
│   ├── user/            menu, buy flow, my-services, wallet/trial/wheel/referral
│   └── admin/           stats, panels, products, users, broadcast, manual sell
├── api/                 REST (miniapp/users/products/payments/settings...),
│                        payment webhooks, /sub proxy, /webhook, white-label
├── routes/webpanel.py   session-based web admin panel
├── i18n/                fa/en/ru/zh
└── whitelabel           via api/whitelabel.py + botsaz table
alembic/                 async migrations
scripts/install.sh       systemd+Caddy installer with webhook secret
```

## Run

```bash
uv venv .venv && uv pip install --python .venv/bin/python .
cp .env.example .env    # fill MIRZA_API_KEY, MIRZA_ADMIN_NUMBER, ...
.venv/bin/alembic upgrade head
.venv/bin/python -m mirza.server          # prod (webhook + scheduler)
```

The upstream Mini App React bundle is served at `/app/` — it lives in this
branch (`app/`, `index.php` converted to `index.html`) and talks to the new
backend through the legacy-compatible action API (`/api/miniapp`).

Dev/tests:

```bash
.venv/bin/pytest tests/ -q     # 20 tests: unit, integration, live-server e2e
```

See `PARITY.md` for the feature-by-feature mapping to the legacy PHP and
`docs/CONFIGURATION.md` for the full operator configuration guide
(env layer vs runtime DB settings).
