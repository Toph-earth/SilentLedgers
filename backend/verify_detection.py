"""
verify_detection.py — Runs the full detection pipeline against the
generator's ground truth and reports precision, recall, F1 per pattern,
plus a cross-pattern confusion breakdown.

CHANGE (unchanged from prior revision): this version calls
detectors.deduplicate_layering() on the raw layering output before
computing any metric. The dedup step must run here too — measuring
layering_raw directly would report numbers for a detector configuration
nobody ships. Metrics in this file should match what /api/generate and
/api/upload actually return.

If this file's reconstruction doesn't match your actual
verify_detection.py byte-for-byte, the load-bearing change to port over
is just this: call deduplicate_layering(layering_raw, round_tripping)
and use its return value everywhere below, before computing metrics or
printing anything.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, List, Set, Tuple

from data_generator import generate_dataset
from graph_builder import build_graph
from models import PatternMatch, PatternType
from detectors import (
    detect_structuring,
    detect_layering,
    detect_round_tripping,
    deduplicate_layering,
)

PATTERN_ORDER = ["structuring", "layering", "round_tripping"]


def _pattern_value(pattern_type) -> str:
    """Normalize PatternType enum or plain string to its string value."""
    return getattr(pattern_type, "value", pattern_type)


def _detected_txn_map(matches: List[PatternMatch]) -> Dict[str, Set[str]]:
    """transaction_id -> set of pattern_type strings that flagged it.

    A set, not a single value, because after dedup a transaction could
    in principle still be claimed by more than one live pattern type
    (e.g. round-tripping and structuring overlapping by coincidence) —
    the confusion table needs to be able to show that, not silently
    pick one.
    """
    out: Dict[str, Set[str]] = defaultdict(set)
    for m in matches:
        ptype = _pattern_value(m.pattern_type)
        for txn_id in m.transactions_involved:
            if txn_id:
                out[txn_id].add(ptype)
    return out


def compute_metrics(
    ground_truth: Dict[str, str],
    detected: Dict[str, Set[str]],
) -> Dict[str, Dict[str, float]]:
    """Per-pattern TP / FP / FN / precision / recall / F1.

    TP: a transaction ground truth labels as pattern P, and P's detector
        (post-dedup) also flagged it.
    FP: a transaction P's detector flagged, but ground truth does not
        label it P (either unlabeled, or labeled a different pattern).
    FN: a transaction ground truth labels as pattern P, but P's detector
        did not flag it.
    """
    metrics: Dict[str, Dict[str, float]] = {}

    for pattern in PATTERN_ORDER:
        gt_txns = {t for t, p in ground_truth.items() if p == pattern}
        detected_txns = {t for t, ptypes in detected.items() if pattern in ptypes}

        tp = len(gt_txns & detected_txns)
        fp = len(detected_txns - gt_txns)
        fn = len(gt_txns - detected_txns)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        metrics[pattern] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    return metrics


def compute_confusion(
    ground_truth: Dict[str, str],
    detected: Dict[str, Set[str]],
) -> List[Tuple[str, str, int]]:
    """(detector_pattern, ground_truth_pattern, count) for every
    detector-vs-label pair with at least one transaction, so mislabeled
    overlap (e.g. layering catching round-tripping txns) is visible even
    after dedup has removed the majority-overlap cases.
    """
    counts: Counter = Counter()
    for txn_id, ptypes in detected.items():
        gt_label = ground_truth.get(txn_id)
        if gt_label is None:
            continue
        for detector_pattern in ptypes:
            counts[(detector_pattern, gt_label)] += 1

    return sorted(
        ((d, g, c) for (d, g), c in counts.items()),
        key=lambda row: (-row[2], row[0], row[1]),
    )


def main() -> None:
    accounts, transactions, ground_truth = generate_dataset()
    G = build_graph(transactions)

    print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    print(f"Ground truth labels: {len(ground_truth)}")
    gt_counts = Counter(ground_truth.values())
    for pattern in PATTERN_ORDER:
        print(f"Ground truth {pattern}: {gt_counts.get(pattern, 0)} txns")
    print()

    structuring = detect_structuring(G)
    round_tripping = detect_round_tripping(G)
    layering_raw = detect_layering(G)

    # CHANGE: dedup happens here, before anything downstream sees
    # layering's output. This mirrors what main.py's _run_pipeline must
    # also do — both call sites should call this function immediately
    # after both detectors have run, and never measure or serve
    # layering_raw directly.
    layering = deduplicate_layering(layering_raw, round_tripping)

    print("Detected matches:")
    print(f"  structuring:     {len(structuring)}")
    print(f"  layering:        {len(layering)}  (raw: {len(layering_raw)}, "
          f"{len(layering_raw) - len(layering)} dropped by dedup)")
    print(f"  round_tripping:  {len(round_tripping)}")
    print()

    detected = _detected_txn_map(structuring + layering + round_tripping)
    metrics = compute_metrics(ground_truth, detected)

    print("Metrics:")
    for pattern in PATTERN_ORDER:
        m = metrics[pattern]
        print(
            f"  {pattern:<15} TP={m['tp']:<5} FP={m['fp']:<5} FN={m['fn']:<5} "
            f"P={m['precision']:.2%}  R={m['recall']:.2%}  F1={m['f1']:.2%}"
        )
    print()

    print("Cross-pattern confusion (post-dedup):")
    for detector_pattern, gt_pattern, count in compute_confusion(ground_truth, detected):
        label = "caught" if detector_pattern == gt_pattern else "MISLABELED as"
        print(f"  {detector_pattern:<15} {label:<14} {count:>4} txns ground truth labels {gt_pattern}")


if __name__ == "__main__":
    main()