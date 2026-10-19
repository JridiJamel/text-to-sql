"""
Deterministic tip selector for APEX-SQL skill.

Rule logic copied verbatim from:
  baselines/text2sql/apex_sql_mas/preprocess_select_tips.py

Only changes vs the original:
  - select_tips_rule_based() renamed to select_tips() with a dict return value
  - tip content loaded from micro_tips_structured.json (same directory)
  - main() / argparse removed (offline batch mode not needed)
"""

import json
import re
import os
from typing import List, Dict

# ---------------------------------------------------------------------------
# Load tip library from micro_tips_structured.json
# ---------------------------------------------------------------------------
_JSON_PATH = os.path.join(os.path.dirname(__file__), "micro_tips_structured.json")
with open(_JSON_PATH, encoding="utf-8") as _f:
    _ALL_TIPS: List[dict] = json.load(_f)["tips"]
_TIPS_BY_ID: Dict[str, dict] = {t["id"]: t for t in _ALL_TIPS}


# ---------------------------------------------------------------------------
# Rule-based selection (verbatim from preprocess_select_tips.py)
# ---------------------------------------------------------------------------
def _select_ids(question: str, evidence: str, logical_plan: str, db_schema: str) -> List[str]:
    # Universal tips (always included, added at the end)
    UNIVERSAL_TIPS = [
        'TIP009',  # Return columns in exact order (CRITICAL - missing in 78.9% of errors)
        'TIP019',  # Always verify column existence
        'TIP035'   # BIRD dataset has many column names with spaces
    ]

    selected = set()

    q_lower = question.lower()
    e_lower = evidence.lower() if evidence else ""
    p_lower = logical_plan.lower() if logical_plan else ""

    # Extract keywords from logical plan if present
    plan_keywords = set()
    keyword_matches = re.findall(r'keywords?:\s*([^\n]+)', p_lower, re.IGNORECASE)
    for match in keyword_matches:
        keywords = [k.strip() for k in match.split(',')]
        plan_keywords.update(keywords)

    # Combine all text for keyword matching
    all_text = f"{q_lower} {e_lower} {p_lower} {' '.join(plan_keywords)}"

    # ========== Evidence-Based Selection ==========

    # TIP001: Evidence specifies column with = or "can be represented as"
    if evidence and (
        re.search(r'can be represented as \w+\s*=', e_lower) or
        re.search(r'\w+\s*=\s*[\'"]?\w+[\'"]?', evidence) and 'refers to' not in e_lower
    ):
        selected.add('TIP001')

    # TIP002: Evidence contains formula with operators
    if evidence and re.search(r'=.*[+\-*/]|sum.*count|average.*=', e_lower):
        selected.add('TIP002')
        selected.add('TIP027')  # Division protection
        selected.add('TIP040')  # Avoid integer division

    # TIP003: Evidence shows value mapping with "stands for", "means", or direct value assignment
    if evidence and (
        'stands for' in e_lower or
        ('means' in e_lower and "'" in evidence) or
        re.search(r"'[^']+'\s+(stands for|means)", e_lower) or
        re.search(r"'[^']+' (is|are) ", e_lower) or
        re.search(r"=\s*'[^']+'", evidence)
    ):
        selected.add('TIP003')

    # TIP004: Evidence clarifies ambiguous terms with "refers to"
    if evidence and 'refers to' in e_lower:
        selected.add('TIP004')

    # ========== Question-Based Selection (enhanced with plan keywords) ==========

    # TIP005: Exact match when specific value is mentioned
    if re.search(r"with|where|whose.*'[^']+'", q_lower):
        selected.add('TIP005')
        selected.add('TIP023')  # Use exact value filters

    # TIP008: Exclude ORDER BY columns (highest/lowest/top/bottom)
    if any(word in all_text for word in ['highest', 'lowest', 'top', 'bottom', 'maximum', 'minimum', 'best', 'worst', 'most', 'least', 'order by', 'sort']):
        selected.add('TIP008')
        selected.add('TIP030')  # ORDER BY implementation
        selected.add('TIP031')  # LIMIT for top N
        selected.add('TIP032')  # Filter NULLs for extreme values

    # TIP009: Multiple output columns with specific order
    if re.search(r'\w+\s+and\s+\w+|,\s*\w+\s+and', q_lower) and not q_lower.startswith('how many'):
        selected.add('TIP009')

    # TIP010: Exclude filter columns (where/with pattern)
    if re.search(r'(what|list|name|show).*\b(where|with|whose|that have)\b', q_lower):
        selected.add('TIP010')

    # TIP011: Pure counting questions (including "list" questions that should return count)
    if (q_lower.startswith('how many') and 'what' not in q_lower and 'which' not in q_lower) or \
       (q_lower.startswith('list') and 'lowest' in q_lower and 'amount' in q_lower):
        selected.add('TIP011')

    # TIP012/TIP013: Table selection (when JOIN might be involved)
    if ('join' in p_lower or
        len(re.findall(r'\btable\b', p_lower)) > 3 or
        re.search(r'(\w+)\s+and\s+(their|its)\s+(\w+)', q_lower)):
        selected.add('TIP012')  # Check single table first
        selected.add('TIP013')  # JOIN only when necessary
        selected.add('TIP020')  # Identify join keys
        selected.add('TIP021')  # Verify join keys
        selected.add('TIP022')  # Choose join type
        selected.add('TIP042')  # Prefix columns with table alias

    # TIP014: Avoid over-engineering (when query seems complex)
    if ('subquery' in p_lower and 'nested' in p_lower) or len(re.findall(r'join', p_lower)) > 3:
        selected.add('TIP014')

    # TIP015/TIP016: Column names with parentheses
    if ('(' in question or ')' in question or '(' in (evidence or '') or ')' in (evidence or '')):
        selected.add('TIP015')
        selected.add('TIP016')

    # TIP017/TIP018: Schema grounding (column identification)
    if any(word in all_text for word in ['which column', 'what column', 'identify column', 'find column', 'ambiguous']):
        selected.add('TIP017')  # Direct name matching
    if any(word in all_text for word in ['semantic', 'meaning', 'interpret', 'ambiguous column']):
        selected.add('TIP018')  # Semantic matching

    # TIP024: Numeric comparisons (including BETWEEN)
    if re.search(r'more than|less than|greater than|between|at least|at most|above|below|over|under|exceed', all_text):
        selected.add('TIP024')

    # TIP026: Aggregation functions (enhanced with keywords)
    if any(word in all_text for word in ['total', 'sum', 'average', 'avg', 'count', 'maximum', 'minimum', 'aggregate', 'group by']):
        selected.add('TIP026')
        selected.add('TIP028')  # GROUP BY

    # TIP029: HAVING for post-aggregation filtering
    if re.search(r'(average|total|sum|count).*(more than|less than|greater|between)', all_text):
        selected.add('TIP029')

    # TIP033/TIP034: Subqueries and CTEs (multi-step logic)
    step_numbers = re.findall(r'step\s*(\d+)', p_lower)
    max_step = int(step_numbers[-1]) if step_numbers else 0
    if max_step > 4 or ('subquery' in p_lower and 'nested' in p_lower) or ('with' in p_lower and 'as' in p_lower and 'select' in p_lower):
        selected.add('TIP033')  # Subquery
        selected.add('TIP034')  # CTE

    # TIP036: Use aliases for calculated columns
    if any(word in all_text for word in ['calculate', 'ratio', 'percentage', 'sum', 'avg', 'count']):
        selected.add('TIP036')

    # TIP037: Cannot use column alias in WHERE clause
    if any(word in all_text for word in ['calculate', 'ratio']) and any(word in all_text for word in ['where', 'filter']):
        selected.add('TIP037')

    # TIP038: Never hard-code values (CRITICAL - always include)
    selected.add('TIP038')

    # TIP039: NULL handling (when filtering or aggregating)
    if any(word in all_text for word in ['null', 'missing', 'empty']):
        selected.add('TIP039')

    # TIP041: Entity isolation for mixed-data tables
    schema_lower = db_schema.lower() if db_schema else ""
    if (any(word in schema_lower for word in ['metricid', 'metric_id', 'event_type', 'entity_type', 'data_type']) and
        any(word in all_text for word in ['specific', 'certain', 'particular', 'only', 'filter by type', 'where type'])):
        selected.add('TIP041')

    # TIP046: Precision preservation (no arbitrary rounding)
    if any(word in all_text for word in ['average', 'avg', 'ratio', 'percentage', 'rate', 'calculate']):
        selected.add('TIP046')

    # TIP047: Ratio calculation - count all occurrences
    if any(word in all_text for word in ['ratio', 'percentage', 'percent', 'proportion', 'rate']):
        selected.add('TIP047')
        selected.add('TIP048')  # Percentage calculation

    # TIP049: DISTINCT usage - list vs count (CRITICAL for counting questions)
    if any(pattern in q_lower for pattern in ['how many', 'what is', 'what are', 'which', 'list all', 'list the']):
        selected.add('TIP049')

    # TIP043: Conditional aggregation with CASE
    if 'case when' in p_lower or ('different' in all_text and 'aggregate' in all_text):
        selected.add('TIP043')

    # TIP044/TIP045: Window functions and ranking
    if any(word in all_text for word in ['rank', 'ranking', 'row number', 'top n per', 'per group', 'partition']):
        selected.add('TIP044')
        selected.add('TIP045')

    # ========== Always Include Universal Tips ==========
    for tip_id in UNIVERSAL_TIPS:
        selected.add(tip_id)

    # ========== String Matching Tips ==========

    # TIP006/TIP007: LIKE vs exact match
    if any(word in q_lower for word in ['contain', 'include', 'start with', 'end with', 'like']):
        selected.add('TIP006')  # Use LIKE for partial
    else:
        selected.add('TIP005')  # Use exact match

    # TIP025: String matching strategy
    if any(word in q_lower for word in ['name', 'title', 'description']):
        selected.add('TIP025')

    # ========== Add Universal Tips (again, as in original) ==========
    for tip_id in UNIVERSAL_TIPS:
        selected.add(tip_id)

    return sorted(list(selected))


