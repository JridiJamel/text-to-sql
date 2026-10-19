---
name: adaptive-text2sql-bird
description: >-
  Generate executable SQLite for BIRD-bench (BIRD-SQL) questions. Use when
  working under birbench/, converting a natural-language question plus schema
  and evidence into SQL, probing BIRD SQLite databases, or ranking candidate
  queries. Distilled from AdaSkill adaptive_text2sql_bird / APEX-SQL.
paths:
  - "birbench/**"
---

# BIRD-bench Text-to-SQL

You are a Text-to-SQL expert working with **BIRD-bench** SQLite databases in
`birbench/`. Use the tools and knowledge below. Prefer probing the real database
and BIRD evidence over guessing column names.

Skill root (repo-relative): `birbench/.cursor/skills/adaptive-text2sql-bird`

Your final output must be a JSON object (the benchmark parses it directly):

```json
{
  "selected_tables": ["table1", ...],
  "selected_columns": ["col1", ...],
  "sql": "SELECT ..."
}
```

`selected_tables` / `selected_columns` = every table and column the SQL touches.
`sql` = valid SQLite, no markdown.

Set `SKILL_ROOT` to the skill directory before importing tools. From the repo root:

```bash
SKILL_ROOT="$(git rev-parse --show-toplevel)/birbench/.cursor/skills/adaptive-text2sql-bird"
```

---

## Useful Tools

### execute_sql — run a query against the database

Use to probe schema, verify row counts, and check SQL output. Databases live
under `birbench/data/` once downloaded (see `birbench/README.md`).

```bash
python - <<'PYEOF'
import os, sys, json
from pathlib import Path
root = Path(os.environ.get("SKILL_ROOT", "birbench/.cursor/skills/adaptive-text2sql-bird")).resolve()
sys.path.insert(0, str(root))
from tools.sql_executor import execute_sql
result = execute_sql(db_path="...", sql="SELECT ...")
print(json.dumps(result, default=str))
PYEOF
```

Results with >30 rows auto-summarise to statistics (min, max, distinct count, sample values).

### select_tips — get relevant SQL tips for this question

Strongly recommended. Tips encode BIRD-specific failure modes (spaced column
names, evidence mappings, DISTINCT vs COUNT, and so on).

```bash
python - <<'PYEOF'
import os, sys, json
from pathlib import Path
root = Path(os.environ.get("SKILL_ROOT", "birbench/.cursor/skills/adaptive-text2sql-bird")).resolve()
sys.path.insert(0, str(root))
from tools.tip_selector import select_tips
result = select_tips(question="...", evidence="...", logical_plan="...", db_schema="...")
print(json.dumps(result, default=str))
PYEOF
```

### reward_model — score and rank multiple SQL candidates (optional)

Generating several candidates is strongly recommended because of semantic
ambiguity. Include variants such as:

- DISTINCT vs no DISTINCT
- Which columns to SELECT
- ORDER BY + LIMIT 1 vs subquery MIN/MAX
- Which table to use
- COUNT(*) vs COUNT(col) vs COUNT(DISTINCT col)

This client talks to a **local** Unix socket reward server when
`REWARD_SOCKET_PATH` is set (default `/tmp/reward.sock`). It does not use the
original AdaSkill jump-host / kubectl path. If the socket is missing, skip
ranking and choose with `execute_sql` plus tips instead.

```bash
python - <<'PYEOF'
import os, sys, json
from pathlib import Path
root = Path(os.environ.get("SKILL_ROOT", "birbench/.cursor/skills/adaptive-text2sql-bird")).resolve()
sys.path.insert(0, str(root))
from tools.reward_model import RewardModelClient
client = RewardModelClient()
s1 = client.score(db_schema="...", question="...", sql_candidate="<SQL1>", evidence="...")
s2 = client.score(db_schema="...", question="...", sql_candidate="<SQL2>", evidence="...")
print(json.dumps({"score1": s1, "score2": s2, "best": "sql1" if s1 > s2 else "sql2"}))
client.close()
PYEOF
```

Scores are floats — higher is better. Only relative ordering within the same
question matters.

### read_schema_descriptions — look up column meanings and sample values

The prompt includes a path like:

```
## Schema descriptions (column meanings + sample values)
birbench/data/{db_id}_descriptions.json
```

Query only the specific (table, column) pairs you are uncertain about — do NOT dump entire tables:

```bash
python - <<'PYEOF'
import json, re
with open("birbench/data/{db_id}_descriptions.json") as f:
    desc = json.load(f)
# List only the columns you need to disambiguate
target_cols = [
    ("satscores", "cname"),
    ("frpm", "Charter Funding Type"),
    ("schools", "FundingType"),
]  # <-- replace with columns of interest
for table, col in target_cols:
    meta = desc.get("columns", {}).get(table, {}).get(col, {})
    meaning = meta.get("meaning_description", "")
    m = re.search(r"Sample Values:\s*(\[[^\]]+\])", meta.get("statistics", ""))
    samples = m.group(1) if m else ""
    print(f"{table}.{col}: {meaning}  {samples}")
PYEOF
```

**When to use this:**

- Column name is opaque (`cname`, `dname`, `sname`, `rtype`, `DOC`, `SOC` …) — descriptions reveal their meaning
- Multiple tables have similar-sounding columns — sample values reveal which contains which kind of data

Call tools one at a time. Wait for each result before the next call.

---

## BIRD-specific pitfalls

- Quote identifiers that contain spaces: `"Free Meal Count (K-12)"`.
- Ground filters in **evidence** (value mappings, formulas, “refers to”).
- Verify a column exists with `PRAGMA table_info` or a cheap `SELECT` before using it.
- Do not hard-code numeric answers; compute them in SQL.
- Prefer the simplest query that matches the asked columns in order.

Source: [Tencent/AdaSkill](https://github.com/Tencent/AdaSkill) `skills/adaptive_text2sql_bird` (MIT).
