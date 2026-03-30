from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from app.logger import logger
from evals.case_contracts import EvalCase, dump_cases_jsonl


DEFAULT_SQL_TOOL_PATH = [
    "route_intent",
    "get_schema",
    "generate_sql",
    "validate_sql",
    "query_sql",
    "analyze_result",
]


def _to_float(raw: str, default: float = 0.0) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _to_int(raw: str, default: int = 0) -> int:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def _parse_iso_date(raw: str) -> str | None:
    try:
        return datetime.fromisoformat(raw.strip()).date().isoformat()
    except ValueError:
        return None


def build_domain_eval_db(
    uci_csv_path: Path,
    movielens_dir: Path,
    out_db_path: Path,
    max_uci_rows: int = 250_000,
    max_ratings_rows: int = 400_000,
    top_videos: int = 500,
) -> None:
    logger.info("Building domain eval db at {path}", path=out_db_path)
    out_db_path.parent.mkdir(parents=True, exist_ok=True)

    daily_revenue: dict[str, float] = defaultdict(float)
    daily_customer_sets: dict[str, set[str]] = defaultdict(set)
    daily_order_count: dict[str, int] = defaultdict(int)

    with uci_csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_idx, row in enumerate(reader, start=1):
            if row_idx > max_uci_rows:
                break
            day = _parse_iso_date(str(row.get("InvoiceDate", "")))
            if not day:
                continue
            quantity = _to_float(str(row.get("Quantity", "0")))
            price = _to_float(str(row.get("Price", "0")))
            revenue = quantity * price
            daily_revenue[day] += revenue
            customer_id = str(row.get("Customer ID", "")).strip()
            if customer_id and customer_id.lower() != "nan":
                daily_customer_sets[day].add(customer_id)
            daily_order_count[day] += 1

    movie_titles: dict[int, str] = {}
    with (movielens_dir / "movies.csv").open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            movie_id = _to_int(row.get("movieId", "0"))
            if movie_id <= 0:
                continue
            movie_titles[movie_id] = str(row.get("title", "")).strip() or f"Movie {movie_id}"

    rating_count: dict[int, int] = defaultdict(int)
    rating_sum: dict[int, float] = defaultdict(float)
    with (movielens_dir / "ratings.csv").open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_idx, row in enumerate(reader, start=1):
            if row_idx > max_ratings_rows:
                break
            movie_id = _to_int(row.get("movieId", "0"))
            if movie_id <= 0:
                continue
            score = _to_float(row.get("rating", "0"))
            rating_count[movie_id] += 1
            rating_sum[movie_id] += score

    with sqlite3.connect(out_db_path) as conn:
        conn.executescript(
            """
            DROP TABLE IF EXISTS daily_metrics;
            DROP TABLE IF EXISTS videos;
            DROP TABLE IF EXISTS metric_definitions;

            CREATE TABLE daily_metrics (
                date TEXT PRIMARY KEY,
                dau INTEGER NOT NULL,
                revenue REAL NOT NULL,
                retention_d1 REAL NOT NULL,
                avg_session_time REAL NOT NULL
            );

            CREATE TABLE videos (
                video_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                publish_date TEXT NOT NULL,
                views INTEGER NOT NULL,
                watch_time REAL NOT NULL,
                retention_rate REAL NOT NULL,
                ctr REAL NOT NULL
            );

            CREATE TABLE metric_definitions (
                metric_name TEXT PRIMARY KEY,
                definition TEXT NOT NULL,
                caveat TEXT NOT NULL,
                business_note TEXT NOT NULL
            );
            """
        )

        sorted_days = sorted(daily_revenue.keys())
        daily_rows: list[tuple[str, int, float, float, float]] = []
        previous_customers: set[str] = set()
        for day in sorted_days:
            customers = daily_customer_sets.get(day, set())
            dau = len(customers)
            if previous_customers and len(previous_customers) > 0:
                retention = len(customers & previous_customers) / len(previous_customers)
            else:
                retention = 0.0
            previous_customers = customers

            order_count = daily_order_count.get(day, 0)
            avg_session_time = min(40.0, 5.0 + (order_count / max(dau, 1)) * 2.0)
            daily_rows.append((day, dau, round(daily_revenue[day], 2), round(retention, 4), round(avg_session_time, 2)))

        conn.executemany(
            """
            INSERT INTO daily_metrics (date, dau, revenue, retention_d1, avg_session_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            daily_rows,
        )

        ranked_movies = sorted(rating_count.items(), key=lambda item: item[1], reverse=True)[:top_videos]
        video_rows: list[tuple[str, str, str, int, float, float, float]] = []
        max_views = max((count * 20 for _, count in ranked_movies), default=1)
        year_pattern = re.compile(r"\((\d{4})\)$")
        for movie_id, count in ranked_movies:
            title = movie_titles.get(movie_id, f"Movie {movie_id}")
            avg_rating = rating_sum[movie_id] / max(count, 1)
            views = count * 20
            watch_time = round(views * (4.0 + avg_rating / 2.0), 2)
            retention = round(min(0.99, max(0.05, avg_rating / 5.0)), 4)
            ctr = round(min(0.25, 0.02 + (views / max_views) * 0.2), 4)

            match = year_pattern.search(title)
            year = int(match.group(1)) if match else 2000
            publish_date = f"{max(1980, min(2025, year))}-01-01"

            video_rows.append((f"movie_{movie_id}", title, publish_date, views, watch_time, retention, ctr))

        conn.executemany(
            """
            INSERT INTO videos (video_id, title, publish_date, views, watch_time, retention_rate, ctr)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            video_rows,
        )

        metric_rows = [
            (
                "dau",
                "Daily Active Users: unique customers active in a calendar day.",
                "Proxy from transaction logs, not product events.",
                "Interpret together with retention and revenue trend.",
            ),
            (
                "retention_d1",
                "Share of previous-day active customers that returned today.",
                "Proxy definition, differs from strict cohort retention.",
                "Use with caveats before product decisions.",
            ),
            (
                "revenue",
                "Total daily revenue from quantity multiplied by unit price.",
                "Includes negative adjustments from returns/cancellations.",
                "Read with 7-day trend for stability.",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO metric_definitions (metric_name, definition, caveat, business_note)
            VALUES (?, ?, ?, ?)
            """,
            metric_rows,
        )
        conn.commit()

    logger.info(
        "Domain eval db built (days={days}, videos={videos})",
        days=len(daily_rows),
        videos=len(video_rows),
    )


def _domain_snapshot(db_path: Path) -> dict[str, str]:
    with sqlite3.connect(db_path) as conn:
        latest_date = conn.execute("SELECT MAX(date) FROM daily_metrics").fetchone()[0] or "unknown"
        top_video = conn.execute(
            "SELECT title FROM videos ORDER BY retention_rate DESC LIMIT 1"
        ).fetchone()
    return {
        "latest_date": str(latest_date),
        "top_video_title": str(top_video[0]) if top_video else "top video",
    }


def generate_domain_cases(domain_db_path: Path) -> list[EvalCase]:
    snapshot = _domain_snapshot(domain_db_path)
    latest_date = snapshot["latest_date"]
    top_video_title = snapshot["top_video_title"]

    templates: list[dict[str, str]] = [
        {
            "intent": "sql",
            "vi": "DAU 7 ngày gần đây có xu hướng tăng hay giảm?",
            "en": "Did DAU trend up or down in the last 7 days?",
            "keywords": "dau,trend",
        },
        {
            "intent": "sql",
            "vi": "Doanh thu 7 ngày gần đây như thế nào?",
            "en": "How did revenue move over the last 7 days?",
            "keywords": "revenue,7",
        },
        {
            "intent": "sql",
            "vi": "Top 5 video có retention cao nhất hiện tại là gì?",
            "en": "What are the top 5 videos by retention right now?",
            "keywords": "top,retention",
        },
        {
            "intent": "sql",
            "vi": f"Ngày {latest_date} thì DAU và revenue là bao nhiêu?",
            "en": f"What were DAU and revenue on {latest_date}?",
            "keywords": "dau,revenue",
        },
        {
            "intent": "sql",
            "vi": "So sánh DAU 2 ngày gần nhất.",
            "en": "Compare DAU for the most recent two days.",
            "keywords": "compare,dau",
        },
        {
            "intent": "sql",
            "vi": "Trung bình revenue 7 ngày gần đây là bao nhiêu?",
            "en": "What is the average revenue over the last 7 days?",
            "keywords": "average,revenue",
        },
        {
            "intent": "rag",
            "vi": "Retention D1 là gì?",
            "en": "What is Retention D1?",
            "keywords": "definition,retention",
        },
        {
            "intent": "rag",
            "vi": "Định nghĩa DAU trong hệ thống này là gì?",
            "en": "How is DAU defined in this system?",
            "keywords": "definition,dau",
        },
        {
            "intent": "rag",
            "vi": "Revenue có caveat dữ liệu nào cần lưu ý?",
            "en": "What data caveats should we note for revenue?",
            "keywords": "caveat,revenue",
        },
        {
            "intent": "rag",
            "vi": "Có lưu ý chất lượng dữ liệu nào khi đọc trend không?",
            "en": "Any data quality notes when interpreting trends?",
            "keywords": "quality,trend",
        },
        {
            "intent": "rag",
            "vi": "Metric retention nên được diễn giải như thế nào?",
            "en": "How should the retention metric be interpreted?",
            "keywords": "retention,interpret",
        },
        {
            "intent": "rag",
            "vi": f"Video '{top_video_title}' có ý nghĩa gì về mặt retention?",
            "en": f"What does retention imply for '{top_video_title}'?",
            "keywords": "retention,video",
        },
        {
            "intent": "mixed",
            "vi": "DAU 7 ngày gần đây thay đổi ra sao và metric này định nghĩa thế nào?",
            "en": "How did DAU change in the last 7 days and how is this metric defined?",
            "keywords": "dau,definition",
        },
        {
            "intent": "mixed",
            "vi": "Doanh thu gần đây giảm từ khi nào và có caveat dữ liệu nào?",
            "en": "Since when did revenue drop recently and what caveats apply?",
            "keywords": "revenue,caveat",
        },
        {
            "intent": "mixed",
            "vi": "Top video retention hiện tại là gì và nên diễn giải ra sao?",
            "en": "What is the current top retention video and how should it be interpreted?",
            "keywords": "top,retention,interpret",
        },
        {
            "intent": "mixed",
            "vi": f"Ngày {latest_date} doanh thu là bao nhiêu và dữ liệu có hạn chế gì?",
            "en": f"What was revenue on {latest_date} and what are the data limitations?",
            "keywords": "revenue,quality",
        },
        {
            "intent": "mixed",
            "vi": "So sánh DAU 2 ngày gần nhất và nhắc lại caveat quan trọng cho DAU.",
            "en": "Compare DAU for the latest two days and restate key DAU caveats.",
            "keywords": "dau,compare,caveat",
        },
        {
            "intent": "mixed",
            "vi": "Revenue 7 ngày gần đây thế nào và metric này tính theo rule nào?",
            "en": "How did 7-day revenue move and what rule defines this metric?",
            "keywords": "revenue,rule",
        },
    ]

    cases: list[EvalCase] = []
    for idx, template in enumerate(templates, start=1):
        intent = str(template["intent"])
        expected_tools = list(DEFAULT_SQL_TOOL_PATH)
        should_have_sql = intent in {"sql", "mixed"}
        if intent == "rag":
            expected_tools = [
                "route_intent",
                "retrieve_metric_definition"
                if "định nghĩa" in template["vi"].lower() or "what is" in template["en"].lower()
                else "retrieve_business_context",
            ]
        elif intent == "mixed":
            expected_tools = list(DEFAULT_SQL_TOOL_PATH) + ["retrieve_business_context"]

        keywords = [chunk.strip() for chunk in str(template["keywords"]).split(",") if chunk.strip()]
        cases.append(
            EvalCase(
                id=f"domain_{intent}_{idx:03d}_vi",
                suite="domain",
                language="vi",
                query=str(template["vi"]),
                expected_intent=intent,  # type: ignore[arg-type]
                expected_tools=expected_tools,
                should_have_sql=should_have_sql,
                expected_keywords=keywords,
                target_db_path=str(domain_db_path),
            )
        )
        cases.append(
            EvalCase(
                id=f"domain_{intent}_{idx:03d}_en",
                suite="domain",
                language="en",
                query=str(template["en"]),
                expected_intent=intent,  # type: ignore[arg-type]
                expected_tools=expected_tools,
                should_have_sql=should_have_sql,
                expected_keywords=keywords,
                target_db_path=str(domain_db_path),
            )
        )
    return cases


def generate_spider_cases(
    spider_dev_json_path: Path,
    spider_db_root: Path,
    seed: int = 42,
    target_total_cases: int = 24,
) -> list[EvalCase]:
    payload = json.loads(spider_dev_json_path.read_text(encoding="utf-8"))
    rng = random.Random(seed)
    rng.shuffle(payload)

    base_count = max(1, target_total_cases // 2)
    selected: list[dict] = []
    seen_db_ids: set[str] = set()
    for item in payload:
        db_id = str(item.get("db_id", ""))
        sqlite_path = spider_db_root / db_id / f"{db_id}.sqlite"
        if not sqlite_path.exists():
            continue
        if db_id in seen_db_ids:
            continue
        selected.append(item)
        seen_db_ids.add(db_id)
        if len(selected) >= base_count:
            break

    if len(selected) < base_count:
        for item in payload:
            db_id = str(item.get("db_id", ""))
            sqlite_path = spider_db_root / db_id / f"{db_id}.sqlite"
            if not sqlite_path.exists():
                continue
            selected.append(item)
            if len(selected) >= base_count:
                break

    cases: list[EvalCase] = []
    for idx, item in enumerate(selected, start=1):
        question = str(item.get("question", "")).strip()
        gold_sql = str(item.get("query", "")).strip()
        db_id = str(item.get("db_id", "")).strip()
        target_db_path = spider_db_root / db_id / f"{db_id}.sqlite"

        common_kwargs = {
            "suite": "spider",
            "expected_intent": "sql",
            "expected_tools": list(DEFAULT_SQL_TOOL_PATH),
            "should_have_sql": True,
            "target_db_path": str(target_db_path),
            "gold_sql": gold_sql,
            "metadata": {"db_id": db_id},
        }
        cases.append(
            EvalCase(
                id=f"spider_sql_{idx:03d}_en",
                language="en",
                query=question,
                **common_kwargs,
            )
        )
        cases.append(
            EvalCase(
                id=f"spider_sql_{idx:03d}_vi",
                language="vi",
                query=f"Hãy trả lời bằng SQL cho câu hỏi sau: {question}",
                **common_kwargs,
            )
        )
    return cases[:target_total_cases]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build dataset-driven eval cases")
    parser.add_argument("--uci-csv", default="data/uci_online_retail/online_retail_II.csv")
    parser.add_argument("--movielens-dir", default="data/movie_lens/ml-32m")
    parser.add_argument("--domain-db-path", default="data/warehouse/domain_eval.db")
    parser.add_argument("--spider-dev-json", default="data/spider_1/spider_data/dev.json")
    parser.add_argument("--spider-db-root", default="data/spider_1/spider_data/database")
    parser.add_argument("--cases-dir", default="evals/cases")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-uci-rows", type=int, default=250000)
    parser.add_argument("--max-ratings-rows", type=int, default=400000)
    parser.add_argument("--spider-total-cases", type=int, default=24)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uci_csv_path = Path(args.uci_csv)
    movielens_dir = Path(args.movielens_dir)
    domain_db_path = Path(args.domain_db_path)
    spider_dev_json_path = Path(args.spider_dev_json)
    spider_db_root = Path(args.spider_db_root)
    cases_dir = Path(args.cases_dir)

    build_domain_eval_db(
        uci_csv_path=uci_csv_path,
        movielens_dir=movielens_dir,
        out_db_path=domain_db_path,
        max_uci_rows=args.max_uci_rows,
        max_ratings_rows=args.max_ratings_rows,
    )
    domain_cases = generate_domain_cases(domain_db_path=domain_db_path)
    spider_cases = generate_spider_cases(
        spider_dev_json_path=spider_dev_json_path,
        spider_db_root=spider_db_root,
        seed=args.seed,
        target_total_cases=args.spider_total_cases,
    )

    dump_cases_jsonl(domain_cases, cases_dir / "domain_cases.jsonl")
    dump_cases_jsonl(spider_cases, cases_dir / "spider_cases.jsonl")

    print(f"Wrote domain DB: {domain_db_path}")
    print(f"Wrote domain cases: {cases_dir / 'domain_cases.jsonl'} ({len(domain_cases)} cases)")
    print(f"Wrote spider cases: {cases_dir / 'spider_cases.jsonl'} ({len(spider_cases)} cases)")


if __name__ == "__main__":
    main()
