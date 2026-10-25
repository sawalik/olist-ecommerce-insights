"""Streamlit preview of the Olist e-commerce insights.
Run `python pipeline.py` first, then `streamlit run app.py`."""
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

M = Path(__file__).parent / "data" / "model"
st.set_page_config(page_title="Olist E-commerce Insights", layout="wide")


@st.cache_data
def load():
    orders = pd.read_csv(M / "fact_orders.csv", parse_dates=["purchase_date"])
    items = pd.read_csv(M / "fact_order_items.csv", parse_dates=["purchase_date"])
    prod = pd.read_csv(M / "dim_product.csv")
    rfm = pd.read_csv(M / "rfm_customers.csv")
    coh = pd.read_csv(M / "cohort_retention.csv", parse_dates=["cohort_month"])
    items = items.merge(prod[["product_id", "category"]], on="product_id", how="left")
    return orders, items, rfm, coh


orders, items, rfm, coh = load()
orders = orders[orders.is_revenue_order == 1]

st.title("Olist E-commerce Insights")
st.caption("Brazilian marketplace, 2016-2018. Default range excludes sparse 2016 and partial late-2018 months.")

# --- filters
min_d, max_d = orders.purchase_date.min().date(), orders.purchase_date.max().date()
c1, c2 = st.sidebar.columns(2)
start = c1.date_input("From", pd.Timestamp("2017-01-01").date(), min_d, max_d)
end = c2.date_input("To", pd.Timestamp("2018-08-31").date(), min_d, max_d)
states = st.sidebar.multiselect("Customer state", sorted(orders.customer_state.dropna().unique()))

o = orders[orders.purchase_date.between(pd.Timestamp(start), pd.Timestamp(end))]
if states:
    o = o[o.customer_state.isin(states)]
it = items[items.order_id.isin(o.order_id)]

# --- KPIs
k = st.columns(5)
k[0].metric("Revenue (R$)", f"{o.order_value.sum():,.0f}")
k[1].metric("Orders", f"{len(o):,}")
k[2].metric("Avg order value", f"R$ {o.order_value.mean():,.0f}")
k[3].metric("On-time delivery", f"{(1 - o.is_late.mean()):.1%}")
k[4].metric("Avg review", f"{o.review_score.mean():.2f} / 5")

tab1, tab2, tab3, tab4 = st.tabs(["Sales", "Customers", "Delivery & satisfaction", "Products & payments"])

with tab1:
    m = (o.assign(month=o.purchase_date.dt.to_period("M").dt.to_timestamp())
          .groupby("month").agg(revenue=("order_value", "sum"), orders=("order_id", "count")).reset_index())
    a, b = st.columns(2)
    a.plotly_chart(px.line(m, x="month", y="revenue", markers=True, title="Monthly revenue"), width='stretch')
    b.plotly_chart(px.bar(m, x="month", y="orders", title="Monthly orders"), width='stretch')
    s = o.groupby("customer_state").agg(revenue=("order_value", "sum"), orders=("order_id", "count")).reset_index()
    s = s.sort_values("revenue", ascending=False)
    a, b = st.columns(2)
    a.plotly_chart(px.bar(s.head(10), x="customer_state", y="revenue", title="Top 10 states by revenue"), width='stretch')
    dow = o.assign(dow=o.purchase_date.dt.day_name()).groupby("dow").size().reindex(
        ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]).reset_index(name="orders")
    b.plotly_chart(px.bar(dow, x="dow", y="orders", title="Orders by weekday"), width='stretch')
    top3 = s.head(3).revenue.sum() / s.revenue.sum()
    st.info(f"Revenue is concentrated: the top 3 states account for {top3:.0%} of revenue in this view.")

