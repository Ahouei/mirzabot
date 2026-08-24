# Configuration guide — for operators

Mirza is a customizable platform. Nothing operator-specific is hardcoded.
Configuration lives in **two layers**, set at different times.

---

## Layer 1 — Deploy-time environment (`.env`)

Set once by whoever installs the platform. Requires restart to change.

| Variable | Purpose | Example |
|---|---|---|
| `MIRZA_API_KEY` | main bot token from @BotFather | `123456:AA...` |
| `MIRZA_ADMIN_NUMBER` | primary admin Telegram id | `172623365` |
| `MIRZA_USERNAME_BOT` | bot username (no @) | `my_vpn_bot` |
| `MIRZA_DOMAIN_HOSTS` | public HTTPS domain serving api/web/sub | `shop.example.com` |
| `MIRZA_DATABASE_URL` | SQLAlchemy async URL | `postgresql+asyncpg://user:pass@host/db` |
| `MIRZA_WEBHOOK_SECRET` | Telegram webhook secret (random hex) | auto-set by installer |
| `MIRZA_SESSION_SECRET` | signs sessions + Fernet panel-password encryption | random 32+ chars |
| `MIRZA_TIMEZONE` | scheduler/report timezone | `Asia/Tehran` |
| `MIRZA_USE_POLLING` | dev polling instead of webhook | `false` |
| `MIRZA_PORT` | HTTP server port | `8080` |
| `MIRZA_MINIAPP_DIR` | path to Mini App React bundle | `app` |
| `MIRZA_API_TOKENS_FILE` | extra REST API tokens file | `hash.txt` |

Copy `.env.example` → `.env`, fill in, then:
```bash
alembic upgrade head
python -m mirza.server
```

---

## Layer 2 — Runtime configuration (database; no restart needed)

Everything an operator tunes day-to-day lives in the DB and is editable
from the **web admin panel** (`/panel/settings`) or admin bot commands.

### Shop settings (`setting` KV table)
| Key | Meaning |
|---|---|
| `channel_lock` | mandatory channel @handle enforced on users |
| `default_panel` | panel used when a product doesn't pin one |
| `support_id` | support contact shown to users |
| `help_text` | fallback help page text |
| `broadcast_text` | message queued for /broadcast delivery |
| `wheel_prizes` | JSON array of lucky-wheel prize amounts |
| `usd_rate` | manual USD/Toman override for Stars pricing |
| `Channel_Report` | report supergroup id (payment/backup topics) |

### Payment gateways (`PaySetting` table)
Fill only what you use:

| Key | Gateway |
|---|---|
| `zarinpal_merchant` | Zarinpal |
| `aqayepardakht_pin` | Aqayepardakht |
| `nowpayment_api` | NowPayments crypto |
| `plisio_api` | Plisio crypto |
| `apiiranpay` + `iranpay_base` (+ `iranpay2_base`) | IranPay card-acquire |
| `apiternado` + `feeternado` + `feestatusternado` (`onfeeternado`) | CubePay TRON + customer fee |
| `active_cards` | card-to-card numbers (one per line) |
| `minbalancestar` / `maxbalancestar` | Stars top-up range |
| `chashbackstar` / `cashbacknowpayment` / `chashbackiranpay1` / `chashbackiranpay2` | cashback % per gateway |

### Panels (`marzban_panel` table)
One row per backend instance. Add via bot `/addpanel name|type|url|user|pass [inbound_id]`
or web panel. Passwords are Fernet-encrypted with `MIRZA_SESSION_SECRET`.
Per-panel pricing columns (extra volume/time/change-location) are edited in the web UI.

### Catalog
- `product` rows: plans with price/volume/days/location/category
- `category` rows: shop sections

### Report routing (`topicid` table)
Maps report kinds (`paymentreport`, `reportnight`, `uptimepanel`,
`uptimenode`, `notifications`, `backupfile`) to forum topic ids inside
the report supergroup.

---

## Adding a new gateway or panel type later

Both are registry plugins keyed `(kind, name, revision)`:

```python
from mirza.contracts import PanelAdapter
from mirza.registry import register_plugin

@register_plugin("panel", "mypanel")
class MyPanel(PanelAdapter):
    ...  # implement the async contract
```

Drop the module into a package imported by `mirza/plugins.py` (or any
addon package) and it appears everywhere panels are picked — no core edits.
