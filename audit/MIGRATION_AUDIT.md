# Mirza Bot — PHP → Python Migration Audit (Static Pass)

**Auditor role:** Senior software architect / technical PM / QA lead
**Date:** 2026‑08‑25
**Scope:** Static analysis only. No code executed, no dependencies installed, no PostgreSQL/panel/live endpoints hit. A separate dynamic/live‑run pass is recommended (see §9).
**Baseline (source of truth):** `origin/main` — PHP 8.2 + MySQL, 97 PHP files, ~63.6k LOC (~44.8k excluding the four language files).
**Rewrite under audit:** `origin/rewrite/python` — Python (aiogram + SQLAlchemy async + aiohttp), 89 `.py` files, ~20.5k LOC (**~8.0k LOC of application logic** excluding ~10.6k of i18n corpora).

> The rewrite branch is `rewrite/python`, not `rewrite`. Everything below refers to it.

---

## 1. Executive summary

The rewrite is a **well‑structured, genuinely more maintainable skeleton that is not yet feature‑complete and — critically — is broken on the one path the whole product exists for: taking money and delivering a config.** Architecturally it is a real improvement over the PHP monolith: a plugin registry for panels/payments/jobs, an ORM with real foreign keys and indexes, JSONB settings, Fernet‑encrypted panel passwords, idempotent payment claiming, and proper Telegram Mini‑App `initData` HMAC validation. If the goal were "a clean foundation to build on," it succeeds.

But measured against the actual instruction — **full feature parity with `main`** — it is roughly **half‑done, and the missing/broken half includes the revenue path.** Three independent defects each break online payments on their own:

1. **`PaymentService.settle_wallet_topup(...)` is called in four places but is never defined anywhere in the codebase.** Every wallet top‑up settlement — Zarinpal, IranPay, Plisio, NowPayments, card‑to‑card, and Telegram Stars — raises `AttributeError` at runtime.
2. **Paying for a *product* through any online gateway never provisions the product.** The bot's checkout (`buy.py::pay_gateway`) creates the payment order with no `invoice_id`, so the settlement logic treats a product purchase as a wallet top‑up (which then hits defect #1).
3. **The customer is never notified when a gateway payment settles** (`_notify_user(None, …)` is hard‑coded to `None`) and the admin **payment report is a no‑op placeholder** (`_report()` builds a value and discards it).

The single biggest risk is therefore **not** "some features are missing" — it is that **the money path looks finished (there are gateway modules, tests, a `PARITY.md` claiming ✅ everywhere) but does not work end‑to‑end, and the test suite is green because it never exercises the broken branch.** Anyone trusting the self‑reported parity matrix would ship a bot that accepts payments and hands out nothing.

Beyond payments, the admin surface is a fraction of the original (~25 mostly create‑and‑list commands vs. ~177 branches in `admin.php`; no multi‑admin support, no in‑bot text customization, no per‑panel pricing/inbound editing), several scheduled jobs are stubs or send to the wrong destination (expiry reminders go to an admin channel instead of the customer; the lottery job is absent; the gift job is `return None`), and a number of admin‑configurable settings are written but never read (lucky‑wheel prizes, gift‑code percentages).

**Verdict:** **Far off** for a drop‑in replacement of `main`. **Close** as an architectural foundation. Estimated **~55% weighted parity** (see §6 for methodology), but *functional* readiness of the core purchase flow is much lower than that number suggests. This should **not** replace `main` until at least the §8 "must‑fix" list is cleared and a dynamic pass confirms provisioning against real panels.

---

## 2. How this pass was conducted

- Both branches materialized as git worktrees and read directly.
- **Breadth‑first, risk‑weighted** (agreed scope): every functional area was inventoried and mapped; deep line‑level scrutiny was concentrated on the money path (purchase, payments, provisioning), scheduled jobs, auth, and the data model.
- Deep‑read: data model & migration, bot purchase flow, `panels/service.py`, `payments/service.py`, payment webhooks, wallet, middleware, webhook entry, admin handlers (`__init__.py` + `manage.py`), all scheduled jobs (`jobs/builtin.py`), the web panel, the REST/Mini‑App API, and user misc/menu handlers.
- Lighter / trusted‑pending‑verification (flagged honestly in §9): individual gateway internals (`stars.py`, `cubepay.py`), `extra.py` (tickets/tariff), most individual panel adapters (only `marzban.py` deep‑read), `whitelabel.py`, `backup.py`, `rates.py`.
- The rewrite's own `PARITY.md` was treated as a **claim to verify**, not evidence. Several of its ✅ entries are contradicted by the code (called out inline).

