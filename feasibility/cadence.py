"""Payment cadence clipped to the program horizon."""

from __future__ import annotations

from datetime import date

from feasibility.models import (
    Client,
    CreditorRules,
    Offer,
    add_months,
    default_first_payment_date,
    end_of_month,
    is_end_of_month,
)


def first_payment_date(client: Client, offer: Offer) -> date:
    return offer.first_payment_date or default_first_payment_date(client)


def cadence_through_horizon(start: date, horizon: date) -> list[date]:
    """Monthly cadence dates from ``start`` through ``horizon`` inclusive.

    Non-EOM dates keep the original day-of-month (clamped), computed from
    ``start`` each month so Feb 28 does not drift into Mar 28.
    """
    if start > horizon:
        return []
    eom = is_end_of_month(start)
    out: list[date] = []
    i = 0
    while True:
        d = add_months(start, i)
        if eom:
            d = end_of_month(d)
        if d > horizon:
            break
        out.append(d)
        i += 1
    return out


def k_max_for(client: Client, offer: Offer, rules: CreditorRules) -> tuple[list[date], int]:
    start = first_payment_date(client, offer)
    cadence = [
        d
        for d in cadence_through_horizon(start, client.last_draft_date)
        if d > client.as_of_date
    ]
    k_max = min(rules.max_payments, rules.max_terms, len(cadence))
    return cadence, k_max
