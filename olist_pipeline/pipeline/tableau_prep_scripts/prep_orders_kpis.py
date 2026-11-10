"""
Tableau Prep Script step  ->  replaces / reproduces the CL_orders clean step.

In Tableau Prep:  IN_orders  ->  [+] Script
    Connection type : Tableau Python (TabPy) Server   (localhost : 9004)
    File name       : prep_orders_kpis.py
    Function name   : orders_kpis

The logic is NOT copied here - it is imported from olist_functions.py,
so Python and Tableau Prep always run the same code.
"""
import os
import sys

import pandas as pd

PIPELINE_DIR = os.environ.get("OLIST_PIPELINE_DIR",
                              r"C:\Users\DELL\Data Management\olist_pipeline\pipeline")
sys.path.insert(0, PIPELINE_DIR)
import importlib  # noqa: E402
if 'olist_functions' in sys.modules:  # TabPy keeps old code in memory -> always load the latest file
    importlib.reload(sys.modules['olist_functions'])
import olist_functions as F  # noqa: E402



def to_prep(df: pd.DataFrame) -> pd.DataFrame:
    """Make the result JSON-safe for TabPy: dates back in Prep's own format, NaN/NaT as None."""
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.strftime("%Y-%m-%dT%H:%M:%SZ[UTC]")
    return df.astype(object).where(df.notna(), None)

def to_datetime_fast(s: pd.Series) -> pd.Series:
    """Accepts what Prep sends: '2017-10-10T21:25:13Z[UTC]', ISO text, datetimes or epoch numbers."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return s.dt.tz_localize(None) if s.dt.tz is not None else s
    if pd.api.types.is_numeric_dtype(s):                       # epoch milliseconds
        return pd.to_datetime(s, unit="ms", errors="coerce")
    txt = s.astype("string").str.replace(r"\[.*\]$", "", regex=True).str.strip()
    out = pd.to_datetime(txt, errors="coerce", format="ISO8601", utc=True).dt.tz_localize(None)
    bad = out.isna() & txt.notna() & (txt != "")
    if bad.any() and txt[bad].str.fullmatch(r"-?\d+(\.\d+)?").all():
        out[bad] = pd.to_datetime(txt[bad].astype(float), unit="ms", errors="coerce")
    elif bad.any():
        out[bad] = pd.to_datetime(txt[bad], errors="coerce", format="mixed")
    return out

NULLABLE_INT = ["delivery_days", "delay_days", "seller_handling_days", "is_late"]


def orders_kpis(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = F.DATE_COLUMNS["orders"]
    df = df.copy()
    for c in date_cols:
        df[c] = to_datetime_fast(df[c])
    out = F.clean_orders(df)
    out[NULLABLE_INT] = out[NULLABLE_INT].astype("float")   # TabPy cannot send pd.NA
    result = to_prep(out)
    return result


def get_output_schema():
    # prep_* helpers are provided by Tableau Prep at run time
    return pd.DataFrame({
        "order_id": prep_string(),
        "customer_id": prep_string(),
        "order_status": prep_string(),
        "order_purchase_timestamp": prep_datetime(),
        "order_approved_at": prep_datetime(),
        "order_delivered_carrier_date": prep_datetime(),
        "order_delivered_customer_date": prep_datetime(),
        "order_estimated_delivery_date": prep_datetime(),
        "purchase_date": prep_datetime(),
        "purchase_month": prep_datetime(),
        "delivery_days": prep_decimal(),
        "delay_days": prep_decimal(),
        "seller_handling_days": prep_decimal(),
        "is_late": prep_decimal(),
        "dq_flag": prep_string(),
    })
