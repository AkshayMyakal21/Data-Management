"""
run_pipeline.py
===============
One command from raw CSVs to the validated star schema.

    python run_pipeline.py --input raw --output clean_output

Steps:  load raw (immutable)  ->  olist_functions.run_all()  ->  quality gate
        ->  write sorted CSVs (+ optional .hyper)  ->  manifest.json (row counts + SHA-256)

Re-running on the same input gives byte-identical files (same hashes).
Running on a newer Olist export applies exactly the same rules.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import olist_functions as F
from quality_gate import assert_gate, run_quality_gate


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_outputs(outputs: dict[str, pd.DataFrame], out_dir: Path, hyper: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, df in outputs.items():
        path = out_dir / f"{name}.csv"
        df.to_csv(path, index=False, float_format="%.6f", date_format="%Y-%m-%d %H:%M:%S",
                  lineterminator="\n")
        files[name] = {"rows": len(df), "columns": df.shape[1], "sha256": sha256_file(path)}
        if hyper:
            write_hyper(df, out_dir / f"{name}.hyper")
    return files


def write_hyper(df: pd.DataFrame, path: Path) -> None:
    """Optional: same .hyper output as Tableau Prep (needs `pip install pantab`)."""
    import pantab
    pantab.frame_to_hyper(df, path, table="Extract")


def run(input_dir: str, output_dir: str, hyper: bool = False) -> dict:
    raw = F.load_raw(input_dir)
    outputs = F.run_all(raw)

    report = run_quality_gate(outputs, raw)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report.to_csv(out_dir / "quality_gate_report.csv", index=False)
    assert_gate(report)                         # stops here if any FAIL

    files = write_outputs(outputs, out_dir, hyper)
    manifest = {
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_dir": str(Path(input_dir).resolve()),
        "input_files": {k: sha256_file(Path(input_dir) / v) for k, v in F.RAW_FILES.items()},
        "code_sha256": sha256_file(Path(F.__file__)),
        "quality_gate": report["status"].value_counts().to_dict(),
        "outputs": files,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Olist reproducible pipeline")
    ap.add_argument("--input", required=True, help="folder with the 9 raw Olist CSVs")
    ap.add_argument("--output", required=True, help="folder for published tables")
    ap.add_argument("--hyper", action="store_true", help="also write .hyper extracts")
    a = ap.parse_args()
    m = run(a.input, a.output, a.hyper)
    print(f"Quality gate: {m['quality_gate']}")
    for name, info in m["outputs"].items():
        print(f"{name:18s} {info['rows']:>8,} rows   sha256 {info['sha256'][:12]}")
