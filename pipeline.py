"""Download the Olist Brazilian e-commerce dataset, clean it, and export
model-ready CSVs (star schema + RFM + cohort) for Power BI / Streamlit."""
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = "https://raw.githubusercontent.com/olist/work-at-olist-data/master/datasets/"
FILES = [
    "olist_customers_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
]
ROOT = Path(__file__).parent
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "model"

STATE_NAMES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul", "RO": "Rondônia",
    "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe",
    "TO": "Tocantins",
}


def download():
    RAW.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        dest = RAW / f
        if dest.exists():
            continue
        print("downloading", f)
        r = requests.get(BASE + f, timeout=120)
        r.raise_for_status()
        dest.write_bytes(r.content)


def load(name):
    return pd.read_csv(RAW / f"olist_{name}_dataset.csv")


def rfm_segment(r):
    if r.F >= 4 and r.R >= 4:
        return "Champions"
    if r.F >= 4 and r.R >= 2:
        return "Loyal"
    if r.F >= 4:
        return "Cant Lose Them"
    if r.R >= 4 and r.M >= 4:
        return "Big Spenders (New)"
    if r.R >= 4:
        return "Recent Customers"
    if r.R == 3:
        return "Needs Attention"
    if r.M >= 4:
        return "At Risk (High Value)"
    return "Hibernating"


