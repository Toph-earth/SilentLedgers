"""
data_generator.py — Synthetic account and transaction generator.

This module produces Account and Transaction objects for Silent Ledger,
plus a side-channel ground-truth dict for testing.

It does NOT touch NetworkX, does NOT know about detection, and does NOT
know about the API. Its only outputs are:
  - accounts: List[Account]
  - transactions: List[Transaction]
  - ground_truth: dict[transaction_id, pattern_type]

The ground_truth dict is a generator-internal side artifact. It never
touches models.Transaction, never appears on the API, and is consumed only
by the verification script. This keeps the API schema free of any
ground-truth field while still giving exact per-transaction labels for
computing precision/recall on the planted edges.

Design reference: the synthetic data strategy — account categories,
behavior parameterization, blending, and scale.

------------------------------------------------------------------------
CHANGES FROM THE PREVIOUS VERSION
------------------------------------------------------------------------
1. Category ratios adjusted to increase laundering label density:
   NORMAL_RATIO 0.75 -> 0.65, STRUCTURING 0.08 -> 0.10,
   LAYERING 0.08 -> 0.12, ROUND_TRIPPING 0.09 -> 0.13.
   Yields ~70 laundering accounts instead of 50.

2. Structuring rings now built by OVERLAPPING SAMPLES rather than by
   slicing the shuffled account list into disjoint chunks. Previously
   each structuring account participated in exactly one ring, capping
   total structuring edges at roughly n_structuring. With overlap, the
   same account can be a source in multiple rings (realistic — real
   mules appear in many funnels). Number of rings is now configurable
   and independent of account count.

3. Layering chains also built by OVERLAPPING SAMPLES. Same reasoning —
   real launderers run multiple chains through the same intermediary.
   Number of chains is now configurable.

4. Round-tripping rings also built by OVERLAPPING SAMPLES. Same
   reasoning — real cycles repeat with overlapping membership.

5. Structuring transfers per source increased from 1-3 to 2-4, further
   raising edge density per ring.

6. Round-tripping cycles per ring increased from 2-4 to 3-6, further
   raising edge density per ring.

Why the overlap matters (the lesson from tuning): the total number of
laundering edges produced by any pattern is bounded by
(accounts_in_pattern x average_edges_per_account). With disjoint chunks,
each account contributes ~1 edge, so density scales linearly with
account count and caps out fast. With overlap, you multiply the number
of pattern instances independently of account count, and density scales
with instance count. Overlap also makes the graph more realistic: real
laundering networks reuse mules, intermediaries, and cycles.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

from models import Account, AccountType, PatternType, Transaction


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Master seed for reproducibility. Change this to regenerate a different
# but still deterministic dataset.
RANDOM_SEED = 42

# Scale targets. The strategy doc calls for 150–250 accounts and
# 2,000–4,000 transactions. We pick the middle of both ranges.
TOTAL_ACCOUNTS = 200
TOTAL_DAYS = 90  # simulated history window

# CHANGED: category proportions rebalanced to raise laundering label
# density. Sum to 1.0 exactly.
NORMAL_RATIO = 0.65
STRUCTURING_RATIO = 0.10
LAYERING_RATIO = 0.12
ROUND_TRIPPING_RATIO = 0.13

# CHANGED: number of overlapping pattern instances. These are decoupled
# from account counts so label density is controlled directly.
# Rule of thumb: 1.0x account count produces ~moderate density,
# 1.5x produces ~dense. Tune both up if recall numbers are too noisy.
N_STRUCTURING_RINGS = 24
N_LAYERING_CHAINS = 28
N_ROUND_TRIPPING_RINGS = 30

# CHANGED: ring/chain shape parameters. Held here so they're easy to
# tune without hunting through the generation loops.
STRUCTURING_SOURCES_PER_RING = 3    # + 1 mule = 4 accounts per ring
LAYERING_CHAIN_LENGTH = 4           # 3 hops per chain
ROUND_TRIPPING_RING_SIZE = 3        # 3 edges per cycle

# Reporting threshold. Transactions below this are less scrutinized.
REPORTING_THRESHOLD = 10_000.0

# Currency for the whole dataset
CURRENCY = "USD"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _lognormal_amount(mu: float, sigma: float, cap: float) -> float:
    """Draw a long-tailed amount, clipped to [10, cap].

    Real transaction amounts are long-tailed: most small, occasional large.
    Never uniform, never normal. Uniform amounts are the fastest way to make
    synthetic data look fake.
    """
    val = random.lognormvariate(mu, sigma)
    return round(min(max(val, 10.0), cap), 2)


def _jitter_seconds(base: float, jitter_frac: float = 0.3) -> float:
    """Add randomness to a time interval so intervals aren't suspiciously fixed."""
    lo = base * (1 - jitter_frac)
    hi = base * (1 + jitter_frac)
    return random.uniform(lo, hi)


