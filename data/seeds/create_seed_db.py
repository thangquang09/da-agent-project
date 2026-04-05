"""Seed PostgreSQL database with online_retail_II.csv dataset.

This script creates the online_retail table and imports data from the CSV file.
Uses PostgreSQL COPY command for efficient bulk loading.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import psycopg

from app.config import load_settings
from app.logger import logger


# Project paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = PROJECT_ROOT / "data" / "uci_online_retail" / "online_retail_II.csv"


def _create_online_retail_table(conn: psycopg.Connection) -> None:
    """Create online_retail table with PostgreSQL schema."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS online_retail (
            invoice TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            description TEXT,
            quantity INTEGER NOT NULL,
            invoice_date TIMESTAMPTZ NOT NULL,
            price NUMERIC(10, 4) NOT NULL,
            customer_id TEXT,
            country TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- Create indexes for common query patterns
        CREATE INDEX IF NOT EXISTS idx_online_retail_invoice ON online_retail(invoice);
        CREATE INDEX IF NOT EXISTS idx_online_retail_stock_code ON online_retail(stock_code);
        CREATE INDEX IF NOT EXISTS idx_online_retail_country ON online_retail(country);
        CREATE INDEX IF NOT EXISTS idx_online_retail_invoice_date ON online_retail(invoice_date);
        """
    )
    logger.info("Created online_retail table with indexes")


def _parse_csv_value(value: str | None) -> str | None:
    """Parse CSV value, handling empty strings and quotes."""
    if value is None or value.strip() == "":
        return None
    # Remove surrounding quotes if present
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1]
    return value


def _parse_invoice_date(date_str: str) -> datetime:
    """Parse invoice date from CSV format (e.g., '2009-12-01 07:45:00')."""
    # Remove any surrounding quotes
    date_str = date_str.strip().strip('"').strip("'")
    # Parse datetime (no timezone in CSV, assume UTC)
    return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")


def _import_csv_via_copy(conn: psycopg.Connection, csv_path: Path) -> None:
    """Import CSV data using PostgreSQL COPY command (fastest method)."""
    logger.info("Importing data via COPY from {path}", path=csv_path)

    with conn.cursor() as cur:
        # Use COPY FROM for efficient bulk loading
        with csv_path.open("r", encoding="utf-8") as f:
            # Skip header row
            headers = f.readline().strip().split(",")
            reader = csv.DictReader(f, fieldnames=headers)

            # Use COPY with row-by-row writing for better error handling
            with cur.copy("COPY online_retail (invoice, stock_code, description, quantity, invoice_date, price, customer_id, country) FROM STDIN") as copy:
                for row_idx, row in enumerate(reader, 1):
                    try:
                        invoice = _parse_csv_value(row.get("Invoice", ""))
                        stock_code = _parse_csv_value(row.get("StockCode", ""))
                        description = _parse_csv_value(row.get("Description", ""))
                        quantity_str = _parse_csv_value(row.get("Quantity", "0"))
                        date_str = _parse_csv_value(row.get("InvoiceDate", ""))
                        price_str = _parse_csv_value(row.get("Price", "0"))
                        customer_id = _parse_csv_value(row.get("Customer ID", ""))
                        country = _parse_csv_value(row.get("Country", ""))

                        if not invoice or not stock_code:
                            continue  # Skip rows without key fields

                        quantity = int(quantity_str) if quantity_str else 0
                        price = float(price_str) if price_str else 0.0
                        invoice_date = _parse_invoice_date(date_str) if date_str else datetime.now()

                        copy.write_row((
                            invoice or "",
                            stock_code or "",
                            description or "",
                            quantity,
                            invoice_date,
                            price,
                            customer_id or "",
                            country or "",
                        ))
                    except Exception as exc:
                        logger.warning(
                            "Skipping row {row_idx} due to error: {exc}",
                            row_idx=row_idx,
                            exc=exc,
                        )
                        continue

    logger.info("Completed CSV import via COPY")


def _get_row_count(conn: psycopg.Connection) -> int:
    """Get total row count from online_retail table."""
    with conn.cursor() as cur:
        cur = cur.execute("SELECT COUNT(*) FROM online_retail")
        return cur.fetchone()[0]


def main() -> None:
    """Main seeding function."""
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"CSV file not found: {CSV_PATH}")

    logger.info("Starting PostgreSQL database seeding...")
    logger.info("CSV path: {path}", path=CSV_PATH)
    logger.info("File size: {size_mb:.1f}MB", size_mb=CSV_PATH.stat().st_size / (1024 * 1024))

    settings = load_settings()

    with psycopg.connect(settings.database_url) as conn:
        # Create table and indexes
        _create_online_retail_table(conn)

        # Import data
        _import_csv_via_copy(conn, CSV_PATH)

        # Verify import
        row_count = _get_row_count(conn)
        logger.info("Seeding completed! Total rows in online_retail: {rows}", rows=row_count)

    print(f"✅ Seeded PostgreSQL database with online_retail data")
    print(f"   Total rows: {row_count:,}")
    print(f"   Connection: {settings.database_url}")


if __name__ == "__main__":
    main()
