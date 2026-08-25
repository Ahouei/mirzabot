# Mirza Bot — Python Platform

<div align="center">

# 🤖 Mirza Bot

### A modern Telegram-first VPN sales platform — fully automated, fully auditable.

<p>
  <a href="https://github.com/Ahouei/mirzabot/tree/rewrite/python">
    <img src="https://img.shields.io/badge/branch-rewrite%2Fpython-informational?style=for-the-badge&logo=github" alt="Branch"/>
  </a>
  <a href="https://github.com/Ahouei/mirzabot/stargazers">
    <img src="https://img.shields.io/github/stars/Ahouei/mirzabot?style=flat-square&color=f5c518" alt="Stars"/>
  </a>
  <a href="https://github.com/Ahouei/mirzabot/network/members">
    <img src="https://img.shields.io/github/forks/Ahouei/mirzabot?style=flat-square" alt="Forks"/>
  </a>
  <a href="https://github.com/Ahouei/mirzabot/blob/rewrite/python/LICENSE">
    <img src="https://img.shields.io/badge/license-AGPL--3.0-orange?style=flat-square" alt="License"/>
  </a>
  <a href="https://github.com/Ahouei/mirzabot/blob/rewrite/python/tests">
    <img src="https://img.shields.io/badge/tests-35%20passed-brightgreen?style=flat-square&logo=pytest" alt="Tests"/>
  </a>
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  </a>
  <a href="https://aiogram.dev/">
    <img src="https://img.shields.io/badge/aiogram-3-2CA5E0?style=flat-square&logo=telegram&logoColor=white" alt="aiogram"/>
  </a>
  <a href="https://www.postgresql.org/">
    <img src="https://img.shields.io/badge/PostgreSQL-JSONB-336791?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL"/>
  </a>
</p>

</div>

---

## 📚 Table of Contents