Where something is inferred rather than proven by reading, it is labelled as such.

---

## 3. Status legend

| Icon | Meaning |
|---|---|
| ✅ | Done — implemented; behaviour matches or reasonably improves on baseline |
| 🔧 | Done + improved — a deliberate, defensible improvement over `main` |
| ⚠️ | Partially done — present but incomplete / materially simplified / edge cases missing |
| 🐞 | Done but wrong — present but a concrete bug, logic error, or regression |
| 🔒 | Done but risky — works on paper but a security / data‑integrity / race / scale concern |
| ❌ | Missing — not implemented |

---

## 4. Feature parity inventory

IDs are stable (`F‑0xx`) for later reference. "Main behaviour" is the baseline requirement; "Status" is the rewrite's fidelity to it.

### 4.1 Purchase & provisioning

| ID | Feature | Main behaviour | Status | Notes (file:where) |
|---|---|---|---|---|
| F‑001 | Category browsing | Category → product drill‑down | ✅ | `buy.py::buy_start/cat_pick` |
| F‑002 | Product listing / selection | Products filtered by category/location | ✅ | `buy.py`, `api/miniapp.py::mini_services` |
| F‑003 | Location (panel) choice at checkout | User picks server location; per‑product `location` honoured | ⚠️ | Bot flow has **no** location pick; `buy.py::_default_panel` just grabs the first product whose `location != "/all"`. Mini‑App has a country filter. |
| F‑004 | Automated config creation on panel | Create user on selected panel, return config/sub | ✅ | `panels/service.py::create_user` (+ per‑adapter) |
| F‑005 | Wallet purchase | Deduct balance, then provision, atomically | 🐞 | `buy.py::pay_wallet` **provisions and commits the invoice before charging the wallet**; a failed charge only `rollback()`s an already‑committed session → free config. TOCTOU double‑spend (balance checked in `buy_confirm`, deducted later). |
| F‑006 | Online‑gateway product purchase | Pay via gateway → provision the product | 🐞 | **Broken.** `buy.py::pay_gateway` calls `create_order(...)` with no `invoice_id`; `payhooks.settle()` only provisions when `order.invoice_id` is set, else routes to wallet top‑up (which crashes, F‑022). Product `code` is discarded (used only in the description string). |
| F‑007 | Discount codes at checkout | Percent or fixed discount; usage limits; per‑product | 🐞 | `buy.py::discount_code` applies only `price_discount` (fixed); **`discount_percent` ignored**, `used_count` never incremented (usage limit unenforceable), `expires_at` not checked, `DiscountSell` (per‑product) unused. |
| F‑008 | One‑purchase‑per‑plan guard | `one_buy_status` blocks re‑buy | ⚠️ | Enforced in `api/miniapp.py::mini_purchase`; **not** in the bot `buy.py` path. |
| F‑009 | QR code for config import | QR image of sub/config | ❌ | No QR generation found in the rewrite. |
| F‑010 | Subscription link / `/sub` proxy | `sub/index.php` proxies sub content | 🔧 | `api/subproxy.py`; `subvip` rewrites to `/sub/{token}`. |
| F‑011 | Protocol / inbound‑based config | Product inbounds/proxies + `protocol` table | ⚠️ | Product `inbounds`/`proxies` passed through, but the legacy **`protocol` table is absent** from the model; protocol‑level config management is not ported. |

### 4.2 Service management ("my services")

| ID | Feature | Main behaviour | Status | Notes |
|---|---|---|---|---|
| F‑012 | View purchased services | List invoices with live panel data | ✅ | `services.py`, `api/miniapp.py::mini_invoices/mini_service` (ownership‑checked) |
| F‑013 | Renew / extend service | Add time (+ optional volume/usage reset) | ⚠️ | `service.py::extend`; volume math `base_vol − used + extra` is questionable and `service_time` semantics are inconsistent across the codebase (see F‑080). Needs dynamic verification. |
| F‑014 | Buy extra volume | Add GB to a live config, paid | ⚠️ | `service.py::extra_volume` modifies the panel, but payment/pricing linkage is thin. |
| F‑015 | Buy extra time | Add days to a live config, paid | ⚠️ | `service.py::extra_time`; same payment‑linkage caveat. |
| F‑016 | Change location (paid migration) | Recreate on new panel preserving remaining quota, remove old | 🐞 | `service.py::change_location` calls `create_user(new, data_limit=0, expire_ts=now)` → **dead, immediately‑expired config with zero volume**; remaining quota dropped. |
| F‑017 | Revoke subscription link | Rotate sub token | ✅ | `service.py::revoke_sub` → adapter `revoke_sub` |
| F‑018 | Config / sub retrieval | Re‑send config & sub link | ✅ | `services.py`, mini‑app |
| F‑019 | User‑initiated disable/enable | User can pause a service | ⚠️ | Partial; legacy `disorder`/`confirmdisorders` flow richer. |
| F‑020 | Cancel / delete service | `cancel_service` table + admin review | ⚠️ | Table exists; end‑to‑end flow not confirmed. |

