"""
SQL executor tool for APEX-SQL skill.

Executes a SQL query against a SQLite database and returns results.
For large result sets (>30 rows), returns statistical summaries instead of raw data.
"""

import sqlite3
import json
import re
from typing import Optional


def execute_sql(db_path: str, sql: str, max_rows: int = 30, timeout: int = 30) -> dict:
    """
    Execute a SQL query against a SQLite database.

    Args:
        db_path:  Path to the SQLite database file.
        sql:      SQL query to execute (SELECT only).
        max_rows: If result has more rows than this, return statistics instead of full data.
        timeout:  Query timeout in seconds.

    Returns:
        dict with keys:
          - columns:     list of column names
          - rows:        list of rows (each row is a list), or None if summarised
          - row_count:   total number of rows returned
          - summary:     statistical summary (if row_count > max_rows), else None
          - error:       error message string, or None on success
    """
    try:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=timeout)
        conn.execute(f"PRAGMA busy_timeout = {timeout * 1000}")
        cursor = conn.cursor()
    except Exception as e:
        return {"columns": [], "rows": None, "row_count": 0, "summary": None,
                "error": f"Cannot open database: {e}"}

    try:
        cursor.execute(sql)
        column_info = cursor.description
        if column_info is None:
            return {"columns": [], "rows": [], "row_count": 0, "summary": None, "error": None}

        columns = [desc[0] for desc in column_info]
        all_rows = cursor.fetchall()
        row_count = len(all_rows)

        if row_count <= max_rows:
            # Return full data
            rows = [list(r) for r in all_rows]
            return {"columns": columns, "rows": rows, "row_count": row_count,
                    "summary": None, "error": None}
        else:
            # Compute statistical summary per column
            summary = _compute_summary(columns, all_rows, max_rows)
            return {"columns": columns, "rows": None, "row_count": row_count,
                    "summary": summary, "error": None}

    except Exception as e:
        return {"columns": [], "rows": None, "row_count": 0, "summary": None,
                "error": str(e)}
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass


def _compute_summary(columns: list, all_rows: list, preview_rows: int = 10) -> dict:
    """
    Compute per-column statistics for large result sets.

    Returns dict mapping column_name -> stats dict with keys:
      total_rows, null_count, min_val, max_val, distinct_count,
      sample_values (up to 10), data_format (string analysis when applicable)
    """
    # Transpose to column-oriented structure
    col_data = {col: [] for col in columns}
    for row in all_rows:
        for col, val in zip(columns, row):
            col_data[col].append(val)

    summary = {}
    for col in columns:
        vals = col_data[col]
        total = len(vals)
        null_count = sum(1 for v in vals if v is None)
        non_null = [v for v in vals if v is not None]

        if not non_null:
            summary[col] = {
                "total_rows": total,
                "null_count": null_count,
                "min_val": None,
                "max_val": None,
                "distinct_count": 0,
                "sample_values": [],
                "data_format": "all NULL"
            }
            continue

        # min/max (works for numbers and strings)
        try:
            min_val = min(non_null)
            max_val = max(non_null)
        except TypeError:
            min_val = str(min(str(v) for v in non_null))
            max_val = str(max(str(v) for v in non_null))

        # distinct
        try:
            distinct_vals = list({str(v): v for v in non_null}.values())
        except Exception:
            distinct_vals = list(set(non_null))
        distinct_count = len(distinct_vals)

        # sample up to 10 distinct values
        sample = [str(v) for v in distinct_vals[:10]]
        if distinct_count > 10:
            sample.append("...")

        # string length analysis (for string-type columns)
        data_format = None
        if non_null and isinstance(non_null[0], str):
            lengths = [len(str(v)) for v in non_null]
            min_len, max_len = min(lengths), max(lengths)
            if min_len == max_len:
                data_format = f"fixed length {min_len} chars"
            elif max_len - min_len <= 20:
                data_format = f"length {min_len}–{max_len} chars"
            # Check for common patterns
            sample_strs = [str(v) for v in non_null[:50]]
            if all(re.match(r'^\d{4}-\d{2}-\d{2}', s) for s in sample_strs):
                data_format = "date format YYYY-MM-DD"
            elif all(re.match(r'^\d+$', s) for s in sample_strs):
                data_format = "numeric strings"

        summary[col] = {
            "total_rows": total,
            "null_count": null_count,
            "min_val": str(min_val)[:80],
            "max_val": str(max_val)[:80],
            "distinct_count": distinct_count,
            "sample_values": sample,
            "data_format": data_format
        }

    return summary


def format_result_for_display(result: dict) -> str:
    """
    Format the execute_sql result into a human-readable string for use in prompts.
    """
    if result.get("error"):
        return f"Error: {result['error']}"

    columns = result.get("columns", [])
    row_count = result.get("row_count", 0)
    rows = result.get("rows")
    summary = result.get("summary")

    if rows is not None:
        # Full data display
        lines = [", ".join(str(c) for c in columns)]
        for row in rows:
            lines.append(", ".join(str(v) for v in row))
        return f"Rows: {row_count}\n" + "\n".join(lines)
    elif summary is not None:
        # Statistical summary display
        lines = [f"Rows: {row_count} (large result — showing statistics)"]
        for col, stats in summary.items():
            null_info = f", {stats['null_count']} NULL" if stats["null_count"] > 0 else ""
            distinct = stats["distinct_count"]
            samples = ", ".join(stats["sample_values"][:5])
            fmt = f" [{stats['data_format']}]" if stats.get("data_format") else ""
            lines.append(
                f"  {col}: min={stats['min_val']}, max={stats['max_val']}, "
                f"distinct={distinct} ({samples}){null_info}{fmt}"
            )
        return "\n".join(lines)
    else:
        return f"Rows: {row_count} (no data)"


if __name__ == "__main__":
    # Smoke test with in-memory database
    import tempfile, os

    # Create a small test database
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute("CREATE TABLE students (id INTEGER, name TEXT, score REAL, grade TEXT)")
    conn.executemany(
        "INSERT INTO students VALUES (?, ?, ?, ?)",
        [(i, f"Student{i}", 50.0 + i * 0.5, "A" if i % 2 == 0 else "B") for i in range(50)]
    )
    conn.commit()
    conn.close()

    # Test small result
    r1 = execute_sql(tmp.name, "SELECT DISTINCT grade FROM students;")
    print("Small result:", json.dumps(r1, default=str))

    # Test large result
    r2 = execute_sql(tmp.name, "SELECT * FROM students;")
    print("Large result (summary):", json.dumps(r2, default=str)[:500])

    # Test error
    r3 = execute_sql(tmp.name, "SELECT nonexistent_col FROM students;")
    print("Error result:", json.dumps(r3, default=str))

    os.unlink(tmp.name)
    print("smoke test OK")
