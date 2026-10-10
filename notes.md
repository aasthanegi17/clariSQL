Notes about the data. Write plain facts the AI cannot guess from column names.

E-commerce tables (customers, orders, order_items, products, payments)
- Revenue means SUM(quantity * unit_price) from order_items.
- Exclude cancelled orders from revenue unless the user asks for them.

students table
- exam_score is the final exam result. There are no per-subject scores (no math or reading score).
- There is no student ID column, so students can only be described by their attributes and scores.
