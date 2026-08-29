"""Part 2: minimum lump sum and monthly draft increment when the offer is cash-infeasible."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import date, timedelta

from feasibility.cadence import k_max_for
from feasibility.models import Client, CreditorRules, Offer, offer_total_cents, program_fee_cents
from feasibility.money import mul_round_half_up
from feasibility.simulate import future_ledger_by_date


def future_draft_dates(client: Client) -> list[date]:
    """One entry per future ledger credit (the drafts). Duplicates allowed."""
    return [
        e.date
        for e in client.ledger
        if e.type == "credit" and e.date > client.as_of_date
    ]


def lump_placement_date(client: Client) -> date | None:
    """Earliest date strictly after as_of and on or before the horizon."""
    d = client.as_of_date + timedelta(days=1)
    if d > client.last_draft_date:
        return None
    return d


def cash_upper_bound(client: Client, offer: Offer, rules: CreditorRules) -> int:
    _cadence, k_max = k_max_for(client, offer, rules)
    committed = sum(debit for _, debit in future_ledger_by_date(client).values())
    return (
        offer_total_cents(offer)
        + program_fee_cents(offer, rules)
        + k_max * rules.bank_fee_cents
        + committed
    )


def _min_feasible(hi: int, feasible: Callable[[int], bool]) -> tuple[int, bool]:
    """Smallest ``x`` in ``0..hi`` for which ``feasible(x)``. If none, ``(hi, False)``."""
    if hi < 0:
        return 0, False
    if feasible(0):
        return 0, True
    if not feasible(hi):
        return hi, False
    lo, bound = 1, hi
    while lo < bound:
        mid = (lo + bound) // 2
        if feasible(mid):
            bound = mid
        else:
            lo = mid + 1
    return lo, True


def increment_extras(draft_dates: list[date], x: int) -> dict[date, int]:
    extras: dict[date, int] = defaultdict(int)
    for d in draft_dates:
        extras[d] += x
    return dict(extras)


def search_additional_funds(
    client: Client,
    offer: Offer,
    rules: CreditorRules,
    oracle: Callable,
) -> tuple[int, date | None, bool, int, int, bool]:
    """Return (L, lump_date, lump_ok, X, N, inc_ok) before guardrails."""
    drafts = future_draft_dates(client)
    n_drafts = len(drafts)
    placement = lump_placement_date(client)
    lump_hi = cash_upper_bound(client, offer, rules)
    # A draft after the first payment cannot fund that payment, so X may need
    # to be as large as the lump (one early draft carrying the whole gap).
    inc_hi = lump_hi

    def lump_ok(amount: int) -> bool:
        if placement is None or amount < 0:
            return False
        return oracle(client, offer, rules, extra_credits={placement: amount}) is not None

    def inc_ok(x: int) -> bool:
        if not drafts:
            return oracle(client, offer, rules) is not None
        return oracle(client, offer, rules, extra_credits=increment_extras(drafts, x)) is not None

    L, lump_found = _min_feasible(lump_hi, lump_ok)
    X, inc_found = _min_feasible(inc_hi, inc_ok)
    return L, placement, lump_found, X, n_drafts, inc_found


def apply_guardrails(
    client: Client,
    offer: Offer,
    lump_amount: int,
    lump_found: bool,
    increment_amount: int,
    increment_found: bool,
) -> tuple[bool, str, bool, str]:
    offer_total = offer_total_cents(offer)
    lump_cap = mul_round_half_up(0.65, offer_total)
    inc_cap = max(10000, mul_round_half_up(0.40, client.draft_amount_cents))

    if not lump_found:
        lump_within, lump_reason = False, "funding cannot create a legal shape / cannot cover the gap"
    elif lump_amount > lump_cap:
        lump_within, lump_reason = False, "lump exceeds 65% of offer total"
    else:
        lump_within, lump_reason = True, ""

    if not increment_found:
        inc_within, inc_reason = False, "funding cannot create a legal shape / cannot cover the gap"
    elif increment_amount > inc_cap:
        inc_within, inc_reason = False, "monthly increment exceeds cap"
    else:
        inc_within, inc_reason = True, ""

    return lump_within, lump_reason, inc_within, inc_reason
