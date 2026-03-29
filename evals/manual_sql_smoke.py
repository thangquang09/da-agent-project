from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.main import run_query


QUERIES = [
    "DAU 7 ngay gan day nhu the nao?",
    "Revenue 7 ngay gan day co giam khong?",
    "Top 5 video co retention cao nhat",
    "Cho toi so dau moi ngay trong 7 ngay qua",
    "Trung binh revenue 7 ngay gan day",
    "Video nao retention cao nhat hien tai?",
    "So sanh dau 2 ngay gan nhat",
    "Cho biet trend revenue gan day",
    "Lay bang daily_metrics 7 ngay gan nhat",
    "Top retention videos tu du lieu hien co",
]


def run_manual_sql_smoke() -> list[dict]:
    results: list[dict] = []
    for idx, query in enumerate(QUERIES, start=1):
        payload = run_query(query)
        results.append(
            {
                "id": idx,
                "query": query,
                "confidence": payload.get("confidence"),
                "intent": payload.get("evidence", ["intent=unknown"])[0].replace("intent=", ""),
                "has_sql": bool(payload.get("generated_sql")),
                "answer_preview": str(payload.get("answer", ""))[:160],
                "tools": payload.get("used_tools", []),
            }
        )
    return results


def write_markdown_report(results: list[dict], out_path: Path) -> None:
    lines = [
        "# Manual SQL Smoke Test",
        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Total queries: {len(results)}",
        "",
    ]
    for item in results:
        lines.extend(
            [
                f"## Case {item['id']}",
                f"- Query: {item['query']}",
                f"- Intent: {item['intent']}",
                f"- Confidence: {item['confidence']}",
                f"- Has SQL: {item['has_sql']}",
                f"- Tools: {', '.join(item['tools'])}",
                f"- Answer preview: {item['answer_preview']}",
                "",
            ]
        )
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    results = run_manual_sql_smoke()
    report_path = Path("evals") / "manual_sql_smoke_report.md"
    json_path = Path("evals") / "manual_sql_smoke_report.json"
    write_markdown_report(results, report_path)
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote report: {report_path}")
    print(f"Wrote json: {json_path}")


if __name__ == "__main__":
    main()

