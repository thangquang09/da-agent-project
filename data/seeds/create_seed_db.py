from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "warehouse" / "analytics.db"


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS daily_metrics (
            date TEXT PRIMARY KEY,
            dau INTEGER NOT NULL,
            revenue REAL NOT NULL,
            retention_d1 REAL NOT NULL,
            avg_session_time REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            publish_date TEXT NOT NULL,
            views INTEGER NOT NULL,
            watch_time REAL NOT NULL,
            retention_rate REAL NOT NULL,
            ctr REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS metric_definitions (
            metric_name TEXT PRIMARY KEY,
            definition TEXT NOT NULL,
            caveat TEXT NOT NULL,
            business_note TEXT NOT NULL
        );
        """
    )


def _seed_daily_metrics(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM daily_metrics")
    today = date.today()
    rows: list[tuple[str, int, float, float, float]] = []
    for idx in range(30):
        day = today - timedelta(days=29 - idx)
        dau = 12000 + (idx * 35) - (200 if idx % 7 == 0 else 0)
        revenue = 4800.0 + (idx * 21.5) - (90.0 if idx % 6 == 0 else 0.0)
        retention_d1 = 0.38 + ((idx % 5) * 0.01)
        avg_session_time = 14.2 + ((idx % 4) * 0.7)
        rows.append(
            (
                day.isoformat(),
                dau,
                round(revenue, 2),
                round(retention_d1, 4),
                round(avg_session_time, 2),
            )
        )

    conn.executemany(
        """
        INSERT INTO daily_metrics (date, dau, revenue, retention_d1, avg_session_time)
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )


def _seed_videos(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM videos")
    rows = [
        ("vid_001", "Gameplay Highlights #1", "2026-03-01", 120000, 56000.0, 0.47, 0.062),
        ("vid_002", "Beginner Guide", "2026-03-03", 93000, 49000.0, 0.53, 0.071),
        ("vid_003", "Patch Notes Breakdown", "2026-03-08", 78000, 35000.0, 0.41, 0.055),
        ("vid_004", "Top 10 Tips", "2026-03-12", 101000, 52000.0, 0.51, 0.069),
        ("vid_005", "Challenge Run", "2026-03-15", 67000, 30000.0, 0.39, 0.049),
        ("vid_006", "Community Q&A", "2026-03-20", 88000, 44500.0, 0.46, 0.058),
    ]
    conn.executemany(
        """
        INSERT INTO videos (video_id, title, publish_date, views, watch_time, retention_rate, ctr)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _seed_metric_definitions(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM metric_definitions")
    rows = [
        (
            "dau",
            "Daily Active Users: unique users active in a calendar day.",
            "Can spike due to campaign-driven low-quality users.",
            "Track alongside retention and revenue quality.",
        ),
        (
            "retention_d1",
            "Share of users returning the day after first activity.",
            "Sensitive to timezone cutoff and event delay.",
            "Use weekly cohorts for trend-level interpretation.",
        ),
        (
            "revenue",
            "Total recognized daily gross revenue.",
            "May be revised after payment reconciliation.",
            "Use 7-day moving average for stable decision-making.",
        ),
    ]
    conn.executemany(
        """
        INSERT INTO metric_definitions (metric_name, definition, caveat, business_note)
        VALUES (?, ?, ?, ?)
        """,
        rows,
    )


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        _create_tables(conn)
        _seed_daily_metrics(conn)
        _seed_videos(conn)
        _seed_metric_definitions(conn)
        conn.commit()
    print(f"Seeded SQLite database at: {DB_PATH}")


if __name__ == "__main__":
    main()