### 4.3 Payments & wallet

| ID | Feature | Main behaviour | Status | Notes |
|---|---|---|---|---|
| F‑021 | Wallet balance & ledger | Balance column; ad‑hoc adjustments | 🔧 | `payments/wallet.py` adds an **append‑only `balance_ledger`** (auditable) — genuine improvement. |
| F‑022 | Wallet top‑up via gateway | Pay → credit balance | 🐞 | **`PaymentService.settle_wallet_topup` is undefined** (called at `payhooks.py:76,107`, `jobs/builtin.py:435`, `stars.py:160`). Every top‑up settlement raises `AttributeError`. |
| F‑023 | Card‑to‑card (manual) | Receipt upload → admin approve → credit | ⚠️ | `card2card.py` + `croncard` job + `admin/paycheck.py`; approval marker path present but incomplete and shares the broken settle path. |
| F‑024 | Zarinpal | PG v4 verify | ⚠️ | `payments/zarinpal.py` verify exists; settlement blocked by F‑006/F‑022 for the common paths. |
| F‑025 | Aqayepardakht | Code‑70 replay‑safe verify | ⚠️ | `payments/aqayepardakht.py`; same settlement caveat. |
| F‑026 | NowPayments | Crypto webhook + poll | ⚠️ | `payments/nowpayments.py` + poll job; settlement caveat. |
| F‑027 | Plisio | Crypto poll | ⚠️ | `payments/plisio.py` + poll job; settlement caveat. |
| F‑028 | IranPay | Factor poll | ⚠️ | `payments/iranpay.py` + `iranpay_poll` (legacy return‑in‑while bug fixed 🔧); settlement caveat. |
| F‑029 | CubePay (TRON) | HMAC callback + result page | 🔧 | `payments/cubepay.py` — signed callback, fee math, HTML result card; **unit‑tested offline** (real strength). Still funnels through the broken settle for top‑ups. |
| F‑030 | Telegram Stars | Invoice link, pre‑checkout, settlement | 🐞 | `payments/stars.py` builds invoices, but settlement calls the undefined `settle_wallet_topup` → crash. |
| F‑031 | Payment idempotency | Avoid double‑settlement | 🔧 | `claim_paid()` atomic `UPDATE … WHERE status='Unpaid'` — good. |
| F‑032 | Payment report → admin channel/topic | Rich report posted to report group | 🐞 | `payhooks._report()` is a **no‑op placeholder** (`_ = chat, kind, text`). Never sends. |
| F‑033 | User notification on payment | DM the buyer on success | 🐞 | `payhooks` calls `_notify_user(None, …)` — `bot` hard‑coded `None`, so the DM is silently dropped. |
| F‑034 | Pending‑payment expiry | Expire stale orders | ✅ | `payment_expire` job (fail after 1h) |

### 4.4 Bot UX & onboarding

| ID | Feature | Main behaviour | Status | Notes |
|---|---|---|---|---|
| F‑035 | `/start`, main menu, deep‑link | Menu + `ref_` capture | ✅ | `handlers/user/menu.py` |
| F‑036 | Language switch (fa/en/ru/zh) | Per‑user language | ✅ | `i18n/` + middleware |
| F‑037 | Accept‑rules gate | Must accept rules before use | ❌ | Legacy `acceptRules` gate not observed. |
| F‑038 | Forced channel membership | Multi‑channel mandatory join | 🔧→⚠️ | `middleware.py` enforces a **single** `channel_lock` setting; the multi‑row `channels` table is populated (`/addchannel`) but never enforced. `_check_member` strips `@` (likely mis‑resolves chat) and **fails open**. |
| F‑039 | Phone / number verification | `iran_number` gate blocks purchase until verified | ⚠️ | `/api/verify` sets `verify_status`, but **no enforcement** anywhere in the purchase path. |
| F‑040 | Ban / block enforcement | Blocked users can't act | ✅ | `AuthMiddleware` + mini‑app `blocked` check |
| F‑041 | FSM / step persistence | Step + scratch stored in DB (`Processing_value*`) | 🔒 | Purchase/top‑up/broadcast state kept in **process‑local `dict`s** (`buy._pending`, `misc._TOPUP`, `admin._BROADCAST`, `webpanel._SESSIONS`). Lost on restart; broken across workers/instances; races. |

