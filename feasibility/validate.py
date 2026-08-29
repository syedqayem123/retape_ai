"""Hard-constraint checks for a feasible schedule (ASSIGNMENT §5)."""

from __future__ import annotations

from feasibility.cadence import k_max_for
from feasibility.models import (
    Client,
    CreditorRules,
    Offer,
    offer_total_cents,
    program_fee_cents,
)
from feasibility.payments import is_non_decreasing, respects_floors, structural_segments
from feasibility.simulate import simulate


def schedule_is_valid(
    client: Client,
    offer: Offer,
    rules: CreditorRules,
    result,
    extra_credits: dict | None = None,
) -> bool:
    if not result.feasible or not result.schedule:
        return False
    cadence, k_max = k_max_for(client, offer, rules)
    rows = result.schedule
    if any(row.date > client.last_draft_date for row in rows):
        return False
    if any(row.date not in cadence for row in rows):
        return False

    pay_rows = [row for row in rows if row.creditor_payment_cents > 0]
    payments = [row.creditor_payment_cents for row in pay_rows]
    k = len(payments)
    if k < 1 or k > k_max:
        return False
    if [row.date for row in pay_rows] != cadence[:k]:
        return False
    if sum(payments) != offer_total_cents(offer):
        return False
    if not is_non_decreasing(payments):
        return False
    if not respects_floors(payments, rules):
        return False

    if rules.even_pays:
        if max(payments) - min(payments) > 1:
            return False
    elif not rules.is_ballooning_allowed:
        if structural_segments(payments) > rules.max_segments:
            return False

    fee_total = sum(row.program_fee_cents for row in rows)
    if fee_total != program_fee_cents(offer, rules):
        return False
    first_pay = pay_rows[0].date
    if any(row.date < first_pay and row.program_fee_cents > 0 for row in rows):
        return False
    for row in rows:
        expected_bank = rules.bank_fee_cents if row.creditor_payment_cents > 0 else 0
        if row.bank_fee_cents != expected_bank:
            return False
        if row.balance_cents < 0:
            return False

    creditor = {row.date: row.creditor_payment_cents for row in rows}
    fees = {row.date: row.program_fee_cents for row in rows}
    ok, bals = simulate(
        client,
        bank_fee_cents=rules.bank_fee_cents,
        creditor_payments=creditor,
        program_fees=fees,
        extra_credits=extra_credits,
        extra_dates=list(cadence),
    )
    if not ok:
        return False
    return all(row.balance_cents == bals[row.date] for row in rows)
