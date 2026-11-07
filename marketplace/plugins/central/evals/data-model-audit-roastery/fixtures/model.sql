-- Roastery reporting model.
-- Star schema (documented):
-- | Fact            | Dimension      | Join key (fact -> dim)      |
-- | fact_sales      | dim_store      | store_key = store_key       |
-- | fact_sales      | dim_customer   | customer_id = customer_id   |
-- | fact_roasts     | dim_shift      | shift_code = shift_code     |
-- | fact_sales      | dim_date       | sale_date = date_day        |

-- Order lines, for the marts
CREATE OR REPLACE VIEW mart.roastery.order_lines AS
SELECT * FROM erp.sales.order_items__vbap;

-- Open order lines only
CREATE OR REPLACE VIEW mart.roastery.src_open_orders AS
SELECT * FROM erp.sales.order_items__vbap WHERE status = 'OPEN';

-- Employees
CREATE OR REPLACE VIEW mart.roastery.dim_employee AS
SELECT employee_id, full_name FROM hr_restricted.people.employees;

CREATE OR REPLACE VIEW mart.roastery.dim_store AS
SELECT store_id AS store_key, store_name, region
FROM erp.master.stores
-- Exclude closed stores
WHERE store_id NOT IN ('S01', 'S02', 'S03', 'S04', 'S05', 'S06');

-- grain: one row per store + shift code
CREATE OR REPLACE VIEW mart.roastery.dim_shift AS
SELECT store_id, shift_code, shift_name FROM erp.master.shifts;

CREATE OR REPLACE VIEW mart.roastery.dim_customer AS
SELECT customer_id, customer_name FROM erp.master.customers;

CREATE OR REPLACE TABLE mart.roastery.dim_date AS
SELECT date_day, year, month FROM erp.master.calendar;

-- SOURCE: erp.sales.order_header__vbak
CREATE OR REPLACE VIEW mart.roastery.fact_sales AS
SELECT
    o.order_id,
    o.store_id,
    CAST(NULL AS STRING) AS customer_id,
    CAST(NULL AS STRING) AS notes,
    o.sale_date,
    o.amount
FROM mart.roastery.order_lines o
WHERE o.channel IN ('web', 'shop', 'phone');

CREATE OR REPLACE VIEW mart.roastery.fact_roasts AS
WITH roasted AS (
    SELECT store_id, shift_code, batch_id, kg, 'roast' AS kind FROM erp.prod.roast_batches
),
spoiled AS (
    -- spoilage write-offs
    SELECT store_id, shift_code, batch_id, 'spoil' AS kind, kg FROM erp.prod.spoilage
),
all_rows AS (
    SELECT * FROM roasted
    UNION ALL
    SELECT * FROM spoiled
)
SELECT store_id, shift_code, batch_id, kg, kind
FROM all_rows
WHERE store_id NOT IN ('S01', 'S02', 'S03', 'S04', 'S05', 'S06');

-- All stock movements
CREATE OR REPLACE VIEW mart.roastery.fact_movements AS
SELECT store_id, batch_id, kg FROM erp.prod.roast_batches
UNION ALL
SELECT store_id, batch_id, kg FROM erp.prod.spoilage;

-- Sales value per kg roasted
CREATE OR REPLACE VIEW mart.roastery.fact_sales_per_kg AS
SELECT s.store_id, SUM(s.amount) / SUM(r.kg) AS amount_per_kg
FROM mart.roastery.fact_sales s
JOIN mart.roastery.fact_roasts r ON r.store_id = s.store_id
GROUP BY s.store_id;

-- Batches across both years
CREATE OR REPLACE VIEW mart.roastery.fact_all_batches AS
SELECT * FROM erp.prod.roast_batches_2025
UNION ALL
SELECT * FROM erp.prod.roast_batches_2026;
