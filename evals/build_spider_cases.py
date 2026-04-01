from __future__ import annotations

import json
from pathlib import Path

BASE_PATH = Path("data/spider_1/spider_data")
DEV_JSON = BASE_PATH / "dev.json"
DEV_GOLD_SQL = BASE_PATH / "dev_gold.sql"
TEST_JSON = BASE_PATH / "test.json"
TEST_GOLD_SQL = BASE_PATH / "test_gold.sql"
DATABASE_DIR = BASE_PATH / "database"
TEST_DATABASE_DIR = BASE_PATH / "test_database"
OUTPUT_DIR = Path("evals/cases")


def load_dev_cases():
    with open(DEV_JSON) as f:
        dev_data = json.load(f)
    gold_map: dict[tuple[str, str], str] = {}
    with open(DEV_GOLD_SQL) as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                sql, db_id = parts[0], parts[1]
                gold_map[(db_id, sql)] = sql
    cases = []
    for idx, item in enumerate(dev_data):
        db_id = item["db_id"]
        question = item["question"]
        gold_sql = item["query"]
        db_path = DATABASE_DIR / db_id / f"{db_id}.sqlite"
        case = {
            "id": f"spider_dev_{idx:04d}_en",
            "suite": "spider",
            "language": "en",
            "query": question,
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
            "target_db_path": str(db_path),
            "gold_sql": gold_sql,
            "metadata": {"db_id": db_id, "spider_idx": idx},
        }
        cases.append(case)
        case_vi = case.copy()
        case_vi["id"] = f"spider_dev_{idx:04d}_vi"
        case_vi["language"] = "vi"
        case_vi["query"] = f"Hãy trả lời bằng SQL cho câu hỏi sau: {question}"
        cases.append(case_vi)
    return cases


def load_test_cases():
    with open(TEST_JSON) as f:
        test_data = json.load(f)
    cases = []
    for idx, item in enumerate(test_data):
        db_id = item["db_id"]
        question = item["question"]
        gold_sql = item["query"]
        db_path = TEST_DATABASE_DIR / db_id / f"{db_id}.sqlite"
        case = {
            "id": f"spider_test_{idx:04d}_en",
            "suite": "spider",
            "language": "en",
            "query": question,
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
            "target_db_path": str(db_path),
            "gold_sql": gold_sql,
            "metadata": {"db_id": db_id, "spider_idx": idx},
        }
        cases.append(case)
        case_vi = case.copy()
        case_vi["id"] = f"spider_test_{idx:04d}_vi"
        case_vi["language"] = "vi"
        case_vi["query"] = f"Hãy trả lời bằng SQL cho câu hỏi sau: {question}"
        cases.append(case_vi)
    return cases


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dev_cases = load_dev_cases()
    test_cases = load_test_cases()
    print(f"Loaded {len(dev_cases)} dev cases (EN+VI)")
    print(f"Loaded {len(test_cases)} test cases (EN+VI)")
    dev_path = OUTPUT_DIR / "dev" / "spider_dev.jsonl"
    dev_path.parent.mkdir(parents=True, exist_ok=True)
    with dev_path.open("w", encoding="utf-8") as f:
        for case in dev_cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"Wrote {len(dev_cases)} cases to {dev_path}")
    test_path = OUTPUT_DIR / "test" / "spider_test.jsonl"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    with test_path.open("w", encoding="utf-8") as f:
        for case in test_cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"Wrote {len(test_cases)} cases to {test_path}")


if __name__ == "__main__":
    main()
