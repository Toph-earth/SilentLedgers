"""
ml_detector.py — Supervised classifier for laundering accounts.

Features are computed per account from the graph. Labels come from the
generator's is_laundering flag. The model learns thresholds and
interactions that the rule detectors hardcode.

Explanations come from SHAP, computed per account against the trained
model. Each explanation names the top contributing features and their
direction.
"""

from __future__ import annotations
from typing import Dict, List, Tuple

import numpy as np
import networkx as nx
import shap
import xgboost as xgb
import joblib
import os

from models import Account

MODEL_PATH = "/tmp/silent_ledger_model.pkl"

FEATURE_NAMES = [
    "txn_count",
    "in_degree",
    "out_degree",
    "total_in",
    "total_out",
    "net_flow",
    "mean_out_amount",
    "std_out_amount",
    "sub_threshold_in_count",   # incoming transfers between 0.80 and 0.99 of 10k
    "sub_threshold_in_sources", # distinct senders of those
    "max_chain_depth_out",      # longest decay-respecting outbound path
    "cycle_membership",         # 1 if the node appears in any 3-6 cycle
]


def _features(G: nx.MultiDiGraph, acc: Account) -> List[float]:
    aid = acc.account_id
    if aid not in G:
        return [0.0] * len(FEATURE_NAMES)

    node = G.nodes[aid]
    in_edges = list(G.in_edges(aid, data=True))
    out_edges = list(G.out_edges(aid, data=True))

    sub_lo, sub_hi = 0.80 * 10_000, 0.99 * 10_000
    sub_in = [
        attrs for _, _, attrs in in_edges
        if sub_lo <= float(attrs.get("amount", 0)) <= sub_hi
    ]
    sub_sources = {src for src, _, attrs in in_edges
                   if sub_lo <= float(attrs.get("amount", 0)) <= sub_hi}

    out_amounts = [float(a.get("amount", 0)) for _, _, a in out_edges]
    mean_out = float(np.mean(out_amounts)) if out_amounts else 0.0
    std_out = float(np.std(out_amounts)) if len(out_amounts) > 1 else 0.0

    # Longest outbound decay-respecting path (depth, not node list).
    max_depth = 0
    for _, first, attrs in out_edges:
        depth = 1
        prev_amt = float(attrs.get("amount", 0))
        cur = first
        seen = {aid, first}
        while depth < 6:
            found = False
            for _, nxt, a2 in G.out_edges(cur, data=True):
                if nxt in seen:
                    continue
                ratio = float(a2.get("amount", 0)) / prev_amt if prev_amt > 0 else 0
                if 0.80 <= ratio <= 0.95:
                    seen.add(nxt)
                    cur = nxt
                    prev_amt = float(a2.get("amount", 0))
                    depth += 1
                    found = True
                    break
            if not found:
                break
        max_depth = max(max_depth, depth)

    # Cycle membership: cheap check via simple_cycles on a bounded subgraph.
    # Precomputed once at the graph level in fit_and_score below; here we
    # just read a flag.
    cycle_flag = float(G.nodes[aid].get("in_cycle", 0))

    return [
        float(node.get("txn_count", 0)),
        float(G.in_degree(aid)),
        float(G.out_degree(aid)),
        float(node.get("total_in", 0.0)),
        float(node.get("total_out", 0.0)),
        float(node.get("total_in", 0.0) - node.get("total_out", 0.0)),
        mean_out,
        std_out,
        float(len(sub_in)),
        float(len(sub_sources)),
        float(max_depth),
        cycle_flag,
    ]


def _mark_cycles(G: nx.MultiDiGraph) -> None:
    """Set node attr in_cycle = 1 for nodes in any 3-6 length cycle."""
    for n in G.nodes:
        G.nodes[n]["in_cycle"] = 0
    try:
        candidates = [n for n in G.nodes if G.in_degree(n) > 0 and G.out_degree(n) > 0]
        sub = G.subgraph(candidates)
        for cycle in nx.simple_cycles(sub, length_bound=6):
            if len(cycle) >= 3:
                for n in cycle:
                    G.nodes[n]["in_cycle"] = 1
    except Exception:
        pass


def fit_and_score(
    accounts: List[Account],
    G: nx.MultiDiGraph,
) -> Tuple[Dict[str, float], Dict[str, str]]:
    """Returns (ml_scores, ml_explanations) keyed by account_id.

    If a persisted model exists at MODEL_PATH, it is loaded and used to
    score the new data without retraining. This is how the model runs on
    unlabeled data: the model was already trained, labels are only
    needed at training time.

    If no persisted model exists, the function trains from scratch on
    the generator's is_laundering labels. If those labels are absent or
    degenerate, the function returns empty dicts and the pipeline
    degrades to rule-only scoring.
    """
    _mark_cycles(G)

    ids = [a.account_id for a in accounts if a.account_id in G]
    if len(ids) < 20:
        return {}, {}

    X = np.array([_features(G, a) for a in accounts if a.account_id in G])

    model = None
    loaded_from_disk = False

    # Try to load a persisted model. If present, skip training entirely.
    if os.path.exists(MODEL_PATH):
        try:
            model = joblib.load(MODEL_PATH)
            loaded_from_disk = True
        except Exception as e:
            print(f"Failed to load persisted model, will retrain: {e}")
            model = None

    # Train if no persisted model was found.
    if model is None:
        y = np.array([int(a.is_laundering) for a in accounts if a.account_id in G])
        if y.sum() == 0 or y.sum() == len(y):
            # No usable labels and no persisted model. Cannot score.
            return {}, {}

        model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.1,
            eval_metric="logloss",
            random_state=42,
        )
        model.fit(X, y)

        try:
            joblib.dump(model, MODEL_PATH)
            print(f"Trained and persisted model to {MODEL_PATH}")
        except Exception as e:
            print(f"Failed to persist model: {e}")

    probs = model.predict_proba(X)[:, 1]

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)

    scores: Dict[str, float] = {}
    explanations: Dict[str, str] = {}

    for i, aid in enumerate(ids):
        p = float(probs[i])
        scores[aid] = p

        contribs = list(zip(FEATURE_NAMES, shap_values[i]))
        contribs.sort(key=lambda x: abs(x[1]), reverse=True)
        top = contribs[:3]
        parts = []
        for name, val in top:
            direction = "pushed up" if val > 0 else "pushed down"
            parts.append(f"{name} ({direction}, {abs(val):.2f})")
        explanations[aid] = (
            f"Model score {p:.2f}. Top contributors: " + ", ".join(parts) + "."
        )

    return scores, explanations