### 4.5 Growth & marketing

| ID | Feature | Main behaviour | Status | Notes |
|---|---|---|---|---|
| F‑042 | Referral link + count | Show link, count referred | ✅ | `misc.py::affiliates`, `menu.py` captures `referrer_id` |
| F‑043 | Referral commission payout | Referrer earns commission on referred purchase | ❌ | Not implemented. `Affiliate.porsant_one_buy`, `reagent_report`, `status_commission` never used in purchase/settle. |
| F‑044 | Cashback rewards | Cashback on spend | ❌ | Only a hard‑coded `cashback = 0` in `jobs/builtin.py::_settle`. |
| F‑045 | Discount codes (admin) | Create % / fixed codes, limits | ⚠️ | `/giftcode` creates a `Discount` with `percent=0/price=0` → **inert** until edited via a web UI that doesn't expose it. |
| F‑046 | Gift codes | Redeemable credit codes; scheduled drops | ⚠️/🐞 | `/giftcodes` consumed‑count is **wrong** (`{g.code: g}` dict collapses many consumptions to ≤1). Scheduled `gift` job is `return None`. |
| F‑047 | Lottery (scheduled draw) | `cronbot/lottery.php` periodic draw | ❌ | No lottery job in `jobs/builtin.py` (header even says "16 jobs"; main has 17). |
| F‑048 | Lucky wheel (daily) | Daily spin, admin‑configured prizes | 🐞 | `misc.py::lucky_wheel` uses a **hard‑coded** `WHEEL_PRIZES`; the admin `/wheelprizes` setting is written but never read. |

### 4.6 Agent / reseller

| ID | Feature | Main behaviour | Status | Notes |
|---|---|---|---|---|
| F‑049 | Agent grant / revoke / list | Multiple agent levels | ⚠️ | `manage.py` sets a single `agent_level="a"`. |
| F‑050 | Agent request approval | User requests → admin approves | ⚠️ | `agentrequests`/`agentok#`; no user notification or panel grant on approval. |
| F‑051 | Agent types & pricing (n / n2) | Distinct reseller pricing tiers | ❌ | Not ported. |
| F‑052 | Agent expiry | Auto‑demote expired agents | ✅ | `expireagent` job (subject to `expire_at` semantics). |
| F‑053 | Agent panel provisioning | `mirza_agent.php` | ⚠️ | `panels/mirza_agent.py` adapter present; not deep‑verified. |

### 4.7 Support & content

| ID | Feature | Main behaviour | Status | Notes |
|---|---|---|---|---|
| F‑054 | Support contact | Show support handle | ✅ | `misc.py::support` |
| F‑055 | Ticketing via departments | Departmental tickets, tracking codes | ⚠️ | `extra.py` ticket flow + `Departman`/`support_message`; admin has add/list only (no delete/assign). |
| F‑056 | FAQ / tutorials browsing | Help entries by OS/category | ✅ | `menu` help + `manage.py` help CRUD |
| F‑057 | Tutorial media (photo/video) | Media‑rich tutorials | ⚠️ | `/addhelp` stores text only. |

### 4.8 Admin management