- [Overview](#-overview)
- [Supported Panels](#-supported-panels)
- [Payment Gateways](#-payment-gateways)
- [Architecture](#-architecture)
- [Features](#-features)
- [Installation](#-installation)
  - [Deploy with the installer](#deploy-with-the-installer)
  - [Manual setup](#manual-setup)
  - [Configuration layers](#configuration-layers)
- [Usage](#-usage)
  - [Admin commands](#admin-commands)
  - [Shop flow](#shop-flow)
- [Development](#-development)
- [Testing](#-testing)
- [Migration from legacy](#-migration-from-legacy)
- [Extensibility](#-extensibility)
- [License](#-license)

---

## ✨ Overview

**Mirza Bot** is the Python rewrite of the legacy PHP `mirzabot` — rebuilt as a clean, async, production-grade platform for selling VPN subscriptions end-to-end.

From purchase to payment to config creation and service management, everything is handled by the bot: customers get a clean **Telegram Mini App**, admins get a **web dashboard**, and every backend panel talks to Mirza through pluggable adapters.

> If the PHP version felt like a spreadsheet with buttons, this is the actual storefront.

---

## 🧩 Supported Panels

Each backend is a registered plugin keyed `(panel, name, revision)` — new panels drop in without touching core code.

| Panel | Auth | Notes |
|-------|------|-------|
| 🟢 **Marzban** | Bearer token (cached 1h) | Full node/system stats, base64 sub decoding |
| 🟢 **Marzneshin** | JWT | ms-expire timestamps, enable/disable endpoints |
| 🟢 **S-UI** | Session cookie | `apiv2/clients` batch operations |
| 🟢 **Hiddify** | Dashboard bearer | REST CRUD, subscription links |
| 🟢 **3x-ui / x-ui** | Cookie | inbound-based clients, traffic reset |
| 🟢 **Alireza / Sanaei** | Cookie | legacy single-inbound variant |
| 🟢 **WGDashboard** (WireGuard) | Cookie | peer management + keypair generation |
| 🟢 **MikroTik** (RouterOS v7) | REST login | PPP/Hotspot users, system resource stats |
| 🟢 **IBSng** | Form-encoded | ISP billing XML-RPC style |
| 🟢 **Rebecca** | Bearer | lightweight user CRUD |
| 🟢 **Pasarguard** | Marzban dialect | registered under its own name for panel pickers |
| 🟢 **Mirza Agent** | Bearer actions | agent-network panel API |

> Protocols: VLESS, VMess, Trojan, Shadowsocks, WireGuard, PPP — product-scoped inbounds/proxies per plan.

---

## 💳 Payment Gateways

| Gateway | Type | Verification |
|--------|------|-------------|
| 💳 **Zarinpal** | Online gateway | PG v4 request → StartPay redirect → verify (100/101 idempotent) |
| 💳 **Aqayepardakht** | Online gateway | create → transid verify, code-70 replay-safe |
| 🪙 **NowPayments** | Crypto | invoice → IPN webhook → double-check API status |
| 🪙 **Plisio** | Crypto | invoice → scheduler polls status until `completed` |
| 💫 **Telegram Stars** | Native XTR | `createInvoiceLink` → pre_checkout ack → `successful_payment` settle |
| 🪙 **CubePay (TRON)** | Crypto | HMAC-signed callback + authority verify, customer-paid fee support |
| 🇮🇷 **IranPay** | Online gateway | factor create + scheduler status poll |
| 💵 **Card-to-Card** | Manual | receipt + admin approval |

> Every payment settles through an **atomic `claim_paid()`** guard — replayed callbacks never double-credit the wallet or double-deliver a config.

---

## 🏗 Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                    Mirza Python Platform                     │
├─────────────┬─────────────┬─────────────┬───────────────────┤
│  aiogram 3  │  SQLAlchemy │ APScheduler │     aiohttp       │
│  dispatcher │  2 async    │  (cron jobs)│  API + webhook    │
├─────────────┴─────────────┴─────────────┴───────────────────┤
│  Plugin registry  (kind, name, revision)                     │
│  Panels ── Payments ── Jobs ── Addons ── Whitelabel          │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL (prod) ── JSONB settings ── SQLite (dev/test)    │
│  alembic migrations ── append-only wallet ledger             │
└─────────────────────────────────────────────────────────────┘
```

**Key contracts** (`src/mirza/contracts.py`):

- `PanelAdapter` — 8 async methods: create / get / modify / remove / revoke / reset / enable / stats
- `PaymentGateway` — `create_payment` + `verify_payment` (idempotent claim)
- `Job` — cron-scheduled with `JobContext` (session factory + report channel)
- `Registry` — plugin-first, revisioned, runtime toggleable

---

## ⚙️ Features

### 🛒 Sales & configuration
- ✅ Automated VPN sales with per-product config creation
- ✅ Trial accounts for new users (`/usertest` flow)
- ✅ Trial expiry auto-disable + daily cleanup
- ✅ QR codes, subscription links, custom name generation
- ✅ On-hold configs (start on first connect, not on buy)

### 👤 Customer experience
- ✅ **Telegram Mini App** (React bundle served at `/app/`, legacy-compatible API)
- ✅ View & manage purchased services: renew, buy extra volume/time, change location, revoke sub links
- ✅ Wallet + balance with **append-only ledger** (`balance_ledger` table)
- ✅ Referral links + commission tracking
- ✅ Phone verification + forced channel membership
- ✅ Support tickets with departments and admin replies

### 📈 Growth & marketing
- ✅ Affiliate system + cashback per gateway
- ✅ Discount / gift codes with usage limits
- ✅ Lucky wheel (daily, admin-configured prizes)
- ✅ Lottery system + daily report to Telegram topics
- ✅ Agent / reseller tiers (`agent`, `administrator`, customer)

### 🛠️ Administration
- ✅ Web admin panel (`/panel/`): users, invoices, payments, panels, products, settings
- ✅ Multiple admins, bcrypt(12) passwords, session regeneration
- ✅ Full bot-text customization from the admin menu
- ✅ Configurable username-generation methods
- ✅ Daily backups (mysqldump / pg_dump / sqlite) to a report topic
- ✅ Node + panel uptime monitors
- ✅ Expiry / volume / on-hold / test-account cleanup cron jobs
- ✅ Broadcast queue with rate-limited delivery

### 🔐 Security upgrades over the PHP version
- ✅ **Webhook secret validation** on every Telegram entrypoint
- ✅ **Fernet-encrypted panel passwords** at rest (`MIRZA_SESSION_SECRET`)
- ✅ **Idempotent payment claiming** (`UPDATE ... WHERE status='Unpaid'` guard)
- ✅ **No unauthenticated cron endpoints** (in-process scheduler)
- ✅ **Timing-safe token compares** (`hmac.compare_digest`)
- ✅ **bcrypt 12** for admin sessions

---

## 🚀 Installation

### Deploy with the installer

One-command setup on a fresh Debian/Ubuntu host (needs `curl`, `uv` or `python3`):

```bash
export BOT_TOKEN="123456:AA..."          # your bot token from @BotFather
export ADMIN_ID="123456789"              # your Telegram user id
export DB_URL="postgresql+asyncpg://mirza:mirza@localhost/mirza"

sudo bash scripts/install.sh myshop.example.com
```

The installer provisions:
- Caddy reverse proxy + automatic HTTPS
- PostgreSQL schema via `alembic upgrade head`
- systemd service with auto-restart
- Telegram webhook registration with a generated secret

### Manual setup

```bash
git clone https://github.com/Ahouei/mirzabot.git
cd mirzabot
git checkout rewrite/python

uv venv .venv && uv pip install --python .venv/bin/python .

cp .env.example .env
# edit .env (bot token, admin id, DB URL, domain, session secret)

.venv/bin/alembic upgrade head
.venv/bin/python -m mirza.server
```

### Configuration layers

Configuration is two-layered — no code edits needed to customize a deployment:

| Layer | What | Where |
|-------|------|-------|
| **Deploy-time** | Bot token, admin id, DB URL, domain, session secret | `.env` / environment |
| **Runtime** | Gateways, panels, plans, shop text, report topics, wheel prizes | Web panel + admin commands |

Full operator guide: [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)

---

## 💻 Usage

### Admin commands

| Command | Purpose |
|---------|---------|
| `/stats` | live shop metrics (users, services, revenue, panels) |
| `/addpanel name\|type\|url\|user\|pass [inbound]` | register a backend panel |
| `/panels` | list panels with status toggle |
| `/addproduct code\|name\|price\|volume_gb\|days\|location` | add a plan |
| `/products` | list plans |
| `/finduser <id_or_username>` | inspect a customer |
| `/block <id>` / `/unblock <id>` | ban control |
| `/broadcast` | queue a message for all users |
| `/payments` | recent transactions |
| `/sell <user_id> <product_code>` | manual config sale |
| `/giftcode <code> <limit>` / `/giftcodes` | discount codes |
| `/addcat <title>` / `/cats` | categories |
| `/addhelp name\|text` / `/helplist` | tutorials |
| `/addchannel @handle` / `/lockchannel @handle` | forced channel join |
| `/makeagent <id>` / `/agents` / `/agentrequests` | reseller management |
| `/addbalance <id> <±amount>` | wallet adjustments (ledgered) |
| `/wheelprizes 0,5000,10000` | lucky wheel prizes |
| `/paycheck` | gateway health without spending money |
| `/lang fa\|en\|ru\|zh` | language switch |

### Shop flow

```
/start → menu
  ↓
🛒 Buy → category → plan → confirm → gateway (or wallet)
  ↓
payment → atomic claim → config created on panel
  ↓
config delivered → /sub/<token> proxy keeps the link alive
  ↓
auto expiry warnings → disable → renew / extend / extra volume
```

---

## 🔧 Development

### Project layout

```
src/mirza/
├── bot.py                 # dispatcher assembly, webhook/polling
├── server.py              # production entry: aiohttp + APScheduler
├── config/                # pydantic-settings (.env)
├── contracts.py           # typed plugin contracts
├── registry/              # plugin-first registry (kind,name,revision)
├── models/                # 30 tables (legacy parity + ledger)
├── db/                    # async engine/session
├── panels/                # 12 adapters + PanelService (ManagePanel port)
├── payments/              # 7 gateways + wallet + rates + Stars
├── jobs/                  # 17 scheduler jobs (legacy cronbot parity)
├── handlers/
│   ├── user/              # menu, buy, services, misc, extra
│   └── admin/             # stats, manage, paycheck
├── api/                   # REST, webhooks, sub proxy, white-label
├── routes/webpanel.py     # web admin panel
├── whitelabel/            # child-bot shop handlers
└── i18n/                  # fa/en/ru/zh (2,381 legacy strings each)
alembic/                   # migrations
tests/                     # 35 tests (unit, integration, e2e, mock-edge)
tools/import_legacy.py     # MySQL dump → new schema importer
scripts/install.sh         # Caddy + systemd installer
docs/CONFIGURATION.md      # operator guide
PARITY.md                  # feature matrix vs legacy PHP
```

### Local dev

```bash
uv venv .venv && uv pip install --python .venv/bin/python '.[dev]'
cp .env.example .env
.venv/bin/python -m pytest tests/ -q
```

---

## 🧪 Testing

| Layer | Proof |
|-------|-------|
| Unit / smoke | 16 tests: registry, i18n, models, dispatcher, API, CubePay HMAC, Stars math |
| Integration | Real file-backed SQLite: alembic up/down, ORM round-trips, wallet ledger, claim idempotency, fake-panel PanelService |
| E2E live server | aiohttp boot: miniapp token → actions, sub proxy, panel login, webhook secret, static bundle |
| Mock-edge | All 8 gateways driven through real pipeline with recorded responses |
| Live demo | `scripts/live_demo.py` — full buy → deliver → extend → wallet cycle against a fake Marzban |

Run the full suite:

```bash
.venv/bin/python -m pytest tests/ -q
```

Run the live integration demo:

```bash
.venv/bin/python scripts/live_demo.py
```

---

## 🔄 Migration from legacy

Moving from the PHP bot? The rewrite ships `tools/import_legacy.py`:

```bash
# dry-run report first (nothing written)
python tools/import_legacy.py legacy.sql --dry-run

# then commit
python tools/import_legacy.py legacy.sql --commit
```

Maps `user`, `invoice`, `Payment_report`, `marzban_panel`, `product`, `Discount`, and the wide `setting` row into the new schema. Panel passwords are re-encrypted with your `MIRZA_SESSION_SECRET`.

---

## 🔌 Extensibility

Add a new backend without touching core:

```python
from mirza.contracts import PanelAdapter
from mirza.registry import register_plugin

@register_plugin("panel", "mypanel")
class MyPanel(PanelAdapter):
    name = "mypanel"
    async def create_user(self, username, **kw): ...
    async def get_user(self, username): ...
    async def modify_user(self, username, config): ...
    async def remove_user(self, username): ...
    async def revoke_sub(self, username): ...
    async def reset_usage(self, username): ...
    async def set_enabled(self, username, enabled): ...
    async def system_stats(self): ...
    async def close(self): ...
```

Import it from `mirza/plugins.py` (or an addon package) and it appears in panel pickers, the scheduler, and the admin UI.

---

## 📜 License

**GNU AGPL-3.0-or-later** — see [`LICENSE`](LICENSE).

If you run a modified copy as a service, you must share your source with users.

---

<div align="center">

Built with ❤️ for the mirzabot community.

</div>
