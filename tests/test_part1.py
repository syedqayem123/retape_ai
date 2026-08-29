"""Part 1 unit tests: money, floors/shapes, simulation, and schedule invariants."""

from __future__ import annotations

from datetime import date

from feasibility.engine import Result, ScheduleRow, evaluate_offer
from feasibility.models import (
    Client,
    CreditorRules,
    LedgerEntry,
    Offer,
    load_case,
    offer_total_cents,
)
from feasibility.money import mul_round_half_up
from feasibility.payments import (
    balloon_payments,
    even_payments,
    even_split,
    is_non_decreasing,
    min_payments,
    respects_floors,
    staircase_payments,
    structural_segments,
)
from feasibility.simulate import simulate
from feasibility.validate import schedule_is_valid


def _rules(**overrides) -> CreditorRules:
    base = dict(
        max_terms=12,
        max_payments=12,
        min_payment_cents=2500,
        max_token_pays=6,
        min_payment_tiers=[],
        even_pays=False,
        is_ballooning_allowed=False,
        max_segments=2,
        bank_fee_cents=0,
        program_fee_pct=0.0,
    )
    base.update(overrides)
    return CreditorRules(**base)



def test_mul_round_half_up_avoids_float_drift():
    assert mul_round_half_up(0.145, 100) == 15


def test_decreasing_payments_fail_non_decreasing_and_validation():
    assert is_non_decreasing([2500, 2500, 3000])
    assert not is_non_decreasing([3000, 2000])
    rules = _rules(
        even_pays=False,
        is_ballooning_allowed=True,
        max_token_pays=12,
        min_payment_cents=100,
        bank_fee_cents=0,
        program_fee_pct=0.0,
    )
    assert not respects_floors([3000, 2000], rules)

    client = Client(
        draft_amount_cents=10000,
        draft_day=1,
        first_draft_date=date(2026, 1, 1),
        last_draft_date=date(2026, 4, 1),
        as_of_date=date(2025, 12, 31),
        current_balance_cents=0,
        ledger=[
            LedgerEntry(date(2026, 1, 1), 10000, "credit"),
            LedgerEntry(date(2026, 2, 1), 10000, "credit"),
            LedgerEntry(date(2026, 3, 1), 10000, "credit"),
        ],
    )
    offer = Offer(
        creditor="DecrCo",
        current_balance_cents=5000,
        original_balance_cents=5000,
        settlement_pct=1.0,
        first_payment_date=date(2026, 1, 31),
    )
    result = Result(
        feasible=True,
        pay_shape_used="even",
        schedule=[
            ScheduleRow(date(2026, 1, 31), 3000, 0, 0, 7000),
            ScheduleRow(date(2026, 2, 28), 2000, 0, 0, 15000),
        ],
    )
    assert schedule_is_valid(client, offer, rules, result) is False


def test_even_remainder_on_latest_and_exact_sum():
    rules = _rules(even_pays=True, max_token_pays=12, min_payment_cents=1)
    p = even_payments(3, 100, rules)
    assert p == [33, 33, 34]
    assert sum(p) == 100
    assert even_split(6, 50000)[0] <= even_split(6, 50000)[-1]


def test_token_pay_cap_in_min_sequence():
    rules = _rules(max_token_pays=2, min_payment_cents=2500)
    mins = min_payments(4, rules)
    assert mins[:2] == [2500, 2500]
    assert mins[2] >= 2501


def test_tier_floors_from_payment_seven():
    rules = _rules(min_payment_tiers=[(7, 5000)], max_token_pays=6)
    mins = min_payments(8, rules)
    assert all(p == 2500 for p in mins[:6])
    assert all(p >= 5000 for p in mins[6:])


def test_staircase_does_not_dump_slack_as_single_balloon():
    rules = _rules(max_segments=2, max_token_pays=6, min_payment_cents=2500)
    p = staircase_payments(6, 30000, rules)
    assert p is not None
    assert sum(p) == 30000
    assert p[-1] != 30000 - sum(p[:-1]) or len(set(p)) == 1 or p.count(p[-1]) >= 2
    # last high run has length >= 2 (not a one-payment balloon)
    assert p.count(p[-1]) >= 2 or structural_segments(p) == 1


def test_max_segments_caps_distinct_levels():
    rules = _rules(max_segments=2, max_token_pays=6, min_payment_tiers=[(7, 5000)])
    p = staircase_payments(12, 60000, rules)
    assert p is not None
    assert structural_segments(p) <= 2
    assert all(x >= 5000 for x in p[6:])


def test_structural_segments_are_distinct_amounts():
    assert structural_segments([1, 1, 2]) == 2
    rules = _rules(max_segments=1, max_token_pays=12, min_payment_cents=1)
    # 100 / 3 is not equal; remainder would be [33, 33, 34] — two levels.
    assert staircase_payments(3, 100, rules) is None
    assert staircase_payments(2, 100, rules) == [50, 50]


def test_balloon_absorbs_remainder_on_last_payment():
    rules = _rules(is_ballooning_allowed=True, max_token_pays=6)
    p = balloon_payments(4, 20000, rules)
    assert p is not None
    assert p[:-1] == min_payments(4, rules)[:-1]
    assert p[-1] == 20000 - sum(p[:-1])
    assert p[-1] >= p[-2]


