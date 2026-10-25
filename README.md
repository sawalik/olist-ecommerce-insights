# Olist E-commerce Insights

Analysis of the Brazilian Olist marketplace (about 100k orders, 2016-2018): a Python cleaning
pipeline, model-ready CSVs for Power BI, and a Streamlit app with the key insights.

## What's inside

| File | Purpose |
|---|---|
| `pipeline.py` | Downloads the raw Olist CSVs, cleans them, exports the star schema plus RFM and cohort tables |
| `data/model/` | Model-ready CSVs: `fact_orders`, `fact_order_items`, `dim_customer`, `dim_product`, `dim_seller`, `dim_date`, `rfm_customers`, `cohort_retention` |
| `app.py` | Streamlit app: Sales, Customers (RFM and cohorts), Delivery & satisfaction, Products & payments |

## Run it

```bash
pip install -r requirements.txt
python pipeline.py        # optional: model CSVs are already committed
streamlit run app.py
```

## Key findings

- Revenue is concentrated: the top 3 states bring in about 63% of revenue, the top 20% of sellers about 82%.
- Only about 3% of customers order again; monthly cohort retention is roughly 0.2-0.5%.
- Late deliveries average 2.56 review stars vs 4.29 when on time.

## Power BI

Load the CSVs in `data/model/` and relate them on `order_id`, `customer_unique_id`,
`product_id`, `seller_id` and `purchase_date` = `dim_date[date]`.

## Data

Brazilian E-Commerce Public Dataset by Olist, licensed CC BY-NC-SA 4.0 (non-commercial use).
Source: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
