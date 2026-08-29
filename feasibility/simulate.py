"""Date-ordered SDA simulation and front-loaded program-fee allocation."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from feasibility.models import Client


def future_ledger_by_date(client: Client) -> dict[date, tuple[int, int]]:
    """Credits and committed debits on dates strictly after ``as_of_date``."""
    by_date: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    for e in client.ledger:
        if e.date <= client.as_of_date:
            continue
        if e.type == "credit":
            by_date[e.date][0] += e.amount_cents
        else:
            by_date[e.date][1] += e.amount_cents
    return {d: (c, deb) for d, (c, deb) in by_date.items()}


def simulate(
    client: Client,
    *,
    bank_fee_cents: int,
    creditor_payments: dict[date, int],
    program_fees: dict[date, int] | None = None,
    extra_credits: dict[date, int] | None = None,
    extra_dates: list[date] | None = None,
) -> tuple[bool, dict[date, int]]:
    """Walk the SDA date by date.

    Credits (ledger + extras) apply before all debits on the same date.
    ``bank_fee_cents`` is charged only on dates with a creditor payment ``> 0``.

    ``extra_credits`` / ``extra_dates`` are for Part 2 (lump sum, extra draft
    days) and are unused in Part 1.

    Returns (never_went_negative, end-of-day balances for every simulated date).
    If a date goes negative, balances include dates up to (but not including)
    the failing date.
    """
    fees = program_fees or {}
    extras = extra_credits or {}
    ledger = future_ledger_by_date(client)

    dates = set(ledger) | set(creditor_payments) | set(fees) | set(extras)
    if extra_dates:
        dates.update(extra_dates)
    ordered = sorted(d for d in dates if d > client.as_of_date)

    balance = client.current_balance_cents
    end_balances: dict[date, int] = {}
    for d in ordered:
        credit, committed_debit = ledger.get(d, (0, 0))
        credit += extras.get(d, 0)
        payment = creditor_payments.get(d, 0)
        fee = fees.get(d, 0)
        bank = bank_fee_cents if payment > 0 else 0
        balance += credit
        balance -= committed_debit + payment + fee + bank
        if balance < 0:
            return False, end_balances
        end_balances[d] = balance
    return True, end_balances


def frontload_program_fee(
    *,
    eligible_dates: list[date],
    timeline: list[date],
    end_balances: dict[date, int],
    program_fee_total: int,
) -> dict[date, int] | None:
    """Assign program fee as early as possible without going negative later.

    At eligible date ``t``, take ``min(remaining, min end-of-day balances on
    dates ``>= t``)``. That bottleneck is the most we can debit at ``t`` while
    leaving later forced payments feasible. Returns None if the fee cannot be
    fully collected.
    """
    if program_fee_total < 0:
        return None
    remaining = program_fee_total
    balances = dict(end_balances)
    fees: dict[date, int] = {}
    for t in eligible_dates:
        if remaining <= 0:
            break
        future = [balances[d] for d in timeline if d >= t and d in balances]
        if not future:
            cap = 0
        else:
            cap = min(future)
        take = min(remaining, max(0, cap))
        if take:
            fees[t] = take
            remaining -= take
            for d in timeline:
                if d >= t and d in balances:
                    balances[d] -= take
    if remaining > 0:
        return None
    return fees
