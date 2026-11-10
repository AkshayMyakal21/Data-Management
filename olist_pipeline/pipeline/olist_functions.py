"""
olist_functions.py
==================
Reusable cleaning & transformation functions for the Olist e-commerce project
(Team 2 "Hercules" - Data Management).

Every function mirrors one step of the Tableau Prep flow (project_flow.tfl),
so the same logic can be
  1. run on its own in Python   ->  python run_pipeline.py --input raw --output clean_output
  2. run inside Tableau Prep    ->  Script step (TabPy) calling tabpy_script_steps.py

Design rules that make the pipeline reproducible
  * pure functions: DataFrame in -> new DataFrame out, the input is never modified
  * no hard-coded paths, no randomness, no "today()" - same input => same output
  * every rule (thresholds, bounding box, mappings) is a named constant below
  * outputs are sorted by their primary key before writing, so files are byte-identical
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Business rules (single place to change them)
# --------------------------------------------------------------------------- #
BRAZIL_LAT = (-34.0, 6.0)          # CL_geo_brazil
BRAZIL_LNG = (-74.0, -34.0)
LOW_SCORE_MAX = 2                  # is_low_score: review_score <= 2
PAYMENT_MISMATCH_BRL = 1.0         # payment_mismatch: |gap| > 1 BRL
EARTH_RADIUS_KM = 6371.0
MISSING_TRANSLATIONS = {           # CL_products_final: categories missing in translation file
    "pc_gamer": "pc_gamer",
    "portateis_cozinha_e_preparadores_de_alimentos": "kitchen_portables_food_preparers",
}

RAW_FILES = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

DATE_COLUMNS = {
    "orders": ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
               "order_delivered_customer_date", "order_estimated_delivery_date"],
    "order_items": ["shipping_limit_date"],
    "order_reviews": ["review_creation_date", "review_answer_timestamp"],
}


# --------------------------------------------------------------------------- #
# 0. Generic helpers
# --------------------------------------------------------------------------- #
def load_raw(data_dir) -> dict[str, pd.DataFrame]:
    """Read the 9 raw CSVs with fixed dtypes (zip codes stay text, dates parsed)."""
    from pathlib import Path
    data_dir = Path(data_dir)
    dfs = {}
    for name, file in RAW_FILES.items():
        df = pd.read_csv(data_dir / file, encoding="utf-8-sig",
                         dtype={c: str for c in ("customer_zip_code_prefix",
                                                 "seller_zip_code_prefix",
                                                 "geolocation_zip_code_prefix")})
        for col in DATE_COLUMNS.get(name, []):
            df[col] = pd.to_datetime(df[col], errors="coerce")
        dfs[name] = df
    return dfs


def pad_zip(s: pd.Series) -> pd.Series:
    """RIGHT("00000" + STR(zip), 5) -> '1037' becomes '01037'."""
    return s.astype(str).str.strip().str.split(".").str[0].str.zfill(5)


def haversine_km(lat1, lng1, lat2, lng2) -> pd.Series:
    """Great-circle distance in km (same formula as CL_items_enriched.distance_km)."""
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def days_between(start: pd.Series, end: pd.Series) -> pd.Series:
    """Tableau DATEDIFF('day', start, end): counts calendar-day boundaries."""
    return (end.dt.normalize() - start.dt.normalize()).dt.days.astype("Int64")


# --------------------------------------------------------------------------- #
# 1. Geolocation   (CL_geo_zip -> AG_geo_distinct -> CL_geo_brazil -> AG_geo_by_zip)
# --------------------------------------------------------------------------- #
def clean_geolocation(geo: pd.DataFrame) -> pd.DataFrame:
    """Pad zip, drop exact duplicates, keep only points inside Brazil."""
    g = geo.copy()
    g["geolocation_zip"] = pad_zip(g["geolocation_zip_code_prefix"])
    g = g.drop_duplicates(subset=["geolocation_zip", "geolocation_city", "geolocation_lat",
                                  "geolocation_lng", "geolocation_state"])
    inside = (g["geolocation_lat"].between(*BRAZIL_LAT)
              & g["geolocation_lng"].between(*BRAZIL_LNG))
    return g[inside].reset_index(drop=True)


def geo_by_zip(geo_clean: pd.DataFrame) -> pd.DataFrame:
    """One row per zip prefix with the average coordinate (removes join fan-out)."""
    return (geo_clean.groupby("geolocation_zip", as_index=False)
            .agg(geolocation_lat=("geolocation_lat", "mean"),
                 geolocation_lng=("geolocation_lng", "mean"))
            .sort_values("geolocation_zip", ignore_index=True))


# --------------------------------------------------------------------------- #
# 2. Customers / sellers   (CL_customers, CL_sellers + geo joins)
# --------------------------------------------------------------------------- #
def clean_customers(customers: pd.DataFrame) -> pd.DataFrame:
    c = customers.copy()
    c["customer_zip"] = pad_zip(c["customer_zip_code_prefix"])
    c["customer_city_clean"] = c["customer_city"].str.strip().str.lower()
    return c


def clean_sellers(sellers: pd.DataFrame) -> pd.DataFrame:
    """seller_city has values like 'sao paulo / sp' or 'rio, rj' -> keep the city part."""
    s = sellers.copy()
    s["seller_city_clean"] = (s["seller_city"].str.split("/").str[0]
                              .str.split(",").str[0].str.strip())
    s["seller_zip"] = pad_zip(s["seller_zip_code_prefix"])
    return s


def add_geo(df: pd.DataFrame, zip_col: str, geo_zip: pd.DataFrame) -> pd.DataFrame:
    """Left join coordinates by zip. Row count must not change (checked)."""
    out = df.merge(geo_zip, how="left", left_on=zip_col, right_on="geolocation_zip")
    assert len(out) == len(df), "join fan-out in add_geo"
    return out


def build_dim_customers(customers, geo_zip) -> pd.DataFrame:
    return (add_geo(clean_customers(customers), "customer_zip", geo_zip)
            .sort_values("customer_id", ignore_index=True))


def build_dim_sellers(sellers, geo_zip) -> pd.DataFrame:
    return (add_geo(clean_sellers(sellers), "seller_zip", geo_zip)
            .sort_values("seller_id", ignore_index=True))


def build_dim_location(dim_customers, dim_sellers, geo_zip) -> pd.DataFrame:
    """UN_locations: union of customer and seller places, one row per zip/city/state/role."""
    cust = dim_customers[["customer_zip", "customer_city_clean", "customer_state"]].set_axis(
        ["zip_code_prefix", "city", "state"], axis=1).assign(role="customer")
    sell = dim_sellers[["seller_zip", "seller_city_clean", "seller_state"]].set_axis(
        ["zip_code_prefix", "city", "state"], axis=1).assign(role="seller")
    loc = pd.concat([cust, sell], ignore_index=True).drop_duplicates()
    loc = loc.merge(geo_zip, how="left", left_on="zip_code_prefix", right_on="geolocation_zip")
    loc = loc.drop(columns="geolocation_zip").rename(
        columns={"geolocation_lat": "lat", "geolocation_lng": "lng"})
    return loc.sort_values(["zip_code_prefix", "city", "state", "role"], ignore_index=True)


# --------------------------------------------------------------------------- #
# 3. Products   (CL_products -> JN_products_category -> CL_products_final)
# --------------------------------------------------------------------------- #
def clean_products(products: pd.DataFrame, translation: pd.DataFrame) -> pd.DataFrame:
    p = products.rename(columns={"product_name_lenght": "product_name_length",
                                 "product_description_lenght": "product_description_length"})
    p = p.merge(translation, how="left", on="product_category_name")
    p["category_en"] = p["product_category_name"].map(MISSING_TRANSLATIONS)
    p["category_en"] = p["category_en"].fillna(p["product_category_name_english"])
    p.loc[p["product_category_name"].isna(), "category_en"] = "unknown"
    p = p.drop(columns="product_category_name_english")
    p["product_weight_g"] = p["product_weight_g"].where(p["product_weight_g"] > 0)  # 0 g -> NULL
    p["volume_cm3"] = p["product_length_cm"] * p["product_height_cm"] * p["product_width_cm"]
    return p.sort_values("product_id", ignore_index=True)


# --------------------------------------------------------------------------- #
# 4. Orders   (CL_orders)
# --------------------------------------------------------------------------- #
def clean_orders(orders: pd.DataFrame) -> pd.DataFrame:
    """Delivery KPIs + a data-quality flag. Suspicious rows are flagged, never deleted."""
    o = orders.copy()
    o["purchase_date"] = o["order_purchase_timestamp"].dt.normalize()
    o["purchase_month"] = o["order_purchase_timestamp"].dt.to_period("M").dt.to_timestamp()
    o["delivery_days"] = days_between(o["order_purchase_timestamp"], o["order_delivered_customer_date"])
    o["delay_days"] = days_between(o["order_estimated_delivery_date"], o["order_delivered_customer_date"])
    o["seller_handling_days"] = days_between(o["order_approved_at"], o["order_delivered_carrier_date"])
    o["is_late"] = np.where(o["order_delivered_customer_date"].isna(), np.nan,
                            (o["delay_days"] > 0).astype(float))
    o["is_late"] = o["is_late"].astype("Int64")

    delivered = o["order_status"].eq("delivered")
    has_date = o["order_delivered_customer_date"].notna()
    conditions = [
        delivered & ~has_date,
        ~delivered & has_date,
        o["order_delivered_carrier_date"] < o["order_purchase_timestamp"],
        o["order_delivered_customer_date"] < o["order_delivered_carrier_date"],
    ]
    labels = ["delivered_no_date", "not_delivered_but_has_date",
              "carrier_before_purchase", "delivered_before_carrier"]
    o["dq_flag"] = np.select(conditions, labels, default="ok")
    return o


# --------------------------------------------------------------------------- #
# 5. Payments   (CL_payments -> AG_payments_by_order)
# --------------------------------------------------------------------------- #
def clean_payments(payments: pd.DataFrame) -> pd.DataFrame:
    p = payments[payments["payment_type"] != "not_defined"].copy()
    p["installments_clean"] = p["payment_installments"].replace(0, 1)
    p["is_voucher"] = (p["payment_type"] == "voucher").astype(int)
    return p.sort_values(["order_id", "payment_sequential"], ignore_index=True)


def payments_by_order(payments_clean: pd.DataFrame) -> pd.DataFrame:
    return (payments_clean.groupby("order_id", as_index=False)
            .agg(total_paid=("payment_value", "sum"),
                 n_payments=("payment_sequential", "count"),
                 max_installments=("installments_clean", "max"),
                 used_voucher=("is_voucher", "max")))


# --------------------------------------------------------------------------- #
# 6. Reviews   (CL_reviews -> CL_reviews_latest)
# --------------------------------------------------------------------------- #
def clean_reviews(reviews: pd.DataFrame) -> pd.DataFrame:
    r = reviews.copy()
    for col in ("review_comment_title", "review_comment_message"):   # trim; blank text -> NULL
        r[col] = r[col].str.strip().replace("", np.nan)
    r["review_key"] = r["review_id"] + "_" + r["order_id"]
    r["has_comment"] = r["review_comment_message"].notna().astype(int)
    r["is_low_score"] = (r["review_score"] <= LOW_SCORE_MAX).astype(int)
    # ROW_NUMBER() over order_id ordered by newest answer; review_id breaks ties deterministically
    r = r.sort_values(["order_id", "review_answer_timestamp", "review_id"],
                      ascending=[True, False, True])
    r["review_rank"] = r.groupby("order_id").cumcount() + 1
    return r.sort_values(["order_id", "review_rank"], ignore_index=True)


def latest_review_per_order(reviews_clean: pd.DataFrame) -> pd.DataFrame:
    return reviews_clean.loc[reviews_clean["review_rank"] == 1,
                             ["order_id", "review_score", "is_low_score",
                              "has_comment", "review_answer_timestamp"]].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 7. Order items   (CL_order_items -> joins -> CL_items_enriched -> AG_items_by_order)
# --------------------------------------------------------------------------- #
def build_fact_order_items(items, dim_products, dim_sellers, orders_clean, dim_customers):
    i = items.copy()
    i["item_total"] = i["price"] + i["freight_value"]
    i["freight_share"] = i["freight_value"] / i["price"]

    i = i.merge(dim_products, how="left", on="product_id")
    s = dim_sellers.drop(columns="geolocation_zip").rename(
        columns={"geolocation_lat": "seller_lat", "geolocation_lng": "seller_lng"})
    i = i.merge(s, how="left", on="seller_id")
    cust = (orders_clean[["order_id", "customer_id"]]
            .merge(dim_customers[["customer_id", "customer_state",
                                  "geolocation_lat", "geolocation_lng"]],
                   how="left", on="customer_id")
            .drop(columns="customer_id")
            .rename(columns={"geolocation_lat": "cust_lat", "geolocation_lng": "cust_lng"}))
    i = i.merge(cust, how="left", on="order_id")
    assert len(i) == len(items), "join fan-out in fact_order_items"

    i["distance_km"] = haversine_km(i["seller_lat"], i["seller_lng"], i["cust_lat"], i["cust_lng"])
    i["is_cross_state"] = (i["seller_state"] != i["customer_state"]).astype(int)
    return i.sort_values(["order_id", "order_item_id"], ignore_index=True)


def items_by_order(fact_items: pd.DataFrame) -> pd.DataFrame:
    return (fact_items.groupby("order_id", as_index=False)
            .agg(n_items=("order_item_id", "count"),
                 n_sellers=("seller_id", "nunique"),
                 n_products=("product_id", "nunique"),
                 items_value=("price", "sum"),
                 freight_total=("freight_value", "sum"),
                 total_weight_g=("product_weight_g", "sum"),
                 max_distance_km=("distance_km", "max"),
                 is_cross_state=("is_cross_state", "max")))


# --------------------------------------------------------------------------- #
# 8. Fact orders   (JN_orders_customers -> JN_fo_items -> JN_fo_payments -> JN_fo_reviews)
# --------------------------------------------------------------------------- #
def build_fact_orders(orders_clean, dim_customers, items_agg, pay_agg, reviews_latest):
    """One row per order. Child tables are aggregated FIRST, so joins can't fan out."""
    fo = orders_clean.merge(
        dim_customers[["customer_id", "customer_unique_id", "customer_zip",
                       "customer_city_clean", "customer_state",
                       "geolocation_lat", "geolocation_lng"]]
        .rename(columns={"geolocation_lat": "cust_lat", "geolocation_lng": "cust_lng"}),
        how="left", on="customer_id")
    for child in (items_agg, pay_agg, reviews_latest):
        fo = fo.merge(child, how="left", on="order_id")
    assert len(fo) == len(orders_clean), "join fan-out in fact_orders"
    fo["order_value"] = fo["items_value"] + fo["freight_total"]
    fo["payment_gap"] = (fo["total_paid"] - fo["order_value"]).round(2)
    fo["payment_mismatch"] = (fo["payment_gap"].abs() > PAYMENT_MISMATCH_BRL).astype(int)
    return fo.sort_values("order_id", ignore_index=True)


