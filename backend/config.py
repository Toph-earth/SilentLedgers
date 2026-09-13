"""
config.py — Runtime configuration for Silent Ledger.

Values here can be overridden at runtime via POST /api/config.
They are read by detectors.py and data_generator.py at pipeline run time,
not at import time, so changing them triggers a different result on the
next pipeline execution.
"""

import os

# The threshold above which transfers must be reported.
# Jurisdiction-dependent:
#   US:  $10,000 (Bank Secrecy Act)
#   EU:  €15,000 (AMLD5)
#   India: ₹10,00,000 (PMLA)
REPORTING_THRESHOLD: float = float(os.getenv("REPORTING_THRESHOLD", "10000"))

# Score above which an account is considered flagged.
FLAG_THRESHOLD: int = int(os.getenv("FLAG_THRESHOLD", "60"))

# Blend weights for the risk score.
RULE_WEIGHT: float = float(os.getenv("RULE_WEIGHT", "0.6"))
ML_WEIGHT: float = float(os.getenv("ML_WEIGHT", "0.4"))