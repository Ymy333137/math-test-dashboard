# Math Test Dashboard

本地数学错题工作台，用于查看错题记录、执行机械式回滚复习、维护复盘历史，并通过多模态 OCR 生成题目 Markdown。

这个仓库只保存 app 代码。个人错题记录、复盘状态和 API key 都应该放在本地或单独的私有记录仓库中。

## 功能

- 错题 Dashboard：按题册查看总记录、ABC 分布、掌握度趋势和目标分层。
- 回滚复习：按 A/B/C 等级和目标分层生成每日复习队列。
- 复盘记录：支持给每次复盘写 comment，并在点错时修改历史记录。
- 活跃图：以 Git 风格热力图展示近期复盘活跃度。
- OCR 批次：调用 OpenAI-compatible 多模态接口，把题目图片识别为 Markdown。

## 本地目录约定

推荐结构：

```text
math-test_2/
  app/                   # 本仓库，只放 app 代码
  records/               # 你的本地/私有错题记录仓库，不提交到本仓库
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

然后在 `.env` 中填写本地配置：

```dotenv
MIMO_API_KEY=your_api_key_here
MIMO_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
MIMO_MODEL=mimo-v2.5
MATH_RECORDS_DIR=../records
```

不要提交真实 `.env`。

## 启动

```bash
pixi run uvicorn app:app --host 127.0.0.1 --port 8000
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

这些文件不属于本 app 仓库。`.gitignore` 已经拦截常见记录文件名，防止误提交。

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
      "error_level": "B",
      "last_reviewed_at": "2026-05-08",
      "next_due_at": "2026-05-09"
    }
  }
}
```

## 安全说明

- 真实 API key 只放在 `.env` 或系统环境变量中。
- 个人错题记录只放在 `MATH_RECORDS_DIR` 指向的目录中。
- OCR 输出默认写入本地 `ocr_output/`，该目录不会提交。
- 如果曾经把 key 发到聊天或公开位置，建议到对应平台轮换 key。

## 开发验证

```bash
pixi run python -m py_compile app.py
```

也可以用浏览器访问 `/api/dashboard`、`/api/review/today` 验证数据读取是否正常。
