from __future__ import annotations

import csv
import json
import random
import sqlite3
from pathlib import Path
from typing import Any

from app.llm.client import LLMClient
from app.logger import logger

MOVIELENS_CSV_DIR = Path("data/movie_lens/ml-32m")
MOVIELENS_DB = Path("data/warehouse/movielens.db")
MOVIELENS_SAMPLE_DB = Path("data/warehouse/movielens_sample.db")
OUTPUT_DIR = Path("evals/cases")

SAMPLE_SIZE = 50000


def _create_movielens_sample_db():
    if MOVIELENS_SAMPLE_DB.exists():
        logger.info(
            "MovieLens sample database already exists at {path}",
            path=MOVIELENS_SAMPLE_DB,
        )
        return
    if not MOVIELENS_DB.exists():
        _create_movielens_db()

    logger.info(
        "Creating sample MovieLens database with ~{count} ratings", count=SAMPLE_SIZE
    )
    conn_src = sqlite3.connect(MOVIELENS_DB)
    conn_dst = sqlite3.connect(MOVIELENS_SAMPLE_DB)
    cursor_src = conn_src.cursor()
    cursor_dst = conn_dst.cursor()

    cursor_dst.execute("""
        CREATE TABLE movies (
            movieId INTEGER PRIMARY KEY,
            title TEXT,
            genres TEXT
        )
    """)
    cursor_dst.execute("""
        CREATE TABLE ratings (
            userId INTEGER,
            movieId INTEGER,
            rating REAL,
            timestamp INTEGER
        )
    """)
    cursor_dst.execute("""
        CREATE TABLE tags (
            userId INTEGER,
            movieId INTEGER,
            tag TEXT,
            timestamp INTEGER
        )
    """)
    cursor_dst.execute("""
        CREATE TABLE links (
            movieId INTEGER PRIMARY KEY,
            imdbId INTEGER,
            tmdbId INTEGER
        )
    """)

    cursor_src.execute("SELECT * FROM movies")
    for row in cursor_src.fetchall():
        cursor_dst.execute("INSERT INTO movies VALUES (?, ?, ?)", row)

    cursor_src.execute(f"SELECT * FROM ratings ORDER BY RANDOM() LIMIT {SAMPLE_SIZE}")
    for row in cursor_src.fetchall():
        cursor_dst.execute("INSERT INTO ratings VALUES (?, ?, ?, ?)", row)

    cursor_src.execute("SELECT * FROM tags")
    for row in cursor_src.fetchall():
        cursor_dst.execute("INSERT INTO tags VALUES (?, ?, ?, ?)", row)

    cursor_src.execute("SELECT * FROM links")
    for row in cursor_src.fetchall():
        cursor_dst.execute("INSERT INTO links VALUES (?, ?, ?)", row)

    cursor_dst.execute("CREATE INDEX idx_ratings_user ON ratings(userId)")
    cursor_dst.execute("CREATE INDEX idx_ratings_movie ON ratings(movieId)")
    cursor_dst.execute("CREATE INDEX idx_tags_user ON tags(userId)")
    cursor_dst.execute("CREATE INDEX idx_tags_movie ON tags(movieId)")

    conn_src.close()
    conn_dst.commit()
    conn_dst.close()
    logger.info("Created MovieLens sample database at {path}", path=MOVIELENS_SAMPLE_DB)