| ID | Feature | Main behaviour | Status | Notes |
|---|---|---|---|---|
| F‑058 | Stats dashboard | Rich financial/user stats | ⚠️ | `admin::stats` — counts + revenue only. |
| F‑059 | User management | Find/block/balance/limits | ⚠️ | find/block/unblock/addbalance only; no `maxbuyagent`/`changeloclimit`/`expireset`/verify mgmt. |
| F‑060 | Product CRUD | Full create/edit/delete + all fields | ⚠️ | `/addproduct` (pipe‑delimited) + list; **no edit/delete**; drops category/inbounds/proxies/agent_only/one_buy/reset. |
| F‑061 | Panel CRUD | Full editing incl. pricing/inbound/test/username/extend | ⚠️ | `/addpanel` + list + toggle only; **no edit**; per‑panel pricing/inbound/test‑account/`method_username`/extend not editable. |
| F‑062 | Category CRUD | Add/list/delete/reorder | ✅ | `manage.py` add/list/delete. |
| F‑063 | Discount / gift CRUD | Full management | ⚠️ | Create/list only; see F‑045/F‑046. |
| F‑064 | Channel management | Register + lock multiple | ⚠️ | add/list + single lock; multi‑channel not enforced (F‑038). |
| F‑065 | Department CRUD | Manage support departments | ⚠️ | add/list only. |
| F‑066 | Manual sell (`/sell`) | Admin gifts a real plan to a user | 🐞 | `manual_sell` provisions `data_limit=0` and ignores the product's volume/days; picks an arbitrary panel. |
| F‑067 | Broadcast | Text/media/pin/forward to all users, batched | ⚠️ | Text only; opens **one DB session per user in a loop** to mark targets (O(N) sessions). |
| F‑068 | Multiple admins + rule levels | `admin` table, permission levels | ❌ | `AdminGate` = "only primary admin passes" (`settings.admin_number`). `Admin` table/`rule` unused for bot gating. **Contradicts `PARITY.md` "Multiple admins ✅".** |
| F‑069 | In‑bot text/message customization | Edit any bot string from the bot | ❌ | No `settext`/`bottext` editing handler found — a headline `main` feature. |
| F‑070 | Username generation methods | Multiple configurable strategies | ⚠️ | `generate_username` supports only `random`/`number`. |
| F‑071 | Card‑number management | Add/remove/toggle payout cards | ❌ | `card_number` model exists; no admin handler. |
| F‑072 | Report‑topic configuration | Map report kinds → forum topics | ❌ | `topicid` model exists; no admin config UI. |
| F‑073 | Settings toggles | Dozens of operational flags | ⚠️ | Web panel exposes ~5 keys; most legacy toggles have no editing surface. |
| F‑074 | Payments report (`/payments`) | Recent payments list | ✅ | `admin::payments_report` |
| F‑075 | Lucky‑wheel prize config | Configure prizes | 🐞 | `/wheelprizes` writes `wheel_prizes`; wheel never reads it (F‑048). |

### 4.9 Scheduled jobs (cron)

`main` has **17** jobs; the rewrite header says "16" and ships 15 real + 1 stub.

| ID | Feature | Main behaviour | Status | Notes |
|---|---|---|---|---|
| F‑076 | Expiry reminders → user | DM the customer before expiry with renew buttons | 🐞 | `notifications` job only `ctx.send_report(...)` to an **admin channel**; the customer is never notified. Renewal‑reminder purpose defeated. |
| F‑077 | Volume warnings → user | DM at ≥80% usage | 🐞 | Same — `volumewarn` posts to the report channel, not the user. |
| F‑078 | Disable expired configs | Disable on panel + persist status | 🐞 | `disableconfig` disables on the panel but **never commits** `inv.status='disabled'` → change lost, re‑runs every tick. |
| F‑079 | Re‑activate / renew configs | Re‑enable renewed configs | ✅ | `activeconfig` (commits). |
| F‑080 | On‑hold activation | Activate on‑hold configs at first use | ⚠️ | Job exists but **no handler ever sets `status='on_hold'`**, and `_days_s(service_time)` mis‑reads an absolute timestamp as a day‑count. Feature effectively dead. |
| F‑081 | Trial cleanup | Remove expired trials | ✅ | `configtest` |
| F‑082 | Node uptime monitor | Alert on down nodes | 🐞 | `uptime_node` builds the adapter with `password_panel = password_panel_encrypted` (**not decrypted**) → auth fails; marzban‑only. |
| F‑083 | Panel uptime monitor | Alert on unreachable panels | ✅ | `uptime_panel` |
| F‑084 | Automatic backups | pg_dump/mysqldump/sqlite backup to admin | ⚠️ | `jobs/backup.py` present; not deep‑verified. |
| F‑085 | Daily status report | Rich nightly financial report | ⚠️ | `statusday` = new‑user + counts only. |

### 4.10 Web / HTTP surfaces