with tab2:
    cust = o.groupby("customer_unique_id").order_id.nunique()
    st.metric("Repeat customer rate (in selected period)", f"{(cust > 1).mean():.1%}")
    a, b = st.columns(2)
    seg = rfm.groupby("segment").agg(customers=("customer_unique_id", "count"), revenue=("monetary", "sum")).reset_index()
    a.plotly_chart(px.bar(seg.sort_values("customers"), x="customers", y="segment", orientation="h",
                          title="RFM segments (customers)"), width='stretch')
    b.plotly_chart(px.treemap(seg, path=["segment"], values="revenue", title="RFM segments (revenue)"),
                   width='stretch')
    piv = coh.pivot(index="cohort_month", columns="month_index", values="retention_pct")
    piv = piv[piv.index >= "2017-01-01"].iloc[:, :13]
    piv.index = piv.index.strftime("%Y-%m")
    fig = px.imshow(piv, text_auto=".1%", aspect="auto", color_continuous_scale="Blues",
                    title="Cohort retention (share of cohort ordering again, by months since first order)")
    st.plotly_chart(fig, width='stretch')
    st.info("Retention after month 0 is only ~0.2-0.5% per month: nearly all customers buy once, so acquisition and first-order "
            "experience matter more than loyalty programmes here.")

with tab3:
    d = o.dropna(subset=["review_score", "is_late"])
    d = d.assign(status=d.is_late.map({0.0: "On time", 1.0: "Late"}))
    a, b = st.columns(2)
    r = d.groupby("status").review_score.mean().reset_index()
    a.plotly_chart(px.bar(r, x="status", y="review_score", text_auto=".2f", range_y=[0, 5],
                          title="Average review score: on time vs late"), width='stretch')
    dist = d.groupby(["review_score", "status"]).size().reset_index(name="orders")
    b.plotly_chart(px.bar(dist, x="review_score", y="orders", color="status", barmode="group",
                          title="Review score distribution"), width='stretch')
    ls = o.groupby("customer_state").agg(late_rate=("is_late", "mean"), avg_days=("delivery_days", "mean"),
                                         orders=("order_id", "count")).reset_index()
    ls = ls[ls.orders >= 100].sort_values("late_rate", ascending=False)
    a, b = st.columns(2)
    a.plotly_chart(px.bar(ls, x="customer_state", y="late_rate", title="Late-delivery rate by state (100+ orders)",
                          labels={"late_rate": "late rate"}), width='stretch')
    b.plotly_chart(px.scatter(ls, x="avg_days", y="late_rate", size="orders", text="customer_state",
                              title="Delivery time vs late rate"), width='stretch')
    gap = r.set_index("status").review_score
    if {"On time", "Late"} <= set(gap.index):
        st.info(f"Late orders average {gap['Late']:.2f} stars vs {gap['On time']:.2f} when on time: "
                f"a {gap['On time'] - gap['Late']:.2f}-star gap.")

with tab4:
    cat = it.groupby("category").agg(revenue=("price", "sum"), units=("order_id", "count")).reset_index()
    cat = cat.sort_values("revenue", ascending=False)
    a, b = st.columns(2)
    a.plotly_chart(px.bar(cat.head(10).sort_values("revenue"), x="revenue", y="category", orientation="h",
                          title="Top 10 categories by revenue"), width='stretch')
    pay = o.groupby("payment_type").agg(orders=("order_id", "count")).reset_index()
    b.plotly_chart(px.pie(pay, names="payment_type", values="orders", hole=0.5, title="Payment methods"),
                   width='stretch')
    sel = it.groupby("seller_id").price.sum().sort_values(ascending=False)
    par = (sel.cumsum() / sel.sum()).reset_index(drop=True)
    par.index = (par.index + 1) / len(par)
    fig = px.line(x=par.index, y=par.values, title="Seller Pareto: cumulative revenue vs share of sellers",
                  labels={"x": "share of sellers", "y": "cumulative revenue share"})
    st.plotly_chart(fig, width='stretch')
    top20 = par[par.index <= 0.2].iloc[-1]
    st.info(f"The top 20% of sellers generate {top20:.0%} of item revenue.")

with st.expander("Data model files"):
    st.write("Exported in `data/model/`: fact_orders, fact_order_items, dim_customer, dim_product, dim_seller, "
             "dim_date, rfm_customers, cohort_retention. Load into Power BI and relate on order_id, "
             "customer_unique_id, product_id, seller_id and date.")
