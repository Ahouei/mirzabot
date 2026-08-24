"""All 16 legacy cron jobs as registry plugins.

Parity map (legacy cronbot/*.php -> job name, cron):
  statusday.php        -> statusday         */15 (daily report gate inside)
  croncard.php         -> croncard          */1
  NoticationsService   -> notifications     */1
  payment_expire.php   -> payment_expire    */5
  sendmessage.php      -> sendmessage       */1
  plisio.php           -> plisio            */3
  activeconfig.php     -> activeconfig      */1
  disableconfig.php    -> disableconfig     */1
  iranpay1.php         -> iranpay_poll      */1
  backupbot.php        -> backupbot         0 */5
  gift.php             -> gift              */2
  expireagent.php      -> expireagent       */30
  on_hold.php          -> on_hold           */15
  configtest.php       -> configtest        */2
  uptime_node.php      -> uptime_node       */15
  uptime_panel.php     -> uptime_panel      */15
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select as sa_select

from mirza.contracts import Job, JobContext
from mirza.models import Invoice, MarzbanPanel, PaymentReport, Setting, User
from mirza.registry import register_plugin, registry

log = logging.getLogger(__name__)


async def _setting(session, key: str, default=None):
    res = await session.execute(
        sa_select(Setting.value_json).where(Setting.key == key))
    val = res.scalar_one_or_none()
    return val if val is not None else default


def _register_jobs() -> None:
    # ── notifications: volume/time expiry warnings (NoticationsService) ──
    @register_plugin("job", "notifications", meta={"cron": "*/1 * * * *"})
    class NotificationsJob(Job):
        async def run(self, ctx: JobContext) -> None:
            flags = await _flag(ctx, "status_cron")
            async with ctx.session_factory() as s:
                if not flags.get("day", True):
                    return
                now = datetime.now(timezone.utc)
                soon = now + timedelta(days=1)
                res = await s.execute(
                    sa_select(Invoice).where(Invoice.status == "enable"))
                warned = 0
                for inv in res.scalars():
                    notif = inv.notifications or {}
                    expire_ts = _parse_expire(inv.service_time)
                    if expire_ts and now <= datetime.fromtimestamp(
                            expire_ts, tz=timezone.utc) <= soon and not notif.get("time"):
                        await ctx.send_report(
                            "notifications",
                            f"⏳ invoice {inv.id_invoice} expires in <24h")
                        notif["time"] = True
                        inv.notifications = notif
                        warned += 1
                    if warned >= 50:   # batch cap per tick (improvement)
                        break
                await s.commit()

    # ── disable expired configs (disableconfig) ──────────────────
    @register_plugin("job", "disableconfig", meta={"cron": "*/1 * * * *"})
    class DisableConfigJob(Job):
        async def run(self, ctx: JobContext) -> None:
            from mirza.panels import PanelService
            async with ctx.session_factory() as s:
                cutoff = int(datetime.now(timezone.utc).timestamp())
                res = await s.execute(
                    sa_select(Invoice).where(Invoice.status == "enable"))
                async with PanelService() as panels:
                    for inv in res.scalars():
                        exp = _parse_expire(inv.service_time)
                        if exp and exp <= cutoff:
                            await panels.change_status(inv.service_location,
                                                       inv.uuid or "", False)
                            inv.status = "disabled"
                            log.info("disabled %s", inv.id_invoice)

    # ── re-enable / renew configs (activeconfig) ─────────────────
    @register_plugin("job", "activeconfig", meta={"cron": "*/1 * * * *"})
    class ActiveConfigJob(Job):
        async def run(self, ctx: JobContext) -> None:
            from mirza.panels import PanelService
            async with ctx.session_factory() as s:
                res = await s.execute(
                    sa_select(Invoice).where(Invoice.status == "renewing"))
                async with PanelService() as panels:
                    for inv in res.scalars():
                        ok = await panels.change_status(inv.service_location,
                                                        inv.uuid or "", True)
                        if ok:
                            inv.status = "enable"
                await s.commit()

    # ── volume warnings (volume part of statusday/cron) ──────────
    @register_plugin("job", "volumewarn", meta={"cron": "*/15 * * * *"})
    class VolumeWarnJob(Job):
        async def run(self, ctx: JobContext) -> None:
            from mirza.panels import PanelService
            async with ctx.session_factory() as s:
                flags = await _setting(s, "status_cron", {})
                if not flags.get("volume", True):
                    return
                res = await s.execute(
                    sa_select(Invoice).where(Invoice.status == "enable"))
                async with PanelService() as panels:
                    for inv in res.scalars():
                        u = await panels.data_user(inv.service_location,
                                                   inv.uuid or "")
                        if not u or not u.data_limit:
                            continue
                        used_ratio = (u.used_traffic or 0) / max(u.data_limit, 1)
                        notif = inv.notifications or {}
                        if used_ratio >= 0.8 and not notif.get("volume"):
                            await ctx.send_report(
                                "notifications",
                                f"📊 {inv.id_invoice} used ≥80% of volume")
                            notif["volume"] = True
                            inv.notifications = notif
                await s.commit()

    # ── daily statistics report (statusday) ──────────────────────
    @register_plugin("job", "statusday", meta={"cron": "*/15 * * * *"})
    class StatusDayJob(Job):
        async def run(self, ctx: JobContext) -> None:
            if datetime.now().strftime("%H:%M") != "23:45":
                return
            async with ctx.session_factory() as s:
                users_today = await s.execute(
                    sa_select(User).where(
                        User.register_at >= datetime.now().strftime("%Y-%m-%d")))
                sales = await s.execute(sa_select(Invoice))
                invoices = list(sales.scalars())
                text = (
                    "📅 daily report\n"
                    f"new users: {len(list(users_today.scalars()))}\n"
                    f"total invoices: {len(invoices)}\n"
                    f"enabled: {sum(1 for i in invoices if i.status == 'enable')}"
                )
                await ctx.send_report("reportnight", text)

    # ── card payments polling (croncard) ─────────────────────────
    @register_plugin("job", "croncard", meta={"cron": "*/1 * * * *"})
    class CronCardJob(Job):
        async def run(self, ctx: JobContext) -> None:
            from mirza.payments import PaymentService
            async with ctx.session_factory() as s:
                svc = PaymentService(s)
                res = await s.execute(
                    sa_select(PaymentReport).where(
                        PaymentReport.payment_status == "Unpaid",
                        PaymentReport.payment_method == "card2card"))
                for order in res.scalars():
                    if order.gateway_payload and \
                            isinstance(order.gateway_payload, dict) and \
                            order.gateway_payload.get("approved"):
                        if await svc.claim_paid(order.order_id):
                            await _settle(ctx, svc, order)

    # ── crypto polling (plisio) ──────────────────────────────────
    @register_plugin("job", "plisio", meta={"cron": "*/3 * * * *"})
    class PlisioJob(Job):
        async def run(self, ctx: JobContext) -> None:
            from mirza.payments import PaymentService
            from mirza.registry import registry
            async with ctx.session_factory() as s:
                svc = PaymentService(s)
                kv = {
                    "plisio_api": await svc.kv("plisio_api"),
                    "nowpayment_api": await svc.kv("nowpayment_api"),
                }
                res = await s.execute(
                    sa_select(PaymentReport).where(
                        PaymentReport.payment_status == "Unpaid",
                        PaymentReport.payment_method.in_(["plisio", "nowpayments"])))
                orders = list(res.scalars())
            for order in orders[:25]:
                gw_raw = (order.gateway_payload or {}) if isinstance(
                    order.gateway_payload, dict) else {}
                track = str(gw_raw.get("invoice_id") or gw_raw.get("payment_id") or "")
                if not track:
                    continue
                gateway = registry.get("payment", order.payment_method)(
                    kv, callback_base=_base())
                try:
                    ok, _ = await gateway.verify_payment(b"", {"track": track})
                except Exception:
                    log.exception("crypto poll failed for %s", order.order_id)
                    continue
                if ok:
                    async with ctx.session_factory() as s2:
                        svc2 = PaymentService(s2)
                        fresh = await svc2.get_order(order.order_id)
                        if fresh and await svc2.claim_paid(fresh.order_id):
                            await _settle(ctx, svc2, fresh)

    # ── iranpay factor polling (iranpay1) ────────────────────────
    @register_plugin("job", "iranpay_poll", meta={"cron": "*/1 * * * *"})
    class IranPayPollJob(Job):
        """Fixes legacy bug: `return` inside while-loop aborted the sweep."""

        async def run(self, ctx: JobContext) -> None:
            from mirza.payments import PaymentService
            from mirza.payments.iranpay import IranPayGateway
            async with ctx.session_factory() as s:
                svc = PaymentService(s)
                kv = {"iranpay_base": await svc.kv("iranpay_base"),
                      "apiiranpay": await svc.kv("apiiranpay")}
                res = await s.execute(
                    sa_select(PaymentReport).where(
                        PaymentReport.payment_status == "Unpaid",
                        PaymentReport.payment_method == "iranpay"))
                orders = list(res.scalars())
            gw = IranPayGateway(kv, callback_base=_base())
            for order in orders[:25]:
                raw = order.gateway_payload if isinstance(
                    order.gateway_payload, dict) else {}
                fid = str(raw.get("factor_id", ""))
                if not fid:
                    continue
                try:
                    ok, _ = await gw.verify_payment(b"", {"id": fid})
                except Exception:
                    log.exception("iranpay poll failed %s", order.order_id)
                    continue
                if ok:
                    async with ctx.session_factory() as s2:
                        svc2 = PaymentService(s2)
                        fresh = await svc2.get_order(order.order_id)
                        if fresh and await svc2.claim_paid(fresh.order_id):
                            await _settle(ctx, svc2, fresh)

    # ── pending payment expiry (payment_expire) ──────────────────
    @register_plugin("job", "payment_expire", meta={"cron": "*/5 * * * *"})
    class PaymentExpireJob(Job):
        async def run(self, ctx: JobContext) -> None:
            from mirza.payments import PaymentService
            async with ctx.session_factory() as s:
                svc = PaymentService(s)
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)
                          ).isoformat(timespec="seconds")
                res = await s.execute(
                    sa_select(PaymentReport).where(
                        PaymentReport.payment_status == "Unpaid",
                        PaymentReport.created_at < cutoff))
                for order in res.scalars():
                    await svc.mark_failed(order.order_id)

    # ── queued broadcast (sendmessage) ───────────────────────────
    @register_plugin("job", "sendmessage", meta={"cron": "*/1 * * * *"})
    class SendMessageJob(Job):
        async def run(self, ctx: JobContext) -> None:
            if ctx.bot is None:
                return
            async with ctx.session_factory() as s:
                res = await s.execute(
                    sa_select(User).where(User.check_status == "sending"))
                targets = list(res.scalars())[:30]   # rate-batched
                text_row = await _setting(s, "broadcast_text", "")
                for u in targets:
                    try:
                        await ctx.bot.send_message(int(u.id), str(text_row),
                                                   parse_mode="HTML")
                    except Exception:
                        pass
                    u.check_status = "done"
                await s.commit()

    # ── gift codes (gift) ────────────────────────────────────────
    @register_plugin("job", "gift", meta={"cron": "*/2 * * * *"})
    class GiftJob(Job):
        async def run(self, ctx: JobContext) -> None:
            # scheduled gift drops are configured via setting.gift_schedule;
            # actual redemption is handler-side. Kept as toggleable no-op tick.
            return None

    # ── agent expiry (expireagent) ───────────────────────────────
    @register_plugin("job", "expireagent", meta={"cron": "*/30 * * * *"})
    class ExpireAgentJob(Job):
        async def run(self, ctx: JobContext) -> None:
            async with ctx.session_factory() as s:
                res = await s.execute(sa_select(User).where(User.is_agent == True))  # noqa: E712
                now = datetime.now()
                changed = 0
                for u in res.scalars():
                    exp = u.expire_at
                    if exp and _parse_expire(exp) and \
                            _parse_expire(exp) < int(now.timestamp()):
                        u.is_agent = False
                        changed += 1
                if changed:
                    await s.commit()

    # ── on-hold test configs activation (on_hold) ────────────────
    @register_plugin("job", "on_hold", meta={"cron": "*/15 * * * *"})
    class OnHoldJob(Job):
        async def run(self, ctx: JobContext) -> None:
            from mirza.panels import PanelService
            async with ctx.session_factory() as s:
                res = await s.execute(
                    sa_select(Invoice).where(Invoice.status == "on_hold"))
                async with PanelService() as panels:
                    for inv in res.scalars():
                        start_ts = int(datetime.now(timezone.utc).timestamp())
                        ok = await panels.modify_user(
                            inv.service_location, inv.uuid or "",
                            {"expire": start_ts + _days_s(inv.service_time)})
                        if ok:
                            inv.status = "enable"
                            inv.time_sell = str(start_ts)
                await s.commit()

    # ── trial config cleanup (configtest) ────────────────────────
    @register_plugin("job", "configtest", meta={"cron": "*/2 * * * *"})
    class ConfigTestJob(Job):
        async def run(self, ctx: JobContext) -> None:
            from mirza.panels import PanelService
            async with ctx.session_factory() as s:
                res = await s.execute(
                    sa_select(Invoice).where(Invoice.status == "test"))
                async with PanelService() as panels:
                    for inv in res.scalars():
                        exp = _parse_expire(inv.service_time)
                        if exp and exp < int(datetime.now(timezone.utc).timestamp()):
                            await panels.remove_user(inv.service_location,
                                                     inv.uuid or "")
                            await s.delete(inv)
                await s.commit()

    # ── node uptime monitor (uptime_node) ────────────────────────
    @register_plugin("job", "uptime_node", meta={"cron": "*/15 * * * *"})
    class UptimeNodeJob(Job):
        async def run(self, ctx: JobContext) -> None:
            from mirza.panels.marzban import MarzbanAdapter
            async with ctx.session_factory() as s:
                res = await s.execute(
                    sa_select(MarzbanPanel).where(MarzbanPanel.panel_type == "marzban"))
                for panel in res.scalars():
                    adapter = MarzbanAdapter({
                        "url_panel": panel.url_panel,
                        "username_panel": panel.username_panel,
                        "password_panel": panel.password_panel_encrypted,
                    })
                    try:
                        nodes = await adapter.list_nodes()
                        down = [n.get("name") for n in nodes
                                if n.get("status") not in ("healthy", "connected")]
                        if down:
                            await ctx.send_report(
                                "uptimenode", "🔴 nodes down: " + ", ".join(map(str, down)))
                    finally:
                        await adapter.close()

    # ── panel uptime monitor (uptime_panel) ──────────────────────
    @register_plugin("job", "uptime_panel", meta={"cron": "*/15 * * * *"})
    class UptimePanelJob(Job):
        async def run(self, ctx: JobContext) -> None:
            from mirza.panels import PanelService
            async with ctx.session_factory() as s:
                res = await s.execute(sa_select(MarzbanPanel))
                async with PanelService() as panels:
                    for panel in res.scalars():
                        try:
                            stats = await _panel_stats(panels, panel)
                            if not stats:
                                await ctx.send_report(
                                    "uptimepanel", f"🔴 panel unreachable: {panel.name_panel}")
                        except Exception:
                            await ctx.send_report(
                                "uptimepanel", f"🔴 panel error: {panel.name_panel}")

    # ── backups (backupbot) ──────────────────────────────────────
    @register_plugin("job", "backupbot", meta={"cron": "0 */5 * * *"})
    class BackupJob(Job):
        async def run(self, ctx: JobContext) -> None:
            from mirza.jobs.backup import run_backup
            try:
                await run_backup(ctx)
            except Exception:
                log.exception("backup failed")


def _register() -> None:
    if not registry.has("job", "notifications"):
        _register_jobs()


_register()


# ── helpers ──────────────────────────────────────────────────────
async def _flag(ctx: JobContext, key: str) -> dict:
    async with ctx.session_factory() as s:
        val = await _setting(s, key, {})
        return val if isinstance(val, dict) else {}


def _parse_expire(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        return int(float(str(raw).replace("D", "").replace("d", "").strip()))
    except ValueError:
        return None


def _days_s(raw: str | None) -> int:
    days = _parse_expire(raw) or 30
    return days * 86400


def _base() -> str:
    from mirza.config import get_settings
    s = get_settings()
    return f"https://{s.domain_hosts}"


async def _settle(ctx: JobContext, svc, order) -> None:
    if order.invoice_id:
        await svc.settle_direct_buy(order)
    else:
        cashback = 0
        await svc.settle_wallet_topup(order, cashback_pct=cashback)


async def _panel_stats(panels, panel) -> dict:
    from mirza.panels.service import PanelService as _P
    adapter = _P._adapter_for(panel)
    try:
        return await adapter.system_stats()
    finally:
        await adapter.close()
