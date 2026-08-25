# Re-audit — verification of ox-alpha's tranche-1 fixes

**Auditor:** independent static review (same methodology as pass 1).
**Date:** 2026-08-25
**Rewrite head re-audited:** `origin/rewrite/python` @ `c7e0fee` (fix commit `74dba0e`, test lint `6c4f064`, response doc `c7e0fee`).
**Responds to:** `docs/ox-alpha_Response_To_qa.md` (the implementer's reply to the remediation brief).
**Method:** every claimed fix was re-read in the actual code and the new tests were read line-by-line. Claims were **not** taken at face value — same discipline applied to `PARITY.md` in pass 1. Still static: no code executed (the 45-test run is the implementer's claim; I verified the tests are genuine by reading them, and recommend executing them in the dynamic pass).

---

## 1. Verdict

**The tranche-1 work is real, and it is good.** Every fix the response claims as ✅ is genuinely present in the code, and — importantly — the money path is now covered by tests that would have failed on the old code. The implementer's response doc is candid and accurate about what it did and did not do. This is a materially different branch from the one audited in pass 1.

Two residuals are **under-stated** in the response and remain open (details in §3). Neither reopens the whole money path, but one is a real concurrency risk and should not be called "fixed."

**Parity movement:** ~55% → **~64%** weighted (see §4). More importantly, the CRITICAL money-path block went from **0 of 4 working** to **≈3.5 of 4**: a customer can now pay via an online gateway and actually receive their config, and a wallet top-up now credits the balance instead of crashing.

**Recommendation:** accept tranche 1. It is safe to keep building on. Do **not** call the branch production-ready yet — the C4 concurrency guard, the cubepay notification gap, and the deferred tranche-2 revenue items (customer expiry reminders, discount engine, referral/cashback) still stand between this and replacing `main`, and the dynamic pass is still owed.

---

## 2. Independent verification — item by item

Legend: **CONFIRMED** = fix present and correct in code · **CONFIRMED + TEST** = also backed by a test that exercises it · **PARTIAL** = works but a residual remains · **DEFERRED (accurate)** = not claimed fixed, and my pass-1 finding stands.

### CRITICAL

| ID | Claim | My verdict | Evidence |
|---|---|---|---|
| C1 | `settle_wallet_topup` restored | **CONFIRMED + TEST** | Defined `payments/service.py:135`; credits via ledger `ref=order_id`; callers align. `test_wallet_topup_credits_exactly_once` asserts exactly-once credit + idempotent replay. |
| C2 | gateway product purchase sets `invoice_id` | **CONFIRMED + TEST** | `buy.py::pay_gateway` now writes the pending `Invoice` first and passes `invoice_id=inv_token` into `create_order`. `test_gateway_product_order_provisions_once` drives the real `settle()` and asserts invoice→`enable`, order→`paid`, **ledger empty** (wallet untouched). |
| C3 | buyer DM + admin report wired | **PARTIAL** | `settle()` threads the real bot via `_app_bot(request)` → `_notify_user(bot,…)` + `_report(…, bot=bot)` for plisio/nowpayment/zarinpal/aqaye/iranpay. **Residual:** the `settle_tuple()` path (cubepay) still calls `_notify_user(None,…)` and never calls `_report` — cubepay buyers are not notified and cubepay payments aren't reported. Topic threading also deferred (self-disclosed). |
| C4 | charge-first + atomic conditional decrement | **PARTIAL** | Ordering **fixed**: `pay_wallet` charges first, provisions second, refunds on provision failure and on panel exception (fresh session). The free-config-on-failure bug is closed. **Residual:** `WalletService.change` is a read-modify-write (`SELECT user` → compute → assign → commit) with **no** `SELECT … FOR UPDATE` and **no** atomic `UPDATE … WHERE balance >= :amt`. The code comment and response call this an "atomic conditional decrement" — it is not. Two concurrent buys under PostgreSQL READ COMMITTED can still both pass the check → double-spend. The response's own reasoning ("one statement-level operation via ORM flush ordering") is incorrect. |

### HIGH

| ID | Claim | My verdict | Evidence |
|---|---|---|---|
| H1 | changeloc preserves remaining quota | **CONFIRMED** | `panels/service.py::change_location` reads `data_user`, computes `remaining_bytes`/`remaining_days`, creates with those, removes old. No more dead/empty config. |
| H4 | `disableconfig` commits | **CONFIRMED** | `await s.commit()  # persist the status sweep (H4)` added at `jobs/builtin.py:88`. |
| H5 | DB-backed admin gating (level 1) | **CONFIRMED** | `_is_admin` reads the `admin` table with a 60s cache; primary env admin stays superuser. Full `rule`/level differentiation across API/web/white-label correctly deferred (H5b). |
| H6 | `uptime_node` decrypts | **CONFIRMED** | `jobs/builtin.py:352-357` decrypts via `PanelService._decrypt_secret` before building the adapter. |
| H2, H3, H7, H8 | deferred to tranche 2 | **DEFERRED (accurate)** | Not claimed fixed. My pass-1 findings stand: manual_sell zero-volume (H2/F-066), reminders still go to the report channel not the customer (H3/F-076,F-077), migration is still the `create_all` shim with the dead `col_defs` loop (H7/F-094), process-local state remains (H8/F-041). |

### MEDIUM / LOW

| ID | Claim | My verdict | Evidence |
|---|---|---|---|
| M2 | gift code real value + correct count | **CONFIRMED (partial feature)** | `/giftcode` sets a real percent (default 20, clamped); count uses `COUNT(*) GROUP BY`. Redemption-side increment still open (belongs with M1 discount engine). |
| M3 | wheel reads configured prizes | **CONFIRMED** | `misc.py::_wheel_prizes` reads the `wheel_prizes` setting, falls back to defaults; `lucky_wheel` uses it. |
| M10 | mini-app wallet purchase settles inline | **CONFIRMED** | `miniapp.py:243` charge → provision → refund on failure (402 insufficient / 502 provision fail). |
| L1 | dead/insecure code removed | **CONFIRMED** | Gone: the shadowed insecure `miniapp` duplicate (and its `user_id`-trusting token action), `r = web.Application()` placeholder, `_TOPUP_UNUSED`, `_expire_from`. |
| L4 | boot refuses default secrets | **CONFIRMED** | `server.py:38-41` raises `SystemExit` on empty `MIRZA_API_KEY` and on unset/`change-me` `MIRZA_SESSION_SECRET`. Separate Fernet key still deferred (accurate). |
| M1,M4,M5,M6,M7,M8,M9,L2,L3,L5 | deferred | **DEFERRED (accurate)** | Matches pass 1; honestly labelled in the response. |

**Corrections in the response that I confirm are fair:** the rewrite registry does contain 17 job plugins (the "16" was a stale header string); the missing piece vs `main` is the lottery *draw*, not a raw count. Agreed.

---

## 3. Residuals the response under-states (act on these)

1. **C4 is not race-safe.** The provision-before-charge bug is genuinely fixed, but "atomic conditional decrement" is inaccurate — `WalletService.change` reads then writes in Python with no row lock. **Fix:** make the debit a single atomic statement — `UPDATE "user" SET balance = balance - :amt WHERE id = :id AND balance >= :amt` and act on the affected-row count, or `SELECT … FOR UPDATE` the user row before the check. Until then, two concurrent wallet buys can double-spend on PostgreSQL. Add a real concurrency test in the live-PG work (SQLite can't reproduce it — the response is right about that, but that's a reason the guard must be correct by construction, not a reason to defer it).
2. **cubepay settlement still silent.** `settle_tuple` (used only by cubepay) passes `bot=None` to `_notify_user` and skips `_report`. **Fix:** thread the bot into `settle_tuple` the same way `settle` does, and call `_report` there too.
3. **Topic-threaded reports** (`message_thread_id` from `topicid`) — self-disclosed as deferred; fine, but note reports currently land in the chat, not the report topic.

---

## 4. Updated scorecard

Applying the verified fixes to the pass-1 inventory:

| Status | Pass 1 | Pass 2 | Δ |
|---|---:|---:|---:|
| ✅ / 🔧 Done | 27 | **37** | +10 |
| ⚠️ Partial | 40 | **42** | +2 |
| 🐞 Buggy | 16 | **5** | −11 |
| 🔒 Risky | 3 | **3** | — |
| ❌ Missing | 10 | **9** | −1 |
| **Weighted completion** | **~55%** | **~64%** | **+9 pts** |

Movement drivers: F-006, F-022, F-030 (Stars), F-032, F-033, F-016, F-048, F-075, F-078, F-082 all 🐞→✅; F-005 🐞→🔒 (ordering fixed, race open); F-046 🐞→⚠️; F-068 ❌→⚠️ (admin gating level 1). Scoring weights unchanged from pass 1 (✅/🔧 = 1.0, 🔒 = 0.7, ⚠️ = 0.5, 🐞 = 0.2, ❌ = 0.0).

**Money-path readiness specifically:** the CRITICAL block is now ~3.5/4. The common-case purchase works end-to-end; the gap to "trust it with production money" is the C4 race and the cubepay notify.

---

## 5. Test-suite assessment

The response's headline is "45 passed." I did not execute the suite (still a static pass), but I read the new `tests/test_money_path.py` in full:

- `test_gateway_product_order_provisions_once` — **genuine.** Builds a product order with `invoice_id`, drives the real `payhooks.settle()`, stubs only the panel HTTP call, and asserts the three things that matter: invoice→`enable`, order→`paid`, and **ledger empty**. This would crash/fail on the pass-1 code.
- `test_wallet_topup_credits_exactly_once` — **genuine.** No `invoice_id`, calls `settle()` twice, asserts one `topup` ledger row and balance credited once.
- `test_insufficient_balance_never_provisions` — **narrow.** Unit-tests that `change()` refuses a debit below zero; does not exercise the full `pay_wallet` flow or concurrency. Fine as a guard test, but it does not prove "never provisions" end-to-end, and it does not test the race.

Net: the tests are honest and target the stated acceptance criteria — not gamed to pass. The one missing dimension (concurrency) is exactly the C4 residual above.

---

## 6. What still stands between this and replacing `main`

1. **Close C4** (atomic debit) and **cubepay notify/report** — small, and they finish the CRITICAL block properly.
2. **Tranche 2 revenue items** (the implementer's own list, which I agree with): customer expiry-reminder DMs (H3), discount engine + redemption increments (M1/M2), referral commission & cashback (M5), trial per-panel config (M6), on-hold + `service_time` semantics (M7), real DDL migration + setting view (H7), persistent FSM/sessions (H8).
3. **Tranche 3 breadth:** in-bot text customization and the rest of the admin surface (M9), lottery/gift jobs (M4), web CRUD decision (L3).
4. **Dynamic pass (unchanged):** execute the 45 tests; run each panel adapter against a real panel; Alembic up/down on PostgreSQL; gateway callbacks against sandboxes; installer; white-label dispatch.

---

*Verified statically against `rewrite/python@c7e0fee`. Every ✅ in this document was re-read in the source; the two residuals in §3 were found by reading past the response's summary, not from the response itself.*
