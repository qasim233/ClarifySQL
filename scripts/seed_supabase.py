#!/usr/bin/env python3
"""
Seed script for Supabase / PostgreSQL database.
Creates schemas and populates realistic eCommerce data for customers, orders, and payments.
"""
import argparse
import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
from config.settings import settings


DDL_SCHEMA = """
-- Drop existing tables
DROP TABLE IF EXISTS payments CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

-- 1. Customers Table
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    signup_date DATE NOT NULL
);

-- 2. Orders Table
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    order_date DATE NOT NULL,
    status VARCHAR(50) NOT NULL -- 'completed', 'pending', 'cancelled', 'refunded'
);

-- 3. Payments Table
CREATE TABLE payments (
    id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    amount NUMERIC(10, 2) NOT NULL,
    payment_status VARCHAR(50) NOT NULL, -- 'successful', 'failed', 'refunded'
    payment_date DATE NOT NULL
);

-- Indexing for performance and realistic query plans
CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_order_date ON orders(order_date);
CREATE INDEX idx_payments_order_id ON payments(order_id);
CREATE INDEX idx_payments_payment_date ON payments(payment_date);
"""

SEED_DATA_SQL = """
-- Insert Customers
INSERT INTO customers (id, name, email, signup_date) VALUES
(1, 'Alice Johnson', 'alice@example.com', '2024-01-15'),
(2, 'Bob Smith', 'bob@example.com', '2024-02-10'),
(3, 'Charlie Brown', 'charlie@example.com', '2024-03-05'),
(4, 'Diana Prince', 'diana@example.com', '2024-04-12'),
(5, 'Evan Wright', 'evan@example.com', '2024-05-20'),
(6, 'Fiona Gallagher', 'fiona@example.com', '2024-06-18'),
(7, 'George Clark', 'george@example.com', '2024-07-22'),
(8, 'Hannah Abbott', 'hannah@example.com', '2024-08-30'),
(9, 'Ian Malcolm', 'ian@example.com', '2024-09-14'),
(10, 'Julia Roberts', 'julia@example.com', '2024-10-01');

SELECT setval('customers_id_seq', (SELECT MAX(id) FROM customers));

-- Insert Orders (25 orders across various dates and statuses)
INSERT INTO orders (id, customer_id, order_date, status) VALUES
(1, 1, '2024-02-01', 'completed'),
(2, 1, '2024-03-15', 'completed'),
(3, 1, '2024-05-10', 'completed'),
(4, 2, '2024-02-20', 'completed'),
(5, 2, '2024-04-05', 'refunded'),
(6, 3, '2024-03-10', 'completed'),
(7, 3, '2024-06-12', 'cancelled'),
(8, 4, '2024-04-15', 'completed'),
(9, 4, '2024-07-01', 'completed'),
(10, 4, '2024-09-20', 'completed'),
(11, 5, '2024-06-01', 'pending'),
(12, 6, '2024-06-25', 'completed'),
(13, 6, '2024-08-14', 'completed'),
(14, 7, '2024-08-01', 'completed'),
(15, 7, '2024-09-05', 'completed'),
(16, 7, '2024-10-10', 'refunded'),
(17, 8, '2024-09-02', 'completed'),
(18, 9, '2024-09-25', 'completed'),
(19, 10, '2024-10-05', 'completed'),
(20, 1, '2024-11-01', 'completed'),
(21, 2, '2024-11-15', 'completed'),
(22, 3, '2024-11-20', 'completed'),
(23, 4, '2024-12-01', 'completed'),
(24, 5, '2024-12-10', 'completed'),
(25, 6, '2024-12-15', 'completed');

SELECT setval('orders_id_seq', (SELECT MAX(id) FROM orders));

-- Insert Payments (25 transactions matching orders with realistic amounts and dates)
INSERT INTO payments (id, order_id, amount, payment_status, payment_date) VALUES
(1, 1, 150.00, 'successful', '2024-02-01'),
(2, 2, 220.50, 'successful', '2024-03-15'),
(3, 3, 310.00, 'successful', '2024-05-11'),
(4, 4, 85.00, 'successful', '2024-02-21'),
(5, 5, 199.99, 'refunded', '2024-04-06'),
(6, 6, 45.00, 'successful', '2024-03-10'),
(7, 7, 120.00, 'failed', '2024-06-12'),
(8, 8, 550.00, 'successful', '2024-04-16'),
(9, 9, 320.00, 'successful', '2024-07-01'),
(10, 10, 780.00, 'successful', '2024-09-21'),
(11, 11, 60.00, 'failed', '2024-06-01'),
(12, 12, 140.00, 'successful', '2024-06-25'),
(13, 13, 215.50, 'successful', '2024-08-15'),
(14, 14, 95.00, 'successful', '2024-08-01'),
(15, 15, 110.00, 'successful', '2024-09-06'),
(16, 16, 450.00, 'refunded', '2024-10-12'),
(17, 17, 280.00, 'successful', '2024-09-03'),
(18, 18, 135.00, 'successful', '2024-09-26'),
(19, 19, 99.00, 'successful', '2024-10-05'),
(20, 20, 420.00, 'successful', '2024-11-02'),
(21, 21, 175.00, 'successful', '2024-11-16'),
(22, 22, 290.00, 'successful', '2024-11-21'),
(23, 23, 620.00, 'successful', '2024-12-02'),
(24, 24, 115.00, 'successful', '2024-12-10'),
(25, 25, 305.00, 'successful', '2024-12-16');

SELECT setval('payments_id_seq', (SELECT MAX(id) FROM payments));
"""


def seed_database(connection_url: str) -> None:
    print(f"Connecting to PostgreSQL database...")
    with psycopg2.connect(connection_url) as conn:
        with conn.cursor() as cur:
            print("Applying DDL schema (customers, orders, payments)...")
            cur.execute(DDL_SCHEMA)

            print("Inserting realistic seed data...")
            cur.execute(SEED_DATA_SQL)

            # Verification
            cur.execute("SELECT COUNT(*) FROM customers;")
            c_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM orders;")
            o_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM payments;")
            p_count = cur.fetchone()[0]

            print("\nDatabase seeded successfully!")
            print(f"- customers: {c_count} rows")
            print(f"- orders:    {o_count} rows")
            print(f"- payments:  {p_count} rows")


def main():
    parser = argparse.ArgumentParser(description="Seed Supabase PostgreSQL with eCommerce dataset.")
    parser.add_argument("--db-url", type=str, default=None, help="PostgreSQL connection string")
    args = parser.parse_args()

    db_url = args.db_url or settings.database_url
    if not db_url:
        print("Error: No database connection URL provided.")
        print("Please set DATABASE_URL in .env or pass --db-url.")
        sys.exit(1)

    try:
        seed_database(db_url)
    except Exception as e:
        print(f"Failed to seed database: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
