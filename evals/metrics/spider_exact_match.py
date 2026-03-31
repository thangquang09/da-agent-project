from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


SQL_COMPONENTS = [
    "select",
    "from",
    "where",
    "group_by",
    "having",
    "order_by",
    "limit",
    "offset",
    "intersect",
    "union",
    "except",
]

COMPONENT_TO_ATTR = {
    "select": "select",
    "from": "from_",
    "where": "where",
    "group_by": "group_by",
    "having": "having",
    "order_by": "order_by",
    "limit": "limit",
    "offset": "offset",
    "intersect": "intersect",
    "union": "union",
    "except": "except_",
}


@dataclass(frozen=True)
class SQLComponentSet:
    select: frozenset[str]
    from_: frozenset[str]
    where: frozenset[str]
    group_by: frozenset[str]
    having: frozenset[str]
    order_by: frozenset[str]
    limit: frozenset[str]
    offset: frozenset[str]
    intersect: frozenset[str]
    union: frozenset[str]
    except_: frozenset[str]

    def as_dict(self) -> dict[str, frozenset[str]]:
        return {
            "select": self.select,
            "from_": self.from_,
            "where": self.where,
            "group_by": self.group_by,
            "having": self.having,
            "order_by": self.order_by,
            "limit": self.limit,
            "offset": self.offset,
            "intersect": self.intersect,
            "union": self.union,
            "except_": self.except_,
        }


def _tokenize(sql: str) -> list[str]:
    sql = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    tokens = re.split(
        r"(\bSELECT\b|\bFROM\b|\bWHERE\b|\bGROUP\s+BY\b|\bHAVING\b|\bORDER\s+BY\b|\bLIMIT\b|\bOFFSET\b|\bINTERSECT\b|\bUNION\b|\bEXCEPT\b|\bAS\b|\bAND\b|\bOR\b|\bNOT\b|\bIN\b|\bLIKE\b|\bBETWEEN\b|\bIS\b|\bNULL\b|\bTRUE\b|\bFALSE\b|\bASC\b|\bDESC\b|\bJOIN\b|\bINNER\s+JOIN\b|\bLEFT\s+JOIN\b|\bRIGHT\s+JOIN\b|\bFULL\s+JOIN\b|\bCROSS\s+JOIN\b|\bON\b|\bIN\b|\bEXISTS\b|\bCASE\b|\bWHEN\b|\bTHEN\b|\bELSE\b|\bEND\b|\bCOUNT\b|\bSUM\b|\bAVG\b|\bMIN\b|\bMAX\b|\bDISTINCT\b|\bORDER\s+BY\b|\bGROUP\s+BY\b|\bHAVING\b|\bINSERT\b|\bINTO\b|\bVALUES\b|\bUPDATE\b|\bSET\b|\bDELETE\b|\bDROP\b|\bCREATE\b|\bALTER\b|\bTRUNCATE\b|\bTABLE\b|\bDATABASE\b|\bINDEX\b)",
        sql,
        flags=re.IGNORECASE,
    )
    cleaned = []
    for tok in tokens:
        tok = tok.strip()
        if tok:
            cleaned.append(tok)
    return cleaned


