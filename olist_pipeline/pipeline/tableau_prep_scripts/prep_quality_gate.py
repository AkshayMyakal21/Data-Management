"""
Tableau Prep Script step  ->  quality gate on fact_orders, inside the flow.

In Tableau Prep:  CL_fact_orders  ->  [+] Script  ->  Output "quality_gate_report.csv"
    File name     : prep_quality_gate.py
    Function name : gate_fact_orders

The step returns the check report (one row per check). If any check is FAIL
the step raises an error, so the Prep run stops and fact_orders is NOT published.
"""
import os
import sys

import pandas as pd

PIPELINE_DIR = os.environ.get("OLIST_PIPELINE_DIR",
                              r"C:\Users\DELL\Data Management\olist_pipeline\pipeline")
sys.path.insert(0, PIPELINE_DIR)
import importlib  # noqa: E402
if 'quality_gate' in sys.modules:  # TabPy keeps old code in memory -> always load the latest file
    importlib.reload(sys.modules['quality_gate'])
from quality_gate import run_quality_gate, assert_gate  # noqa: E402


def gate_fact_orders(df: pd.DataFrame) -> pd.DataFrame:
    report = run_quality_gate({"fact_orders": df})
    # always keep a copy on disk, also when the gate fails and stops the flow
    report.to_csv(os.path.join(PIPELINE_DIR, "prep_gate_last_run.csv"), index=False)
    assert_gate(report)                  # stops the flow on FAIL
    return report


def get_output_schema():
    return pd.DataFrame({
        "table": prep_string(),
        "check": prep_string(),
        "failed_rows": prep_int(),
        "status": prep_string(),
        "detail": prep_string(),
    })
