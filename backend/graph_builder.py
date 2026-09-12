"""
graph_builder.py — Build a NetworkX MultiDiGraph from a transaction list.

This module's single job is: transactions in, graph out. It does NOT run
detection, does NOT score risk, does NOT know about the API.

Why MultiDiGraph, not DiGraph:
  A DiGraph collapses parallel edges — if ACC_001 sends ACC_042 two
  separate transfers, a DiGraph keeps only one. Every one of our three
  detections needs the exact evidence trail (which specific transfers
  formed this chain/cycle/funnel). Collapsing loses that. A MultiDiGraph
  keeps every transfer as a distinct edge, keyed by transaction_id.

Two public entry points:
  - build_graph(transactions) -> nx.MultiDiGraph
  - export_subgraph(G, center_id, max_nodes, max_edges) -> dict
    (JSON-serializable shape matching GraphPayload)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import networkx as nx

from models import Transaction


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(transactions: List[Transaction]) -> nx.MultiDiGraph:
    """Build a MultiDiGraph from a flat transaction list.

    Nodes are accounts. Edges are individual transfers. Each edge carries
    the full transaction payload as attributes, and its edge key is the
    transaction_id, so parallel edges survive and remain addressable.

    Node attributes:
      - label: the account_id (graph_builder does not know display names;
        the API layer attaches those from the Account list when needed).
      - total_in: sum of incoming transaction amounts.
      - total_out: sum of outgoing transaction amounts.
      - txn_count: number of transactions touching this account.

    Edge attributes:
      - transaction_id
      - amount
      - timestamp (ISO string)
      - currency
    """
    G = nx.MultiDiGraph()

    for txn in transactions:
        # Ensure both endpoints exist as nodes before adding the edge.
        if txn.source_account not in G:
            G.add_node(
                txn.source_account,
                label=txn.source_account,
                total_in=0.0,
                total_out=0.0,
                txn_count=0,
            )
        if txn.dest_account not in G:
            G.add_node(
                txn.dest_account,
                label=txn.dest_account,
                total_in=0.0,
                total_out=0.0,
                txn_count=0,
            )

        # Add the edge. The third positional arg is the key — using the
        # transaction_id makes parallel edges distinct and addressable.
        G.add_edge(
            txn.source_account,
            txn.dest_account,
            key=txn.transaction_id,
            transaction_id=txn.transaction_id,
            amount=txn.amount,
            timestamp=txn.timestamp.isoformat(),
            currency=txn.currency,
        )

        # Roll up node-level aggregates.
        G.nodes[txn.source_account]["total_out"] += txn.amount
        G.nodes[txn.source_account]["txn_count"] += 1
        G.nodes[txn.dest_account]["total_in"] += txn.amount
        G.nodes[txn.dest_account]["txn_count"] += 1

    return G


# ---------------------------------------------------------------------------
# Graph queries used by detectors and the API
# ---------------------------------------------------------------------------

def get_edges_between(
    G: nx.MultiDiGraph,
    u: str,
    v: str,
) -> List[dict]:
    """Return every edge from u to v as a list of dicts.

    Because G is a MultiDiGraph, this can return more than one entry. The
    detectors need to reason over all of them (e.g. a chain hop could be
    satisfied by any one of several parallel transfers).
    """
    if not G.has_edge(u, v):
        return []
    return [
        G[u][v][key]
        for key in G[u][v]
    ]


def get_neighbors(G: nx.MultiDiGraph, node_id: str) -> Tuple[List[str], List[str]]:
    """Return (predecessors, successors) of a node.

    Raises KeyError if the node does not exist — callers should check
    with `node_id in G` first when the ID comes from a request.
    """
    return list(G.predecessors(node_id)), list(G.successors(node_id))


# ---------------------------------------------------------------------------
# JSON-serializable export for the API
# ---------------------------------------------------------------------------

def _node_payload(
    G: nx.MultiDiGraph,
    node_id: str,
    risk_lookup: Optional[Dict[str, float]] = None,
) -> dict:
    """Build a single node dict matching GraphNode.

    risk_lookup is optional because graph_builder does not compute risk —
    the API layer passes in a precomputed {account_id: normalized_risk}
    map when serializing. When absent, risk defaults to 0.0.
    """
    attrs = G.nodes[node_id]
    risk = 0.0
    if risk_lookup is not None:
        risk = float(risk_lookup.get(node_id, 0.0))
    return {
        "id": node_id,
        "label": attrs.get("label", node_id),
        "risk": max(0.0, min(1.0, risk)),
    }


def _edge_payload(source: str, target: str, attrs: dict) -> dict:
    """Build a single edge dict matching GraphEdge.

    When multiple parallel edges exist between the same source and target,
    the caller is responsible for deciding which to emit (see
    export_subgraph). This helper just shapes one edge.
    """
    return {
        "source": source,
        "target": target,
        "amount": float(attrs.get("amount", 0.0)),
        "timestamp": attrs.get("timestamp"),
    }


def export_subgraph(
    G: nx.MultiDiGraph,
    center_id: Optional[str] = None,
    max_nodes: int = 25,
    max_edges: int = 60,
    risk_lookup: Optional[Dict[str, float]] = None,
    collapse_parallel: bool = True,
) -> dict:
    """Export a JSON-serializable subgraph matching GraphPayload.

    Two modes:
      - center_id provided: return the k-hop neighborhood around that
        account, bounded by max_nodes and max_edges. Used by
        GET /api/graph/{account_id}.
      - center_id None: return the whole graph (or the top-N by node
        degree when the graph exceeds max_nodes). Used by
        GET /api/graph/full.

    collapse_parallel: when True, multiple edges between the same
    (source, target) pair are collapsed into a single edge whose amount
    is the sum. The frontend graph cannot meaningfully draw overlapping
    edges, so this is the right default for visualization. The detectors
    operate on the full MultiDiGraph and are unaffected by this choice.
    """
    if not G.nodes:
        return {"nodes": [], "edges": []}

    # --- Select the node set --------------------------------------------
    if center_id is not None:
        if center_id not in G:
            return {"nodes": [], "edges": []}
        # Breadth-first expansion outward until we hit max_nodes.
        selected = {center_id}
        frontier = [center_id]
        while frontier and len(selected) < max_nodes:
            nxt: List[str] = []
            for node in frontier:
                for neighbor in list(G.successors(node)) + list(G.predecessors(node)):
                    if neighbor not in selected:
                        selected.add(neighbor)
                        nxt.append(neighbor)
                        if len(selected) >= max_nodes:
                            break
                if len(selected) >= max_nodes:
                    break
            frontier = nxt
    else:
        # Full-graph mode: take the highest-degree nodes if we exceed the cap.
        if G.number_of_nodes() <= max_nodes:
            selected = set(G.nodes)
        else:
            degree_sorted = sorted(
                G.nodes, key=lambda n: G.degree(n), reverse=True
            )
            selected = set(degree_sorted[:max_nodes])

    # --- Collect edges within the selected node set ---------------------
    candidate_edges: List[Tuple[str, str, dict]] = []
    for u, v, attrs in G.edges(data=True):
        if u in selected and v in selected:
            candidate_edges.append((u, v, attrs))

    # --- Collapse parallel edges for visualization ----------------------
    if collapse_parallel:
        merged: Dict[Tuple[str, str], dict] = {}
        for u, v, attrs in candidate_edges:
            key = (u, v)
            if key not in merged:
                merged[key] = {
                    "source": u,
                    "target": v,
                    "amount": float(attrs.get("amount", 0.0)),
                    "timestamp": attrs.get("timestamp"),
                }
            else:
                merged[key]["amount"] += float(attrs.get("amount", 0.0))
                # Keep the earliest timestamp so temporal context is
                # preserved on merged edges.
                if attrs.get("timestamp") and (
                    merged[key]["timestamp"] is None
                    or attrs["timestamp"] < merged[key]["timestamp"]
                ):
                    merged[key]["timestamp"] = attrs["timestamp"]
        edge_payloads = list(merged.values())
    else:
        edge_payloads = [_edge_payload(u, v, attrs) for u, v, attrs in candidate_edges]

    # --- Trim to max_edges, highest-value first -------------------------
    if len(edge_payloads) > max_edges:
        edge_payloads.sort(key=lambda e: e["amount"], reverse=True)
        edge_payloads = edge_payloads[:max_edges]

    # --- Prune nodes that ended up with no edges ------------------------
    # Keep the center node even if isolated so the API returns a coherent
    # "this account has no visible connections" response rather than an
    # empty payload.
    connected_ids = set()
    for e in edge_payloads:
        connected_ids.add(e["source"])
        connected_ids.add(e["target"])
    if center_id is not None:
        connected_ids.add(center_id)

    node_payloads = [
        _node_payload(G, nid, risk_lookup)
        for nid in selected
        if nid in connected_ids
    ]

    return {"nodes": node_payloads, "edges": edge_payloads}


# ---------------------------------------------------------------------------
# CLI entry point for manual inspection
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    from data_generator import generate_dataset

    accounts, transactions, ground_truth = generate_dataset()
    G = build_graph(transactions)

    print(f"Nodes: {G.number_of_nodes()}")
    print(f"Edges: {G.number_of_edges()}")
    print(f"Parallel-edge example: ", end="")

    # Find a pair with more than one edge, if any.
    found = False
    for u, v in G.edges():
        if G.number_of_edges(u, v) > 1:
            print(f"{u} -> {v} ({G.number_of_edges(u, v)} edges)")
            found = True
            break
    if not found:
        print("(none found — dataset may not have parallel edges)")

    print()
    print("Sample subgraph export (center = first node):")
    sample_center = next(iter(G.nodes))
    payload = export_subgraph(G, center_id=sample_center, max_nodes=10)
    print(json.dumps(payload, indent=2)[:800] + "...")