def _split_by_clause(tokens: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {
        "select": [],
        "from": [],
        "where": [],
        "group_by": [],
        "having": [],
        "order_by": [],
        "limit": [],
        "offset": [],
        "intersect": [],
        "union": [],
        "except": [],
    }
    current_clause = "select"
    clause_order = [
        "select",
        "from",
        "where",
        "group_by",
        "having",
        "order_by",
        "limit",
        "offset",
        "intersect",
        "union",
        "except",
    ]
    for tok in tokens:
        upper = tok.upper()
        if upper == "SELECT":
            current_clause = "select"
        elif upper == "FROM":
            current_clause = "from"
        elif upper == "WHERE":
            current_clause = "where"
        elif upper == "GROUP":
            current_clause = "group_by"
        elif upper == "HAVING":
            current_clause = "having"
        elif upper == "ORDER":
            current_clause = "order_by"
        elif upper == "LIMIT":
            current_clause = "limit"
        elif upper == "OFFSET":
            current_clause = "offset"
        elif upper == "INTERSECT":
            current_clause = "intersect"
        elif upper == "UNION":
            current_clause = "union"
        elif upper == "EXCEPT":
            current_clause = "except"
        else:
            sections[current_clause].append(tok)
    return sections


def _normalize_value(val: str) -> str:
    val = val.strip()
    val = re.sub(r"'([^']*)'", r"\1", val)
    val = re.sub(r'"([^"]*)"', r"\1", val)
    return val.lower()


def _extract_select_items(items: list[str]) -> frozenset[str]:
    result = set()
    current = ""
    paren_depth = 0
    for tok in items:
        current += tok + " "
        paren_depth += tok.count("(") - tok.count(")")
        if paren_depth == 0:
            tok_clean = current.strip().rstrip(",").strip()
            if tok_clean:
                normalized = _normalize_value(tok_clean)
                if normalized:
                    result.add(normalized)
            current = ""
    if current.strip():
        normalized = _normalize_value(current.strip().rstrip(",").strip())
        if normalized:
            result.add(normalized)
    return frozenset(result)


def _extract_from_items(items: list[str]) -> frozenset[str]:
    result = set()
    current = ""
    paren_depth = 0
    for tok in items:
        paren_depth += tok.count("(") - tok.count(")")
        if paren_depth > 0:
            current += tok + " "
        else:
            if tok.upper() in ("JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "ON"):
                if tok.upper() == "ON" and current.strip():
                    result.add(current.strip().lower())
                    current = ""
                else:
                    current += tok + " "
            elif tok.upper() == "AS":
                current += tok + " "
            else:
                if tok == ",":
                    if current.strip():
                        result.add(current.strip().lower())
                    current = ""
                else:
                    current += tok + " "
    if current.strip():
        result.add(current.strip().lower())
    final = set()
    for item in result:
        item = re.sub(r"\s+", " ", item).strip()
        item = re.sub(
            r"\s*(,|JOIN|INNER|LEFT|RIGHT|FULL|CROSS)\s*",
            " ",
            item,
            flags=re.IGNORECASE,
        )
        item = item.strip()
        if item and item.upper() not in (
            "JOIN",
            "INNER",
            "LEFT",
            "RIGHT",
            "FULL",
            "CROSS",
            "AS",
        ):
            final.add(item.lower())
    return frozenset(final)


def _extract_where_conditions(items: list[str]) -> frozenset[str]:
    result = set()
    current = ""
    paren_depth = 0
    for tok in items:
        paren_depth += tok.count("(") - tok.count(")")
        if paren_depth > 0:
            current += tok + " "
        else:
            if tok.upper() in ("AND", "OR"):
                if current.strip():
                    normalized = _normalize_condition(current.strip())
                    if normalized:
                        result.add(normalized)
                current = ""
            else:
                current += tok + " "
    if current.strip():
        normalized = _normalize_condition(current.strip())
        if normalized:
            result.add(normalized)
    return frozenset(result)


def _normalize_condition(cond: str) -> str:
    cond = re.sub(r"\s+", " ", cond).strip().lower()
    cond = re.sub(r"'([^']*)'", r"\1", cond)
    cond = re.sub(r"(\d+)\s*<=\s*(\d+)", r"\2 >= \1", cond)
    cond = re.sub(r"(\w+)\s*<>\s*(\w+)", r"\2 <> \1", cond)
    parts = re.split(
        r"(>=|<=|=|<>|<|>|\bLIKE\b|\bIN\b|\bBETWEEN\b|\bIS\b)",
        cond,
        flags=re.IGNORECASE,
    )
    parts = [p.strip() for p in parts if p.strip()]
    return " ".join(parts)


def _extract_group_by(items: list[str]) -> frozenset[str]:
    result = set()
    current = ""
    for tok in items:
        if tok.upper() in ("HAVING", "ORDER", "LIMIT"):
            if current.strip():
                normalized = _normalize_value(current.strip().rstrip(",").strip())
                if normalized:
                    result.add(normalized)
            current = ""
            if tok.upper() == "ORDER":
                current = "ORDER "
            elif tok.upper() == "LIMIT":
                break
        else:
            current += tok + " "
    if current.strip():
        normalized = _normalize_value(current.strip().rstrip(",").strip())
        if normalized:
            result.add(normalized)
    return frozenset(result)


def _extract_order_by(items: list[str]) -> frozenset[str]:
    result = set()
    current = ""
    for tok in items:
        if tok.upper() in ("LIMIT", "OFFSET"):
            if current.strip():
                result.add(current.strip().lower())
            current = ""
        elif tok.upper() in ("ASC", "DESC"):
            current += " " + tok
        else:
            current += tok + " "
    if current.strip():
        result.add(current.strip().lower())
    return frozenset(result)


def _extract_list_items(items: list[str]) -> frozenset[str]:
    result = set()
    current = ""
    paren_depth = 0
    for tok in items:
        paren_depth += tok.count("(") - tok.count(")")
        if paren_depth > 0:
            current += tok + " "
        else:
            if tok == ",":
                if current.strip():
                    normalized = _normalize_value(current.strip())
                    if normalized:
                        result.add(normalized)
                current = ""
            else:
                current += tok + " "
    if current.strip():
        normalized = _normalize_value(current.strip())
        if normalized:
            result.add(normalized)
    return frozenset(result)


def _extract_limit(items: list[str]) -> frozenset[str]:
    result = set()
    for tok in items:
        if re.match(r"^\d+$", tok.strip()):
            result.add(tok.strip())
    return frozenset(result)


def _extract_nested(sql: str) -> frozenset[str]:
    sql_upper = sql.upper()
    result = set()
    if "INTERSECT" in sql_upper:
        result.add("intersect")
    if "UNION" in sql_upper:
        result.add("union")
    if "EXCEPT" in sql_upper:
        result.add("except")
    return frozenset(result)


def parse_sql_into_components(sql: str) -> SQLComponentSet:
    tokens = _tokenize(sql)
    sections = _split_by_clause(tokens)
    return SQLComponentSet(
        select=_extract_select_items(sections["select"]),
        from_=_extract_from_items(sections["from"]),
        where=_extract_where_conditions(sections["where"]),
        group_by=_extract_group_by(sections["group_by"]),
        having=_extract_list_items(sections["having"]),
        order_by=_extract_order_by(sections["order_by"]),
        limit=_extract_limit(sections["limit"]),
        offset=_extract_limit(sections["offset"]),
        intersect=_extract_nested(sql),
        union=_extract_nested(sql),
        except_=_extract_nested(sql),
    )


def _safe_f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * (precision * recall) / (precision + recall)


def _set_metrics(
    pred_set: frozenset[str], gold_set: frozenset[str]
) -> dict[str, float]:
    if not pred_set and not gold_set:
        return {"acc": 1.0, "rec": 1.0, "f1": 1.0}
    if not pred_set:
        return {"acc": 0.0, "rec": 0.0, "f1": 0.0}
    if not gold_set:
        return {"acc": 0.0, "rec": 0.0, "f1": 0.0}
    tp = len(pred_set & gold_set)
    precision = tp / len(pred_set)
    recall = tp / len(gold_set)
    return {
        "acc": round(precision, 4),
        "rec": round(recall, 4),
        "f1": round(_safe_f1(precision, recall), 4),
    }


@dataclass(frozen=True)
class SpiderExactMatchResult:
    exact_match: bool
    partial_scores: dict[str, dict[str, float]]
    component_breakdown: dict[str, bool]
    overall_f1: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "exact_match": self.exact_match,
            "partial_scores": self.partial_scores,
            "component_breakdown": self.component_breakdown,
            "overall_f1": self.overall_f1,
        }


class SpiderExactMatchEvaluator:
    def evaluate(
        self, pred_sql: str, gold_sql: str, db_path: str | None = None
    ) -> SpiderExactMatchResult:
        pred_sql = pred_sql.strip() if pred_sql else ""
        gold_sql = gold_sql.strip() if gold_sql else ""
        if not pred_sql and not gold_sql:
            return SpiderExactMatchResult(
                exact_match=True,
                partial_scores={
                    comp: {"acc": 1.0, "rec": 1.0, "f1": 1.0} for comp in SQL_COMPONENTS
                },
                component_breakdown={comp: True for comp in SQL_COMPONENTS},
                overall_f1=1.0,
            )
        if not pred_sql or not gold_sql:
            return SpiderExactMatchResult(
                exact_match=False,
                partial_scores={
                    comp: {"acc": 0.0, "rec": 0.0, "f1": 0.0} for comp in SQL_COMPONENTS
                },
                component_breakdown={comp: False for comp in SQL_COMPONENTS},
                overall_f1=0.0,
            )
        pred_components = parse_sql_into_components(pred_sql)
        gold_components = parse_sql_into_components(gold_sql)
        partial_scores: dict[str, dict[str, float]] = {}
        component_breakdown: dict[str, bool] = {}
        all_f1s: list[float] = []
        for attr in SQL_COMPONENTS:
            attr_name = COMPONENT_TO_ATTR[attr]
            pred_val = getattr(pred_components, attr_name)
            gold_val = getattr(gold_components, attr_name)
            metrics = _set_metrics(pred_val, gold_val)
            partial_scores[attr] = metrics
            component_breakdown[attr] = bool(pred_val == gold_val)
            all_f1s.append(metrics["f1"])
        overall_f1 = sum(all_f1s) / len(all_f1s) if all_f1s else 0.0
        exact_match = all(component_breakdown.values())
        return SpiderExactMatchResult(
            exact_match=exact_match,
            partial_scores=partial_scores,
            component_breakdown=component_breakdown,
            overall_f1=round(overall_f1, 4),
        )