| ID | Feature | Main behaviour | Status | Notes |
|---|---|---|---|---|
| F‑086 | Web admin panel | Full CRUD admin (`panel/*.php`, ~90k bytes) | ⚠️ | `routes/webpanel.py` = **list‑only** dashboards + a 5‑key settings form. No product/panel/user/discount editing. In‑memory sessions (F‑041). |
| F‑087 | Mini‑App backend API | Signed‑request user API | ✅ | `api/miniapp.py` — session‑token identity, ownership checks, `verify_init_data` HMAC. Solid. |
| F‑088 | Mini‑App static serving | Serve the SPA bundle | ✅ | `api/miniapp_static.py` |
| F‑089 | Telegram webhook + secret | Receive updates | 🔒 | `api/webhook.py` validates `X‑Telegram‑Bot‑Api‑Secret‑Token` (**improvement over `main`**) but **fails open** if the secret is unset. |
| F‑090 | Sub proxy | Serve subscription content | 🔧 | `api/subproxy.py` |
| F‑091 | White‑label child bots | `vpnbot/` per‑child dispatch (`botsaz`) | ⚠️ | `api/whitelabel.py` + `botsaz` model; not deep‑verified. |
| F‑092 | Machine API tokens | `hash.txt` token auth for `/api` | ✅ | `api.auth` (constant‑time compare) + session dual‑auth. |

### 4.11 Data & infrastructure

| ID | Feature | Main behaviour | Status | Notes |
|---|---|---|---|---|
| F‑093 | DB schema parity | ~30 MySQL tables | ⚠️ | 29 tables modelled well; **`protocol` table missing**; the wide `setting` row is redesigned as a KV store (large downstream blast radius; a promised compatibility view does **not** exist). |
| F‑094 | Migrations | Schema versioning | 🐞 | `alembic/versions/0001_initial.py` is `Base.metadata.create_all` in disguise (loops `sorted_tables` + `table.create()`); lines 30–42 build `col_defs` via `col.compile()` and **never use them** (dead code); no real DDL captured; no compat view. |
| F‑095 | Panel password encryption | (plaintext in `main`) | 🔒 | Fernet‑at‑rest (**improvement**), but the key derives from `MIRZA_SESSION_SECRET`, whose `.env.example` default is `change-me` → creds encrypted under a known key if unchanged. |
| F‑096 | Installer | Apache/PHP/MySQL/certbot | ⚠️ | `scripts/install.sh` (systemd + Caddy + alembic + setWebhook); different stack, not verified. |

---

## 5. Additions in the rewrite (➕)

Genuinely useful, and mostly aligned with the "improve where reasonable / design for extension" instruction:

- **Plugin registry** for panels, payments, and jobs (`registry/`, `@register_plugin`) with runtime enable/disable — the main extensibility win.
- **Append‑only balance ledger** (`balance_ledger`) — auditable wallet.
- **Idempotent payment claiming** (`claim_paid`) — correct concurrency guard (undermined in practice by the settle bug).
- **Webhook secret validation** — closes a real `main` gap (fail‑open caveat).
- **Fernet encryption of panel passwords at rest** (weak‑default‑key caveat).
- **JSONB settings + real FKs and indexes** on `invoice`/`payment` hot paths.
- **Proper Telegram `initData` HMAC validation** for the Mini‑App (stronger than `main`).
- **Batched/rate‑capped** broadcast and payment polling (30/25/50 caps).

None of these are "silently mixed into parity work" — they're labelled in `PARITY.md`. That instruction (#3) was followed. The problem is the ✅ parity claims sitting next to them, several of which are false.

---

## 6. Overall completion & how it was calculated

**Methodology.** Each of the 96 inventoried parity features (F‑001…F‑096; additions excluded from the denominator) is scored by fidelity to baseline: ✅/🔧 = 1.0, 🔒 = 0.7, ⚠️ = 0.5, 🐞 = 0.2, ❌ = 0.0. Weighted completion = Σ(score) / 96.

| Status | Count | % of features |
|---|---:|---:|
| ✅ Done | 22 | 23% |
| 🔧 Done + improved | 5 | 5% |
| ⚠️ Partially done | 40 | 42% |
| 🐞 Done but wrong | 16 | 17% |
| 🔒 Done but risky | 3 | 3% |
| ❌ Missing | 10 | 10% |
| **Total** | **96** | 100% |

**Weighted completion ≈ 55%.**

> ⚠️ **Read this number carefully.** Completion is concentrated in *read/display* paths (viewing services, stats, listings, the Mini‑App). The *transactional* core — take payment → provision → notify — is where the 🐞 cluster sits. A user‑journey‑weighted score (weighting the revenue path by its business importance) would land **well below 55%**. Treat 55% as "how much of the surface area is present," not "how ready it is to run a shop."