def _rand_timestamp_within(start: datetime, end: datetime) -> datetime:
    """Return a random timestamp between start and end, inclusive."""
    delta_seconds = (end - start).total_seconds()
    return start + timedelta(seconds=random.uniform(0, delta_seconds))


# ---------------------------------------------------------------------------
# Account generation
# ---------------------------------------------------------------------------

def _build_accounts(rng_seed: int) -> Tuple[List[Account], Dict[str, str]]:
    """Create all accounts across every category.

    Returns (accounts, category_map) where category_map is a dict mapping
    account_id -> category string ("normal", "structuring", "layering",
    "round_tripping"). The category map is generator-internal ground truth
    used for assembling rings and chains. It does not leave this module
    via the public API.
    """
    random.seed(rng_seed)

    n_normal = int(TOTAL_ACCOUNTS * NORMAL_RATIO)
    n_structuring = int(TOTAL_ACCOUNTS * STRUCTURING_RATIO)
    n_layering = int(TOTAL_ACCOUNTS * LAYERING_RATIO)
    n_round_tripping = TOTAL_ACCOUNTS - n_normal - n_structuring - n_layering

    accounts: List[Account] = []
    category_map: Dict[str, str] = {}

    # Simulation window for account creation dates. Accounts are opened at
    # different times across a longer history than the transaction window,
    # which is realistic.
    history_start = datetime.now(timezone.utc) - timedelta(days=TOTAL_DAYS * 3)
    history_end = datetime.now(timezone.utc) - timedelta(days=TOTAL_DAYS)

    def _make_account(idx: int, category: str) -> Account:
        # Roughly 70% individuals, 30% businesses for normal accounts.
        # Businesses are more common in laundering categories because
        # structuring is easier to disguise as business activity.
        if category == "normal":
            acc_type = (
                AccountType.BUSINESS if random.random() < 0.30
                else AccountType.INDIVIDUAL
            )
        else:
            acc_type = (
                AccountType.BUSINESS if random.random() < 0.55
                else AccountType.INDIVIDUAL
            )

        acc = Account(
            account_id=f"ACC_{idx:03d}",
            name=f"Account {idx:03d}",
            account_type=acc_type,
            is_laundering=(category != "normal"),
            created_at=_rand_timestamp_within(history_start, history_end),
        )
        category_map[acc.account_id] = category
        return acc

    idx = 1
    for _ in range(n_normal):
        accounts.append(_make_account(idx, "normal"))
        idx += 1
    for _ in range(n_structuring):
        accounts.append(_make_account(idx, "structuring"))
        idx += 1
    for _ in range(n_layering):
        accounts.append(_make_account(idx, "layering"))
        idx += 1
    for _ in range(n_round_tripping):
        accounts.append(_make_account(idx, "round_tripping"))
        idx += 1

    return accounts, category_map


# ---------------------------------------------------------------------------
# Transaction generation — one function per pattern family
# ---------------------------------------------------------------------------

class _TxnFactory:
    """Stateful counter for transaction IDs so they are unique and ordered."""

    def __init__(self) -> None:
        self._n = 0

    def next_id(self) -> str:
        self._n += 1
        return f"TXN_{self._n:05d}"


