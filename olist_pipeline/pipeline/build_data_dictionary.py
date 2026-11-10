"""
build_data_dictionary.py
========================
Generates governance_pack.xlsx from the published tables, so the data dictionary
is always in sync with what the pipeline actually produced.

    python build_data_dictionary.py --clean clean_output --out governance_pack.xlsx
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from quality_gate import GRAIN

# ---------------------------------------------------------------- descriptions
# column -> (description, source / rule, sensitivity)
COL = {
    "order_id": ("Order identifier (hashed by Olist)", "orders.order_id", "Pseudonymous ID"),
    "customer_id": ("Customer key per order (one per order)", "orders / customers.customer_id", "Pseudonymous ID"),
    "customer_unique_id": ("Real customer across orders - use for repeat buyers", "customers.customer_unique_id", "Pseudonymous ID"),
    "seller_id": ("Seller identifier", "sellers.seller_id", "Pseudonymous ID"),
    "product_id": ("Product identifier", "products.product_id", "Public"),
    "review_id": ("Review identifier (not unique alone: 814 duplicates)", "order_reviews.review_id", "Pseudonymous ID"),
    "order_item_id": ("Line number inside the order (1..n)", "order_items.order_item_id", "Public"),
    "payment_sequential": ("Sequence of the payment inside the order", "order_payments.payment_sequential", "Public"),
    "order_status": ("Order status (delivered, shipped, canceled, ...)", "orders.order_status", "Public"),
    "order_purchase_timestamp": ("When the customer placed the order", "orders, parsed to datetime", "Public"),
    "order_approved_at": ("When payment was approved", "orders, parsed to datetime", "Public"),
    "order_delivered_carrier_date": ("Handed to the carrier", "orders, parsed to datetime", "Public"),
    "order_delivered_customer_date": ("Delivered to the customer (NULL if not delivered)", "orders, parsed to datetime", "Public"),
    "order_estimated_delivery_date": ("Delivery date promised at purchase", "orders, parsed to datetime", "Public"),
    "purchase_date": ("Purchase day (no time)", "DATE(order_purchase_timestamp)", "Public"),
    "purchase_month": ("First day of purchase month", "DATETRUNC('month', purchase)", "Public"),
    "delivery_days": ("Days from purchase to delivery", "DATEDIFF(day, purchase, delivered)", "Public"),
    "delay_days": ("Days late (+) or early (-) vs promise", "DATEDIFF(day, estimated, delivered)", "Public"),
    "seller_handling_days": ("Days from approval to carrier hand-over", "DATEDIFF(day, approved, carrier)", "Public"),
    "is_late": ("1 = delivered after promised date, NULL = not delivered", "delay_days > 0", "Public"),
    "dq_flag": ("Data-quality flag; suspicious rows are kept, not deleted", "ok / delivered_no_date / not_delivered_but_has_date / carrier_before_purchase / delivered_before_carrier", "Public"),
    "customer_zip_code_prefix": ("Raw 5-digit zip prefix (leading zero lost in raw)", "customers", "Quasi-identifier"),
    "customer_zip": ("Zip prefix as 5-char text", "RIGHT('00000'+zip,5)", "Quasi-identifier"),
    "customer_city": ("City as delivered by Olist", "customers.customer_city", "Quasi-identifier"),
    "customer_city_clean": ("City trimmed + lower case", "LOWER(TRIM(city))", "Quasi-identifier"),
    "customer_state": ("Brazilian state (UF)", "customers.customer_state", "Public"),
    "seller_zip_code_prefix": ("Raw zip prefix of seller", "sellers", "Quasi-identifier"),
    "seller_zip": ("Seller zip as 5-char text", "RIGHT('00000'+zip,5)", "Quasi-identifier"),
    "seller_city": ("Seller city as in raw (has 'city / uf' variants)", "sellers.seller_city", "Quasi-identifier"),
    "seller_city_clean": ("City part only", "TRIM(SPLIT(SPLIT(city,'/',1),',',1))", "Quasi-identifier"),
    "seller_state": ("Seller state (UF)", "sellers.seller_state", "Public"),
    "geolocation_zip": ("Zip used for the coordinate join", "geolocation, padded", "Quasi-identifier"),
    "geolocation_lat": ("Average latitude of the zip prefix", "AVG(lat) per zip, Brazil box only", "Quasi-identifier"),
    "geolocation_lng": ("Average longitude of the zip prefix", "AVG(lng) per zip, Brazil box only", "Quasi-identifier"),
    "cust_lat": ("Customer zip latitude", "dim_customers.geolocation_lat", "Quasi-identifier"),
    "cust_lng": ("Customer zip longitude", "dim_customers.geolocation_lng", "Quasi-identifier"),
    "seller_lat": ("Seller zip latitude", "dim_sellers.geolocation_lat", "Quasi-identifier"),
    "seller_lng": ("Seller zip longitude", "dim_sellers.geolocation_lng", "Quasi-identifier"),
    "lat": ("Zip latitude", "geo_by_zip", "Quasi-identifier"),
    "lng": ("Zip longitude", "geo_by_zip", "Quasi-identifier"),
    "zip_code_prefix": ("5-char zip prefix", "customers + sellers union", "Quasi-identifier"),
    "city": ("Clean city name", "customers + sellers union", "Quasi-identifier"),
    "state": ("State (UF)", "customers + sellers union", "Public"),
    "role": ("Whether the place is a customer or a seller location", "'customer' / 'seller'", "Public"),
    "shipping_limit_date": ("Seller deadline to hand over to carrier", "order_items", "Public"),
    "price": ("Item price (BRL)", "order_items.price", "Public"),
    "freight_value": ("Freight charged for the item (BRL)", "order_items.freight_value", "Public"),
    "item_total": ("Price + freight (BRL)", "price + freight_value", "Public"),
    "freight_share": ("Freight relative to price", "freight_value / price", "Public"),
    "product_category_name": ("Category in Portuguese", "products", "Public"),
    "category_en": ("Category in English; 'unknown' if missing", "translation join + 2 manual fixes", "Public"),
    "product_name_length": ("Characters in product name", "renamed from 'lenght'", "Public"),
    "product_description_length": ("Characters in description", "renamed from 'lenght'", "Public"),
    "product_photos_qty": ("Number of photos", "products", "Public"),
    "product_weight_g": ("Weight in grams; 0 g set to NULL", "IF weight<=0 THEN NULL", "Public"),
    "product_length_cm": ("Length (cm)", "products", "Public"),
    "product_height_cm": ("Height (cm)", "products", "Public"),
    "product_width_cm": ("Width (cm)", "products", "Public"),
    "volume_cm3": ("Package volume", "length * height * width", "Public"),
    "distance_km": ("Seller-to-customer great-circle distance", "Haversine on zip coordinates", "Public"),
    "is_cross_state": ("1 = seller and customer in different states", "seller_state <> customer_state", "Public"),
    "n_items": ("Items in the order", "COUNT(order_item_id)", "Public"),
    "n_sellers": ("Distinct sellers in the order", "COUNTD(seller_id)", "Public"),
    "n_products": ("Distinct products in the order", "COUNTD(product_id)", "Public"),
    "items_value": ("Sum of item prices (BRL)", "SUM(price)", "Public"),
    "freight_total": ("Sum of freight (BRL)", "SUM(freight_value)", "Public"),
    "total_weight_g": ("Sum of product weights", "SUM(product_weight_g)", "Public"),
    "max_distance_km": ("Longest seller distance in the order", "MAX(distance_km)", "Public"),
    "total_paid": ("Total paid by customer (BRL)", "SUM(payment_value)", "Public"),
    "n_payments": ("Number of payment records", "COUNT(payment_sequential)", "Public"),
    "max_installments": ("Highest instalment count", "MAX(installments_clean)", "Public"),
    "used_voucher": ("1 = voucher used", "MAX(is_voucher)", "Public"),
    "review_score": ("Customer rating 1-5", "order_reviews.review_score", "Public"),
    "is_low_score": ("1 = score <= 2 (dissatisfied)", "review_score <= 2", "Public"),
    "has_comment": ("1 = customer wrote a comment", "comment not NULL/blank", "Public"),
    "review_answer_timestamp": ("When the review was answered", "order_reviews", "Public"),
    "review_comment_title": ("Free-text title (Portuguese)", "order_reviews, trimmed", "Free text - may contain personal data"),
    "review_comment_message": ("Free-text comment (Portuguese)", "order_reviews, trimmed", "Free text - may contain personal data"),
    "review_creation_date": ("Survey sent to customer", "order_reviews", "Public"),
    "review_key": ("Unique review key", "review_id + '_' + order_id", "Pseudonymous ID"),
    "review_rank": ("1 = latest review of the order", "ROW_NUMBER() per order by answer time DESC", "Public"),
    "order_value": ("Items + freight (BRL)", "items_value + freight_total", "Public"),
    "payment_gap": ("Paid minus order value (BRL)", "ROUND(total_paid - order_value, 2)", "Public"),
    "payment_mismatch": ("1 = gap > 1 BRL (interest, vouchers)", "ABS(payment_gap) > 1", "Public"),
    "payment_type": ("credit_card, boleto, voucher, debit_card", "'not_defined' rows removed", "Public"),
    "payment_installments": ("Instalments as in raw", "order_payments", "Public"),
    "payment_value": ("Payment amount (BRL)", "order_payments", "Public"),
    "installments_clean": ("Instalments, 0 replaced by 1", "IF 0 THEN 1", "Public"),
    "is_voucher": ("1 = voucher payment", "payment_type = 'voucher'", "Public"),
    "orders_count": ("Orders placed that day", "COUNT(order_id)", "Public"),
    "year": ("Year", "YEAR(purchase_date)", "Public"),
    "month": ("Month number", "MONTH(purchase_date)", "Public"),
    "month_name": ("Month name", "DATENAME('month')", "Public"),
    "weekday": ("Weekday name", "DATENAME('weekday')", "Public"),
    "is_weekend": ("1 = Saturday/Sunday", "weekday in (Sat, Sun)", "Public"),
}

TABLES = {  # table -> (grain description, raw sources, steward)
    "fact_orders": ("one row per order", "orders, customers, geolocation, order_items, order_payments, order_reviews", "Hrithik"),
    "fact_order_items": ("one row per order item", "order_items, products, translation, sellers, customers, geolocation", "Hrithik"),
    "fact_payments": ("one row per order payment", "order_payments", "Hrithik"),
    "fact_reviews": ("one row per review x order", "order_reviews", "Hrithik"),
    "dim_customers": ("one row per customer_id", "customers, geolocation", "Hrithik"),
    "dim_sellers": ("one row per seller", "sellers, geolocation", "Hrithik"),
    "dim_products": ("one row per product", "products, category_translation", "Hrithik"),
    "dim_location": ("one row per zip/city/state/role", "customers, sellers, geolocation", "Hrithik"),
    "dim_date": ("one row per purchase day", "orders", "Hrithik"),
}

ROLES = [
    ("Data owner (raw)", "Olist / Kaggle publisher", "Original data and licence (CC BY-NC-SA 4.0)", "-"),
    ("Data owner (published dataset) + metadata steward", "Fred", "Chose the source, checked the licence, keeps the FAIR metadata record", "Approves publication"),
    ("Data quality steward", "Gaurav", "Defines quality KPIs and thresholds, reviews the gate report after every run", "Read raw + clean, edit KPI rules"),
    ("Transformation steward", "Hrithik", "Maintains the Tableau Prep flow: cleaning, joins, calculated fields", "Edit flow"),
    ("Pipeline & governance steward", "Akshay", "Python functions, quality gate, lineage, data dictionary", "Edit Python code"),
    ("Data users / consumers", "Sahil", "Read-only use of published tables to answer the problem statement", "Read published only"),
]

LINEAGE = [
    ("1 Source", "Kaggle - Olist v7 (DOI 10.34740/kaggle/dsv/195341)", "9 CSV files", "download", "Fred"),
    ("2 Raw zone", "raw/  (immutable, + source metadata, SHA-256 in manifest)", "9 CSV files", "never edited", "Fred"),
    ("3 Python preprocessing", "olist_functions.load_raw()", "typed DataFrames", "fixed dtypes, zip as text, dates parsed", "Akshay"),
    ("4 Tableau Prep flow", "project_flow.tfl  (or run_all() in Python)", "4 facts + 5 dims", "clean, union, joins, calc fields, aggregate", "Hrithik"),
    ("5 Script steps (TabPy)", "prep_orders_kpis / prep_reviews_latest / prep_quality_gate", "same tables", "same Python functions inside Prep", "Akshay"),
    ("6 Quality gate", "quality_gate.run_quality_gate()", "quality_gate_report.csv", "PK, FK, domain, reconciliation; FAIL blocks", "Gaurav"),
    ("7 Published", "clean_output/  (.hyper / .csv + manifest.json)", "star schema", "read-only for users", "Fred"),
]

AI_RISKS = [
    ("Personal data", "Zip, city and coordinates could help re-identify customers (GDPR/LGPD).", "Data is already pseudonymised; keep location at zip-prefix level; no joins with outside data.", "Fred"),
    ("Bias", "Orders concentrated in Sao Paulo / Southeast - models generalise poorly to other regions.", "Document the imbalance; report results per region/state.", "Gaurav"),
    ("Review free text", "Portuguese free text; sentiment / LLM translation can misread it or expose personal details.", "Human review of samples; remove names before using text in AI tools.", "Sahil"),
    ("Licence", "CC BY-NC-SA 4.0: non-commercial, attribution, share-alike.", "Licence note in manifest and dictionary; no commercial use.", "Fred"),
    ("AI-generated code", "AI-assisted pandas code may contain silent logic errors.", "Human code review + quality gate + Python-vs-Prep comparison on every run.", "Akshay"),
]

HEAD = PatternFill("solid", fgColor="DF4807")
THIN = Side(style="thin", color="D0D0D0")


def friendly_type(s: pd.Series) -> str:
    """Readable type for the dictionary (CSV reads dates as text, so detect them)."""
    if "zip" in str(s.name):              # zip codes are codes, not numbers (leading zeros)
        return "text"
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    if pd.api.types.is_integer_dtype(s):
        return "integer"
    if pd.api.types.is_float_dtype(s):
        non_null = s.dropna()
        return "integer" if len(non_null) and (non_null % 1 == 0).all() else "decimal"
    sample = s.dropna().astype(str).head(200)
    if len(sample) and sample.str.match(r"^\d{4}-\d{2}-\d{2}").all():
        return "date" if sample.str.len().max() <= 10 or sample.str.endswith("00:00:00").all() else "datetime"
    return "text"


def write_sheet(wb, title, header, rows, widths):
    ws = wb.create_sheet(title)
    ws.append(header)
    for r in rows:
        ws.append(list(r))
    for c in ws[1]:
        c.font = Font(name="Arial", bold=True, color="FFFFFF")
        c.fill = HEAD
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.font = Font(name="Arial", size=10)
            c.alignment = Alignment(vertical="top", wrap_text=True)
            c.border = Border(bottom=THIN)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def main(clean_dir: str, out: str) -> None:
    clean = Path(clean_dir)
    tables = {t: pd.read_csv(clean / f"{t}.csv", low_memory=False) for t in TABLES}

    overview, dictionary = [], []
    for t, df in tables.items():
        grain, src, steward = TABLES[t]
        overview.append((t, "Fact" if t.startswith("fact") else "Dimension", grain,
                         ", ".join(GRAIN[t]), len(df), df.shape[1], src, steward, "Fred",
                         "Each pipeline run"))
        for col in df.columns:
            desc, rule, sens = COL.get(col, ("", "", ""))
            s = df[col]
            example = s.dropna().iloc[0] if s.notna().any() else ""
            dictionary.append((t, col, friendly_type(s), desc, rule,
                               "PK" if col in GRAIN[t] else "",
                               round(s.isna().mean() * 100, 2), int(s.nunique()),
                               str(example)[:40], sens))

    wb = Workbook()
    wb.remove(wb.active)
    write_sheet(wb, "Tables", ["Table", "Type", "Grain", "Primary key", "Rows", "Columns",
                               "Raw sources", "Steward", "Owner", "Refresh"], overview,
                [18, 11, 28, 30, 10, 9, 45, 11, 9, 16])
    write_sheet(wb, "Data dictionary", ["Table", "Column", "Type", "Description",
                                        "Source / transformation rule", "Key", "Null %",
                                        "Distinct", "Example", "Sensitivity"], dictionary,
                [17, 28, 10, 42, 42, 6, 8, 10, 24, 22])
    write_sheet(wb, "Roles", ["Role", "Person", "Responsibility", "Access"], ROLES,
                [40, 22, 60, 28])
    write_sheet(wb, "Lineage", ["Stage", "Where / what", "Output", "What happens", "Responsible"],
                LINEAGE, [22, 52, 22, 45, 13])
    write_sheet(wb, "AI risks", ["Risk", "Description", "Mitigation", "Owner"], AI_RISKS,
                [18, 55, 55, 10])
    gate = clean / "quality_gate_report.csv"
    if gate.exists():
        g = pd.read_csv(gate).fillna("")
        write_sheet(wb, "Quality gate", list(g.columns), g.itertuples(index=False),
                    [18, 46, 12, 9, 30])
    wb.save(out)
    missing = sorted({r[1] for r in dictionary if not r[3]})
    print(f"saved {out}  ({len(dictionary)} columns documented, undocumented: {missing})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", required=True)
    ap.add_argument("--out", default="governance_pack.xlsx")
    a = ap.parse_args()
    main(a.clean, a.out)