def clean():
    orders = load("orders")
    for c in ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
              "order_delivered_customer_date", "order_estimated_delivery_date"]:
        orders[c] = pd.to_datetime(orders[c])
    items = load("order_items")
    pay = load("order_payments")
    rev = load("order_reviews")
    cust = load("customers")
    prod = load("products")
    sell = load("sellers")
    tr = pd.read_csv(RAW / "product_category_name_translation.csv")

    # --- dimensions
    prod = prod.merge(tr, on="product_category_name", how="left")
    prod["category"] = (prod["product_category_name_english"]
                        .fillna("unknown").str.replace("_", " ").str.title())
    dim_product = prod[["product_id", "category", "product_weight_g", "product_photos_qty"]].copy()

    dim_customer = cust.drop_duplicates("customer_id").copy()
    dim_customer["state_name"] = dim_customer["customer_state"].map(STATE_NAMES)
    dim_customer["customer_city"] = dim_customer["customer_city"].str.title()

    dim_seller = sell.copy()
    dim_seller["seller_city"] = dim_seller["seller_city"].str.title()

    # --- reviews: one per order (keep latest)
    rev["review_creation_date"] = pd.to_datetime(rev["review_creation_date"])
    rev = (rev.sort_values("review_creation_date")
              .drop_duplicates("order_id", keep="last")[["order_id", "review_score"]])

    # --- orders fact
    pay_o = pay.groupby("order_id").agg(
        payment_value=("payment_value", "sum"),
        payment_installments=("payment_installments", "max"),
        payment_type=("payment_type", lambda s: s.mode().iat[0]),
    ).reset_index()
    it_o = items.groupby("order_id").agg(
        items_count=("order_item_id", "count"),
        items_value=("price", "sum"),
        freight_value=("freight_value", "sum"),
    ).reset_index()
    fo = (orders.merge(it_o, on="order_id", how="left")
                .merge(pay_o, on="order_id", how="left")
                .merge(rev, on="order_id", how="left"))
    # orders without items (unavailable/canceled shells) carry no revenue
    fo = fo[fo["items_count"].notna()].copy()
    fo["order_value"] = (fo["items_value"] + fo["freight_value"]).round(2)
    fo["purchase_date"] = fo["order_purchase_timestamp"].dt.normalize()
    fo["delivery_days"] = ((fo["order_delivered_customer_date"] - fo["order_purchase_timestamp"])
                           .dt.total_seconds() / 86400).round(2)
    fo["delay_days"] = ((fo["order_delivered_customer_date"] - fo["order_estimated_delivery_date"])
                        .dt.total_seconds() / 86400).round(2)
    # delivered before purchase is impossible
    fo.loc[fo["delivery_days"] < 0, ["delivery_days", "delay_days"]] = np.nan
    fo["is_late"] = np.where(fo["delay_days"].notna(), (fo["delay_days"] > 0).astype(float), np.nan)
    fo = fo.merge(dim_customer[["customer_id", "customer_unique_id", "customer_state"]],
                  on="customer_id", how="left")
    fo["is_revenue_order"] = (~fo["order_status"].isin(["canceled", "unavailable"])).astype(int)
    fo["is_complete_period"] = fo["purchase_date"].between("2017-01-01", "2018-08-31").astype(int)
    fact_orders = fo.drop(columns=["order_approved_at", "order_delivered_carrier_date"])

    # --- order items fact
    fact_items = items.merge(orders[["order_id", "order_purchase_timestamp"]], on="order_id")
    fact_items["purchase_date"] = fact_items["order_purchase_timestamp"].dt.normalize()
    fact_items = fact_items.drop(columns=["order_purchase_timestamp", "shipping_limit_date"])

    # --- date table
    d0 = fo["purchase_date"].min().replace(day=1)
    d1 = fo["purchase_date"].max() + pd.offsets.MonthEnd(0)
    dd = pd.DataFrame({"date": pd.date_range(d0, d1)})
    dd["year"] = dd.date.dt.year
    dd["quarter"] = "Q" + dd.date.dt.quarter.astype(str)
    dd["month_num"] = dd.date.dt.month
    dd["month_name"] = dd.date.dt.strftime("%b")
    dd["year_month"] = dd.date.dt.strftime("%Y-%m")
    dd["week_num"] = dd.date.dt.isocalendar().week.astype(int)
    dd["day_of_week_num"] = dd.date.dt.dayofweek + 1
    dd["day_of_week"] = dd.date.dt.strftime("%a")
    dd["is_weekend"] = (dd.day_of_week_num >= 6).astype(int)
    dd["month_start"] = dd.date.dt.to_period("M").dt.to_timestamp()

    # --- RFM (revenue orders, per unique customer)
    ro = fo[fo.is_revenue_order == 1].copy()
    snap = ro["purchase_date"].max() + pd.Timedelta(days=1)
    rfm = ro.groupby("customer_unique_id").agg(
        last_purchase=("purchase_date", "max"),
        frequency=("order_id", "nunique"),
        monetary=("order_value", "sum"),
    ).reset_index()
    rfm["recency"] = (snap - rfm["last_purchase"]).dt.days
    rfm["monetary"] = rfm["monetary"].round(2)
    rfm["R"] = pd.qcut(rfm.recency.rank(method="first"), 5, labels=[5, 4, 3, 2, 1]).astype(int)
    rfm["F"] = np.where(rfm.frequency >= 3, 5, np.where(rfm.frequency == 2, 4, 1))  # ~97% buy once
    rfm["M"] = pd.qcut(rfm.monetary.rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    rfm["segment"] = rfm.apply(rfm_segment, axis=1)

    # --- cohort retention (month of first purchase vs months since)
    ro["order_month"] = ro.purchase_date.dt.to_period("M")
    ro = ro.join(ro.groupby("customer_unique_id")["order_month"].min().rename("cohort_month"),
                 on="customer_unique_id")
    ro["month_index"] = (ro.order_month - ro.cohort_month).apply(lambda x: x.n)
    coh = (ro.groupby(["cohort_month", "month_index"])["customer_unique_id"]
             .nunique().reset_index(name="customers"))
    size = coh[coh.month_index == 0].set_index("cohort_month")["customers"]
    coh["cohort_size"] = coh.cohort_month.map(size)
    coh["retention_pct"] = (coh.customers / coh.cohort_size).round(4)
    coh["cohort_month"] = coh.cohort_month.dt.to_timestamp()

    tables = {
        "fact_orders": fact_orders,
        "fact_order_items": fact_items,
        "dim_customer": dim_customer,
        "dim_product": dim_product,
        "dim_seller": dim_seller,
        "dim_date": dd,
        "rfm_customers": rfm,
        "cohort_retention": coh,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"{name:18s} {len(df):>8,} rows  {df.shape[1]} cols")


if __name__ == "__main__":
    download()
    clean()
