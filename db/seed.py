"""Create the sample schema and fill it with reproducible fake data.

Usage:  python -m db.seed
"""
import random
from datetime import date, timedelta
from pathlib import Path

from psycopg2.extras import execute_values

from clarisql.db import get_conn

random.seed(42)

FIRST = ["Aarav", "Vivaan", "Aditya", "Ishaan", "Kabir", "Ananya", "Diya", "Meera", "Saanvi",
         "Riya", "Rohan", "Karan", "Neha", "Priya", "Arjun", "Sneha", "Rahul", "Pooja", "Amit", "Kavya"]
LAST = ["Sharma", "Verma", "Gupta", "Singh", "Patel", "Rawat", "Joshi", "Nair", "Reddy", "Mehta",
        "Kapoor", "Bose", "Iyer", "Das", "Chauhan"]
CITIES = [("Haridwar", "India"), ("Dehradun", "India"), ("Delhi", "India"), ("Mumbai", "India"),
          ("Bengaluru", "India"), ("Pune", "India"), ("Dubai", "UAE"), ("London", "UK"),
          ("Toronto", "Canada"), ("Singapore", "Singapore")]
CATALOG = {
    "Electronics": ["Wireless Earbuds", "Smart Watch", "Power Bank", "Bluetooth Speaker", "USB-C Hub",
                    "Mechanical Keyboard", "Webcam", "Gaming Mouse"],
    "Books": ["Python Crash Course", "Clean Code", "Database Internals", "Atomic Habits", "Deep Work",
              "Designing Data-Intensive Apps", "SQL Cookbook"],
    "Clothing": ["Cotton T-Shirt", "Denim Jeans", "Hoodie", "Running Shoes", "Winter Jacket", "Formal Shirt"],
    "Home": ["Desk Lamp", "Water Bottle", "Backpack", "Coffee Mug", "Yoga Mat", "Office Chair"],
    "Sports": ["Cricket Bat", "Football", "Badminton Racket", "Dumbbell Set", "Skipping Rope"],
}
STATUSES = ["delivered"] * 6 + ["shipped"] * 2 + ["pending", "cancelled"]
METHODS = ["card", "upi", "upi", "netbanking", "cod"]


def main() -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute((Path(__file__).parent / "schema.sql").read_text())
    today = date.today()

    # customers
    customers = []
    for i in range(1, 201):
        city, country = random.choice(CITIES)
        name = f"{random.choice(FIRST)} {random.choice(LAST)}"
        customers.append((name, f"user{i}@example.com", city, country, today - timedelta(days=random.randint(30, 700))))
    execute_values(cur, "INSERT INTO customers (name,email,city,country,signup_date) VALUES %s", customers)

    # products (distinct prices so rankings have no ties)
    products, used = [], set()
    for category, names in CATALOG.items():
        for n in names:
            price = round(random.uniform(150, 9000), 2)
            while price in used:
                price = round(random.uniform(150, 9000), 2)
            used.add(price)
            products.append((n, category, price, random.randint(0, 300)))
    execute_values(cur, "INSERT INTO products (name,category,price,stock) VALUES %s", products)

    # orders, items, payments (built in memory, then inserted in bulk)
    orders, items, payments = [], [], []
    for order_id in range(1, 1501):
        cust = random.randint(1, 200)
        odate = today - timedelta(days=random.randint(0, 365))
        status = random.choice(STATUSES)
        orders.append((order_id, cust, odate, status))
        total = 0
        for pid in random.sample(range(1, len(products) + 1), random.randint(1, 4)):
            qty = random.randint(1, 3)
            price = products[pid - 1][2]
            total += qty * price
            items.append((order_id, pid, qty, price))
        if status != "cancelled":
            payments.append((order_id, random.choice(METHODS), round(total, 2),
                             odate + timedelta(days=random.randint(0, 2))))

    execute_values(cur, "INSERT INTO orders (order_id,customer_id,order_date,status) VALUES %s", orders)
    execute_values(cur, "INSERT INTO order_items (order_id,product_id,quantity,unit_price) VALUES %s", items)
    execute_values(cur, "INSERT INTO payments (order_id,method,amount,paid_at) VALUES %s", payments)
    cur.execute("SELECT setval(pg_get_serial_sequence('orders','order_id'), 1500)")

    conn.commit()
    conn.close()
    print("Seeded: 200 customers, %d products, 1500 orders." % len(products))


if __name__ == "__main__":
    main()