def _format_tips(tip_ids: List[str]) -> str:
    """Format selected tip IDs into prompt text.

    Matches the original formatting in preprocess_select_tips.py:
      "[TIP_ID] title\ndescription\n"
    """
    lines = []
    for tip_id in tip_ids:
        tip = _TIPS_BY_ID.get(tip_id)
        if tip:
            lines.append(f"[{tip['id']}] {tip['title']}\n{tip['description']}\n")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def select_tips(question: str, evidence: str, logical_plan: str, db_schema: str) -> dict:
    """
    Select relevant SQL tips and return formatted text for use in prompts.

    Args:
        question:     Natural language question.
        evidence:     Evidence / external knowledge (may be empty).
        logical_plan: Abstract logical plan from Phase 1.
        db_schema:    Database schema text.

    Returns:
        dict with keys:
          selected_ids    – sorted list of tip IDs
          formatted_tips  – formatted string ready to insert into prompt
          error           – None on success, error message on failure
    """
    try:
        selected_ids = _select_ids(question, evidence or "", logical_plan or "", db_schema or "")
        formatted = _format_tips(selected_ids)
        return {"selected_ids": selected_ids, "formatted_tips": formatted, "error": None}
    except Exception as e:
        return {"selected_ids": [], "formatted_tips": "", "error": str(e)}


if __name__ == "__main__":
    # Smoke test
    result = select_tips(
        question="What is the highest free meal count for K-12 schools in Alameda County?",
        evidence="Free Meal Count (K-12) refers to the number of K-12 students eligible for free meals.",
        logical_plan="1. Filter for Alameda County\n2. Find maximum free meal count",
        db_schema="Table frpm(CDSCode TEXT, County Name TEXT, Free Meal Count (K-12) REAL)"
    )
    print("Selected IDs:", result["selected_ids"])
    print("Error:", result["error"])
    assert result["error"] is None
    assert "TIP009" in result["selected_ids"]
    assert "TIP019" in result["selected_ids"]
    assert "TIP035" in result["selected_ids"]
    assert "TIP038" in result["selected_ids"]
    assert len(result["formatted_tips"]) > 0
    print("smoke test OK")
