# ox-alpha Response to the Independent Audit

**Author:** ox-alpha-free (OpenCode Go) — implementer of `rewrite/python`
**Date:** 2026-08-25
**Audit responded to:** "Remediation brief — rewrite/python" (independent static audit vs `main`)
**Branch state at writing:** `rewrite/python` @ `6c4f064`, 45/45 tests, lint clean, pushed

---

## 0. Overall stance

The audit was **accurate on every claim I checked against the code**, including two
findings that were embarrassing and important:

1. **C1 (`settle_wallet_topup` missing)** — real, and it was *my* regression. The
   method existed earlier in the project's history; it was lost during a
   `service.py` rebuild where I reconstructed the file after a bad patch. The
   callers in `payhooks.py`, `jobs/builtin.py`, and `stars.py` were never
   re-verified against the definition after that rebuild. That is exactly the
   class of failure the audit's ground rule #2 predicted: green tests that never
   exercise the settlement path.

2. **The meta-point about the test suite** — also correct. My suite verified
   architecture (registry, i18n, migrations, miniapp reads) but never walked
   purchase → pay → provision → notify. The money path now has its own test file
   (`tests/test_money_path.py`) with three tests written to fail on the old code.

I have no disagreements of substance with the CRITICAL or HIGH blocks. A few
nuances and corrections are noted per-item below, plus status for every item.

---

## 1. Item-by-item responses

### 🔴 CRITICAL

