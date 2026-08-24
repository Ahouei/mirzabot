"""ORM models - full parity with the legacy 29-table MySQL schema.

Legacy quirks intentionally preserved where behavior depends on them:
- user.id is the Telegram id (string PK)
- wide VARCHAR columns, JSON stored as TEXT (upgraded to JSONB here)
- invoice.id_invoice doubles as the public /sub/ token
Improvements: real FKs on hot paths (invoice.user_id, payment.invoice_id),
proper indexes, JSONB instead of serialized strings.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from mirza.db import Base
from mirza.db.base import PortableJSON

# Portable JSON: JSONB on postgres, serialized TEXT on sqlite (tests/dev).
JSONType = PortableJSON()


class User(Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)   # telegram id
    username: Mapped[str] = mapped_column(String(255), default="none")
    step: Mapped[str] = mapped_column(String(255), default="none")
    balance: Mapped[int] = mapped_column(Integer, default=0)        # major units x100
    user_status: Mapped[str] = mapped_column("User_Status", String(64), default="active")
    block_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone_number: Mapped[str] = mapped_column(String(64), default="none")
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    # FSM scratch slots kept for parity with Processing_value{,_one,_tow,_four}
    pv: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True, default=dict)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_time: Mapped[int] = mapped_column(Integer, default=0)
    is_agent: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_level: Mapped[str] = mapped_column(String(32), default="f")
    affiliates_count: Mapped[int] = mapped_column(Integer, default=0)
    referrer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    custom_name: Mapped[str | None] = mapped_column(String(128))
    max_username_len: Mapped[int] = mapped_column(Integer, default=100)
    register_at: Mapped[str] = mapped_column(String(64), default="none")
    verify_status: Mapped[str] = mapped_column(String(32), default="1")
    card_payment_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    invite_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    price_discount: Mapped[int] = mapped_column(Integer, default=0)
    hide_miniapp_guide: Mapped[bool] = mapped_column(Boolean, default=False)
    max_buy_agent: Mapped[int] = mapped_column(Integer, default=0)
    join_channel_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    check_status: Mapped[str] = mapped_column(String(32), default="0")
    bot_type: Mapped[str | None] = mapped_column(String(64))          # main / whitelabel child
    score: Mapped[int] = mapped_column(Integer, default=0)
    limit_change_loc: Mapped[int] = mapped_column(Integer, default=0)
    status_cron: Mapped[bool] = mapped_column(Boolean, default=True)
    expire_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token: Mapped[str | None] = mapped_column(String(100), nullable=True)  # mini-app session
    lang: Mapped[str] = mapped_column(String(5), default="fa")

    __table_args__ = (
        Index("ix_user_token", "token"),
        Index("ix_user_referrer", "referrer_id"),
    )


class Admin(Base):
    __tablename__ = "admin"

    id_admin: Mapped[str] = mapped_column(String(64), primary_key=True)  # telegram id
    username: Mapped[str] = mapped_column(String(200), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200), default="")
    rule: Mapped[str] = mapped_column(String(200), default="administrator")


class Channel(Base):
    __tablename__ = "channels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    remark: Mapped[str] = mapped_column(String(200), default="")
    link_join: Mapped[str] = mapped_column(String(200), default="")
    link: Mapped[str] = mapped_column(String(200), default="")


class Help(Base):
    __tablename__ = "help"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name_os: Mapped[str] = mapped_column(String(500))
    media_os: Mapped[str] = mapped_column(String(5000))
    type_media_os: Mapped[str] = mapped_column(String(100), default="photo")
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_os: Mapped[str] = mapped_column(Text)


class Setting(Base):
    """Wide key/value-ish settings table (legacy kept ~70 flat columns).

    Improvement: modeled as a proper KV store with typed values; a compatibility
    view exposes the old column names during migration.
    """
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(190), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(),
                                                 onupdate=func.now())


class MarzbanPanel(Base):
    """All backend panels regardless of adapter (legacy name kept)."""
    __tablename__ = "marzban_panel"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_panel: Mapped[str] = mapped_column(String(200), unique=True)
    name_panel: Mapped[str] = mapped_column(String(200))
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    url_panel: Mapped[str] = mapped_column(String(500))
    username_panel: Mapped[str] = mapped_column(String(500), default="")
    password_panel_encrypted: Mapped[str] = mapped_column(String(1000), default="")  # Fernet
    admin_id: Mapped[str | None] = mapped_column(String(64))            # owning admin
    agent_flag: Mapped[str] = mapped_column(String(16), default="f")
    sublink: Mapped[bool] = mapped_column(Boolean, default=True)
    config_mode: Mapped[str] = mapped_column(String(32), default="auto")  # auto|manual
    method_username: Mapped[str] = mapped_column(String(32), default="random")
    test_account: Mapped[bool] = mapped_column(Boolean, default=False)
    limit_panel: Mapped[int] = mapped_column(Integer, default=0)         # 0 = unlimited
    name_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    method_extend: Mapped[str] = mapped_column(String(32), default="extend")
    connect_on: Mapped[str | None] = mapped_column(String(64))
    link_sub_x: Mapped[str | None] = mapped_column(String(500))
    inbound_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    panel_type: Mapped[str] = mapped_column(String(40))                  # registry kind name
    inbound_status: Mapped[bool] = mapped_column(Boolean, default=False)
    inbound_deactive: Mapped[str | None] = mapped_column(Text)
    time_usertest: Mapped[int] = mapped_column(Integer, default=3)       # days
    val_usertest: Mapped[int] = mapped_column(Integer, default=1)        # GB
    secret_code: Mapped[str | None] = mapped_column(String(200))
    price_change_loc: Mapped[int] = mapped_column(Integer, default=0)
    price_extra_volume: Mapped[int] = mapped_column(Integer, default=0)
    price_custom_volume: Mapped[int] = mapped_column(Integer, default=0)
    price_custom_time: Mapped[int] = mapped_column(Integer, default=0)
    price_extra_time: Mapped[int] = mapped_column(Integer, default=0)
    main_volume: Mapped[int] = mapped_column(Integer, default=0)
    max_volume: Mapped[int] = mapped_column(Integer, default=0)
    main_time: Mapped[int] = mapped_column(Integer, default=0)
    max_time: Mapped[int] = mapped_column(Integer, default=0)
    status_extend: Mapped[bool] = mapped_column(Boolean, default=True)
    login_cache: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)  # token cache
    proxies_default: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    inbounds_default: Mapped[list[Any] | None] = mapped_column(JSONType, nullable=True)
    subvip: Mapped[bool] = mapped_column(Boolean, default=False)         # rewrite sub URL via /sub/
    change_loc: Mapped[bool] = mapped_column(Boolean, default=False)
    on_hold_test: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (Index("ix_marzban_panel_name", "name_panel"),)


class Category(Base):
    __tablename__ = "category"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(400))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Product(Base):
    __tablename__ = "product"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_product: Mapped[str] = mapped_column(String(200), unique=True)
    name_product: Mapped[str] = mapped_column(String(2000))
    price_product: Mapped[int] = mapped_column(Integer, default=0)
    volume_gb: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[str] = mapped_column(String(200), default="/all")   # panel name or /all
    service_days: Mapped[int] = mapped_column(Integer, default=30)
    agent_only: Mapped[str] = mapped_column(String(50), default="f")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_limit_reset: Mapped[str] = mapped_column(String(100), default="no_reset")
    one_buy_status: Mapped[bool] = mapped_column(Boolean, default=False)
    inbounds: Mapped[list[Any] | None] = mapped_column(JSONType, nullable=True)
    proxies: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"), nullable=True)
    hide_panel: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    __table_args__ = (Index("ix_product_location", "location"),)


class Invoice(Base):
    __tablename__ = "invoice"

    id_invoice: Mapped[str] = mapped_column(String(200), primary_key=True)  # = /sub/ token
    user_id: Mapped[str | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    username: Mapped[str | None] = mapped_column(String(300))
    service_location: Mapped[str] = mapped_column(String(300), default="")   # panel name
    time_sell: Mapped[str] = mapped_column(String(200), default="")
    product_name: Mapped[str | None] = mapped_column(String(200))
    price_product: Mapped[str] = mapped_column(String(200), default="0")
    volume: Mapped[str] = mapped_column(String(200), default="")
    service_time: Mapped[str] = mapped_column(String(200), default="")
    uuid: Mapped[str | None] = mapped_column(Text)                           # panel username
    note: Mapped[str | None] = mapped_column(String(700))
    user_info: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    bot_type: Mapped[str | None] = mapped_column(String(200))
    referral: Mapped[str | None] = mapped_column(String(100))
    time_cron: Mapped[str | None] = mapped_column(String(100))
    notifications: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict)                                              # {volume,time: bool}
    status: Mapped[str] = mapped_column(String(200), default="enable")

    __table_args__ = (
        Index("ix_invoice_user", "user_id"),
        Index("ix_invoice_uuid", "uuid"),
    )


class PaymentReport(Base):
    __tablename__ = "Payment_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(200), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[str] = mapped_column(String(200), default="")
    price: Mapped[int] = mapped_column(Integer, default=0)
    gateway_payload: Mapped[dict[str, Any] | str | None] = mapped_column(JSONType, nullable=True)
    payment_method: Mapped[str] = mapped_column(String(200), default="")
    payment_status: Mapped[str] = mapped_column(String(64), default="Unpaid")
    bot_type: Mapped[str | None] = mapped_column(String(200))
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoice.id_invoice"), nullable=True)

    __table_args__ = (Index("ix_payment_user", "user_id"),)


class Discount(Base):
    __tablename__ = "Discount"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(200), unique=True)
    discount_percent: Mapped[int] = mapped_column(Integer, default=0)
    usage_limit: Mapped[int] = mapped_column(Integer, default=0)      # 0 = unlimited
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    price_discount: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[str | None] = mapped_column(String(100))


class GiftCodeConsumed(Base):
    __tablename__ = "Giftcodeconsumed"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(200))
    user_id: Mapped[str] = mapped_column(String(64))
    consumed_at: Mapped[str] = mapped_column(String(100))

    __table_args__ = (Index("ix_gift_code", "code"),)


class PaySetting(Base):
    __tablename__ = "PaySetting"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name_pay: Mapped[str] = mapped_column(String(200), unique=True)   # e.g. zarinpal_merchant
    value_pay: Mapped[str | None] = mapped_column(Text)


class DiscountSell(Base):
    __tablename__ = "DiscountSell"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(200))
    product_code: Mapped[str] = mapped_column(String(200))
    percent: Mapped[int] = mapped_column(Integer, default=0)


class Affiliate(Base):
    __tablename__ = "affiliates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    description: Mapped[str | None] = mapped_column(Text)
    status_commission: Mapped[bool] = mapped_column(Boolean, default=False)
    discount: Mapped[int] = mapped_column(Integer, default=0)
    price_discount: Mapped[int] = mapped_column(Integer, default=0)
    porsant_one_buy: Mapped[int] = mapped_column(Integer, default=0)  # commission %
    id_media: Mapped[str | None] = mapped_column(String(200))


class ShopSetting(Base):
    __tablename__ = "shopSetting"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(190))
    value_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)


class CancelService(Base):
    __tablename__ = "cancel_service"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64))
    invoice_id: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(100))


class ServiceOther(Base):
    """Extra-volume / extra-time purchases attached to an invoice."""
    __tablename__ = "service_other"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32))     # volume|time|changeloc
    amount: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(100))


class CardNumber(Base):
    __tablename__ = "card_number"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bank_name: Mapped[str] = mapped_column(String(200))
    card_number: Mapped[str] = mapped_column(String(200))
    card_holder: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AgentRequest(Base):
    __tablename__ = "Requestagent"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(300), default="")
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="pending")


class TopicId(Base):
    """Maps report kinds to forum-topic ids in the report supergroup."""
    __tablename__ = "topicid"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report: Mapped[str] = mapped_column(String(64), unique=True)      # e.g. paymentreport
    topic_id: Mapped[int] = mapped_column(Integer, default=0)


class ManualSell(Base):
    __tablename__ = "manualsell"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64))
    product_code: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[str] = mapped_column(String(64))               # admin id


class WheelList(Base):
    __tablename__ = "wheel_list"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64))
    spun_at: Mapped[str] = mapped_column(String(100))
    first_name: Mapped[str | None] = mapped_column(String(200))
    wheel_code: Mapped[str | None] = mapped_column(String(100))
    prize: Mapped[int] = mapped_column(Integer, default=0)


class Botsaz(Base):
    """White-label child-bot registry."""
    __tablename__ = "botsaz"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(64))
    bot_token: Mapped[str] = mapped_column(String(200), unique=True)
    admin_ids: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    bot_username: Mapped[str] = mapped_column(String(200))
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    hide_panel: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String(100), default="")


class AppLink(Base):
    __tablename__ = "app"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    link: Mapped[str] = mapped_column(String(500))


class LogsApi(Base):
    __tablename__ = "logs_api"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route: Mapped[str] = mapped_column(String(200))
    actor_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReagentReport(Base):
    __tablename__ = "reagent_report"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[str] = mapped_column(String(64))
    referred_id: Mapped[str] = mapped_column(String(64))
    bought: Mapped[bool] = mapped_column(Boolean, default=False)
    commission: Mapped[int] = mapped_column(Integer, default=0)


class SupportMessage(Base):
    __tablename__ = "support_message"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracking: Mapped[str] = mapped_column(String(100))
    department_id: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[str] = mapped_column(String(100))


class Departman(Base):
    __tablename__ = "departman"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(600))