**By functional area (weighted):**

| Area | Completion |
|---|---:|
| Web / HTTP surfaces | ~86% |
| Support & content | ~75% |
| Service management | ~63% |
| Bot UX & onboarding | ~60% |
| Payments & wallet | ~56% |
| Purchase & provisioning | ~55% |
| Data & infrastructure | ~55% |
| Scheduled jobs | ~53% |
| Agent / reseller | ~50% |
| Admin management | ~41% |
| Growth & marketing | ~31% |

---

## 7. Code quality & QA findings (by severity)

### 🔴 Critical (block launch)
1. **`settle_wallet_topup` undefined** (`payments/service.py` lacks it; called 4×). Every gateway top‑up + Stars settlement crashes. — F‑022, F‑030.
2. **Gateway product purchase never provisions** — missing `invoice_id` on the order routes real purchases to the (broken) top‑up branch. — F‑006.
3. **Customer never notified & admin report is a no‑op** on gateway settlement. — F‑032, F‑033.
4. **Wallet purchase charges after provisioning + commits before charging** → free‑config race / double‑spend. — F‑005.

### 🟠 High
5. **Change‑location and manual‑sell create zero‑volume / expired configs.** — F‑016, F‑066.
6. **Expiry & volume reminders go to an admin channel, not the customer** — the renewal engine doesn't reach buyers. — F‑076, F‑077.
7. **`disableconfig` never commits** its status change. — F‑078.
8. **Multiple‑admins unimplemented** despite ✅ claim; secondary admins are locked out. — F‑068.
9. **Migrations are `create_all` in disguise** with dead code and no compatibility view for the redesigned `setting` table. — F‑094, F‑093.
10. **Process‑local state** (`_pending`, `_TOPUP`, `_BROADCAST`, `_SESSIONS`) breaks restarts and any multi‑worker deployment; enables the F‑005 race. — F‑041.

### 🟡 Medium
11. Discount engine ignores percentages, usage limits, per‑product codes, and expiry. — F‑007, F‑045.
12. Lucky‑wheel and gift‑code admin config is written but never read. — F‑048, F‑075, F‑046.
13. Lottery job and scheduled gift drops absent/stubbed. — F‑047, F‑046.
14. `uptime_node` uses the encrypted password without decrypting. — F‑082.
15. Referral commission & cashback not implemented. — F‑043, F‑044.
16. Admin surface ~25 cmds vs ~177; no in‑bot text customization; create‑and‑list only for most entities; pipe‑delimited CLI args replace interactive flows. — §4.8.
17. Web admin panel is list‑only. — F‑086.
18. `service_time` stores an absolute timestamp in some paths and a day‑count in others → on‑hold/extend math bugs. — F‑080, F‑013.

### 🟢 Low / hygiene
19. **Dead / placeholder code (AI‑generation tells):** the shadowed insecure `api/__init__.py::miniapp` duplicate (with a `user_id`‑trusting token action); `payhooks._report`; `service._expire_from`; migration `col_defs` loop; `api/__init__.py:320 r = web.Application()  # placeholder to keep linters calm`; `admin._TOPUP_UNUSED`; `manage.new_tracking_code`.
20. Web panel: no `Secure` cookie flag; inconsistent HTML‑escaping in `_table`; bcrypt timing‑parity dummy hash is invalid (raises → *faster* path, defeating the intent). SQL itself is parameterized via the ORM — **no injection found**.
21. Webhook secret and forced‑channel checks **fail open** when misconfigured.
22. Weak default `MIRZA_SESSION_SECRET=change-me` doubles as the panel‑password encryption key.

### Testing
- **38 test functions.** Strengths: `initData` validation (5 cases), CubePay HMAC/fee math, Stars conversion, `claim_paid` idempotency, wallet ledger, schema round‑trip, Mini‑App flow, webhook‑secret gate.
- **Critical gap:** no test exercises `settle_wallet_topup` or the bot `pay_gateway`/`pay_wallet` checkout — which is exactly why the suite is green while the money path is broken. Tests validate components in isolation and never assemble the end‑to‑end purchase→settle→provision→notify journey.

---

## 8. Recommended next steps (priority order)

**Before this can replace `main`:**

