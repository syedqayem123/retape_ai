"""Creditor-payment floors and even / balloon / staircase constructors."""

from __future__ import annotations

from feasibility.models import CreditorRules


def positional_floor(index_1based: int, rules: CreditorRules, tokens_used: int) -> int:
    """Minimum legal size of the payment at this 1-based position."""
    floor = rules.min_payment_cents
    for from_n, cents in rules.min_payment_tiers:
        if index_1based >= from_n:
            floor = max(floor, cents)
    if tokens_used >= rules.max_token_pays:
        floor = max(floor, rules.min_payment_cents + 1)
    return floor


def min_payments(k: int, rules: CreditorRules) -> list[int]:
    """Smallest non-decreasing sequence that meets floors and the token cap.

    Token pays (exactly ``min_payment_cents``) are used as early as possible.
    """
    out: list[int] = []
    tokens = 0
    prev = 0
    for i in range(1, k + 1):
        fl = max(positional_floor(i, rules, tokens), prev)
        out.append(fl)
        if fl == rules.min_payment_cents:
            tokens += 1
        prev = fl
    return out


def is_non_decreasing(payments: list[int]) -> bool:
    """ASSIGNMENT §5.3: each creditor payment is ≥ the one before it."""
    return all(payments[i] >= payments[i - 1] for i in range(1, len(payments)))


def respects_floors(payments: list[int], rules: CreditorRules) -> bool:
    if not is_non_decreasing(payments):
        return False
    tokens = 0
    for i, p in enumerate(payments, start=1):
        if p < positional_floor(i, rules, tokens):
            return False
        if p == rules.min_payment_cents:
            tokens += 1
            if tokens > rules.max_token_pays:
                return False
    return True


def even_split(n: int, total: int) -> list[int]:
    """``n`` non-decreasing parts summing to ``total``; remainder on the latest."""
    if n <= 0:
        return []
    base, rem = divmod(total, n)
    return [base] * (n - rem) + [base + 1] * rem


def even_payments(k: int, total: int, rules: CreditorRules) -> list[int] | None:
    if k <= 0 or total < 0:
        return None
    payments = even_split(k, total)
    if not respects_floors(payments, rules):
        return None
    return payments


def balloon_payments(k: int, total: int, rules: CreditorRules) -> list[int] | None:
    if k <= 0 or total < 0:
        return None
    mins = min_payments(k, rules)
    prefix_sum = sum(mins[:-1]) if k > 1 else 0
    last = total - prefix_sum
    payments = (mins[:-1] if k > 1 else []) + [last]
    if not respects_floors(payments, rules):
        return None
    return payments


def structural_segments(payments: list[int]) -> int:
    """Number of distinct payment amounts (ASSIGNMENT payment levels)."""
    return len(set(payments))


def _runs(values: list[int]) -> list[tuple[int, int]]:
    """Half-open index ranges of equal consecutive values."""
    if not values:
        return []
    runs: list[tuple[int, int]] = []
    start = 0
    for i in range(1, len(values) + 1):
        if i == len(values) or values[i] != values[start]:
            runs.append((start, i))
            start = i
    return runs


def _merge_early_runs(mins: list[int], max_segments: int) -> list[int] | None:
    """Raise earlier runs to the next level until segment count fits."""
    values = list(mins)
    if max_segments < 1:
        return None
    while structural_segments(values) > max_segments:
        runs = _runs(values)
        if len(runs) < 2:
            return None
        a0, a1 = runs[0]
        b0, _b1 = runs[1]
        lifted = values[b0]
        for i in range(a0, a1):
            values[i] = lifted
    return values


def _apply_slack_on_suffix(mins: list[int], last_len: int, slack: int) -> list[int] | None:
    k = len(mins)
    if last_len < 1 or last_len > k:
        return None
    start = k - last_len
    prefix = mins[:start]
    suffix_target = sum(mins[start:]) + slack
    floor_level = max(mins[start:]) if last_len else 0
    if prefix:
        floor_level = max(floor_level, prefix[-1])
    if suffix_target < floor_level * last_len:
        return None
    suffix = even_split(last_len, suffix_target)
    if suffix[0] < floor_level:
        return None
    return prefix + suffix


def staircase_payments(k: int, total: int, rules: CreditorRules) -> list[int] | None:
    """Lex-min non-decreasing payments with at most ``max_segments`` levels.

    Slack after the floor sequence is parked on the latest run (as equal as
    possible). A brand-new high run is not allowed to have length 1 when
    ``k >= 2`` — that would be a balloon, which this constructor must not use.
    """
    if k <= 0 or total < 0:
        return None
    mins = min_payments(k, rules)
    merged = _merge_early_runs(mins, rules.max_segments)
    if merged is None:
        return None
    slack = total - sum(merged)
    if slack < 0:
        return None
    if slack == 0:
        return merged if respects_floors(merged, rules) else None

    runs = _runs(merged)
    nseg = len(runs)
    min_new_last = 1 if k == 1 else 2

    if nseg >= rules.max_segments:
        last_start, last_end = runs[-1]
        last_len = last_end - last_start
        cand = _apply_slack_on_suffix(merged, last_len, slack)
        if (
            cand is not None
            and sum(cand) == total
            and respects_floors(cand, rules)
            and structural_segments(cand) <= rules.max_segments
        ):
            return cand
        return None

    for last_len in range(min_new_last, k + 1):
        cand = _apply_slack_on_suffix(merged, last_len, slack)
        if cand is None or sum(cand) != total:
            continue
        if not respects_floors(cand, rules):
            continue
        if structural_segments(cand) > rules.max_segments:
            continue
        return cand
    return None


def payments_for_k(k: int, total: int, rules: CreditorRules) -> list[int] | None:
    if rules.even_pays:
        return even_payments(k, total, rules)
    if rules.is_ballooning_allowed:
        return balloon_payments(k, total, rules)
    return staircase_payments(k, total, rules)


def shape_name(rules: CreditorRules) -> str:
    if rules.even_pays:
        return "even"
    if rules.is_ballooning_allowed:
        return "balloon"
    return "staircase"