def test_same_day_credits_before_debits_can_hit_zero():
    client = Client(
        draft_amount_cents=10000,
        draft_day=1,
        first_draft_date=date(2026, 1, 1),
        last_draft_date=date(2026, 3, 1),
        as_of_date=date(2025, 12, 31),
        current_balance_cents=0,
        ledger=[
            LedgerEntry(date(2026, 1, 31), 10000, "credit"),
            LedgerEntry(date(2026, 1, 31), 4000, "debit"),
        ],
    )
    ok, bals = simulate(
        client,
        bank_fee_cents=0,
        creditor_payments={date(2026, 1, 31): 6000},
        program_fees={},
    )
    assert ok
    assert bals[date(2026, 1, 31)] == 0


def test_case1_invariants():
    client, offer, rules = load_case("cases/case1_feasible_even")
    r = evaluate_offer(client, offer, rules)
    assert r.feasible and r.schedule
    assert r.pay_shape_used == "even"
    pays = [row.creditor_payment_cents for row in r.schedule if row.creditor_payment_cents]
    assert sum(pays) == offer_total_cents(offer)
    assert max(pays) - min(pays) <= 1
    assert all(row.balance_cents >= 0 for row in r.schedule)
    assert all(row.date <= client.last_draft_date for row in r.schedule)
    first_pay = min(row.date for row in r.schedule if row.creditor_payment_cents > 0)
    assert all(
        row.date >= first_pay
        for row in r.schedule
        if row.program_fee_cents > 0
    )


def test_case3_balloon_and_zero_balance_path():
    client, offer, rules = load_case("cases/case3_balloon")
    r = evaluate_offer(client, offer, rules)
    assert r.feasible and r.pay_shape_used == "balloon"
    pays = [row.creditor_payment_cents for row in r.schedule if row.creditor_payment_cents]
    assert pays[-1] >= pays[0]
    assert all(row.date <= client.last_draft_date for row in r.schedule)
    assert all(row.balance_cents >= 0 for row in r.schedule)


def test_case4_tiers_and_tokens():
    client, offer, rules = load_case("cases/case4_tiers")
    r = evaluate_offer(client, offer, rules)
    assert r.feasible and r.pay_shape_used == "staircase"
    pays = [row.creditor_payment_cents for row in r.schedule if row.creditor_payment_cents]
    assert all(p >= 5000 for p in pays[6:])
    assert sum(1 for p in pays if p == rules.min_payment_cents) <= rules.max_token_pays
    assert structural_segments(pays) <= rules.max_segments


def test_fee_only_date_has_no_bank_fee():
    """Fewer creditor payments than cadence dates can leave a fee-only month."""
    client = Client(
        draft_amount_cents=20000,
        draft_day=1,
        first_draft_date=date(2026, 1, 1),
        last_draft_date=date(2026, 4, 1),
        as_of_date=date(2025, 12, 31),
        current_balance_cents=0,
        ledger=[
            LedgerEntry(date(2026, 1, 1), 20000, "credit"),
            LedgerEntry(date(2026, 2, 1), 20000, "credit"),
            LedgerEntry(date(2026, 3, 1), 20000, "credit"),
            LedgerEntry(date(2026, 4, 1), 20000, "credit"),
        ],
    )
    offer = Offer(
        creditor="FeeOnlyCo",
        current_balance_cents=10000,
        original_balance_cents=40000,
        settlement_pct=1.0,
        first_payment_date=date(2026, 1, 31),
    )
    # 100% of 10000 = 10000 offer; 50% of 40000 = 20000 program fee.
    # k_max = 3 cadence dates through Apr 1 (Jan 31, Feb 28, Mar 31).
    rules = _rules(
        even_pays=True,
        max_terms=1,
        max_payments=1,
        min_payment_cents=100,
        max_token_pays=4,
        bank_fee_cents=500,
        program_fee_pct=0.5,
        max_segments=1,
    )
    r = evaluate_offer(client, offer, rules)
    assert r.feasible
    fee_only = [
        row
        for row in r.schedule
        if row.creditor_payment_cents == 0 and row.program_fee_cents > 0
    ]
    assert fee_only
    assert all(row.bank_fee_cents == 0 for row in fee_only)


def test_infeasible_reports_additional_funds():
    client, offer, rules = load_case("cases/case2_infeasible_minima")
    r = evaluate_offer(client, offer, rules)
    assert r.feasible is False
    assert r.schedule is None
    assert r.additional_funds is not None


def test_omitted_first_payment_defaults_to_eom():
    client, offer, rules = load_case("cases/case1_feasible_even")
    offer.first_payment_date = None
    r = evaluate_offer(client, offer, rules)
    assert r.feasible
    assert r.schedule[0].date == date(2026, 1, 31)


def test_load_offer_accepts_creditor_balance_cents(tmp_path):
    from feasibility.models import load_offer

    p = tmp_path / "offer.json"
    p.write_text(
        '{"creditor": "X", "creditor_balance_cents": 999,'
        ' "original_balance_cents": 1000, "settlement_pct": 0.5}'
    )
    offer = load_offer(p)
    assert offer.current_balance_cents == 999
    assert offer_total_cents(offer) == 500
