"""
test_reproducibility.py
=======================
Evidence for the "Reproducible pipeline" slide.

Test 1  Determinism    : run the full pipeline twice -> every output file has the same SHA-256.
Test 2  New data       : run on an "old" snapshot (orders until 2017-12-31), then on the full
                         data. The gate passes both times, and every 2017 order in the full run
                         is identical to the snapshot run -> new data does not change old results.
Test 3  Gate catches errors : break the data on purpose (duplicate order, orphan item)
                         -> the gate must FAIL and block publishing.

    python test_reproducibility.py --input raw
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

import pandas as pd

import olist_functions as F
from quality_gate import run_quality_gate
from run_pipeline import run


def snapshot(raw: dict[str, pd.DataFrame], cutoff: str) -> dict[str, pd.DataFrame]:
    """Simulate an older export: only orders purchased up to `cutoff` (and their children)."""
    snap = dict(raw)
    orders = raw["orders"][raw["orders"]["order_purchase_timestamp"] <= cutoff]
    ids = set(orders["order_id"])
    snap["orders"] = orders
    for t in ("order_items", "order_payments", "order_reviews"):
        snap[t] = raw[t][raw[t]["order_id"].isin(ids)]
    return snap


def main(input_dir: str) -> None:
    tmp = Path(tempfile.mkdtemp())

    # ---- Test 1: determinism -------------------------------------------------
    m1 = run(input_dir, tmp / "run1")
    m2 = run(input_dir, tmp / "run2")
    same = all(m1["outputs"][t]["sha256"] == m2["outputs"][t]["sha256"] for t in m1["outputs"])
    print(f"Test 1  identical SHA-256 on re-run ........ {'PASS' if same else 'FAIL'}")

    # ---- Test 2: new data ----------------------------------------------------
    raw = F.load_raw(input_dir)
    old = F.run_all(snapshot(raw, "2017-12-31 23:59:59"))
    new = F.run_all(raw)
    gate_old = run_quality_gate(old)
    gate_new = run_quality_gate(new, raw)
    old_ids = old["fact_orders"]["order_id"]
    a = old["fact_orders"].set_index("order_id").sort_index()
    b = new["fact_orders"].set_index("order_id").loc[old_ids].sort_index()[a.columns]
    stable = a.equals(b)
    print(f"Test 2  snapshot 2017: {len(a):,} orders, full: {len(new['fact_orders']):,} orders")
    print(f"        gate on snapshot ................... "
          f"{'PASS' if (gate_old.status != 'FAIL').all() else 'FAIL'}")
    print(f"        gate on full data .................. "
          f"{'PASS' if (gate_new.status != 'FAIL').all() else 'FAIL'}")
    print(f"        2017 orders unchanged by new data .. {'PASS' if stable else 'FAIL'}")

    # ---- Test 3: gate blocks bad data ---------------------------------------
    broken = F.run_all(raw)
    broken["fact_orders"] = pd.concat([broken["fact_orders"], broken["fact_orders"].head(1)])
    orphan = broken["fact_order_items"].head(1).assign(order_id="does_not_exist")
    broken["fact_order_items"] = pd.concat([broken["fact_order_items"], orphan])
    g = run_quality_gate(broken)
    caught = g[g.status == "FAIL"]["check"].tolist()
    print(f"Test 3  gate blocks broken data ............ {'PASS' if caught else 'FAIL'}  {caught}")

    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    main(ap.parse_args().input)
