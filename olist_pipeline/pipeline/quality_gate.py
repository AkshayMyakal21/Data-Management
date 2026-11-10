"""
quality_gate.py
===============
Python quality gate that runs AFTER the transformation (Tableau Prep or Python)
and BEFORE anything is published.

  FAIL  -> the run is blocked, nothing is published
  WARN  -> published, but the issue is written to the quality report

Can be used three ways:
  * from run_pipeline.py (automatic)
  * stand-alone on CSVs exported from Tableau Prep:
        python quality_gate.py --raw raw --clean clean_output
  * inside a Tableau Prep Script step (see tabpy_script_steps.py)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

GRAIN = {                                   # output contract: one row per ...
    "fact_orders": ["order_id"],
    "fact_order_items": ["order_id", "order_item_id"],
    "fact_payments": ["order_id", "payment_sequential"],
    "fact_reviews": ["review_id", "order_id"],
    "dim_customers": ["customer_id"],
    "dim_sellers": ["seller_id"],
    "dim_products": ["product_id"],
    "dim_date": ["purchase_date"],
    "dim_location": ["zip_code_prefix", "city", "state", "role"],
}

FOREIGN_KEYS = [                            # (child, column, parent, column)
    ("fact_order_items", "order_id", "fact_orders", "order_id"),
    ("fact_order_items", "product_id", "dim_products", "product_id"),
    ("fact_order_items", "seller_id", "dim_sellers", "seller_id"),
    ("fact_payments", "order_id", "fact_orders", "order_id"),
    ("fact_reviews", "order_id", "fact_orders", "order_id"),
    ("fact_orders", "customer_id", "dim_customers", "customer_id"),
]


def _check(results, table, check, failed_rows, severity="FAIL", detail=""):
    results.append({
        "table": table, "check": check, "failed_rows": int(failed_rows),
        "status": "PASS" if failed_rows == 0 else severity, "detail": detail,
    })


def run_quality_gate(out: dict[str, pd.DataFrame],
                     raw: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """Return one row per check. Any status == 'FAIL' blocks publishing."""
    res: list[dict] = []

    # 1. Grain / primary key
    for t, pk in GRAIN.items():
        if t in out:
            _check(res, t, f"PK unique ({', '.join(pk)})", out[t].duplicated(subset=pk).sum())
            _check(res, t, "PK not null", out[t][pk].isna().any(axis=1).sum())

    # 2. Referential integrity
    for child, ccol, parent, pcol in FOREIGN_KEYS:
        if child in out and parent in out:
            orphans = ~out[child][ccol].isin(out[parent][pcol])
            _check(res, child, f"FK {ccol} -> {parent}", orphans.sum())

    # 3. Domain rules
    if "fact_reviews" in out:
        _check(res, "fact_reviews", "review_score in 1..5",
               (~out["fact_reviews"]["review_score"].between(1, 5)).sum())
    if "fact_order_items" in out:
        fi = out["fact_order_items"]
        _check(res, "fact_order_items", "price > 0", (fi["price"] <= 0).sum())
        _check(res, "fact_order_items", "freight >= 0", (fi["freight_value"] < 0).sum())
        _check(res, "fact_order_items", "distance missing (no geo match)",
               fi["distance_km"].isna().sum(), "WARN")
    if "fact_payments" in out:
        _check(res, "fact_payments", "installments >= 1",
               (out["fact_payments"]["installments_clean"] < 1).sum())
    if "fact_orders" in out:
        fo = out["fact_orders"]
        _check(res, "fact_orders", "is_late in {0,1,null}",
               (~fo["is_late"].isin([0, 1]) & fo["is_late"].notna()).sum())
        flagged = (fo["dq_flag"] != "ok").sum()
        counts = fo["dq_flag"].value_counts().to_dict()
        date_cols = [c for c in fo.columns if c.startswith("order_") and c not in ("order_id", "order_status")]
        example = fo.loc[fo["dq_flag"] != "ok", ["order_status"] + date_cols].head(1).to_dict("records")
        _check(res, "fact_orders", "dq_flag != ok (flagged, kept)", flagged, "WARN",
               detail=f"{counts} | example: {example}")
        # more than 1 % flagged means a broken load (e.g. dates not parsed), not bad data
        _check(res, "fact_orders", "flagged orders <= 1 % (date parsing ok)",
               int(flagged > 0.01 * len(fo)), detail=f"{flagged} of {len(fo)} flagged")
        delivered = fo["order_status"] == "delivered"
        _check(res, "fact_orders", "delivered orders have a delivery date (>= 99 %)",
               int(fo.loc[delivered, "order_delivered_customer_date"].notna().mean() < 0.99))
        _check(res, "fact_orders", "payment_mismatch > 1 BRL",
               fo["payment_mismatch"].sum(), "WARN")
    if "dim_location" in out:
        _check(res, "dim_location", "role in {customer, seller}",
               (~out["dim_location"]["role"].isin(["customer", "seller"])).sum())
        _check(res, "dim_location", "both roles present",
               int(out["dim_location"]["role"].nunique() < 2))

    # 4. Reconciliation with the raw source (nothing lost, nothing invented)
    if raw is not None:
        pairs = [("fact_orders", "orders", 0),
                 ("fact_order_items", "order_items", 0),
                 ("fact_reviews", "order_reviews", 0),
                 ("dim_customers", "customers", 0),
                 ("dim_sellers", "sellers", 0),
                 ("dim_products", "products", 0),
                 ("fact_payments", "order_payments",
                  int((raw["order_payments"]["payment_type"] == "not_defined").sum()))]
        for t, r, expected_drop in pairs:
            if t in out:
                diff = abs(len(raw[r]) - expected_drop - len(out[t]))
                _check(res, t, f"row count = raw {r} ({len(raw[r]):,}) - {expected_drop}", diff,
                       detail=f"raw={len(raw[r])}, out={len(out[t])}")
        if "fact_order_items" in out:
            gap = round(raw["order_items"]["price"].sum() - out["fact_order_items"]["price"].sum(), 2)
            _check(res, "fact_order_items", "sum(price) equals raw", int(gap != 0),
                   detail=f"difference = {gap}")

    return pd.DataFrame(res)


def assert_gate(report: pd.DataFrame) -> None:
    fails = report[report["status"] == "FAIL"]
    if len(fails):
        raise RuntimeError("Quality gate FAILED - not publishing:\n" + fails.to_string(index=False))


if __name__ == "__main__":
    from olist_functions import load_raw
    ap = argparse.ArgumentParser(description="Run the quality gate on published CSVs")
    ap.add_argument("--raw", required=True, help="folder with the 9 raw Olist CSVs")
    ap.add_argument("--clean", required=True, help="folder with fact_*/dim_* CSVs")
    a = ap.parse_args()
    outs = {p.stem: pd.read_csv(p) for p in Path(a.clean).glob("*.csv") if p.stem in GRAIN}
    rep = run_quality_gate(outs, load_raw(a.raw))
    print(rep.to_string(index=False))
    assert_gate(rep)
    print("\nQuality gate PASSED")
