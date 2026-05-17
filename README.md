# Work Intensity

## 运行方法（仅可用于 macOS）

```bash
pip3 install rumps pynput chinese-calendar pyobjc-framework-Quartz pyobjc-framework-ApplicationServices pyobjc-framework-Cocoa

python3 main.py
```

## 图表解释

![](imgs/example.png)

上半部分用热力图展示 24 周滚动窗口内每天的「工作时长」（单位：小时），下半部分展示 12 周滚动窗口内的每日工作时长与 Codex token 用量趋势曲线。

将鼠标悬停在单日热力图格子上时，会显示当天每小时活跃度与每小时 token 用量的合并趋势。

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

对每个 JSONL 文件，程序读取 `event_msg.payload.type == "token_count"` 事件里的 `info.total_token_usage.total_tokens`，按累计值的正向增量计算实际用量，并按本地日期与小时聚合。

## 数据存储与 iCloud 备份

程序使用 SQLite 存储活动数据，本地数据库文件位于 `log/work_intensity.sqlite3`。

* 如果开启了 iCloud Drive，会自动备份到 `~/Library/Mobile Documents/com~apple~CloudDocs/WorkIntensity/work_intensity.sqlite3`
* 当本地数据库缺失且 iCloud 备份存在时，程序会自动从 iCloud 恢复

token 小时聚合结果会缓存在同一个 SQLite 数据库中，并通过本地 JSONL 文件清单指纹判断是否需要重建缓存。

## 开发验证

```bash
python3 -m unittest
python3 -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['main.py','record.py','storage.py','plot.py','token_usage.py']]"
```

更多数据流与表结构见 [`docs/architecture.md`](docs/architecture.md)。
