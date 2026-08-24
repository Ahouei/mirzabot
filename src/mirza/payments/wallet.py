"""Wallet ledger - append-only balance history (new in rewrite)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, func, select as sa_select

from mirza.db import Base


class LedgerEntry(Base):
    __tablename__ = "balance_ledger"

    id: int = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
    user_id: str = Column(String(64), index=True, nullable=False)
    delta: int = Column(Integer, nullable=False)
    reason: str = Column(String(64), nullable=False)   # purchase|topup|cashback|refund|gift|commission|wheel|admin
    ref: str | None = Column(String(200), nullable=True)   # order id / invoice id
    note: str | None = Column(Text, nullable=True)
    created_at: datetime = Column(DateTime, server_default=func.now())  # type: ignore[assignment]


@dataclass
class BalanceChange:
    ok: bool
    new_balance: int = 0
    error: str | None = None


class WalletService:
    """Every balance mutation writes a ledger row - auditable by construction."""

    def __init__(self, session):
        self.session = session

    async def get_balance(self, user_id: str) -> int:
        from mirza.models import User
        res = await self.session.execute(
            sa_select(User.balance).where(User.id == user_id))
        return res.scalar_one_or_none() or 0

    async def change(self, user_id: str, delta: int, reason: str,
                     ref: str | None = None, note: str | None = None,
                     allow_negative: bool = False) -> BalanceChange:
        from mirza.models import User
        res = await self.session.execute(sa_select(User).where(User.id == user_id))
        user = res.scalar_one_or_none()
        if user is None:
            return BalanceChange(ok=False, error="user not found")
        new_balance = user.balance + delta
        if new_balance < 0 and not allow_negative:
            return BalanceChange(ok=False, error="insufficient balance",
                                 new_balance=user.balance)
        user.balance = new_balance
        self.session.add(LedgerEntry(user_id=user_id, delta=delta, reason=reason,
                                     ref=ref, note=note))
        await self.session.commit()
        return BalanceChange(ok=True, new_balance=new_balance)

    async def history(self, user_id: str, limit: int = 20) -> list[LedgerEntry]:
        res = await self.session.execute(
            sa_select(LedgerEntry).where(LedgerEntry.user_id == user_id)
            .order_by(LedgerEntry.id.desc()).limit(limit))
        return list(res.scalars().all())