1. **Define `PaymentService.settle_wallet_topup(order, cashback_pct=0)`** and cover it with a settlement test. (Unblocks all gateway top‑ups + Stars.)
2. **Set `invoice_id` on gateway product orders** in `buy.py::pay_gateway` (and mirror the Mini‑App `mini_purchase` that already does it) so purchases provision instead of top up.
3. **Wire a real bot instance into `payhooks` settlement** — replace `_notify_user(None, …)` and implement `_report()` so buyers and the admin channel are actually notified.
4. **Fix the wallet‑purchase ordering** (charge → provision in one transaction; no commit‑before‑charge; re‑verify balance atomically).
5. **Fix change‑location and manual‑sell** to carry real volume/expiry.
6. **Point expiry/volume reminders at the customer**, not the report channel; **commit** `disableconfig`.
7. **Move ephemeral state to the DB/Redis** (`user.step` + a payload table, or aiogram FSM with a Redis backend). Removes the F‑005 race and multi‑worker breakage.
8. **Restore admin parity for the money‑adjacent controls:** multi‑admin gating, per‑panel pricing/inbound/test config, product edit/delete, discount %/limits, card‑number management, in‑bot text customization.
9. **Rewrite the discount engine** (percent + fixed + per‑product + usage‑limit + expiry) and increment `used_count`.
10. **Real migrations:** replace the `create_all` shim with an explicit DDL migration and, if keeping the `setting` KV redesign, ship the compatibility view (or a data‑migration) it depends on.
11. **Port the lottery job**; implement gift drops; connect `/wheelprizes` to the wheel.
12. **Referral commission & cashback**, phone‑verification enforcement, on‑hold creation path.
13. **Harden config:** require a non‑default `MIRZA_SESSION_SECRET`/webhook secret at boot; separate the encryption key from the session secret; add `Secure` cookies and consistent escaping.
14. **Add end‑to‑end tests** for the full purchase journey per gateway before re‑claiming parity.

**Sequencing:** items 1–7 are the "make the core actually work" tranche and should land together with an e2e test; 8–14 are the "reach real parity" tranche.

---

## 9. What could NOT be verified statically (dynamic pass)

These require the second (live‑run) pass explicitly deferred here:

- **Panel adapters against real panels.** Only `marzban.py` was deep‑read (looks faithful). Marzneshin, Alireza/x‑ui single, S‑UI, Hiddify, WGDashboard (keygen), MikroTik (REST v7 ppp/hotspot), IBSng, Pasarguard, Rebecca, and `mirza_agent` need live create/modify/remove/revoke/usage round‑trips.
- **The end‑to‑end purchase → payment → provision → notify flow** for each gateway (the §7 critical bugs are from reading; confirm the crashes and the top‑up mis‑route on a running instance).
- **Alembic `upgrade`/`downgrade`** against real PostgreSQL (JSONB types, FKs, the missing compatibility view, `protocol` table absence).
- **Gateway callback signatures / verify logic** against live sandbox endpoints (Zarinpal PG v4, Aqayepardakht code‑70, Plisio/NowPayments webhooks, IranPay factor poll, CubePay HMAC).
- **Telegram Mini‑App** loaded inside Telegram (real `initData`, token exchange, purchase actions).
- **Scheduled jobs** firing on the real scheduler (cron cadence, the `disableconfig` no‑commit and `service_time` semantics in practice, backup output).
- **White‑label** child‑bot dispatch and per‑child webhooks.
- **Installer** (`scripts/install.sh`) on a clean host (systemd + Caddy + webhook registration).
- **Rate/limit behaviour** under load (broadcast O(N) sessions, poll caps, token caching).

---

## 10. Coverage statement (honesty)

**Fully read & reasoned about:** data model + migration; bot purchase flow; `panels/service.py`; `payments/service.py`; payment webhooks; wallet; middleware; webhook entry; admin `__init__.py` + `manage.py`; all scheduled jobs; web panel; REST + Mini‑App API; user misc/menu; `marzban.py`.

**Read lightly / trusted pending dynamic verification:** individual gateway internals (`stars.py`, `cubepay.py`, `zarinpal.py`, etc.), `extra.py`, `services.py` detail, `whitelabel.py`, `backup.py`, `rates.py`, and 13 of the 14 panel adapters.

This is a complete **breadth‑first** pass: every functional area is inventoried and mapped, with deep scrutiny on the risk‑weighted core. It is **not** a line‑by‑line audit of all 89 rewrite files or all 97 baseline files; the areas above are the known depth boundary. No partial result is presented as exhaustive.
