# Math Test Dashboard

本地数学错题工作台，用于查看错题记录、执行机械式回滚复习、维护复盘历史和展示单元掌握情况。

> [!NOTE]
> 自 v0.3.0 起，OCR 批次功能已弃用并从项目中移除。当前版本聚焦于错题记录可视化、机械式回滚复习与复盘历史管理。

这个仓库只保存 app 代码。个人错题记录、复盘状态放在本地其他目录。

## 功能

- 错题 Dashboard：按题册查看总记录、ABC 分布、掌握度趋势和目标分层。
- 回滚复习：完整显示当日到期题，新错题优先，机械到期题按原始记录时间从新到旧排列。
- 遗留队列：可将单题或当日剩余题目压入持久遗留栈，最近加入的题优先处理。
- 动态缓冲：做对后的未来复盘按每日容量释放，最多等待 7 天；强制释放时显示“饿死”标签。
- 毕业维护：完成最后一次常规复习后进入毕业题库，每 60 天进行一次低频维护。
- 复盘记录：支持给每次复盘写 comment，并在点错时修改历史记录。
- 活跃图：以 Git 风格热力图展示近期复盘活跃度。

### 公开展示副本

提供独立的复盘进度展示页面，与操作端分离。副本支持定时更新和手动刷新，并显示上次更新时间；仅用于查看，不支持修改复盘记录。

## 本地目录约定

推荐结构：

```text
math-test_2/
  app/                   # 本仓库，只放 app 代码
  records/               # 你的本地/私有错题记录仓库，不提交到仓库
```

app 默认从 `../records` 读取记录文件。也可以在 `.env` 中修改：

```dotenv
MATH_RECORDS_DIR=/absolute/path/to/your/math-records
```

## 环境配置

项目使用 `pixi` 管理 Python 环境。

```bash
pixi install
cp .env.example .env
```


```dotenv
MATH_RECORDS_DIR=../records
```


## 启动

```bash
pixi run dev
```

打开：

```text
http://127.0.0.1:8000
```

## 记录文件

记录目录中目前预期包含类似文件：

- `math_records.json`
- `660-record.json`
- `800-record.json`
- `workbook_660_error_abc.md`
- `review_state.json`
- `review_schedule.json`

这些文件不属于本 app 仓库。

### `math_records.json`

总索引文件，负责告诉 app 当前 active 题册、每本题册对应的独立 record 文件，以及题册的状态信息。最小格式：

```json
{
  "version": "2.0",
  "active_workbook": "workbook_660",
  "record_files": {
    "workbook_660": "660-record.json",
    "workbook_800": "800-record.json"
  },
  "units": {
    "workbook_660": {
      "status": "active",
      "recorded_range": "660-1..660-18",
      "current_target_score_tier": 110
    },
    "workbook_800": {
      "status": "archived",
      "recorded_range": "800-1..800-127"
    }
  }
}
```

### `*-record.json`

每本题册一个独立记录文件。app 主要读取 `history`。错题回滚只会纳入 `error_level` 为 `A`、`B`、`C` 的题目；`error_level: null` 视为正确题，不进入回滚队列。

```json
{
  "book_id": "workbook_660",
  "status": "active",
  "recorded_range": "660-1..660-18",
  "history": [
    {
      "question_id": "660-1",
      "mastery": 0.94,
      "performance_level": "优秀",
      "unit": "unit_1",
      "target_score_tier": 90,
      "required_for_scores": [90, 110, 135],
      "error_level": null,
      "error_tags": [],
      "weakness_focus": [],
      "student_answer_summary": ""
    },
    {
      "question_id": "660-2",
      "mastery": 0.49,
      "performance_level": "不佳",
      "unit": "unit_1",
      "target_score_tier": 90,
      "required_for_scores": [90, 110, 135],
      "error_level": "A",
      "error_tags": ["calculation"],
      "weakness_focus": ["limit"],
      "student_answer_summary": "示例错因摘要"
    }
  ]
}
```

字段约定：

- `question_id`：题号，建议使用 `660-2`、`800-18` 这种稳定格式。
- `mastery`：0 到 1 的掌握度，用于 Dashboard 显示。
- `performance_level`：中文表现标签，例如 `优秀`、`合格`、`不佳`。
- `unit`：单元 ID，例如 `unit_1`。
- `target_score_tier`：题目所属最低目标分层，目前支持 `90`、`110`、`135`。
- `required_for_scores`：这道题服务的目标分层列表。
- `error_level`：`A`、`B`、`C` 或 `null`。
- `error_tags` / `weakness_focus`：可选数组，用于错因和薄弱点统计。
- `student_answer_summary`：可选摘要，会显示在错题卡片和回滚卡片中。

### `workbook_*_error_abc.md`

ABC 错题索引，用于错题页按单元和等级展示。app 会读取二级标题作为单元，三级标题中的 `A/B/C` 作为等级，并从正文中提取题号。

```markdown
# 题册660错题分级索引

## 第一单元

### A 级

- 660-2
- 660-5

### B 级

- 660-3

### C 级

- 660-6
```

### `review_state.json`

复盘状态文件由 app 自动生成和更新，保存每日上限、已选目标分层、每道题的复盘历史、下一次到期日和 comment。这个文件属于个人学习记录，默认不提交到 app 仓库。

```json
{
  "version": "1.0",
  "settings": {
    "daily_limit": 10,
    "selected_tiers": [90, 110, 135],
    "active_workbook": "workbook_660",
    "first_pass_interval": 5,
    "release_buffer_max_wait": 7,
    "maintenance_interval": 60,
    "intervals": {
      "A": [1, 3, 10, 21],
      "B": [1, 2, 5, 12, 24],
      "C": [1, 3, 7, 14]
    }
  },
  "items": {
    "660-2": {
      "history": [
        {
          "reviewed_at": "2026-05-08T14:30:00",
          "outcome": "wrong",
          "error_level": "B",
          "note": "示例复盘 comment",
          "next_due_at": "2026-05-09"
        }
      ],
      "interval_index": 0,
      "status": "active",
      "error_level": "B",
      "last_reviewed_at": "2026-05-08",
      "next_due_at": "2026-05-09"
    }
  }
}
```

`status` 为 `active` 时按 A/B/C 机械间隔回滚；完成最后一次常规复习后变为 `graduated`，并进入 60 天低频维护。维护时做错会恢复为 `active`。

### `review_schedule.json`

复盘计划只保存 `book_id:question_id` 复合键，不重复保存题目内容：

```json
{
  "version": "1.1",
  "timezone": "Asia/Shanghai",
  "buckets": {
    "2026-08-04": [
      "workbook_660:660-30"
    ]
  },
  "release_buffer": {
    "2026-08-10": [
      "workbook_880:880-basic-choice-P7-(9)"
    ]
  },
  "backlog": [
    "workbook_880:880-basic-solution-P20-(1)-(III)"
  ],
  "forced_releases": {
    "2026-08-17": [
      "workbook_660:660-125"
    ]
  },
  "daily_plans": {}
}
```

- `buckets`：固定日期进入日常队列的新错题、做错后次日题和当天已释放题。
- `release_buffer`：已达到机械间隔最早日期、等待每日容量释放的题。
- `backlog`：人工遗留栈，数组开头是最近加入的题；进入后暂停机械回滚。
- `forced_releases`：缓冲超过 7 天后被强制释放的题，页面显示“饿死”。
- `daily_plans`：每日应复盘快照，完成或移入遗留后仍保留当天原始总数。

也可以用浏览器访问 `/api/dashboard`、`/api/review/today` 验证数据读取是否正常。
