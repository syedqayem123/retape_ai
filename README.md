# Settlement Feasibility & Fee Engine — Take-home

Welcome, and thanks for taking the time. The full problem is in
[`ASSIGNMENT.md`](./ASSIGNMENT.md). This README is just orientation.

## The task in one line

Given a client's escrow account, a settlement offer, and a creditor's rules,
decide whether the offer is affordable (and schedule it, collecting our fee as
early as allowed) or — if not — compute the minimum extra funding needed.

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## Layout

```
hiring_takehome/
├── ASSIGNMENT.md
├── feasibility/
│   ├── models.py            # data models, JSON loaders, date/EOM helpers
│   ├── money.py             # round-half-up
│   ├── cadence.py           # horizon-clipped payment dates
│   ├── payments.py          # floors, even / balloon / staircase
│   ├── simulate.py          # ledger walk + fee front-load
│   ├── validate.py          # §5 schedule checks
│   ├── funding.py           # Part 2 binary search + guardrails
│   └── engine.py            # evaluate_offer
├── cases/
├── tests/
│   ├── test_smoke.py
│   ├── test_cases.py
│   ├── test_part1.py
│   └── test_part2.py
├── run.py
└── requirements.txt
```

## Run

```bash
# evaluate a single case (prints the Result as JSON)
python run.py cases/case1_feasible_even

# tests
pytest -q
```

`tests/test_smoke.py`, `tests/test_part1.py`, `tests/test_part2.py`, and
`tests/test_cases.py` should all pass.

## Approach

The engine searches payment count `k` from 1 through the horizon-clipped cadence
cap. For each `k` it builds a creditor-payment vector from the creditor flags,
simulates the SDA **without** program fee, then greedily front-loads the fee:
at each eligible cadence date it takes `min(remaining fee, min remaining
end-of-day balances from that date onward)`. That bottleneck is the most we can
debit today without making a later forced payment go negative.

Among feasible `k`, we keep the schedule whose fee vector on the cadence is
lexicographically largest (more fee earlier). Shape is reported from the flags,
not inferred from the numbers.

If no `k` works, Part 2 binary-searches extra funding: a single lump on the
earliest date after `as_of`, and a uniform add-on to every future draft, each
reusing that same oracle.

Alternatives considered: an ILP/solver (overkill at `k ≤ ~12`), and dumping all
surplus as fee on day one without a future-bottleneck check (that can starve
later payments).

## Payment-shape interpretation

- **Even** (`even_pays`): payments as equal as possible, remainder cents on the
  latest dates. This flag wins even if ballooning is also allowed.
- **Balloon** (`is_ballooning_allowed`, and not even): each prefix payment sits
  at the minimum legal floor (token pays used early; tiers and the
  non-decreasing constraint applied). The last payment absorbs the remainder.
- **Staircase** (neither flag): lexicographically smallest non-decreasing
  sequence that meets floors, sums to the offer, and uses at most
  `max_segments` structural levels. Slack after the floor sequence is spread
  evenly across the **latest run**. If floors already use `max_segments` levels,
  slack stays on that last run. If we would otherwise introduce a new high run,
  its length is at least 2 when `k ≥ 2` so we do not sneak in a balloon.
  `max_segments` counts **distinct payment amounts** (`[1, 1, 2]` is two levels).
  A 1¢ remainder split is therefore a second level unless `even_pays` is set
  (even pays ignore `max_segments` and still put remainder on the latest).

Token pays are payments exactly equal to `min_payment_cents`. After
`max_token_pays` of them, later payments must be at least one cent above the
base min (tiers may already force more).

## Assumptions and limitations

- Rounding is round-half-up via `Decimal` for rate × cents (so `0.145 × 100`
  is 15, not a float 14). Guardrails use the same helper.
- Cadence dates after the `k` creditor payments may collect leftover fee
  (fee-only; no bank fee). Nothing is scheduled after `last_draft_date`.
- Same-day ordering: all credits, then all debits (committed ledger + creditor
  + bank + program fee).
- Part 2 (infeasible offers): binary-search the smallest lump `L` on the
  earliest date after `as_of` and the smallest uniform increment `X` on every
  future ledger credit, using the same schedule oracle as Part 1. Extra cash
  cannot repair a schedule that violates creditor floors. Guardrails: lump
  `> 65%` of offer total, increment `> max(10000, 40% of draft)`.
- Known edges: very large `k` is still enumerable but not optimized; merging
  extra tier runs when they exceed `max_segments` lifts early runs to the next
  level (increases early payments); a last-run of length 1 that is **forced by
  tiers** is allowed even when ballooning is off.

