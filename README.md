# Work Intensity

## 运行方法（仅可用于 macOS）

```bash
pip3 install rumps pynput chinese-calendar pyobjc-framework-Quartz pyobjc-framework-ApplicationServices pyobjc-framework-Cocoa

python3 main.py
```

## 图表解释

![](imgs/example.png)

上半部分用热力图展示 24 周滚动窗口内每天的「工作时长」（单位：小时），下半部分展示 12 周滚动窗口内的每日工作时长与 Codex token 用量趋势曲线。

将鼠标悬停在单日热力图格子或趋势图日期上时，会显示当天每小时活跃度、每小时 token 用量，以及当天各项目 token 用量占比。

## 每日工作时间计算方式

「每日工作时间」是基于输入事件（鼠标/键盘）与会议检测日志，对「活跃时长」的估算：

* 将一天按小时划分为 24 个统计周期（每小时一个）
* 每个小时再切成 100 个小时间块（每块 36 秒）
* 只要某个 36 秒时间块内出现过一次鼠标/键盘事件（或会议检测事件），就认为该时间块“活跃”
* 该小时的活跃时长 = 活跃块数 / 100（单位：小时）
* 当天工作时间（小时）= 24 个小时的活跃时长求和

## 每日 token 用量计算方式

程序只读取本地 Codex JSONL 会话文件，不拉取远程数据。扫描范围为：

* `~/.codex/sessions`
* `~/.codex/archived_sessions`

对每个 JSONL 文件，程序读取 `event_msg.payload.type == "token_count"` 事件里的 `info.total_token_usage.total_tokens`，按累计值的正向增量计算实际用量，并按本地日期与小时聚合。项目维度来自 Codex 会话里的 `session_meta.payload.cwd`，显示时使用路径 basename。

如果 token 事件同时包含足够的 `last_token_usage` / `total_token_usage` 细项，程序会为该事件生成不依赖 timestamp 的内容指纹。这样 Codex fork 或 subagent replay 复制历史 `token_count` 事件时，重复历史用量会被折叠，只保留 fork 后新增的 token。

## 数据存储与 iCloud 备份

程序使用 SQLite 存储活动数据，本地数据库文件位于 `log/work_intensity.sqlite3`。

* 如果开启了 iCloud Drive，会自动备份到 `~/Library/Mobile Documents/com~apple~CloudDocs/WorkIntensity/work_intensity.sqlite3`
* 当本地数据库缺失且 iCloud 备份存在时，程序会自动从 iCloud 恢复

token 小时聚合结果和按天/项目聚合结果会缓存在同一个 SQLite 数据库中，并通过本地 JSONL 文件清单指纹判断是否需要重建缓存。

## Codex 套餐余量

菜单栏通过官方 `codex app-server` 的 `account/rateLimits/read` 接口读取 Codex 主额度桶，显示剩余额度百分比、距离重置的时间和按 7 天窗口计算的剩余时间百分比，例如 `82% · 2d20h(40%)`。额度与工时、token 用量共用同一个 10 分钟刷新周期；查询失败时显示 `--% · --`。

该功能要求本机已安装 `codex` 命令，并已使用 ChatGPT 账号登录 Codex。套餐余量读取不改变每日 token 用量的本地统计方式。

## 开发验证

```bash
python3 -m unittest
python3 -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['main.py','record.py','storage.py','plot.py','token_usage.py','codex_quota.py']]"
```

更多数据流与表结构见 [`docs/architecture.md`](docs/architecture.md)。
