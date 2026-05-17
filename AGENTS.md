# WorkIntensity Agent Notes

## Project Shape

- macOS-only Python status bar app.
- Entry point: `main.py`.
- Activity recording: `record.py`.
- SQLite/iCloud cache layer: `storage.py`.
- Local Codex token aggregation: `token_usage.py`.
- Chart data/rendering: `plot.py` + `plot_template.html`.

## Local Commands

Use the local venv for verification:

```bash
/Users/bytedance/Downloads/.venv/bin/python3 -m unittest
/Users/bytedance/Downloads/.venv/bin/python3 -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['main.py','record.py','storage.py','plot.py','token_usage.py']]"
```

## Boundaries

- Do not fetch remote token data. Token usage comes only from local `~/.codex/sessions` and `~/.codex/archived_sessions`.
- Keep `token_usage.py` free of UI and SQLite concerns; it should only scan JSONL files and aggregate totals.
- Keep SQLite cache schema and iCloud backup behavior in `storage.py`.
- Avoid changing existing `log/` contents or user activity data during tests; tests should use temporary directories/databases.
- `.DS_Store`, `log/`, and `__pycache__/` should stay ignored.
