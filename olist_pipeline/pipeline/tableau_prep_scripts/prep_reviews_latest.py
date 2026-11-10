"""
Tableau Prep Script step  ->  reproduces CL_reviews (flags + review_rank).

In Tableau Prep:  IN_order_reviews  ->  [+] Script
    File name     : prep_reviews_latest.py
    Function name : reviews_ranked
Then keep the existing Filter  [review_rank] = 1  for fact_orders.
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
    """Tableau Prep sends dates as '2017-10-10T21:25:13Z[UTC]' -> naive datetime."""
    txt = s.astype("string").str.replace(r"\[.*\]$", "", regex=True).str.strip()
    out = pd.to_datetime(txt, errors="coerce", format="ISO8601", utc=True).dt.tz_localize(None)
    bad = out.isna() & txt.notna() & (txt != "")
    if bad.any():
        out[bad] = pd.to_datetime(txt[bad], errors="coerce", format="mixed")
    return out


def reviews_ranked(df: pd.DataFrame) -> pd.DataFrame: #reads two review dates (review_creation_date, review_answer_timestamp) and returns the cleaned reviews with flags and review_rank
    df = df.copy()
    for c in F.DATE_COLUMNS["order_reviews"]:
        df[c] = to_datetime_fast(df[c])
    return to_prep(F.clean_reviews(df))#trim extra spaces, add review_key=review_id+_+order_id
#thats how fact_orders gets exactly one review per order

def get_output_schema():
    return pd.DataFrame({
        "review_id": prep_string(),
        "order_id": prep_string(),
        "review_score": prep_int(),
        "review_comment_title": prep_string(),
        "review_comment_message": prep_string(),
        "review_creation_date": prep_datetime(),
        "review_answer_timestamp": prep_datetime(),
        "review_key": prep_string(),
        "has_comment": prep_int(),
        "is_low_score": prep_int(),
        "review_rank": prep_int(),
    })
