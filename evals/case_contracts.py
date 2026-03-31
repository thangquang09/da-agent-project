from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


SuiteName = Literal["domain", "spider", "movielens"]
IntentName = Literal["sql", "rag", "mixed"]
Language = Literal["vi", "en"]


def _normalize_path(raw_path: str | None) -> str | None:
    if not raw_path:
        return None
    # Keep eval paths portable across Windows/WSL by normalizing separators.
    return str(Path(str(raw_path).strip().replace("\\", "/")))


@dataclass(frozen=True)
class EvalCase:
    id: str
    suite: SuiteName
    language: Language
    query: str
    expected_intent: IntentName
    expected_tools: list[str]
    should_have_sql: bool
    expected_keywords: list[str] = field(default_factory=list)
    target_db_path: str | None = None
    gold_sql: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "EvalCase":
        return EvalCase(
            id=str(payload["id"]),
            suite=str(payload["suite"]),  # type: ignore[arg-type]
            language=str(payload["language"]),  # type: ignore[arg-type]
            query=str(payload["query"]),
            expected_intent=str(payload["expected_intent"]),  # type: ignore[arg-type]
            expected_tools=[str(item) for item in payload.get("expected_tools", [])],
            should_have_sql=bool(payload.get("should_have_sql", False)),
            expected_keywords=[
                str(item) for item in payload.get("expected_keywords", [])
            ],
            target_db_path=_normalize_path(payload.get("target_db_path")),
            gold_sql=payload.get("gold_sql"),
            metadata=dict(payload.get("metadata", {})),
        )


def load_cases_jsonl(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    if not path.exists():
        return cases
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            case = EvalCase.from_dict(payload)
            if not case.id:
                raise ValueError(f"Invalid case id at line {line_no} in {path}")
            cases.append(case)
    return cases


def dump_cases_jsonl(cases: list[EvalCase], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case.to_dict(), ensure_ascii=False) + "\n")