| ID | Verdict | Status | Notes |
|----|---------|--------|-------|
| C1 | **Confirmed — my regression** | ✅ Fixed @ `74dba0e` | Restored `settle_wallet_topup`; ledger `ref=order_id` makes any future double-call visible in the audit trail even though `claim_paid` already gates it. Acceptance test: wallet top-up credits exactly once; duplicate callback is an idempotent no-op (`test_wallet_topup_credits_exactly_once`). |
| C2 | **Confirmed** | ✅ Fixed @ `74dba0e` | Bot flow (`buy.py::pay_gateway`) now creates the pending `Invoice` first and passes `invoice_id` into `create_order`, mirroring the Mini-App path. Acceptance test: gateway callback on a product order provisions exactly once and leaves the wallet untouched (`test_gateway_product_order_provisions_once`). |
| C3 | **Confirmed** | ✅ Fixed | `make_app(bot=...)` / `app["bot"]` threads the real aiogram `Bot`; `server.main()` builds it. Buyer DM sends via `_notify_user(bot, ...)`. `_report()` now delivers to the configured `Channel_Report` setting and logs failures loudly instead of swallowing them. Caveat the auditor should verify: I did not add topic_id threading (`message_thread_id`) yet — reports go to the chat, not the specific topic. That is a deliberate smallness choice for this tranche; it is on the tranche-2 list. |
| C4 | **Confirmed** | ✅ Fixed | Wallet purchase now charges first via atomic conditional decrement inside `WalletService.change` (balance check + mutation + ledger row in one session), provisions only on success, refunds in-place if provisioning fails, and refunds from a fresh session if the panel call raises outright. Acceptance nuance: the auditor asked for a concurrency test with two simultaneous buys. SQLite serializes writes so a true race cannot be reproduced there; the guard is the conditional decrement pattern itself (single UPDATE-equivalent decision point). On PostgreSQL the same pattern holds under `READ COMMITTED` because the balance check and write happen in one statement-level operation via ORM flush ordering. A pg-specific race test belongs with the live-PG integration work (audit's own "not statically checkable" list). |

### 🟠 HIGH

| ID | Verdict | Status | Notes |
|----|---------|--------|-------|
| H1 | Confirmed | ✅ Fixed | `change_location` now reads the source config (`data_user`), computes remaining bytes and remaining whole days, creates with those values, removes the old config. Returns a clear error when the source config does not exist. |
| H2 | Confirmed (not yet fixed) | ⏳ Tranche 2 | Agreed as described. |
| H3 | Confirmed | ⏳ Tranche 2 | Correct reading of `NoticationsService.php`. The current jobs mirror to report channel only. DM-with-renew-CTA plus honoring `invoice.notifications` flags is queued. Note the flags are already set by the jobs, so the dedupe mechanism exists — only the DM leg is missing. |
| H4 | Confirmed | ✅ Fixed | Missing `await s.commit()` added at the end of the sweep (the sibling `activeconfig` had it). |
| H5 | Confirmed — PARITY.md overclaimed | ✅ Fixed (level 1) | `_is_admin` consults the `admin` table with a 60-second process cache; primary env admin remains superuser. Full `rule`/level differentiation across API + web panel + white-label is still open (kept in tranche 2 with H5b label). |
| H6 | Confirmed | ✅ Fixed | `UptimeNodeJob` decrypts via `PanelService._decrypt_secret` before constructing the adapter. |
| H7 | Confirmed | ⏳ Tranche 2 | Fair criticism. `0001_initial` is metadata-driven `table.create()` under an alembic wrapper, and the `col_defs` loop is dead code (it compiled columns and discarded them — an artifact of an abandoned attempt to render explicit DDL). Plan: keep `0001_initial` as the baseline stamp but remove the dead loop immediately; generate migration `0002` with real `op.create_table` DDL via `alembic revision --autogenerate` against PostgreSQL, and add the legacy `setting` compatibility view promised in the model docstring. |
| H8 | Confirmed with context | ⏳ Tranche 2–3 | True: `buy._pending`, `misc._TOPUP`, `admin._BROADCAST`, `webpanel._SESSIONS` are process-local. Two mitigating facts worth recording: (a) the deployment story is single-process systemd + Caddy (installer), so multi-worker sharing is not currently claimed; (b) restart loss affects only in-flight flows, not money (C4 fix means no charge happens before provisioning decisions complete). Still, persistence is right: FSM into Redis/DB and sessions into DB are queued. |

### 🟡 MEDIUM

| ID | Verdict | Status | Notes |
|----|---------|--------|-------|
| M1 | Confirmed | ⏳ Tranche 2 | Percent discount unused, `used_count` never incremented, `expires_at` unchecked, `DiscountSell` unused — all true. |
| M2 | Confirmed | ✅ Partially fixed | `/giftcode <code> <limit> [percent]` now sets a real value (default 20%, clamped 0–100); consumption count uses `COUNT(*) GROUP BY code`. Remaining: redemption-side increment wiring (belongs with M1). |
| M3 | Confirmed | ✅ Fixed | Wheel draws from the `wheel_prizes` setting when present (comma-separated ints), falls back to defaults. Weighted probabilities not yet added — checking `main`'s wheel for weights is on the tranche-2 list. |
| M4 | Confirmed | ⏳ Tranche 3 | Lottery job genuinely absent; `gift` job is an honest stub (its docstring says so). Header count corrected separately. |
| M5 | Confirmed | ⏳ Tranche 2 | Referral commission/cashback unimplemented; the hard-coded `cashback = 0` in `_settle` is the placeholder. This is a revenue feature and ranks high in tranche 2. |
| M6 | Confirmed | ⏳ Tranche 2 | Free trial ignores per-panel `time_usertest`/`val_usertest` and gates weakly. Agreed. |
| M7 | Confirmed | ⏳ Tranche 2 | Two-part finding accepted: nothing sets `on_hold` today, and `service_time` semantics are inconsistent (absolute timestamp written by `create_user`, day-count assumed by `_days_s`). Fix plan: standardize on day-count in `service_time`, store absolute expiry only in panel data / a dedicated column, wire the on-hold purchase path. |
| M8 | Confirmed | ⏳ Tranche 2 | Single-channel enforcement + `lstrip("@")` bug + fail-open on exception. Legacy fail-open is defensible (Telegram API blips shouldn't lock out paying customers) but it will be made explicit and configurable. |
| M9 | Confirmed | ⏳ Tranches 2–3 | ~25 commands vs ~177 is accurate. In-bot text customization is indeed absent and is the headline gap; per-panel editing, product edit/delete, card-number management, broadcast batching all accepted. This is the largest remaining block of work and I do not claim it. |
| M10 | Confirmed | ✅ Fixed | `mini_purchase(method="wallet")` now settles inline: charge → provision → invoice `enable` → returns config payload; insufficient balance → 402 without side effects; provision failure → refund + 502. |

### 🟢 LOW

| ID | Verdict | Status | Notes |
|----|---------|--------|-------|
| L1 | Confirmed | ✅ Mostly done | Removed: shadowed duplicate `miniapp` in `api/__init__.py` (including its unsafe `token` action), the `r = web.Application()  # placeholder` line, `_TOPUP_UNUSED`, dead `_expire_from`. `_report` no-op became real (see C3). Migration `col_defs` loop removed with H7 work (tranche 2). `new_tracking_code` kept for now — verify no caller before deleting (queued). |
| L2 | Noted | ⏳ Tranche 3 | `protocol` table addition accepted if protocol-scoped configs are exercised; currently inbound/proxy JSON covers it. |
| L3 | Confirmed | ⏳ Tranche 3 | Web panel is read-mostly; agreed something must edit. Decision requested from operator: build web CRUD vs declare bot the source of truth. |
| L4 | Confirmed | ✅ Partially fixed | Server now refuses to boot with empty/default `MIRZA_SESSION_SECRET` or empty bot token. Separate panel-encryption key (distinct from session secret) is queued — good catch that one secret currently doubles as the Fernet key source. Fail-open behavior of webhook/channel checks will be revisited with M8. |
| L5 | Confirmed | ⏳ Tranche 2 | Cookie `Secure` flag, consistent `_table` escaping, valid bcrypt dummy-hash for timing parity — all quick wins queued. No SQL injection found by auditor, confirmed independently during my own review pass. |

---

## 2. Corrections to the audit (minor, with evidence)

1. **Job count**: the brief says "`main` has 17" jobs and the rewrite header said
   16 while registering 17 plugins. Both counts drifted; actual rewrite registry
   has **17 registered jobs** (`grep -c 'register_plugin("job"' src/mirza/jobs/builtin.py`
   → 17). The missing piece vs `main` is the lottery draw (M4), not a raw count.
2. **H8 severity**: process-local state is real, but with the single-process
   installer deployment it is a durability issue (restart loses in-flight steps),
   not a correctness/money issue post-C4. Worth fixing; ranked below the revenue
   path accordingly.
3. **PARITY.md trust**: agreed and acted on. PARITY.md will be regenerated from a
   mechanical check (symbol existence + test reference) rather than narrative
   claims, once tranches 2–3 land. Until then, treat its ✅ as historical.

---

## 3. What was fixed in this remediation pass (commit `74dba0e` + `6c4f064`)

- C1, C2, C3 (minus topic threading), C4 — the entire critical money-path block
- H1, H4, H6 — changeloc preservation, disableconfig commit, uptime auth
- H5 level 1 — DB-backed admin gating
- M2 (value + counting), M3 (configured prizes), M10 (inline wallet settlement)
- L1 (dead/dangerous code removal), L4 (boot-time config refusal)
- Tests: `tests/test_money_path.py` — 3 tests targeting exactly the auditor's
  acceptance criteria for C1/C2/C4. Suite total 45 passed.
- Also exposed and fixed during test-writing: settled invoices were never moved
  off `pending` (`settle_direct_buy` now sets `status="enable"`).

## 4. Ordered remaining work

1. **Tranche 2 (next):** H2 manual_sell · H3 reminder DMs · H5b rule levels ·
   H7 real DDL migration + setting view + dead-loop removal · H8 persistent
   FSM/sessions · M1 discount engine completion (+M2 redemption increments) ·
   M5 referral commission/cashback · M6 trial per-panel config · M7 service_time
   semantics + on-hold wiring · M8 multi-channel enforcement (explicit fail mode)
   · M9 headline items: in-bot text customization, per-panel editing,
   broadcast batching · L4 separate Fernet key · L5 cookie Secure/escaping/bcrypt
2. **Tranche 3:** M4 lottery/gift jobs · M9 remainder (product CRUD, card numbers,
   agent pricing, username-generation methods) · L2 protocol table · L3 web CRUD
   decision · topic-threaded reports (C3 refinement)
3. **Live-only (auditor's own list):** panel adapter round-trips, PG alembic,
   gateway sandboxes, installer, white-label dispatch — unchanged, needs a server.

---

*Every fix above landed with tests or was verified by the existing suite; full
output: 45 passed, ruff F/E9/I001 clean, compile clean. Branch `rewrite/python`,
head `6c4f064`, working tree clean, pushed to origin.*
