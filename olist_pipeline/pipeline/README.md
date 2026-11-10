# Olist reproducible pipeline (Team 2 – Hercules)

Put this `pipeline/` folder inside `DM_project/` next to the raw CSVs.

```
pip install pandas numpy openpyxl          # (+ pantab for --hyper, tabpy for Prep script steps)

python run_pipeline.py --input .. --output ../clean_output_py      # raw -> gate -> 9 tables + manifest.json
python test_reproducibility.py --input ..                          # 3 reproducibility tests
python quality_gate.py --raw .. --clean ../clean_output            # gate on CSVs exported from Tableau Prep
python build_data_dictionary.py --clean ../clean_output_py --out governance_pack.xlsx
```

| File | What it is |
|---|---|
| `olist_functions.py` | One pure function per Tableau Prep step (`clean_orders`, `clean_reviews`, `build_fact_orders`, ...) + `run_all()` |
| `quality_gate.py` | PK, FK, domain and raw-reconciliation checks. FAIL = do not publish |
| `run_pipeline.py` | CLI: runs everything, writes sorted CSVs (+ .hyper) and `manifest.json` with SHA-256 hashes |
| `test_reproducibility.py` | Same hashes on re-run · new data doesn't change old results · gate blocks broken data |
| `tableau_prep_scripts/` | The same functions called from a Tableau Prep **Script** step (TabPy) |
| `build_data_dictionary.py` | Generates the governance pack (tables, dictionary, roles, lineage, AI risks, gate report) |

## Using the functions inside Tableau Prep (Script step)

1. `pip install tabpy` then start it: `tabpy` (runs on `localhost:9004`).
2. Tableau Prep → **Help › Settings and Performance › Manage Analytics Extensions Connection** → TabPy, localhost, 9004.
3. In the flow click **+** after `IN_orders` → **Script** → Tableau Python (TabPy) Server
   → file `tableau_prep_scripts/prep_orders_kpis.py`, function `orders_kpis`.
   Same for `IN_order_reviews` → `prep_reviews_latest.py` / `reviews_ranked`,
   and after `CL_fact_orders` → `prep_quality_gate.py` / `gate_fact_orders` → Output `quality_gate_report.csv`.
4. If the project is not in `C:\Users\DELL\Data Management\olist_pipeline\pipeline`, set the environment
   variable `OLIST_PIPELINE_DIR` (or edit `PIPELINE_DIR` at the top of each script).

## Notes from the first real run in Tableau Prep
* Prep sends dates to TabPy as text like `2017-10-10T21:25:13Z[UTC]`; the scripts parse and return this format.
* Start TabPy with `tabpy --config=tabpy.conf` (raises the 30 s script timeout to 600 s).
* Prep keeps its own copy of a script: after editing a `.py` file, click the Script step → **Browse** → select the file again, then Run Flow and save.
* Expected gate result on Olist v7: 203 of 99,441 orders flagged (WARN), payment_mismatch 249 (WARN), all other checks PASS.
