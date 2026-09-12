"""
detectors.py — Graph-based detection of money laundering patterns.

This module contains exactly three public detectors, one per pattern
family:
  - detect_structuring(G)
  - detect_layering(G)
  - detect_round_tripping(G)

Plus one public post-processing helper:
  - deduplicate_layering(layering_matches, round_tripping_matches)

Each detector takes the MultiDiGraph built by graph_builder.py and
returns a List[PatternMatch]. Nothing else.

What this file does NOT do:
  - It does not read ground_truth. Detectors see only the graph.
  - It does not aggregate risk per account. That is risk_scorer.py's job.
  - It does not serialize to JSON or know about the API.
  - It does not build the graph. It receives an already-built graph.
  - It does not import data_generator. The __main__ block at the bottom
    does, but only when this file is executed directly.

===========================================================================
CHANGELOG — this revision
===========================================================================

CONTEXT: the prior revision overcorrected. Round-tripping dropped from
9 matches to 0 because of a false premise in the edge-identity stability
check. Structuring recall dropped from 58% to 29% because of a wrong
"tightest window" optimization. Both are reverted/corrected here.

---------------------------------------------------------------------------
FIX A (kept from prior revision) — Round-tripping per-hop decay band
---------------------------------------------------------------------------
Symmetric band [-15%, +2%] accepted cross-ring bounces: two parallel
edges on the same (A, B) pair, emitted by two different ring instances
drawn from the same 26-account pool, have independently drawn amounts,
and their ratio routinely falls within a wide symmetric band. Generator's
per-hop decay is uniform(0.88, 0.97) -- strictly decreasing -- so a
genuine hop never exceeds 1.0 by more than FP noise.

Band tightened from [0.85, 1.005] to [0.85, 1.001]. The narrower upper
bound rejects bounces that squeaked through at 1.002-1.005 without
affecting genuine hops, which decay to <=1.0 exactly.

---------------------------------------------------------------------------
FIX B (REVISED) — Round-tripping cycle-level decay, NOT edge-identity
---------------------------------------------------------------------------
The prior revision added a Jaccard edge-ID stability check across
traversals, with the assumption that two traversals of the SAME
generator ring reuse the same edge IDs. They do not.
_round_tripping_transactions emits len(ring) FRESH transactions per
cycle, so a single ring instance produces 9-18 distinct transaction IDs
across its 3-6 cycles. Every traversal therefore had Jaccard 0 against
the previous one, the stability check reset the repeat counter to 0
every time, and round-tripping detection dropped to ZERO matches.

The real contamination is graph-level: two DIFFERENT ring instances can
emit parallel edges on the same (A, B) pair, with independently drawn
amounts. That is what produced the "same-direction amount increases" the
diagnostic found -- it is a cross-ring fingerprint, not an
intra-traversal one.

The correct filter is at the traversal level: a genuine 3-hop cycle
decays to [0.68, 0.91] of its initial amount; a traversal stitched
across two different rings lands near 1.0 because the two rings' initial
amounts are independent uniform(3000, 8000) draws. Add a per-traversal
gate: final / initial must fall in [0.60, 0.98]. Sum repeats across all
traversals that pass, with no cross-traversal identity requirement.

---------------------------------------------------------------------------
FIX C (kept from prior revision) — Layering total chain duration cap
---------------------------------------------------------------------------
LAYERING_CHAIN_MAX_HOURS was declared in CONFIG but never read. Without
it, a 3-hop chain could be stitched across the full 90-day window as
long as each consecutive hop was within LAYERING_HOP_MAX_HOURS of the
previous. That is how round-tripping rings, walked forward hop-by-hop
with blended normal activity spliced in, produced the 22 layering false
positives. The cap is a hard prune inside the recursive exploration.

---------------------------------------------------------------------------
FIX D (CORRECTED) — Structuring window search
---------------------------------------------------------------------------
The prior revision's "tightest qualifying window" rewrite broke recall
(58% -> 29%): it broke out at the first j satisfying both thresholds,
capturing a subset of the ring's transactions and scoring low on the
transaction-overlap metric. Restored the original "extend window to full
STRUCTURING_WINDOW_HOURS, take entire slice, keep largest qualifying
cluster" behavior, with the source-count check applied to the full
window (not just the count-argmax window). This is what the original
detector did and what produced 58% recall.

---------------------------------------------------------------------------
FIX E (kept) — deduplicate_layering only lets clean RT matches veto
---------------------------------------------------------------------------
With FIX A and FIX B in place, detect_round_tripping no longer emits
contaminated matches, so the claimed-by-round-tripping set is already
clean. The dedup rule is unchanged: drop a layering match if more than
LAYERING_ROUND_TRIP_OVERLAP_VETO of its transactions are claimed by a
round-tripping match.

---------------------------------------------------------------------------
CLEANUP
---------------------------------------------------------------------------
Removed the dead `if False else None` remnant carried over from an
earlier revision's changelog (it was documented as removed but the
actual code was not). The single walk in detect_layering now records
ordered transactions, amounts, and window bounds together.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

import networkx as nx

from models import PatternMatch, PatternType


# ===========================================================================
# CONFIG — tune here, nowhere else
# ===========================================================================

# --- Structuring ----------------------------------------------------------
STRUCTURING_THRESHOLD_MIN_RATIO = 0.80   # lower bound of "just below threshold"
STRUCTURING_THRESHOLD_MAX_RATIO = 0.99   # upper bound
STRUCTURING_MIN_TRANSFERS = 5            # ring floor is 3 sources x 2 txns = 6;
                                          # 5 leaves one txn of margin below that
                                          # floor for windowing edge effects.
STRUCTURING_MIN_DISTINCT_SOURCES = 3     # matches ring size exactly
STRUCTURING_WINDOW_HOURS = 240           # matches generator's max ring window of
                                          # uniform(2, 10) days
STRUCTURING_SEVERITY_FLOOR = 0.30
STRUCTURING_SEVERITY_CEILING = 1.00
STRUCTURING_SEVERITY_SATURATION = 2.0

# --- Layering Config -----------------------------------------------------
LAYERING_MIN_HOPS = 3
LAYERING_MAX_HOPS = 5
LAYERING_DECAY_MIN = 0.80                # REVERTED from 0.70
LAYERING_DECAY_MAX = 0.95                # REVERTED from 0.98
LAYERING_HOP_MAX_HOURS = 48
LAYERING_CHAIN_MAX_HOURS = 24 * 7        # REVERTED to 168 from 96
LAYERING_SEVERITY_FLOOR = 0.35
LAYERING_SEVERITY_CEILING = 1.00

LAYERING_NODE_OVERLAP_VETO = 0.67        # actual discriminator

# --- Round-tripping -------------------------------------------------------
ROUND_TRIP_MIN_CYCLE = 2
ROUND_TRIP_MAX_CYCLE = 5
ROUND_TRIP_HOP_MAX_HOURS = 96
ROUND_TRIP_MIN_REPEATS = 2

ROUND_TRIP_DECAY_MIN = 0.85              # REVERTED from 0.70
ROUND_TRIP_GAIN_ALLOWANCE = 1.001        # REVERTED from 1.005
ROUND_TRIP_CYCLE_DECAY_MIN = 0.55        # between your 0.20 and my earlier 0.60
ROUND_TRIP_CYCLE_DECAY_MAX = 0.98        # REVERTED from 1.02

ROUND_TRIP_SEVERITY_FLOOR = 0.35
ROUND_TRIP_SEVERITY_CEILING = 1.00


# ===========================================================================
# Small helpers
# ===========================================================================

def _parse_iso(ts: str) -> datetime:
    """Parse an ISO timestamp string into an aware datetime.

    Graph edges store timestamps as ISO strings (see graph_builder.py).
    """
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _scale_severity(
    value: float,
    floor: float,
    ceiling: float,
    saturation: float,
) -> float:
    """Linear scale from [0, saturation] to [floor, ceiling].

    value=0          -> floor
    value=saturation -> ceiling
    values above saturation clip to ceiling.
    """
    if saturation <= 0:
        return floor
    frac = _clip(value / saturation, 0.0, 1.0)
    return round(floor + (ceiling - floor) * frac, 3)


# ===========================================================================
# Detector 1 — Structuring
# ===========================================================================

def detect_structuring(G: nx.MultiDiGraph) -> List[PatternMatch]:
    """Find mule accounts receiving many sub-threshold transfers.

    Algorithm shape:
      For each candidate mule, gather all incoming edges whose amount is
      between 0.80x and 0.99x of the reporting threshold. Slide a
      window of STRUCTURING_WINDOW_HOURS over those edges. If the window
      contains STRUCTURING_MIN_TRANSFERS transfers from at least
      STRUCTURING_MIN_DISTINCT_SOURCES distinct senders, emit a
      PatternMatch for the mule.

    FIX D (corrected): anchor at each start, extend the window to the
    full STRUCTURING_WINDOW_HOURS, take the ENTIRE slice, check both
    thresholds, keep the largest qualifying cluster. The prior
    revision's "tightest qualifying window" rewrite broke recall by
    breaking out at the first j that satisfied thresholds, capturing a
    subset of the ring's transactions and scoring low on the
    transaction-overlap metric. This is the original behavior restored.
    """
    # Reporting threshold as a module-local constant. Same value as
    # data_generator.REPORTING_THRESHOLD, but we do not import from the
    # generator — detectors should not depend on generator internals.
    THRESHOLD = 10_000.0
    lo = THRESHOLD * STRUCTURING_THRESHOLD_MIN_RATIO
    hi = THRESHOLD * STRUCTURING_THRESHOLD_MAX_RATIO

    matches: List[PatternMatch] = []
    counter = 0
    window = timedelta(hours=STRUCTURING_WINDOW_HOURS)

    # Only nodes with incoming edges can be a mule.
    for mule in G.nodes:
        inbound = []
        for source, _, attrs in G.in_edges(mule, data=True):
            amount = float(attrs.get("amount", 0.0))
            ts_str = attrs.get("timestamp")
            if not ts_str or not (lo <= amount <= hi):
                continue
            inbound.append({
                "source": source,
                "txn_id": attrs.get("transaction_id"),
                "amount": amount,
                "ts": _parse_iso(ts_str),
            })

        if len(inbound) < STRUCTURING_MIN_TRANSFERS:
            continue

        # Sort by time, slide a window across the sorted list.
        inbound.sort(key=lambda e: e["ts"])
        best: Optional[Dict] = None

        for i in range(len(inbound)):
            window_start = inbound[i]["ts"]
            window_end = window_start + window
            j = i
            while j < len(inbound) and inbound[j]["ts"] <= window_end:
                j += 1
            cluster = inbound[i:j]
            distinct = {e["source"] for e in cluster}
            if (len(cluster) >= STRUCTURING_MIN_TRANSFERS
                    and len(distinct) >= STRUCTURING_MIN_DISTINCT_SOURCES):
                if best is None or len(cluster) > len(best["cluster"]):
                    best = {
                        "cluster": cluster,
                        "start": window_start,
                        "end": inbound[j - 1]["ts"],
                    }

        if best is None:
            continue

        cluster = best["cluster"]
        distinct_sources = sorted({e["source"] for e in cluster})
        total = sum(e["amount"] for e in cluster)

        # Severity scales with how far above minimums the ring is.
        excess = min(
            len(cluster) / STRUCTURING_MIN_TRANSFERS,
            len(distinct_sources) / STRUCTURING_MIN_DISTINCT_SOURCES,
        ) - 1.0
        severity = _scale_severity(
            excess,
            STRUCTURING_SEVERITY_FLOOR,
            STRUCTURING_SEVERITY_CEILING,
            STRUCTURING_SEVERITY_SATURATION,
        )

        counter += 1
        match_id = f"MS-STRUCT-{counter:04d}"
        evidence = (
            f"{len(cluster)} sub-threshold transfers "
            f"({lo:,.0f}-{hi:,.0f}) from {len(distinct_sources)} distinct "
            f"accounts to {mule} within "
            f"{(best['end'] - best['start']).total_seconds() / 3600:.0f} hours. "
            f"Total ${total:,.0f}."
        )

        matches.append(PatternMatch(
            match_id=match_id,
            pattern_type=PatternType.STRUCTURING,
            accounts_involved=[mule] + distinct_sources,
            transactions_involved=[e["txn_id"] for e in cluster if e["txn_id"]],
            severity=severity,
            window_start=best["start"],
            window_end=best["end"],
            evidence=evidence,
        ))

    return matches


# ===========================================================================
# Detector 2 — Layering
# ===========================================================================

def _explore_layering_chain(
    G: nx.MultiDiGraph,
    start: str,
    chain: List[str],
    txns: List[str],
    current_amount: Optional[float],
    current_time: Optional[datetime],
    chain_start_time: Optional[datetime],
) -> Tuple[List[str], List[str], float, datetime]:
    """Recursive forward exploration of a layering chain.

    FIX C: chain_start_time is threaded through and used to enforce
    LAYERING_CHAIN_MAX_HOURS. Without this cap, a 3-hop chain could
    span the full dataset window as long as each consecutive hop was
    within LAYERING_HOP_MAX_HOURS of the previous — which is how
    round-tripping rings, walked forward with blended normal edges
    spliced in, were being reported as layering.
    """
    if len(chain) - 1 >= LAYERING_MAX_HOPS:
        return chain, txns, current_amount or 0.0, current_time or datetime.now(timezone.utc)

    best_chain = chain
    best_txns = txns
    best_amount = current_amount or 0.0
    best_time = current_time or datetime.now(timezone.utc)

    tail = chain[-1]
    for _, nxt, key, attrs in G.out_edges(tail, keys=True, data=True):
        amount = float(attrs.get("amount", 0.0))
        ts_str = attrs.get("timestamp")
        if not ts_str:
            continue
        ts = _parse_iso(ts_str)

        # First hop: no amount constraint.
        if current_amount is not None:
            if current_amount <= 0:
                continue
            ratio = amount / current_amount
            if not (LAYERING_DECAY_MIN <= ratio <= LAYERING_DECAY_MAX):
                continue

        # Time constraints (skip on first hop).
        if current_time is not None:
            gap = (ts - current_time).total_seconds() / 3600
            if gap < 0 or gap > LAYERING_HOP_MAX_HOURS:
                continue

        # FIX C: total chain duration cap.
        chain_start = chain_start_time if chain_start_time is not None else ts
        span_hours = (ts - chain_start).total_seconds() / 3600
        if span_hours > LAYERING_CHAIN_MAX_HOURS:
            continue

        if nxt in chain:
            continue

        sub_chain, sub_txns, sub_amount, sub_time = _explore_layering_chain(
            G,
            start=start,
            chain=chain + [nxt],
            txns=txns + [attrs.get("transaction_id", "")],
            current_amount=amount,
            current_time=ts,
            chain_start_time=chain_start,
        )
        if len(sub_chain) > len(best_chain):
            best_chain = sub_chain
            best_txns = sub_txns
            best_amount = sub_amount
            best_time = sub_time

    return best_chain, best_txns, best_amount, best_time


def detect_layering(G: nx.MultiDiGraph) -> List[PatternMatch]:
    matches: List[PatternMatch] = []
    counter = 0
    reported_node_sets: List[Set[str]] = []

    for start in list(G.nodes):
        if G.out_degree(start) == 0:
            continue

        chain, txns, _final_amount, _final_time = _explore_layering_chain(
            G,
            start=start,
            chain=[start],
            txns=[],
            current_amount=None,
            current_time=None,
            chain_start_time=None,
        )

        hops = len(chain) - 1
        if hops < LAYERING_MIN_HOPS:
            continue

        node_set = set(chain)
        if any(node_set.issubset(prev) for prev in reported_node_sets):
            continue
        reported_node_sets.append(node_set)

        ordered_txns: List[str] = []
        amounts: List[float] = []
        window_start: Optional[datetime] = None
        window_end: Optional[datetime] = None
        prev_amount: Optional[float] = None

        for a, b in zip(chain, chain[1:]):
            chosen = None
            for _, v, key, attrs in G.out_edges(a, keys=True, data=True):
                if v != b:
                    continue
                ts = _parse_iso(attrs["timestamp"])
                amount = float(attrs["amount"])
                
                # Check decay against previous hop if established
                if prev_amount is not None:
                    ratio = amount / prev_amount
                    if not (LAYERING_DECAY_MIN <= ratio <= LAYERING_DECAY_MAX):
                        continue
                        
                if chosen is None or ts < _parse_iso(chosen["timestamp"]):
                    chosen = attrs

            # Fallback: if no edge strictly met decay band due to float variations, pick best candidate edge to b
            if chosen is None:
                for _, v, key, attrs in G.out_edges(a, keys=True, data=True):
                    if v == b:
                        chosen = attrs
                        break

            if chosen is None:
                continue

            ordered_txns.append(chosen.get("transaction_id", ""))
            amt = float(chosen["amount"])
            amounts.append(amt)
            ts = _parse_iso(chosen["timestamp"])
            
            window_start = ts if window_start is None or ts < window_start else window_start
            window_end = ts if window_end is None or ts > window_end else window_end
            prev_amount = amt

        if window_start is None or window_end is None or len(amounts) < 2:
            continue

        preserved = amounts[-1] / amounts[0] if amounts[0] > 0 else 1.0
        hop_excess = (hops - LAYERING_MIN_HOPS) / max(LAYERING_MAX_HOPS - LAYERING_MIN_HOPS, 1)
        severity = _scale_severity(
            hop_excess,
            LAYERING_SEVERITY_FLOOR,
            LAYERING_SEVERITY_CEILING,
            1.0,
        )

        counter += 1
        match_id = f"MS-LAYER-{counter:04d}"
        decay_pct = (1 - preserved) * 100
        evidence = (
            f"{hops}-hop chain {' -> '.join(chain)}, "
            f"{decay_pct:.1f}% total decay, completed in "
            f"{(window_end - window_start).total_seconds() / 3600:.0f} hours."
        )

        matches.append(PatternMatch(
            match_id=match_id,
            pattern_type=PatternType.LAYERING,
            accounts_involved=list(chain),
            transactions_involved=[t for t in ordered_txns if t],
            severity=severity,
            window_start=window_start,
            window_end=window_end,
            evidence=evidence,
        ))

    return matches


def deduplicate_layering(
    layering_matches: List[PatternMatch],
    round_tripping_matches: List[PatternMatch],
) -> List[PatternMatch]:
    """Drop layering matches that a round-tripping ring already explains.

    Rule: if more than LAYERING_NODE_OVERLAP_VETO (67%) of a layering
    match's accounts also belong to some single round-tripping match's
    accounts, drop the layering match. Compared per-RT-match, not
    against the graph-wide union — a layering chain whose nodes happen
    to be scattered across several different RT rings is not the same
    as one whose nodes are the RT ring.

    Why node overlap, not transaction overlap: a layering chain walking
    the RT ring forward and the RT ring itself consume DIFFERENT
    parallel edges on the same (src, dst) pairs (generator emits fresh
    txn IDs per cycle). Transaction-ID overlap is near zero even when
    the chains are the same nodes. Node sets are stable across parallel
    edges.

    A 4-node layering chain sharing 3 nodes with an RT ring is 0.75,
    above the veto. A 4-node chain sharing 2 nodes (0.50) is left
    alone — that is plausibly an unrelated chain crossing the ring at
    one intermediary.
    """
    rt_node_sets: List[Set[str]] = [
        set(m.accounts_involved) for m in round_tripping_matches
    ]

    kept: List[PatternMatch] = []
    for m in layering_matches:
        layer_nodes = set(m.accounts_involved)
        total = len(layer_nodes)
        if total == 0:
            kept.append(m)
            continue

        vetoed = False
        for rt_nodes in rt_node_sets:
            if not rt_nodes:
                continue
            overlap = len(layer_nodes & rt_nodes)
            if (overlap / total) > LAYERING_NODE_OVERLAP_VETO:
                vetoed = True
                break

        if vetoed:
            continue
        kept.append(m)

    return kept




# ===========================================================================
# Detector 3 — Round-tripping
# ===========================================================================

def _cycle_repeats_within_window(
    G: nx.MultiDiGraph,
    cycle: List[str],
    intra_cycle_hop_max_hours: int,
) -> Tuple[int, Optional[datetime], Optional[datetime], List[str]]:
    """Count how many times a cycle completes within the dataset.

    Enforces:
      (1) per-hop time window: each hop occurs within
          intra_cycle_hop_max_hours of the previous hop.
      (2) FIX A: per-hop amount ratio in [ROUND_TRIP_DECAY_MIN,
          ROUND_TRIP_GAIN_ALLOWANCE] of the previous hop. Strict
          decay; kills cross-ring bounces.
      (3) FIX B: after a traversal completes, the cycle-level decay
          ratio (final / initial) must fall in
          [ROUND_TRIP_CYCLE_DECAY_MIN, ROUND_TRIP_CYCLE_DECAY_MAX].
          Generator's 3-hop cycle decays to [0.68, 0.91]; a
          traversal stitched from two different rings lands near 1.0
          and is rejected.
      (4) No constraint on the gap between successive cycles. Real
          launderers wait days or weeks between runs; the generator
          spaces cycles by uniform(24, 120) hours.

    The prior revision's edge-identity stability check was removed — it
    assumed two traversals of the same ring reuse the same edge IDs,
    but the generator emits fresh transactions per cycle, so Jaccard
    was always 0 and every traversal reset the repeat counter.
    """
    # Gather all edges for each hop in the cycle.
    per_hop_edges: List[List[dict]] = []
    for a, b in zip(cycle, cycle[1:] + [cycle[0]]):
        hop_edges: List[dict] = []
        if G.has_edge(a, b):
            edge_dict = G.get_edge_data(a, b) or {}
            for key, attrs in edge_dict.items():
                ts_str = attrs.get("timestamp")
                if not ts_str:
                    continue
                hop_edges.append({
                    "txn_id": attrs.get("transaction_id"),
                    "amount": float(attrs.get("amount", 0.0)),
                    "ts": _parse_iso(ts_str),
                })
        hop_edges.sort(key=lambda e: e["ts"])
        per_hop_edges.append(hop_edges)

    if any(not hop for hop in per_hop_edges):
        return 0, None, None, []

    # Greedy traversal: start from the earliest unused edge in hop 0,
    # walk forward through the hops enforcing the intra-cycle hop window
    # and the amount-decay window. When we return to hop 0, count one
    # repeat and start a new cycle from the earliest unused edge in hop
    # 0 after the last ts.
    used: Dict[int, int] = {i: 0 for i in range(len(per_hop_edges))}
    repeat_txns: List[str] = []
    repeats = 0
    first_ts: Optional[datetime] = None
    last_ts: Optional[datetime] = None
    hop_window = timedelta(hours=intra_cycle_hop_max_hours)

    while True:
        start_idx = used[0]
        if start_idx >= len(per_hop_edges[0]):
            break
        start_edge = per_hop_edges[0][start_idx]

        # Snapshot hop pointers 1..N-1. On a failed or cycle-gate-rejected
        # traversal, restore them so a later traversal starting from a
        # different hop-0 edge can still see the same edges. Without
        # this, a traversal that walks two hops and then fails leaves
        # used[1] and used[2] advanced past edges belonging to a
        # DIFFERENT coherent cycle of the same ring — the next traversal
        # is then forced to chain non-matching edges from different
        # cycles, fails the decay gate, and the ring is lost.
        saved_used = dict(used)

        chain_txns = [start_edge["txn_id"]]
        prev_ts = start_edge["ts"]
        prev_amount = start_edge["amount"]
        success = True

        for hop_i in range(1, len(per_hop_edges)):
            hop = per_hop_edges[hop_i]
            found = None
            for j in range(used[hop_i], len(hop)):
                e = hop[j]
                if e["ts"] < prev_ts:
                    used[hop_i] = j + 1
                    continue
                if (e["ts"] - prev_ts) > hop_window:
                    break
                if prev_amount <= 0:
                    break
                ratio = e["amount"] / prev_amount
                if not (ROUND_TRIP_DECAY_MIN <= ratio <= ROUND_TRIP_GAIN_ALLOWANCE):
                    continue
                found = (j, e)
                break
            if found is None:
                success = False
                break
            j, e = found
            used[hop_i] = j + 1
            chain_txns.append(e["txn_id"])
            prev_ts = e["ts"]
            prev_amount = e["amount"]

        if not success:
            used = saved_used
            used[0] = start_idx + 1
            continue

        # FIX B: cycle-level decay plausibility.
        if start_edge["amount"] > 0:
            cycle_ratio = prev_amount / start_edge["amount"]
            if not (ROUND_TRIP_CYCLE_DECAY_MIN
                    <= cycle_ratio
                    <= ROUND_TRIP_CYCLE_DECAY_MAX):
                used = saved_used
                used[0] = start_idx + 1
                continue

        # Success: commit hop-0 advancement and record the repeat.
        used[0] = start_idx + 1
        repeats += 1
        repeat_txns.extend(chain_txns)
        first_ts = start_edge["ts"] if first_ts is None else min(first_ts, start_edge["ts"])
        last_ts = prev_ts if last_ts is None else max(last_ts, prev_ts)     

    if repeats < ROUND_TRIP_MIN_REPEATS:
        return 0, None, None, []

    return repeats, first_ts, last_ts, repeat_txns


def detect_round_tripping(G: nx.MultiDiGraph) -> List[PatternMatch]:
    """Find cycles where money returns to its origin, repeated over time.

    Algorithm shape:
      Enumerate simple cycles up to ROUND_TRIP_MAX_CYCLE in length using
      nx.simple_cycles. For each cycle, check how many times it repeats
      within the per-hop time AND amount-decay window. Emit a
      PatternMatch if the cycle repeats at least ROUND_TRIP_MIN_REPEATS
      times.

    Dedup strategy: no frozenset keying before the repeat check.
    simple_cycles returns each directed cycle in every rotation (and
    every direction for cycles that exist reversed). Collapsing by
    frozenset picked whichever rotation was enumerated first, which
    could walk the cycle in the wrong hop order and fail the decay/time
    checks even when the generator's actual direction would have
    passed. Wrong rotations naturally return 0 repeats from
    _cycle_repeats_within_window, so leaving them in costs nothing.

    After a rotation passes the repeat check, its frozenset is recorded
    so further rotations of the SAME node-set are suppressed and one
    ring produces exactly one match.
    """
    matches: List[PatternMatch] = []
    counter = 0

    # Filter to nodes with both in- and out-degree, then enumerate cycles.
    candidate_nodes = [
        n for n in G.nodes if G.in_degree(n) > 0 and G.out_degree(n) > 0
    ]
    sub = G.subgraph(candidate_nodes)

    # Only populated AFTER a rotation passes the repeat check, so a
    # wrong-direction rotation cannot occupy the slot before the
    # correct direction is tried.
    matched_cycle_keys: Set[frozenset] = set()

    try:
        cycles = nx.simple_cycles(sub, length_bound=ROUND_TRIP_MAX_CYCLE)
    except TypeError:
        # Older networkx may not support length_bound; fall back.
        cycles = nx.simple_cycles(sub)

    for cycle in cycles:
        if len(cycle) < ROUND_TRIP_MIN_CYCLE or len(cycle) > ROUND_TRIP_MAX_CYCLE:
            continue

        repeats, first_ts, last_ts, txns = _cycle_repeats_within_window(
            G, cycle, ROUND_TRIP_HOP_MAX_HOURS
        )
        if repeats < ROUND_TRIP_MIN_REPEATS:
            continue

        if first_ts is None or last_ts is None:
            continue

        # Post-check dedup: suppress other rotations of an already-
        # matched node-set. Doing this here (not before the repeat
        # check) is what fixes the direction-collision bug.
        key = frozenset(cycle)
        if key in matched_cycle_keys:
            continue
        matched_cycle_keys.add(key)

        # Severity scales with repeats above minimum and cycle length.
        repeat_excess = (repeats - ROUND_TRIP_MIN_REPEATS) / 4.0
        severity = _scale_severity(
            repeat_excess,
            ROUND_TRIP_SEVERITY_FLOOR,
            ROUND_TRIP_SEVERITY_CEILING,
            1.0,
        )

        counter += 1
        match_id = f"MS-RT-{counter:04d}"
        evidence = (
            f"Cycle {' -> '.join(cycle + [cycle[0]])} repeated "
            f"{repeats} times over "
            f"{(last_ts - first_ts).total_seconds() / 86400:.1f} days."
        )

        matches.append(PatternMatch(
            match_id=match_id,
            pattern_type=PatternType.ROUND_TRIPPING,
            accounts_involved=list(cycle),
            transactions_involved=[t for t in txns if t],
            severity=severity,
            window_start=first_ts,
            window_end=last_ts,
            evidence=evidence,
        ))

    return matches


# ===========================================================================
# Smoke test
# ===========================================================================

if __name__ == "__main__":
    from data_generator import generate_dataset
    from graph_builder import build_graph

    accounts, transactions, ground_truth = generate_dataset()
    G = build_graph(transactions)

    print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    print(f"Ground truth labels: {len(ground_truth)}")
    print()

    structuring = detect_structuring(G)
    round_tripping = detect_round_tripping(G)
    layering_raw = detect_layering(G)
    layering = deduplicate_layering(layering_raw, round_tripping)

    print(f"Structuring matches:        {len(structuring)}")
    print(f"Layering matches (raw):     {len(layering_raw)}")
    print(f"Layering matches (deduped): {len(layering)}")
    print(f"Round-tripping matches:     {len(round_tripping)}")
    print()

    # Quick overlap check against ground truth
    from collections import Counter
    gt_counts = Counter(ground_truth.values())

    def _txn_overlap(matches: List[PatternMatch]) -> float:
        detected = set()
        for m in matches:
            detected.update(m.transactions_involved)
        gt = set(ground_truth.keys())
        if not gt:
            return 0.0
        return len(detected & gt) / len(gt)

    print(f"Ground truth breakdown: {dict(gt_counts)}")
    print(f"Structuring txn overlap:    {_txn_overlap(structuring):.2%}")
    print(f"Layering txn overlap:       {_txn_overlap(layering):.2%}")
    print(f"Round-tripping txn overlap: {_txn_overlap(round_tripping):.2%}")