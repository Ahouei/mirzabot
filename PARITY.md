# Parity matrix — PHP mirzabot 0.3.2 → Python rewrite

Legend: ✅ ported · 🔧 ported+improved · 🆕 new · ⏳ phase-2 slot

## Panels (legacy file → registry name)
| Legacy | Rewrite | Status |
|---|---|---|
| Marzban.php (462) | panels/marzban.py + nodes API | ✅ |
| marzneshin.php | panels/marzneshin.py | ✅ |
| alireza_single.php | panels/alireza_single.py | ✅ |
| x-ui_single.php | panels/xui_single.py | ✅ |
| s_ui.php | panels/sui.py | ✅ |
| hiddify.php | panels/hiddify.py (+serverstatus) | ✅ |
| WGDashboard.php | panels/wgdashboard.py (keygen incl.) | ✅ |
| mikrotik.php | panels/mikrotik.py (REST v7, ppp/hotspot) | ✅ |
| ibsng.php + Modules/IBSng.php | panels/ibsng.py | ✅ |
| Rebecca.php | panels/rebecca.py | ✅ |
| pasarguard alias | panels/pasarguard.py (own registry entry) | 🔧 |
| mirza_agent.php | panels/mirza_agent.py (+list_agent_panels) | ✅ |
| panels.php ManagePanel (2554) | panels/service.py PanelService | 🔧 |

## Payments
| Legacy | Rewrite | Status |
|---|---|---|
| payment/zarinpal.php | payments/zarinpal.py (PG v4, 100/101 idempotent) | ✅ |
| payment/aqayepardakht.php | payments/aqayepardakht.py (code 70 replay-safe) | ✅ |
| payment/nowpayment.php + cronbot/plisio.php polling | payments/nowpayments.py + jobs plisio | ✅ |
| cronbot/plisio.php | payments/plisio.py + scheduler poll job | ✅ |
| payment/iranpay1/2.php + cronbot/iranpay1.php | payments/iranpay.py (base URL configurable) + iranpay_poll job | 🔧 |
| CubePay TRON gateway (late upstream: function.php trnado() + payment/iranpay2.php) | payments/cubepay.py — HMAC-signed callback + authority verify, customer-paid fee (percent/flat), HTML result card | 🔧 unit-tested offline |
| Telegram Stars (index.php startelegrams + pre_checkout/successful_payment) | payments/stars.py — native aiogram invoice link, legacy stars conversion, replay-guarded settlement | 🔧 |
| card-to-card (croncard) | payments/card2card.py + croncard job | ✅ |
| wallet Balance | payments/wallet.py + **append-only balance_ledger** | 🔧 |
| DirectPayment / claim logic | payments/service.py claim_paid() atomic | 🔧 |

## Scheduler (cronbot/*.php)
statusday→statusday · NoticationsService→notifications(+volumewarn split) ·
disableconfig→disableconfig · activeconfig→activeconfig · payment_expire→payment_expire ·
sendmessage→sendmessage(batched 30/min) · gift→gift · expireagent→expireagent ·
on_hold→on_hold · configtest→configtest · uptime_node→uptime_node · uptime_panel→uptime_panel ·
backupbot→backupbot(pg_dump/mysqldump/sqlite auto) · croncard→croncard ·
plisio→plisio · iranpay1→iranpay_poll (**fixes legacy return-inside-while bug**) — all ✅,
toggleable via setting.status_cron JSON like legacy.

