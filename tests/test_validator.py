import pytest

from clarisql.validator import UnsafeSQLError, validate_sql

TABLES = {"customers", "orders", "order_items", "products", "payments"}


@pytest.mark.parametrize("sql", [
    "SELECT * FROM customers",
    "select count(*) from orders;",
    "SELECT c.name FROM customers c JOIN orders o ON o.customer_id = c.customer_id",
    "WITH t AS (SELECT customer_id FROM orders) SELECT * FROM t",
    "SELECT EXTRACT(year FROM order_date) AS y, COUNT(*) FROM orders GROUP BY 1",
    "SELECT * FROM customers WHERE name = 'delete me; drop table x'",
    "SELECT created_at_not_a_keyword FROM public.customers",
    "SELECT * FROM generate_series(1,3)",
])
def test_safe_queries_pass(sql):
    assert validate_sql(sql, TABLES)


@pytest.mark.parametrize("sql", [
    "DROP TABLE customers",
    "DELETE FROM orders",
    "UPDATE products SET price = 0",
    "INSERT INTO customers VALUES (1)",
    "SELECT * FROM customers; DROP TABLE orders",
    "SELECT * INTO backup FROM customers",
    "SELECT pg_sleep(10)",
    "SELECT * FROM pg_catalog.pg_user",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM secret_table",
    "",
    "EXPLAIN SELECT 1",
    "SET ROLE postgres",
])
def test_unsafe_queries_blocked(sql):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql, TABLES)


def test_trailing_semicolon_removed():
    assert validate_sql("SELECT 1 FROM customers;", TABLES) == "SELECT 1 FROM customers"
