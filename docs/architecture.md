# Work Intensity Architecture

WorkIntensity is a macOS status bar app that estimates local activity time and visualizes it with local Codex token usage. It also reads Codex plan limits through the local Codex app-server process.

## Runtime Flow

1. `main.py` checks macOS Accessibility and Input Monitoring permissions, then starts a `rumps` status bar app.
2. `record.py` listens for mouse, keyboard, and meeting-detection activity.
3. `storage.py` writes activity into SQLite as deduplicated 36-second blocks.
4. `token_usage.py` scans local Codex JSONL files and aggregates token usage by local day/hour and local day/project.
5. `codex_quota.py` asks `codex app-server` for the current Codex rate-limit bucket.
6. `plot.py` reads the cached activity/token data and renders `log/work_intensity.html` from `plot_template.html`.

## Data Model

The local database lives at `log/work_intensity.sqlite3`.

`activity_blocks`

| Column | Meaning |
| --- | --- |
| `day` | Local date in `YYYY-MM-DD` format |
| `block_index` | 36-second block index within that day |

`token_usage_hourly`

| Column | Meaning |
| --- | --- |
| `day` | Local date in `YYYY-MM-DD` format |
| `hour` | Local hour, `0` through `23` |
| `total_tokens` | Aggregated Codex token count for that hour |

`token_usage_project_daily`

| Column | Meaning |
| --- | --- |
| `day` | Local date in `YYYY-MM-DD` format |
| `project` | Project name derived from the Codex session `cwd` basename |
| `total_tokens` | Aggregated Codex token count for that project on that day |

`token_usage_cache_meta`

| Column | Meaning |
| --- | --- |
| `key` | Cache metadata key |
| `value` | Cache metadata value |

The token cache stores a fingerprint of the local JSONL file list: path, size, and `mtime_ns`. If that fingerprint changes, the hourly and daily-project token caches are rebuilt.

## Token Usage Source

Token usage is local-only. The scanner recursively reads:

- `~/.codex/sessions`
- `~/.codex/archived_sessions`

For each JSONL file, token events are `event_msg` entries whose payload has `type == "token_count"`. The displayed metric uses `payload.info.total_token_usage.total_tokens`.

Within each file, the value is cumulative. The aggregator counts the first total, then only positive deltas between consecutive totals. Duplicate totals are ignored. If the total drops, the new total starts a new sequence.

Project attribution comes from `session_meta.payload.cwd` when present, falling back to `turn_context.payload.cwd` or `unknown`.

## Codex Plan Limit Source

Every status-title refresh starts `codex app-server`, completes its JSONL initialization handshake, and calls `account/rateLimits/read`. The app prefers the `codex` entry in `rateLimitsByLimitId` and falls back to the legacy `rateLimits` field. The menu bar displays `100 - usedPercent`, the `resetsAt` countdown, and the countdown's remaining share of a seven-day window as `<percent>% · <days>d<hours>h(<time-percent>%)`.

This remote plan-limit lookup is separate from token aggregation. No Codex auth token is read or stored by WorkIntensity.

## Visualization

The generated HTML has two main charts:

- A 24-week heatmap of daily work hours. Hovering a day shows a combined hourly chart with activity percentage and token usage, plus a pie chart for that day's token share by project.
- A 12-week daily trend chart with work hours on the left axis and token usage on the right axis. Hovering a day also shows that day's project token share.

The HTML uses ECharts from jsDelivr, so chart rendering needs network access unless ECharts is vendored locally.

## Backup

If iCloud Drive is available, `storage.py` backs up the SQLite database to:

```text
~/Library/Mobile Documents/com~apple~CloudDocs/WorkIntensity/work_intensity.sqlite3
```

When the local database is missing and the iCloud backup exists, the app restores from the backup before opening the database.