# --------------------------------------------------------------------------- #
# 9. Date dimension   (AG_dates -> CL_dim_date)
# --------------------------------------------------------------------------- #
def build_dim_date(orders_clean: pd.DataFrame) -> pd.DataFrame:
    d = (orders_clean.groupby("purchase_date", as_index=False)
         .agg(orders_count=("order_id", "count")))
    d["year"] = d["purchase_date"].dt.year
    d["month"] = d["purchase_date"].dt.month
    d["month_name"] = d["purchase_date"].dt.month_name()
    d["weekday"] = d["purchase_date"].dt.day_name()
    d["is_weekend"] = d["purchase_date"].dt.dayofweek.isin([5, 6]).astype(int)
    return d.sort_values("purchase_date", ignore_index=True)


# --------------------------------------------------------------------------- #
# 10. Whole pipeline in one call
# --------------------------------------------------------------------------- #
def run_all(raw: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """raw tables in -> published star schema out (4 facts + 5 dims)."""
    geo_zip = geo_by_zip(clean_geolocation(raw["geolocation"]))
    dim_customers = build_dim_customers(raw["customers"], geo_zip)
    dim_sellers = build_dim_sellers(raw["sellers"], geo_zip)
    dim_products = clean_products(raw["products"], raw["category_translation"])
    orders = clean_orders(raw["orders"])
    fact_payments = clean_payments(raw["order_payments"])
    fact_reviews = clean_reviews(raw["order_reviews"])
    fact_items = build_fact_order_items(raw["order_items"], dim_products, dim_sellers,
                                        orders, dim_customers)
    fact_orders = build_fact_orders(orders, dim_customers, items_by_order(fact_items),
                                    payments_by_order(fact_payments),
                                    latest_review_per_order(fact_reviews))
    return {
        "dim_customers": dim_customers,
        "dim_sellers": dim_sellers,
        "dim_products": dim_products,
        "dim_location": build_dim_location(dim_customers, dim_sellers, geo_zip),
        "dim_date": build_dim_date(orders),
        "fact_orders": fact_orders,
        "fact_order_items": fact_items,
        "fact_payments": fact_payments,
        "fact_reviews": fact_reviews,
    }
