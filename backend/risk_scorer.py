"""
risk_scorer.py — Blend rule-based and ML-based risk into a single score.

Rule layer (detectors.py):
  Named patterns produce PatternMatch objects with severity in [0, 1].
  Summing severities per account gives a rule signal that scales with
  how many patterns the account participates in and how extreme those
  patterns are. This is the audit layer — every point traces to a
  specific match with a specific transaction list.

ML layer (ml_detector.py):
  A supervised classifier trained on the generator's is_laundering flag
  produces a per-account probability of laundering. This catches
  patterns the rules do not name. It is the evasion-resistance layer.

Blend:
  final = RULE_WEIGHT * rule_component + ML_WEIGHT * ml_component
  Weights chosen so that a single strong rule match already pushes an
  account near the flag threshold, and the ML signal can tip marginal
  accounts over. Tuning these is the main knob for precision/recall.

The output RiskScore carries contributing_matches so the frontend can
explain the rule component. The ML component is exposed separately via
the API as mlScore and mlExplanation.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import networkx as nx

from models import Account, PatternMatch, RiskScore


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Blend weights. Must sum to 1.0.
RULE_WEIGHT = 0.6
ML_WEIGHT = 0.4

# Rule component scaling. A sum of severities of 1.0 maps to this raw
# rule score (before the blend). With RULE_WEIGHT = 0.6 and this at 100,
# a single severity-1.0 match yields a final score of 60 — right at the
# flag threshold. Two matches push clearly over.
RULE_SCALE = 100.0

# ML component scaling. Model outputs a probability in [0, 1]. Multiply
# by 100 to get a 0–100 value before the blend.
ML_SCALE = 100.0

# Small centrality bonus. Capped low so it cannot single-handedly flag
# an account. Applied only to the rule component to keep the ML signal
# independent.
CENTRALITY_BONUS_MAX = 10.0

# Threshold above which an account is considered flagged. Same value
# that main.py uses in _compute_summary and /api/accounts. Kept here as
# a reference; the API still owns the flag decision.
FLAG_THRESHOLD = 60


# ---------------------------------------------------------------------------
# Rule component
# ---------------------------------------------------------------------------

def _rule_score(
    matches: List[PatternMatch],
    centrality: float,
) -> float:
    """Sum of match severities, scaled and boosted by centrality.

    Returns a value in [0, 100].
    """
    if not matches:
        return 0.0

    severity_sum = sum(m.severity for m in matches)
    base = severity_sum * RULE_SCALE

    # Centrality bonus: an account at the center of a dense neighborhood
    # is more suspicious than an isolated one with the same matches.
    # Capped so it cannot dominate the score.
    bonus = min(CENTRALITY_BONUS_MAX, centrality * CENTRALITY_BONUS_MAX)

    return min(100.0, base + bonus)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def score_accounts(
    accounts: List[Account],
    matches_by_account: Dict[str, List[PatternMatch]],
    G: nx.MultiDiGraph,
    ml_scores: Optional[Dict[str, float]] = None,
) -> Dict[str, RiskScore]:
    """Compute a RiskScore for every account.

    accounts:            List of Account objects (all accounts).
    matches_by_account:  Dict mapping account_id -> List[PatternMatch].
    G:                   The MultiDiGraph (used for centrality).
    ml_scores:           Dict mapping account_id -> probability in [0, 1].
                         Optional. If None, the blend reduces to the rule
                         component alone. This is how the pipeline
                         degrades gracefully when ml_detector is
                         unavailable.

    Returns a dict of {account_id: RiskScore}.
    """
    ml_scores = ml_scores or {}

    # Precompute normalized degree centrality once.
    try:
        centrality_map = nx.degree_centrality(G)
    except Exception:
        centrality_map = {}

    out: Dict[str, RiskScore] = {}

    for acc in accounts:
        aid = acc.account_id
        acc_matches = matches_by_account.get(aid, [])

        rule_component = _rule_score(acc_matches, centrality_map.get(aid, 0.0))

        ml_prob = ml_scores.get(aid)
        if ml_prob is None:
            # No ML signal for this account; score is rule-only.
            blended = rule_component
        else:
            ml_component = float(ml_prob) * ML_SCALE
            blended = RULE_WEIGHT * rule_component + ML_WEIGHT * ml_component

        final = int(round(min(100.0, max(0.0, blended))))

        out[aid] = RiskScore(
            account_id=aid,
            score=final,
            contributing_matches=[m.match_id for m in acc_matches],
        )

    return out