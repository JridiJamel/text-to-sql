# birbench (BIRD-bench)

Workspace for [BIRD-bench](https://bird-bench.github.io/) text-to-SQL: large-scale
SQLite databases, natural-language questions, evidence, and gold SQL.

Cursor loads the nested skill at
`.cursor/skills/adaptive-text2sql-bird/` whenever you work under this folder.

## Skill

`adaptive-text2sql-bird` is the BIRD skill from
[Tencent/AdaSkill](https://github.com/Tencent/AdaSkill)
(`skills/adaptive_text2sql_bird`, MIT), adapted for this repo:

- SQLite `execute_sql` (read-only)
- Rule-based BIRD `select_tips`
- Optional local Unix-socket reward model
- Schema-description lookup pattern for `{db_id}_descriptions.json`

Invoke it while editing files here, or with `/adaptive-text2sql-bird`.

## Data (not in git)

Download BIRD from the official site and unpack into `data/`:

- https://bird-bench.github.io/
- Mini-Dev: https://github.com/bird-bench/mini_dev

Typical layout:

```text
birbench/data/
  dev_databases/<db_id>/<db_id>.sqlite
  <db_id>_descriptions.json
  mini_dev_sqlite.json   # or equivalent question file
```