def _create_movielens_db():
    if MOVIELENS_DB.exists():
        logger.info("MovieLens database already exists at {path}", path=MOVIELENS_DB)
        return
    MOVIELENS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(MOVIELENS_DB)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE movies (
            movieId INTEGER PRIMARY KEY,
            title TEXT,
            genres TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE ratings (
            userId INTEGER,
            movieId INTEGER,
            rating REAL,
            timestamp INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE tags (
            userId INTEGER,
            movieId INTEGER,
            tag TEXT,
            timestamp INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE links (
            movieId INTEGER PRIMARY KEY,
            imdbId INTEGER,
            tmdbId INTEGER
        )
    """)

    with open(MOVIELENS_CSV_DIR / "movies.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cursor.execute(
                "INSERT INTO movies VALUES (?, ?, ?)",
                (int(row["movieId"]), row["title"], row["genres"]),
            )
    logger.info("Loaded movies table")

    with open(MOVIELENS_CSV_DIR / "ratings.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            cursor.execute(
                "INSERT INTO ratings VALUES (?, ?, ?, ?)",
                (
                    int(row["userId"]),
                    int(row["movieId"]),
                    float(row["rating"]),
                    int(row["timestamp"]),
                ),
            )
            if i > 0 and i % 500000 == 0:
                logger.info("Loaded {count} ratings", count=i)
    logger.info("Loaded ratings table")

    with open(MOVIELENS_CSV_DIR / "tags.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cursor.execute(
                "INSERT INTO tags VALUES (?, ?, ?, ?)",
                (
                    int(row["userId"]),
                    int(row["movieId"]),
                    row["tag"],
                    int(row["timestamp"]),
                ),
            )
    logger.info("Loaded tags table")

    with open(MOVIELENS_CSV_DIR / "links.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            imdb = int(row["imdbId"]) if row["imdbId"] else None
            tmdb = int(row["tmdbId"]) if row["tmdbId"] else None
            cursor.execute(
                "INSERT INTO links VALUES (?, ?, ?)", (int(row["movieId"]), imdb, tmdb)
            )
    logger.info("Loaded links table")

    cursor.execute("CREATE INDEX idx_ratings_user ON ratings(userId)")
    cursor.execute("CREATE INDEX idx_ratings_movie ON ratings(movieId)")
    cursor.execute("CREATE INDEX idx_tags_user ON tags(userId)")
    cursor.execute("CREATE INDEX idx_tags_movie ON tags(movieId)")

    conn.commit()
    conn.close()
    logger.info("Created MovieLens database at {path}", path=MOVIELENS_DB)


def get_movielens_schema_with_samples() -> dict[str, Any]:
    _create_movielens_sample_db()
    if not MOVIELENS_SAMPLE_DB.exists():
        return {}
    conn = sqlite3.connect(MOVIELENS_SAMPLE_DB)
    cursor = conn.cursor()
    schema = {}
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    for (table_name,) in cursor.fetchall():
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [{"name": col[1], "type": col[2]} for col in cursor.fetchall()]
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
        rows = [
            dict(zip([col[1] for col in cursor.description], row))
            for row in cursor.fetchall()
        ]
        schema[table_name] = {"columns": columns, "sample_rows": rows}
    conn.close()
    return schema


def _generate_cases_with_llm(
    schema: dict[str, Any],
    difficulty: str,
    count: int,
    language: str,
) -> list[dict[str, Any]]:
    schema_text = json.dumps(schema, indent=2, ensure_ascii=False)
    lang_instruction = "in Vietnamese" if language == "vi" else "in English"
    difficulty_instruction = {
        "easy": "simple queries using only SELECT, COUNT, AVG, SUM with no JOINs",
        "medium": "queries using JOINs, GROUP BY, ORDER BY, LIMIT",
        "hard": "complex queries using subqueries, INTERSECT/UNION/EXCEPT, nested aggregations",
    }[difficulty]

    prompt = f"""Given this MovieLens database schema:
{schema_text}

Generate {count} natural language questions {lang_instruction} that can be answered with SQL.
Difficulty: {difficulty_instruction}

Requirements:
- Questions must be answerable with the provided schema
- Each question must have exactly ONE correct SQL query
- Questions should be practical/realistic analytics questions
- For easy: basic counting, averaging, simple filters
- For medium: JOINs, GROUP BY with aggregation, ordering
- For hard: subqueries, set operations, complex aggregations

Output format (JSON array):
[
  {{
    "question": "question text",
    "gold_sql": "SELECT ... FROM ..."
  }}
]

Important:
- gold_sql must be a valid SELECT query only (no INSERT/UPDATE/DELETE)
- Use table aliases when doing JOINs (e.g., SELECT ... FROM ratings r JOIN movies m ON r.movieId = m.movieId)
- Only generate questions that match the difficulty level"""

    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "You are a data analyst expert. Generate realistic SQL test questions.",
                },
                {"role": "user", "content": prompt},
            ],
            model="gh/gpt-4o",
            temperature=0.3,
            max_tokens=4000,
            stream=False,
        )
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        if content:
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            return json.loads(content.strip())
    except Exception as e:
        logger.warning("LLM case generation failed: {error}", error=str(e))
    return []


def generate_movielens_cases(
    n_easy: int = 3,
    n_medium: int = 3,
    n_hard: int = 2,
    language: str = "en",
    output_path: Path | None = None,
) -> list[dict[str, Any]]:
    if output_path is None:
        output_path = OUTPUT_DIR / "dev" / f"movielens_{language}_dev.jsonl"

    schema = get_movielens_schema_with_samples()
    if not schema:
        logger.warning("MovieLens database not found at {path}", path=MOVIELENS_DB)
        return []

    cases = []
    case_id = 0

    for difficulty, count in [("easy", n_easy), ("medium", n_medium), ("hard", n_hard)]:
        llm_cases = _generate_cases_with_llm(schema, difficulty, count, language)
        for item in llm_cases:
            cases.append(
                {
                    "id": f"movielens_{difficulty}_{case_id:03d}_{language}",
                    "suite": "movielens",
                    "language": language,
                    "query": item["question"],
                    "expected_intent": "sql",
                    "expected_tools": [
                        "route_intent",
                        "get_schema",
                        "generate_sql",
                        "validate_sql",
                        "query_sql",
                        "analyze_result",
                    ],
                    "should_have_sql": True,
                    "expected_keywords": [],
                    "target_db_path": str(MOVIELENS_SAMPLE_DB),
                    "gold_sql": item["gold_sql"],
                    "metadata": {"difficulty": difficulty, "source": "llm_generated"},
                }
            )
            case_id += 1

    if output_path and cases:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            for case in cases:
                f.write(json.dumps(case, ensure_ascii=False) + "\n")

    return cases


def main():
    schema = get_movielens_schema_with_samples()
    print(f"MovieLens schema loaded: {list(schema.keys())}")

    for lang in ["en", "vi"]:
        dev_path = OUTPUT_DIR / "dev" / f"movielens_{lang}_dev.jsonl"
        dev_cases = generate_movielens_cases(
            n_easy=5, n_medium=5, n_hard=5, language=lang, output_path=dev_path
        )
        print(f"Generated {len(dev_cases)} {lang} dev cases -> {dev_path}")

        test_path = OUTPUT_DIR / "test" / f"movielens_{lang}_test.jsonl"
        test_cases = generate_movielens_cases(
            n_easy=10, n_medium=10, n_hard=10, language=lang, output_path=test_path
        )
        print(f"Generated {len(test_cases)} {lang} test cases -> {test_path}")


if __name__ == "__main__":
    main()
