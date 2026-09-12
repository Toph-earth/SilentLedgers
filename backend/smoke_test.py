"""
smoke_test.py — End-to-end verification of models, generator, loader, graph.

Run from backend/ with: python smoke_test.py
"""

import json
from collections import Counter

from models import Account, Transaction, AccountType
from data_generator import generate_dataset
from csv_loader import load_from_csv, CSVLoadError
from graph_builder import build_graph, export_subgraph


def section(title):
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def test_generator():
    section("Generator")
    accounts, transactions, ground_truth = generate_dataset()
    laundering = sum(1 for a in accounts if a.is_laundering)

    assert len(accounts) > 0, "No accounts generated"
    assert len(transactions) > 0, "No transactions generated"
    assert laundering > 0, "No laundering accounts"
    assert len(ground_truth) > 0, "No ground-truth labels"

    print(f"PASS  accounts={len(accounts)}  "
          f"transactions={len(transactions)}  "
          f"laundering={laundering}  "
          f"ground_truth={len(ground_truth)}")
    print(f"      pattern breakdown: {dict(Counter(ground_truth.values()))}")

    return accounts, transactions, ground_truth


def test_loader_with_csv():
    section("CSV loader")
    csv_bytes = (
        b"source_account,dest_account,amount,timestamp,pattern_tag\n"
        b"ACC_001,ACC_042,9500,2025-08-15T14:23:00Z,structuring\n"
        b"ACC_042,ACC_117,8800,2025-08-16T09:10:00Z,structuring\n"
        b"ACC_205,ACC_001,1200,2025-08-18T16:30:00Z,\n"
    )
    accounts, transactions, ground_truth = load_from_csv(csv_bytes)

    assert len(transactions) == 3
    assert len(ground_truth) == 2
    assert len(accounts) == 4
    print(f"PASS  transactions={len(transactions)}  "
          f"derived_accounts={len(accounts)}  "
          f"ground_truth={len(ground_truth)}")


def test_loader_errors():
    section("CSV loader — error handling")
    cases = [
        (b"source_account,dest_account,amount\nACC_1,ACC_2,500\n",
         "missing timestamp column"),
        (b"source_account,dest_account,amount,timestamp\nACC_1,ACC_2,500,not-a-date\n",
         "unparseable timestamp"),
        (b"source_account,dest_account,amount,timestamp\nACC_1,ACC_2,abc,2025-08-15\n",
         "non-numeric amount"),
        (b"source_account,dest_account,amount,timestamp\nACC_1,ACC_1,500,2025-08-15\n",
         "self-transfer"),
    ]
    for csv_bytes, label in cases:
        try:
            load_from_csv(csv_bytes)
            raise AssertionError(f"{label} was accepted")
        except CSVLoadError:
            print(f"PASS  rejected: {label}")


def test_graph(transactions):
    section("Graph builder")
    G = build_graph(transactions)

    assert G.number_of_nodes() > 0
    assert G.number_of_edges() == len(transactions)
    print(f"PASS  nodes={G.number_of_nodes()}  "
          f"edges={G.number_of_edges()}")

    # JSON serializability
    center = next(iter(G.nodes))
    payload = export_subgraph(G, center_id=center, max_nodes=15)
    json.dumps(payload)  # raises if not serializable
    print(f"PASS  subgraph payload serializable  "
          f"nodes={len(payload['nodes'])}  edges={len(payload['edges'])}")

    # Full export
    full = export_subgraph(G, center_id=None, max_nodes=50)
    json.dumps(full)
    print(f"PASS  full payload serializable  "
          f"nodes={len(full['nodes'])}  edges={len(full['edges'])}")

    # Nonexistent center
    empty = export_subgraph(G, center_id="ACC_999999")
    assert empty == {"nodes": [], "edges": []}
    print("PASS  nonexistent center returns empty payload")


def test_cross_module_consistency(transactions, ground_truth):
    section("Cross-module consistency")
    # Every ground-truth transaction_id should appear as an edge key
    G = build_graph(transactions)
    edge_ids = set()
    for u, v, k in G.edges(keys=True):
        edge_ids.add(k)

    missing = set(ground_truth.keys()) - edge_ids
    assert not missing, f"Ground-truth IDs missing from graph: {list(missing)[:5]}"
    print(f"PASS  all {len(ground_truth)} ground-truth IDs present as graph edges")


def main():
    accounts, transactions, ground_truth = test_generator()
    test_loader_with_csv()
    test_loader_errors()
    test_graph(transactions)
    test_cross_module_consistency(transactions, ground_truth)

    section("All checks passed")


if __name__ == "__main__":
    main()