## Bot surface
| Feature | Where | Status |
|---|---|---|
| start/menu/lang switch/deep-link ref | handlers/user/menu.py | ✅ |
| forced channel join + rejoin notices | middleware + ChatMemberHandler | ✅ |
| ban/block enforcement | AuthMiddleware | ✅ |
| buy: category→product→confirm→discount→gateway pick | handlers/user/buy.py | ✅ |
| wallet pay path | buy.pay_wallet | ✅ |
| my services + config view | services.my_services | ✅ |
| extend / extra volume / extra time | services numeric-input FSM-light | ✅ |
| change location (paid migration) | services.change_loc* | ✅ |
| revoke sub link | services.revoke | ✅ |
| trial accounts (usertest) | misc.free_trial | ✅ |
| lucky wheel (daily, prize to ledger) | misc.lucky_wheel + admin /wheelprizes | 🔧 |
| referrals (link, count) | misc.affiliates | ✅ |
| support tickets via departments | user/extra.py ticket_* + Departman table | ✅ |
| tariff list | extra.tariff_list (grouped by location) | ✅ |
| tutorial browsing in help | menu help + extra.help_browse/uhelp | ✅ |
| custom volume/time pricing | api miniapp custom_price + panel cols | ✅ |
| support contact | misc.support | ✅ |
| broadcast queue (admin) | admin.broadcast_* | ✅ |
| stats/finduser/block/products/panels CRUD | admin/* | ✅ |
| manual sell (/sell) | admin.manual_sell | ✅ |
| payments report (/payments) | admin.payments_report | ✅ |
| gift/discount codes CRUD (/giftcode, /giftcodes) | admin/manage.py | ✅ |
| categories CRUD (/addcat /cats) | admin/manage.py | ✅ |
| tutorials CRUD (/addhelp /helplist) | admin/manage.py | ✅ |
| channels register + mandatory lock (/addchannel /lockchannel) | admin/manage.py | ✅ |
| agent grant/revoke/list/requests (/makeagent /agents …) | admin/manage.py | ✅ |
| departments (/adddept /depts) | admin/manage.py | ✅ |
| balance adjust with ledger (/addbalance) | admin/manage.py | ✅ |
| wheel prize config (/wheelprizes) | admin/manage.py | ✅ |
| i18n fa/en/ru/zh | i18n/ | ✅ |

## HTTP surfaces
| Legacy | Rewrite | Status |
|---|---|---|
| api/*.php (miniapp, users, product, payment, settings, discount, invoice, log, statbot, verify, keyboard) | api/__init__.py token-or-session auth | ✅ |
| pay callbacks | api/payhooks.py (idempotent settle) | 🔧 |
| sub/index.php | api/subproxy.py | 🔧 |
| index.php webhook | api/webhook.py — **validates secret_token (legacy gap fixed)** | 🔧 |
| panel/*.php web admin | routes/webpanel.py (bcrypt12, session regen, warm dark theme) | ✅ core pages |
| vpnbot/index.php white-label | api/whitelabel.py per-child dispatchers | ✅ |

## Installer
install.sh (Apache/PHP/MySQL/certbot) → scripts/install.sh (systemd+Caddy auto-HTTPS,
.env, alembic upgrade, setWebhook with secret) — ✅

## New in the rewrite (🆕)
- Append-only **balance ledger** (auditable wallet)
- **Webhook secret validation** on all entrypoints
- **Fernet encryption** for panel passwords at rest
- Plugin **revision history** in registry; runtime enable/disable
- Atomic payment claiming (`UPDATE ... WHERE status='Unpaid'` guard)
- Batched broadcast delivery + payment-poll caps (rate-limit friendly)
- JSONB settings KV replacing 70-flat-column setting row
- Real FKs + indexes on invoice/payment hot paths
- `/api` machine tokens via hash.txt preserved + admin-session dual auth

## Phase-2 slots (⏳)
- Live panel certification: run each adapter against a real panel instance
- Multi-owner panel ACLs (admin.rule levels beyond legacy single rule)
- Redis FSM storage backend for multi-instance deployments

## i18n corpora
- Full legacy `lang/{fa,en,ru,zh}.php` converted: **2,381 strings × 4 languages**
  → `src/mirza/i18n/{fa,en,ru,zh}_full.py` (regenerate:
  `python scripts/convert_legacy_langs.py`)
- Rewrite-only strings live in `i18n/additions.py`; `i18n/aliases.py` binds
  rewrite keys to admin-editable legacy keys (bottext UI keeps working)

## Verification status
| Layer | Proof |
|---|---|
| Unit/smoke | 16 pytest cases (registry, i18n, models, dispatcher, API, CubePay HMAC, Stars math) |
| Integration | real SQLite file DB: alembic up/down + ORM round-trips + wallet ledger + claim idempotency + fake-adapter PanelService |
| E2E live server | booted aiohttp app: miniapp token→actions flow, sub proxy, web-panel login gate, webhook secret gate, static Mini App bundle |
| Rates | live-verified USD/TRX fetch (TGJU+diaadata) on build host |