def _record_ground_truth(
    ground_truth: Dict[str, str],
    txn: Transaction,
    pattern: PatternType,
) -> Transaction:
    """Stamp a transaction as belonging to a planted pattern.

    This is the single point where ground truth is attached. It records
    into the side-channel dict only — the Transaction model is never
    touched, so no ground-truth field ever leaks into the API.
    """
    ground_truth[txn.transaction_id] = pattern.value
    return txn


def _normal_transactions_for(
    account: Account,
    counterparties: List[str],
    window_start: datetime,
    window_end: datetime,
    txn: _TxnFactory,
    min_count: int = 3,
    max_count: int = 30,
) -> List[Transaction]:
    """Generate a plausible set of normal transactions for one account.

    Amounts are long-tailed lognormal. Counterparties come from a small
    fixed pool for this account plus occasional one-offs. Timestamps are
    jittered, not evenly spaced.

    Normal transactions are NEVER recorded in ground_truth.
    """
    out: List[Transaction] = []

    # Poisson-ish count via a simple approximation: draw mean, jitter.
    mean_count = (min_count + max_count) / 2
    count = max(min_count, int(random.gauss(mean_count, (max_count - min_count) / 4)))

    # A small recurring set of counterparties for this account.
    recurring_n = min(len(counterparties), max(2, count // 4))
    recurring = random.sample(counterparties, recurring_n)

    for _ in range(count):
        # 85% to recurring counterparties, 15% to random ones.
        if random.random() < 0.85 and recurring:
            dest = random.choice(recurring)
        else:
            dest = random.choice(counterparties)

        # Skip self-transfers.
        if dest == account.account_id:
            continue

        # Long-tailed amount. Individuals transact smaller than businesses.
        if account.account_type == AccountType.BUSINESS:
            amount = _lognormal_amount(mu=7.2, sigma=1.1, cap=25_000.0)
        else:
            amount = _lognormal_amount(mu=5.8, sigma=1.2, cap=12_000.0)

        ts = _rand_timestamp_within(window_start, window_end)
        out.append(
            Transaction(
                transaction_id=txn.next_id(),
                source_account=account.account_id,
                dest_account=dest,
                amount=amount,
                timestamp=ts,
                currency=CURRENCY,
            )
        )

    return out


def _structuring_transactions(
    mule: Account,
    sources: List[Account],
    exit_account: str,
    window_start: datetime,
    window_end: datetime,
    txn: _TxnFactory,
    ground_truth: Dict[str, str],
) -> List[Transaction]:
    """Generate a structuring ring feeding into a single mule.

    Each source sends 2–4 amounts just below the reporting threshold
    (CHANGED from 1–3 to raise edge density per ring). Amounts are drawn
    from uniform(0.80, 0.99) * threshold, so no round numbers. Window is
    2–10 days.

    Every transaction emitted here is stamped in ground_truth as
    "structuring".
    """
    out: List[Transaction] = []
    window_days = random.uniform(2, 10)
    ring_start = _rand_timestamp_within(window_start, window_end)
    ring_end = min(ring_start + timedelta(days=window_days), window_end)

    for source in sources:
        # CHANGED: 2–4 transfers per source, not 1–3.
        n_transfers = random.randint(2, 4)
        for _ in range(n_transfers):
            amount = round(random.uniform(0.80, 0.99) * REPORTING_THRESHOLD, 2)
            ts = _rand_timestamp_within(ring_start, ring_end)
            t = Transaction(
                transaction_id=txn.next_id(),
                source_account=source.account_id,
                dest_account=mule.account_id,
                amount=amount,
                timestamp=ts,
                currency=CURRENCY,
            )
            _record_ground_truth(ground_truth, t, PatternType.STRUCTURING)
            out.append(t)

    # The mule forwards the aggregated amount to an exit account, shortly
    # after the last inbound transfer. This forwarding edge is also part
    # of the structuring pattern.
    if out:
        total_in = sum(t.amount for t in out)
        last_ts = max(t.timestamp for t in out)
        forward = Transaction(
            transaction_id=txn.next_id(),
            source_account=mule.account_id,
            dest_account=exit_account,
            amount=round(total_in * random.uniform(0.90, 0.97), 2),
            timestamp=last_ts + timedelta(hours=random.uniform(2, 24)),
            currency=CURRENCY,
        )
        _record_ground_truth(ground_truth, forward, PatternType.STRUCTURING)
        out.append(forward)

    return out


def _layering_transactions(
    chain: List[Account],
    window_start: datetime,
    window_end: datetime,
    txn: _TxnFactory,
    ground_truth: Dict[str, str],
) -> List[Transaction]:
    """Generate a layering chain: A -> B -> C -> ... with decay per hop.

    Each hop passes along 85–95% of what it received. Inter-hop delay is
    jittered between 2 and 48 hours.

    Every hop is stamped in ground_truth as "layering".
    """
    out: List[Transaction] = []

    # Initial amount drawn to be realistic — large enough to be worth
    # layering, small enough to not hit the threshold in a single hop.
    current_amount = round(random.uniform(5_000.0, 9_500.0), 2)
    current_time = _rand_timestamp_within(window_start, window_end)

    for i in range(len(chain) - 1):
        src = chain[i]
        dst = chain[i + 1]
        t = Transaction(
            transaction_id=txn.next_id(),
            source_account=src.account_id,
            dest_account=dst.account_id,
            amount=current_amount,
            timestamp=current_time,
            currency=CURRENCY,
        )
        _record_ground_truth(ground_truth, t, PatternType.LAYERING)
        out.append(t)

        # Apply decay and advance time.
        decay = random.uniform(0.85, 0.95)
        current_amount = round(current_amount * decay, 2)
        hop_hours = _jitter_seconds(random.uniform(2, 48))
        current_time = current_time + timedelta(hours=hop_hours)
        if current_time >= window_end:
            break

    return out


def _round_tripping_transactions(
    ring: List[Account],
    window_start: datetime,
    window_end: datetime,
    txn: _TxnFactory,
    ground_truth: Dict[str, str],
) -> List[Transaction]:
    """Generate a round-tripping ring: X -> Y -> Z -> X, possibly repeated.

    Each cycle loses a small amount at each hop. Total cycle time is
    jittered. Repeated cycles are separated by a gap so they look like
    separate business activity, not a single loop.

    Every hop in every cycle is stamped in ground_truth as
    "round_tripping".
    """
    out: List[Transaction] = []

    initial_amount = round(random.uniform(3_000.0, 8_000.0), 2)
    cycle_start = _rand_timestamp_within(window_start, window_end)

    # CHANGED: 3–6 cycles per ring (was 2–4). Raises edge density.
    n_cycles = random.randint(3, 6)

    for _ in range(n_cycles):
        amount = initial_amount
        ts = cycle_start

        for i in range(len(ring)):
            src = ring[i]
            dst = ring[(i + 1) % len(ring)]
            t = Transaction(
                transaction_id=txn.next_id(),
                source_account=src.account_id,
                dest_account=dst.account_id,
                amount=amount,
                timestamp=ts,
                currency=CURRENCY,
            )
            _record_ground_truth(ground_truth, t, PatternType.ROUND_TRIPPING)
            out.append(t)

            decay = random.uniform(0.88, 0.97)
            amount = round(amount * decay, 2)
            hop_hours = _jitter_seconds(random.uniform(6, 72))
            ts = ts + timedelta(hours=hop_hours)
            if ts >= window_end:
                break

        # Gap between cycles.
        gap_hours = _jitter_seconds(random.uniform(24, 120))
        cycle_start = ts + timedelta(hours=gap_hours)
        if cycle_start >= window_end:
            break

    return out


# ---------------------------------------------------------------------------
# Blending — give every laundering account some normal activity
# ---------------------------------------------------------------------------

def _blend_normal_activity(
    accounts: List[Account],
    laundering_ids: List[str],
    all_account_ids: List[str],
    window_start: datetime,
    window_end: datetime,
    txn: _TxnFactory,
) -> List[Transaction]:
    """Give each laundering account 2–5 normal-looking transactions.

    This is the step that prevents the demo from undermining itself. A mule
    that only ever appears in a funnel is trivially detectable by isolation
    alone. Real laundering accounts have other activity.

    Blend transactions are NOT recorded in ground_truth — they are meant
    to look normal.
    """
    out: List[Transaction] = []
    by_id = {a.account_id: a for a in accounts}

    for acc_id in laundering_ids:
        acc = by_id[acc_id]
        # Counterparties drawn from normal accounts, not other launderers,
        # so the laundering cluster connects to the rest of the graph.
        normal_counterparties = [
            aid for aid in all_account_ids if aid not in laundering_ids
        ][:80]
        if not normal_counterparties:
            continue

        n = random.randint(2, 5)
        for _ in range(n):
            dest = random.choice(normal_counterparties)
            amount = _lognormal_amount(mu=6.0, sigma=1.0, cap=5_000.0)
            ts = _rand_timestamp_within(window_start, window_end)
            out.append(
                Transaction(
                    transaction_id=txn.next_id(),
                    source_account=acc.account_id,
                    dest_account=dest,
                    amount=amount,
                    timestamp=ts,
                    currency=CURRENCY,
                )
            )

    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_dataset(
    seed: int = RANDOM_SEED,
) -> Tuple[List[Account], List[Transaction], Dict[str, str]]:
    """Generate the full synthetic dataset.

    Returns (accounts, transactions, ground_truth).

    ground_truth is a dict mapping transaction_id -> pattern_type string
    ("structuring", "layering", "round_tripping") for every transaction
    planted as part of a laundering pattern. Normal and blend transactions
    are absent from the dict. This dict is the exact label source consumed
    by the verification script — it never touches models.py and never
    appears on the API.

    Regenerating with the same seed produces the same dataset. Regenerating
    with a different seed produces a new one with the same statistical
    properties.

    This is the only function other modules should call.
    """
    random.seed(seed)

    accounts, category_map = _build_accounts(seed)
    all_ids = [a.account_id for a in accounts]
    by_id = {a.account_id: a for a in accounts}

    # Simulation window for transactions (the most recent TOTAL_DAYS).
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(days=TOTAL_DAYS)

    txn = _TxnFactory()
    all_transactions: List[Transaction] = []
    ground_truth: Dict[str, str] = {}

    # --- Normal activity ------------------------------------------------
    normal_ids = [aid for aid, cat in category_map.items() if cat == "normal"]
    for aid in normal_ids:
        acc = by_id[aid]
        # Counterparties: 8–15 others, drawn from the full population so the
        # normal graph is well-connected.
        pool_size = random.randint(8, 15)
        counterparties = random.sample(all_ids, min(pool_size, len(all_ids)))
        all_transactions.extend(
            _normal_transactions_for(acc, counterparties, window_start, window_end, txn)
        )

    # --- Structuring rings ---------------------------------------------
    # CHANGED: overlapping sampling. Each ring is drawn independently from
    # the structuring account pool, so the same account can be a source in
    # multiple rings (and occasionally a mule in one ring while being a
    # source in another). This reflects real laundering topology and lets
    # us control label density via N_STRUCTURING_RINGS independently of
    # how many structuring accounts exist.
    structuring_ids = [
        aid for aid, cat in category_map.items() if cat == "structuring"
    ]
    random.shuffle(structuring_ids)

    for _ in range(N_STRUCTURING_RINGS):
        # Need 1 mule + N sources. If we don't have enough structuring
        # accounts, skip the ring (will not happen at current scale, but
        # guard against shrinking account counts later).
        ring_size = STRUCTURING_SOURCES_PER_RING + 1
        if len(structuring_ids) < ring_size:
            break
        ring_sample = random.sample(structuring_ids, ring_size)
        mule_id = ring_sample[0]
        sources = [by_id[aid] for aid in ring_sample[1:]]
        # Exit account is a normal account, so the mule connects outward.
        exit_account = random.choice(normal_ids)
        all_transactions.extend(
            _structuring_transactions(
                mule=by_id[mule_id],
                sources=sources,
                exit_account=exit_account,
                window_start=window_start,
                window_end=window_end,
                txn=txn,
                ground_truth=ground_truth,
            )
        )

    # --- Layering chains -----------------------------------------------
    # CHANGED: overlapping sampling. Each chain is drawn independently, so
    # the same intermediary can appear in multiple chains. Real launderers
    # reuse nodes; this makes the graph more realistic and raises edge
    # density to a level where precision/recall numbers are stable.
    layering_ids = [aid for aid, cat in category_map.items() if cat == "layering"]
    random.shuffle(layering_ids)

    for _ in range(N_LAYERING_CHAINS):
        if len(layering_ids) < LAYERING_CHAIN_LENGTH:
            break
        chain_ids = random.sample(layering_ids, LAYERING_CHAIN_LENGTH)
        chain = [by_id[aid] for aid in chain_ids]
        all_transactions.extend(
            _layering_transactions(chain, window_start, window_end, txn, ground_truth)
        )

    # --- Round-tripping rings ------------------------------------------
    # CHANGED: overlapping sampling. Rings share membership, which is what
    # real round-tripping networks look like over months.
    rt_ids = [aid for aid, cat in category_map.items() if cat == "round_tripping"]
    random.shuffle(rt_ids)

    for _ in range(N_ROUND_TRIPPING_RINGS):
        if len(rt_ids) < ROUND_TRIPPING_RING_SIZE:
            break
        ring_ids = random.sample(rt_ids, ROUND_TRIPPING_RING_SIZE)
        ring = [by_id[aid] for aid in ring_ids]
        all_transactions.extend(
            _round_tripping_transactions(
                ring, window_start, window_end, txn, ground_truth
            )
        )

    # --- Blend normal activity into laundering accounts ----------------
    laundering_ids = [aid for aid, cat in category_map.items() if cat != "normal"]
    all_transactions.extend(
        _blend_normal_activity(
            accounts, laundering_ids, all_ids, window_start, window_end, txn
        )
    )

    # Interleave transactions in time order, so a raw list read top-to-bottom
    # does not show a suspicious block at the end.
    all_transactions.sort(key=lambda t: t.timestamp)

    return accounts, all_transactions, ground_truth


# ---------------------------------------------------------------------------
# CLI entry point for manual inspection
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    accounts, transactions, ground_truth = generate_dataset()
    laundering_count = sum(1 for a in accounts if a.is_laundering)

    print(f"Generated {len(accounts)} accounts ({laundering_count} laundering)")
    print(f"Generated {len(transactions)} transactions")
    print(f"Ground-truth labels: {len(ground_truth)} transactions")
    print()

    # Breakdown by pattern
    from collections import Counter
    breakdown = Counter(ground_truth.values())
    for pattern, count in breakdown.items():
        print(f"  {pattern}: {count} transactions")
    print()

    # Sanity check: how many distinct accounts appear in ground truth?
    gt_txns = [t for t in transactions if t.transaction_id in ground_truth]
    accounts_in_gt = set()
    for t in gt_txns:
        accounts_in_gt.add(t.source_account)
        accounts_in_gt.add(t.dest_account)
    print(f"Distinct accounts in ground truth: {len(accounts_in_gt)}")
    print()

    print("First 5 transactions:")
    for t in transactions[:5]:
        tag = ground_truth.get(t.transaction_id, "-")
        print(
            f"  {t.transaction_id}  {t.source_account} -> {t.dest_account}  "
            f"{t.amount:>10.2f}  {t.timestamp.isoformat()}  [{tag}]"
        )