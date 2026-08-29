"""Candidate implementation goes here.

Implement ``evaluate_offer`` so that it satisfies the rules in ASSIGNMENT.md and
the example expectations in tests/test_cases.py. The dataclasses below define the
required OUTPUT shape (see ASSIGNMENT.md "Output"). You may add helpers, modules,
or rewrite internals freely, but keep ``evaluate_offer``'s signature and the
serialized shape of ``Result`` (so the runner and tests work).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

from feasibility.cadence import k_max_for
from feasibility.funding import apply_guardrails, search_additional_funds
from feasibility.models import (
    Client,
    CreditorRules,
    Offer,
    offer_total_cents,
    program_fee_cents,
)
from feasibility.payments import payments_for_k, shape_name
from feasibility.simulate import frontload_program_fee, simulate
from feasibility.validate import schedule_is_valid


@dataclass
class ScheduleRow:
    date: date
    creditor_payment_cents: int
    program_fee_cents: int
    bank_fee_cents: int
    balance_cents: int


@dataclass
class FundsOption:
    amount_cents: int
    within_guardrail: bool
    reason: str
    # lump-sum only:
    date: date | None = None
    # monthly-increment only:
    num_drafts: int | None = None


@dataclass
class AdditionalFunds:
    lump_sum: FundsOption
    monthly_increment: FundsOption


@dataclass
class Result:
    feasible: bool
    # One of "even", "staircase", or "balloon" — the shape your solution produced
    # (driven by the creditor flags). None when infeasible.
    pay_shape_used: str | None = None
    schedule: list[ScheduleRow] | None = None
    additional_funds: AdditionalFunds | None = None

    def to_dict(self) -> dict:
        out: dict = {"feasible": self.feasible, "pay_shape_used": self.pay_shape_used}
        out["schedule"] = (
            [
                {
                    "date": r.date.isoformat(),
                    "creditor_payment_cents": r.creditor_payment_cents,
                    "program_fee_cents": r.program_fee_cents,
                    "bank_fee_cents": r.bank_fee_cents,
                    "balance_cents": r.balance_cents,
                }
                for r in self.schedule
            ]
            if self.schedule is not None
            else None
        )
        if self.additional_funds is None:
            out["additional_funds"] = None
        else:
            def opt(o: FundsOption) -> dict:
                d = {
                    "amount_cents": o.amount_cents,
                    "within_guardrail": o.within_guardrail,
                    "reason": o.reason,
                }
                if o.date is not None:
                    d["date"] = o.date.isoformat()
                if o.num_drafts is not None:
                    d["num_drafts"] = o.num_drafts
                return d

            out["additional_funds"] = {
                "lump_sum": opt(self.additional_funds.lump_sum),
                "monthly_increment": opt(self.additional_funds.monthly_increment),
            }
        return out


def best_schedule(
    client: Client,
    offer: Offer,
    rules: CreditorRules,
    extra_credits: dict[date, int] | None = None,
) -> Result | None:
    """Return the best feasible Part 1 Result, or None if no ``k`` works.

    ``extra_credits`` is a date -> extra SDA credit map (Part 2 lump / increment).
    """
    total = offer_total_cents(offer)
    fee_total = program_fee_cents(offer, rules)
    cadence, k_max = k_max_for(client, offer, rules)
    shape = shape_name(rules)
    extras = extra_credits or {}

    best: tuple[tuple[int, ...], int, list[ScheduleRow]] | None = None

    for k in range(1, k_max + 1):
        payments = payments_for_k(k, total, rules)
        if payments is None or sum(payments) != total:
            continue

        creditor = {cadence[i]: payments[i] for i in range(k)}
        extra_dates = list(cadence)

        ok, no_fee_balances = simulate(
            client,
            bank_fee_cents=rules.bank_fee_cents,
            creditor_payments=creditor,
            program_fees={},
            extra_credits=extras,
            extra_dates=extra_dates,
        )
        if not ok:
            continue

        timeline = sorted(no_fee_balances)
        fee_map = frontload_program_fee(
            eligible_dates=cadence,
            timeline=timeline,
            end_balances=no_fee_balances,
            program_fee_total=fee_total,
        )
        if fee_map is None:
            continue

        ok, with_fee_balances = simulate(
            client,
            bank_fee_cents=rules.bank_fee_cents,
            creditor_payments=creditor,
            program_fees=fee_map,
            extra_credits=extras,
            extra_dates=extra_dates,
        )
        if not ok:
            continue

        rows: list[ScheduleRow] = []
        for d in cadence:
            pay = creditor.get(d, 0)
            fee = fee_map.get(d, 0)
            bank = rules.bank_fee_cents if pay > 0 else 0
            if pay == 0 and fee == 0:
                continue
            rows.append(
                ScheduleRow(
                    date=d,
                    creditor_payment_cents=pay,
                    program_fee_cents=fee,
                    bank_fee_cents=bank,
                    balance_cents=with_fee_balances[d],
                )
            )

        score = tuple(fee_map.get(d, 0) for d in cadence)
        if best is None or score > best[0]:
            candidate = Result(
                feasible=True,
                pay_shape_used=shape,
                schedule=rows,
                additional_funds=None,
            )
            if schedule_is_valid(client, offer, rules, candidate, extra_credits=extras):
                best = (score, k, rows)

    if best is None:
        return None
    return Result(
        feasible=True,
        pay_shape_used=shape,
        schedule=best[2],
        additional_funds=None,
    )


def evaluate_offer(client: Client, offer: Offer, rules: CreditorRules) -> Result:
    """Evaluate a single offer. See ASSIGNMENT.md for the full specification.

    Return a Result with feasible=True and a schedule when the offer fits, or
    feasible=False with additional_funds (minimum lump sum AND minimum monthly
    increment) when it does not.
    """
    found = best_schedule(client, offer, rules)
    if found is not None:
        return found

    L, lump_date, lump_found, X, n_drafts, inc_found = search_additional_funds(
        client, offer, rules, best_schedule
    )
    lump_within, lump_reason, inc_within, inc_reason = apply_guardrails(
        client, offer, L, lump_found, X, inc_found
    )
    return Result(
        feasible=False,
        pay_shape_used=None,
        schedule=None,
        additional_funds=AdditionalFunds(
            lump_sum=FundsOption(
                amount_cents=L,
                within_guardrail=lump_within,
                reason=lump_reason,
                date=lump_date,
            ),
            monthly_increment=FundsOption(
                amount_cents=X,
                within_guardrail=inc_within,
                reason=inc_reason,
                num_drafts=n_drafts,
            ),
        ),
    )
