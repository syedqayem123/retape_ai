"""Part 2: minimum lump sum, monthly increment, and guardrails."""

from __future__ import annotations

from datetime import date

from feasibility.engine import evaluate_offer
from feasibility.models import Client, CreditorRules, LedgerEntry, Offer, load_case
from feasibility.simulate import simulate


def test_case2_minima_and_guardrails():
    client, offer, rules = load_case("cases/case2_infeasible_minima")
    r = evaluate_offer(client, offer, rules)
    assert r.feasible is False
    af = r.additional_funds
    assert af is not None
    assert af.lump_sum.amount_cents == 10000
    assert af.lump_sum.within_guardrail is True
    assert af.lump_sum.reason == ""
    assert af.lump_sum.date is not None
    assert client.as_of_date < af.lump_sum.date <= client.last_draft_date
    assert af.monthly_increment.amount_cents == 2500
    assert af.monthly_increment.num_drafts == 5
    assert af.monthly_increment.within_guardrail is True
    assert af.monthly_increment.reason == ""


def test_increment_n_matches_future_credits():
    client, offer, rules = load_case("cases/case2_infeasible_minima")
    r = evaluate_offer(client, offer, rules)
    n_credits = sum(
        1 for e in client.ledger if e.type == "credit" and e.date > client.as_of_date
    )
    assert r.additional_funds.monthly_increment.num_drafts == n_credits


def test_structural_infeasibility_fails_guardrail():
    """Floors that exceed the offer cannot be fixed with extra cash."""
    client = Client(
        draft_amount_cents=50000,
        draft_day=1,
        first_draft_date=date(2026, 1, 1),
        last_draft_date=date(2026, 4, 1),
        as_of_date=date(2025, 12, 31),
        current_balance_cents=0,
        ledger=[
            LedgerEntry(date(2026, 1, 1), 50000, "credit"),
            LedgerEntry(date(2026, 2, 1), 50000, "credit"),
            LedgerEntry(date(2026, 3, 1), 50000, "credit"),
            LedgerEntry(date(2026, 4, 1), 50000, "credit"),
        ],
    )
    offer = Offer(
        creditor="FloorCo",
        current_balance_cents=10000,
        original_balance_cents=10000,
        settlement_pct=1.0,
        first_payment_date=date(2026, 1, 31),
    )
    rules = CreditorRules(
        max_terms=4,
        max_payments=4,
        min_payment_cents=50000,
        max_token_pays=4,
        min_payment_tiers=[],
        even_pays=True,
        is_ballooning_allowed=False,
        max_segments=1,
        bank_fee_cents=0,
        program_fee_pct=0.0,
    )
    r = evaluate_offer(client, offer, rules)
    assert r.feasible is False
    assert r.additional_funds is not None
    assert r.additional_funds.lump_sum.within_guardrail is False
    assert "legal shape" in r.additional_funds.lump_sum.reason
    assert r.additional_funds.monthly_increment.within_guardrail is False


def test_increment_exceeds_cap():
    """One useful draft and a large shortfall pushes X above the $100 cap."""
    client = Client(
        draft_amount_cents=1000,
        draft_day=1,
        first_draft_date=date(2026, 1, 1),
        last_draft_date=date(2026, 2, 1),
        as_of_date=date(2025, 12, 31),
        current_balance_cents=0,
        ledger=[
            LedgerEntry(date(2026, 1, 1), 1000, "credit"),
            LedgerEntry(date(2026, 2, 1), 1000, "credit"),
        ],
    )
    # Cadence: Jan 31 only (Feb 28 > Feb 1 horizon). Offer 20000 + fee 0.
    # One useful draft of 1000; need ~19000 more on that date => X=19000
    # and the Feb 1 increment does not help payments. Cap = max(10000, 400)=10000.
    offer = Offer(
        creditor="CapCo",
        current_balance_cents=20000,
        original_balance_cents=20000,
        settlement_pct=1.0,
        first_payment_date=date(2026, 1, 31),
    )
    rules = CreditorRules(
        max_terms=1,
        max_payments=1,
        min_payment_cents=100,
        max_token_pays=1,
        min_payment_tiers=[],
        even_pays=True,
        is_ballooning_allowed=False,
        max_segments=1,
        bank_fee_cents=0,
        program_fee_pct=0.0,
    )
    r = evaluate_offer(client, offer, rules)
    assert r.feasible is False
    inc = r.additional_funds.monthly_increment
    assert inc.amount_cents > 10000
    assert inc.within_guardrail is False
    assert "cap" in inc.reason


def test_increment_not_capped_by_late_useful_drafts():
    """Feb 1 is before last cadence but after the only payment date (Jan 31).

    Old bound ceil(lump_hi / 2) was 12_500; the first draft must carry X=24_000.
    """
    client = Client(
        draft_amount_cents=1000,
        draft_day=1,
        first_draft_date=date(2026, 1, 1),
        last_draft_date=date(2026, 3, 1),
        as_of_date=date(2025, 12, 31),
        current_balance_cents=0,
        ledger=[
            LedgerEntry(date(2026, 1, 1), 1000, "credit"),
            LedgerEntry(date(2026, 2, 1), 1000, "credit"),
            LedgerEntry(date(2026, 3, 1), 1000, "credit"),
        ],
    )
    offer = Offer(
        creditor="LateDraftCo",
        current_balance_cents=25000,
        original_balance_cents=25000,
        settlement_pct=1.0,
        first_payment_date=date(2026, 1, 31),
    )
    rules = CreditorRules(
        max_terms=1,
        max_payments=1,
        min_payment_cents=100,
        max_token_pays=1,
        min_payment_tiers=[],
        even_pays=True,
        is_ballooning_allowed=False,
        max_segments=1,
        bank_fee_cents=0,
        program_fee_pct=0.0,
    )
    r = evaluate_offer(client, offer, rules)
    assert r.feasible is False
    assert r.additional_funds.monthly_increment.amount_cents == 24000
    assert r.additional_funds.monthly_increment.num_drafts == 3


def test_extra_credit_same_day_applies_before_debits():
    client = Client(
        draft_amount_cents=0,
        draft_day=1,
        first_draft_date=date(2026, 1, 1),
        last_draft_date=date(2026, 1, 31),
        as_of_date=date(2025, 12, 31),
        current_balance_cents=0,
        ledger=[
            LedgerEntry(date(2026, 1, 31), 4000, "debit"),
        ],
    )
    ok, bals = simulate(
        client,
        bank_fee_cents=0,
        creditor_payments={},
        extra_credits={date(2026, 1, 31): 4000},
    )
    assert ok
    assert bals[date(2026, 1, 31)] == 0
