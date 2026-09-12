"""
csv_loader.py — Parse uploaded CSV bytes into Account and Transaction lists.

This module mirrors data_generator.py's output contract exactly:
  (accounts, transactions, ground_truth)

Everything downstream (graph_builder, detectors, risk_scorer) does not know
or care whether those lists came from the generator or from a user-uploaded
CSV. That is the whole point of the isolation boundary.

What this module does:
  - Parse required transaction columns: source_account, dest_account,
    amount, timestamp. Currency is optional (defaults to USD).
  - Derive the account list from transaction endpoints when no separate
    accounts file is provided. Default account_type to "individual" and
    name to the account_id.
  - Validate and reject clearly: missing columns, unparseable timestamps,
    non-numeric amounts. Errors are returned as specific messages, never
    as stack traces — this is the one place untrusted input touches the
    system.

What this module explicitly does NOT do:
  - Run detection.
  - Touch NetworkX.
  - Know anything about the API.

Ground truth: if the CSV carries a `pattern_tag` column, it is read into
the same dict[str, str] shape the generator produces
(transaction_id -> pattern_type). If the column is absent, ground_truth
is an empty dict. Transaction objects never carry the tag themselves.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from models import Account, AccountType, PatternType, Transaction


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------

class CSVLoadError(ValueError):
    """Raised when a CSV cannot be parsed into a valid dataset.

    The message is always human-readable and specific — it is shown to the
    user as-is. Never wrap this in a generic 500 handler.
    """


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REQUIRED_TXN_COLUMNS = {"source_account", "dest_account", "amount", "timestamp"}
OPTIONAL_TXN_COLUMNS = {"transaction_id", "currency", "pattern_tag"}

# Account file columns, if a separate accounts CSV is uploaded.
REQUIRED_ACCOUNT_COLUMNS = {"account_id"}
OPTIONAL_ACCOUNT_COLUMNS = {"name", "account_type", "created_at"}

DEFAULT_CURRENCY = "USD"


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

_TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y",
)


def _parse_timestamp(raw: str, row_num: int) -> datetime:
    """Parse a timestamp string into an aware UTC datetime.

    Tries a small set of common formats. If none match, raises
    CSVLoadError with the row number and the raw value so the user can fix
    it. Never silently drops rows.
    """
    raw = raw.strip()
    if not raw:
        raise CSVLoadError(f"Row {row_num}: timestamp is empty.")

    # Try ISO first — handles most exports including those with +00:00.
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass

    # Fall back to the explicit format list.
    for fmt in _TIMESTAMP_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    raise CSVLoadError(
        f"Row {row_num}: cannot parse timestamp '{raw}'. "
        f"Expected ISO 8601 (e.g. 2025-08-15T14:23:00Z) or a common "
        f"date format."
    )


# ---------------------------------------------------------------------------
# Amount parsing
# ---------------------------------------------------------------------------

def _parse_amount(raw: str, row_num: int) -> float:
    """Parse an amount string into a positive float.

    Strips $ and , so common exports validate. Rejects zero, negative, and
    non-numeric values with a row-specific message.
    """
    raw = raw.strip()
    if not raw:
        raise CSVLoadError(f"Row {row_num}: amount is empty.")

    cleaned = raw.replace("$", "").replace(",", "").strip()
    try:
        value = float(cleaned)
    except ValueError:
        raise CSVLoadError(
            f"Row {row_num}: cannot parse amount '{raw}' as a number."
        )

    if value <= 0:
        raise CSVLoadError(
            f"Row {row_num}: amount must be positive (got {value})."
        )

    return round(value, 2)


# ---------------------------------------------------------------------------
# CSV header validation
# ---------------------------------------------------------------------------

def _validate_headers(
    fieldnames: Optional[List[str]],
    required: set,
    file_label: str,
) -> None:
    """Raise CSVLoadError if any required column is missing.

    Reports exactly which columns are missing so the user can add them.
    """
    if not fieldnames:
        raise CSVLoadError(f"{file_label}: file has no header row.")

    present = {name.strip() for name in fieldnames if name}
    missing = required - present
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise CSVLoadError(
            f"{file_label}: missing required column(s): {missing_list}."
        )


# ---------------------------------------------------------------------------
# Transaction parsing
# ---------------------------------------------------------------------------

def _parse_transactions(
    txn_bytes: bytes,
) -> Tuple[List[Transaction], Dict[str, str]]:
    """Parse transaction CSV bytes into Transaction objects + ground truth.

    Returns (transactions, ground_truth). ground_truth maps
    transaction_id -> pattern_type string for every row carrying a
    non-empty pattern_tag value.
    """
    try:
        text = txn_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CSVLoadError(
            "Transactions file: not valid UTF-8. Save the CSV as UTF-8 and retry."
        )

    reader = csv.DictReader(io.StringIO(text))
    _validate_headers(
        reader.fieldnames, REQUIRED_TXN_COLUMNS, "Transactions file"
    )

    transactions: List[Transaction] = []
    ground_truth: Dict[str, str] = {}

    for row_num, row in enumerate(reader, start=2):  # header is row 1
        # Skip entirely blank rows silently.
        if not any((v or "").strip() for v in row.values()):
            continue

        source = (row.get("source_account") or "").strip()
        dest = (row.get("dest_account") or "").strip()
        if not source:
            raise CSVLoadError(f"Row {row_num}: source_account is empty.")
        if not dest:
            raise CSVLoadError(f"Row {row_num}: dest_account is empty.")
        if source == dest:
            raise CSVLoadError(
                f"Row {row_num}: source_account and dest_account are the same "
                f"({source}). Self-transfers are not valid."
            )

        amount = _parse_amount(row.get("amount", ""), row_num)
        timestamp = _parse_timestamp(row.get("timestamp", ""), row_num)

        currency = (row.get("currency") or "").strip() or DEFAULT_CURRENCY

        # transaction_id is optional. If absent, assign a stable synthetic
        # ID derived from the row position so the rest of the system has a
        # consistent handle on each transaction.
        txn_id = (row.get("transaction_id") or "").strip()
        if not txn_id:
            txn_id = f"CSV_{row_num:05d}"

        transactions.append(
            Transaction(
                transaction_id=txn_id,
                source_account=source,
                dest_account=dest,
                amount=amount,
                timestamp=timestamp,
                currency=currency,
            )
        )

        # Read pattern_tag into ground truth if present. Never attach it to
        # the Transaction object.
        tag_raw = (row.get("pattern_tag") or "").strip()
        if tag_raw:
            try:
                pattern = PatternType(tag_raw)
            except ValueError:
                valid = ", ".join(p.value for p in PatternType)
                raise CSVLoadError(
                    f"Row {row_num}: unknown pattern_tag '{tag_raw}'. "
                    f"Expected one of: {valid}."
                )
            ground_truth[txn_id] = pattern.value

    if not transactions:
        raise CSVLoadError("Transactions file: no data rows found.")

    return transactions, ground_truth


# ---------------------------------------------------------------------------
# Account parsing
# ---------------------------------------------------------------------------

def _parse_accounts(
    acc_bytes: bytes,
) -> Tuple[List[Account], Dict[str, str]]:
    """Parse an optional accounts CSV into Account objects.

    Returns (accounts, category_map). category_map is always empty for
    uploaded accounts — we have no way to know which are laundering.
    The return shape mirrors the generator so callers can treat both
    uniformly.
    """
    try:
        text = acc_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CSVLoadError(
            "Accounts file: not valid UTF-8. Save the CSV as UTF-8 and retry."
        )

    reader = csv.DictReader(io.StringIO(text))
    _validate_headers(
        reader.fieldnames, REQUIRED_ACCOUNT_COLUMNS, "Accounts file"
    )

    accounts: List[Account] = []
    seen: set = set()

    for row_num, row in enumerate(reader, start=2):
        if not any((v or "").strip() for v in row.values()):
            continue

        acc_id = (row.get("account_id") or "").strip()
        if not acc_id:
            raise CSVLoadError(f"Row {row_num}: account_id is empty.")
        if acc_id in seen:
            raise CSVLoadError(
                f"Row {row_num}: duplicate account_id '{acc_id}'."
            )
        seen.add(acc_id)

        name = (row.get("name") or "").strip() or acc_id

        type_raw = (row.get("account_type") or "").strip().lower()
        if type_raw:
            try:
                acc_type = AccountType(type_raw)
            except ValueError:
                valid = ", ".join(t.value for t in AccountType)
                raise CSVLoadError(
                    f"Row {row_num}: unknown account_type '{type_raw}'. "
                    f"Expected one of: {valid}."
                )
        else:
            acc_type = AccountType.INDIVIDUAL

        created_raw = (row.get("created_at") or "").strip()
        if created_raw:
            created_at = _parse_timestamp(created_raw, row_num)
        else:
            # Default to "now" so the field is populated. Real CSVs rarely
            # carry account creation dates.
            created_at = datetime.now(timezone.utc)

        accounts.append(
            Account(
                account_id=acc_id,
                name=name,
                account_type=acc_type,
                is_laundering=False,
                created_at=created_at,
            )
        )

    return accounts, {}


# ---------------------------------------------------------------------------
# Account derivation from transactions
# ---------------------------------------------------------------------------

def _derive_accounts(
    transactions: List[Transaction],
) -> List[Account]:
    """Build an Account list from the endpoints present in transactions.

    Most real-world CSVs hand you a transaction log with no account table.
    We synthesize one: default account_type to "individual" and name to
    the account_id itself. If a separate accounts file is uploaded, this
    function is not called and the uploaded accounts are used instead.
    """
    seen: Dict[str, Account] = {}
    now = datetime.now(timezone.utc)

    for txn in transactions:
        for acc_id in (txn.source_account, txn.dest_account):
            if acc_id not in seen:
                seen[acc_id] = Account(
                    account_id=acc_id,
                    name=acc_id,
                    account_type=AccountType.INDIVIDUAL,
                    is_laundering=False,
                    created_at=now,
                )

    return list(seen.values())


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_from_csv(
    txn_bytes: bytes,
    acc_bytes: Optional[bytes] = None,
) -> Tuple[List[Account], List[Transaction], Dict[str, str]]:
    """Load a dataset from uploaded CSV bytes.

    Mirrors data_generator.generate_dataset() in return shape:
      (accounts, transactions, ground_truth)

    acc_bytes is optional. If provided, accounts are read from it. If not,
    accounts are derived from the transaction endpoints.

    Raises CSVLoadError with a specific, human-readable message on any
    validation failure. The caller (an API route) is expected to catch
    CSVLoadError and return a 400 with the message — this is the boundary
    where untrusted input stops.
    """
    transactions, ground_truth = _parse_transactions(txn_bytes)

    if acc_bytes is not None:
        accounts, _ = _parse_accounts(acc_bytes)
        # Cross-check: every transaction endpoint must exist in the account
        # list. A mismatch is almost always a user error and worth catching
        # before it silently corrupts the graph.
        known = {a.account_id for a in accounts}
        referenced = set()
        for txn in transactions:
            referenced.add(txn.source_account)
            referenced.add(txn.dest_account)
        unknown = referenced - known
        if unknown:
            sample = ", ".join(sorted(unknown)[:5])
            more = "" if len(unknown) <= 5 else f" (+{len(unknown) - 5} more)"
            raise CSVLoadError(
                f"Transactions reference {len(unknown)} account(s) not present "
                f"in the accounts file: {sample}{more}."
            )
    else:
        accounts = _derive_accounts(transactions)

    return accounts, transactions, ground_truth