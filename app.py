import json
import os
import re
import subprocess
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

DEFAULT_RECORDS_DIR = (BASE_DIR / "../records").resolve()
RECORDS_DIR = Path(os.getenv("MATH_RECORDS_DIR", str(DEFAULT_RECORDS_DIR))).expanduser()
if not RECORDS_DIR.is_absolute():
    RECORDS_DIR = (BASE_DIR / RECORDS_DIR).resolve()

RECORDS_REPO_URL = os.getenv("MATH_RECORDS_REPO_URL", "")
AUTO_SYNC_RECORDS = os.getenv("AUTO_SYNC_RECORDS", "1").lower() not in {"0", "false", "no", "off"}
INDEX_FILE = RECORDS_DIR / "math_records.json"
REVIEW_STATE_FILE = RECORDS_DIR / "review_state.json"
REVIEW_SCHEDULE_FILE = RECORDS_DIR / "review_schedule.json"

app = FastAPI(title="数学错题工作台", version="0.3.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

BOOK_LABELS = {
    "workbook_660": "题册660",
    "workbook_800": "题册800",
    "workbook_880": "题册880",
}

TierValue = int | str

DEFAULT_TIER_OPTIONS_BY_BOOK: dict[str, list[TierValue]] = {
    "workbook_660": [90, 110, 135],
    "workbook_880": ["120以下", "120+"],
}

REVIEWABLE_BOOK_STATUSES = {"active", "review_only"}

DEFAULT_REVIEW_SETTINGS = {
    "daily_limit": 10,
    "selected_tiers": [90, 110, 135, "120以下", "120+"],
    "active_workbook": "workbook_660",
    "tier_schema_version": 2,
    "first_pass_interval": 5,
    "intervals": {
        "A": [1, 3, 10, 21],
        "B": [1, 2, 5, 12, 24],
        "C": [1, 3, 7, 14],
    },
}

CHINESE_UNIT_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


class ReviewSettingsRequest(BaseModel):
    daily_limit: int = Field(default=10, ge=1, le=200)
    selected_tiers: list[TierValue] = Field(default_factory=lambda: DEFAULT_REVIEW_SETTINGS["selected_tiers"].copy())


class ReviewFeedbackRequest(BaseModel):
    book_id: str
    question_id: str
    outcome: str = Field(..., pattern="^(pass|wrong)$")
    error_level: str | None = Field(default=None, pattern="^[ABC]$")
    note: str | None = None


class ReviewEventUpdateRequest(BaseModel):
    book_id: str
    outcome: str = Field(..., pattern="^(pass|wrong)$")
    error_level: str | None = Field(default=None, pattern="^[ABC]$")
    note: str | None = None


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"{path.name} 不存在：{path}")
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    tmp_path.replace(path)


def load_index() -> dict[str, Any]:
    return read_json(INDEX_FILE)


def display_book_label(book_id: str) -> str:
    return BOOK_LABELS.get(book_id, book_id)


def get_record_file_map(index: dict[str, Any] | None = None) -> dict[str, str]:
    index = index or load_index()
    return index.get("record_files", {})


def load_book_record(book_id: str) -> dict[str, Any]:
    record_file = get_record_file_map().get(book_id)
    if not record_file:
        raise HTTPException(status_code=404, detail=f"没有找到 {book_id} 的 record 文件配置")
    return read_json(RECORDS_DIR / record_file)


def load_all_book_records(index: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    records = {}
    for book_id, record_file in get_record_file_map(index).items():
        path = RECORDS_DIR / record_file
        if path.exists():
            records[book_id] = read_json(path)
    return records


def score_tiers_for_book(book_id: str, index: dict[str, Any] | None = None) -> list[TierValue]:
    index = index or load_index()
    configured = index.get("units", {}).get(book_id, {}).get("score_tiers")
    if configured:
        return configured
    return DEFAULT_TIER_OPTIONS_BY_BOOK.get(book_id, [])


def reviewable_book_ids(index: dict[str, Any] | None = None) -> list[str]:
    index = index or load_index()
    units = index.get("units", {})
    active_book = index.get("active_workbook")
    book_ids = [
        book_id
        for book_id in index.get("record_files", {})
        if units.get(book_id, {}).get("status") in REVIEWABLE_BOOK_STATUSES
    ]
    return sorted(book_ids, key=lambda book_id: (book_id != active_book, book_id))


def load_reviewable_book_records(index: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    index = index or load_index()
    return {book_id: load_book_record(book_id) for book_id in reviewable_book_ids(index)}


def tier_groups(index: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    index = index or load_index()
    return [
        {
            "book_id": book_id,
            "label": display_book_label(book_id),
            "tiers": score_tiers_for_book(book_id, index),
        }
        for book_id in reviewable_book_ids(index)
    ]


def all_review_tiers(index: dict[str, Any] | None = None) -> list[TierValue]:
    return [tier for group in tier_groups(index) for tier in group["tiers"]]


def unit_label_to_id(label: str) -> str:
    match = re.search(r"第([一二三四五六七八九十]+)单元", label)
    if not match:
        return label
    text = match.group(1)
    if text == "十":
        number = 10
    elif text.startswith("十"):
        number = 10 + CHINESE_UNIT_NUMBERS.get(text[-1], 0)
    elif text.endswith("十"):
        number = CHINESE_UNIT_NUMBERS.get(text[0], 1) * 10
    elif "十" in text:
        left, right = text.split("十", 1)
        number = CHINESE_UNIT_NUMBERS.get(left, 1) * 10 + CHINESE_UNIT_NUMBERS.get(right, 0)
    else:
        number = CHINESE_UNIT_NUMBERS.get(text, 0)
    return f"unit_{number}" if number else label


def parse_abc_indexes() -> dict[str, dict[str, Any]]:
    indexes: dict[str, dict[str, Any]] = {}
    for path in RECORDS_DIR.glob("*error_abc.md"):
        book_match = re.search(r"workbook_(\d+)_error_abc", path.stem)
        book_id = f"workbook_{book_match.group(1)}" if book_match else path.stem.replace("_error_abc", "")
        book = indexes.setdefault(
            book_id,
            {"book_id": book_id, "label": display_book_label(book_id), "units": {}},
        )
        current_unit_id = "unknown"
        current_unit_label = "未分单元"
        current_level = None

        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("## "):
                current_unit_label = line.removeprefix("## ").strip()
                current_unit_id = unit_label_to_id(current_unit_label)
                book["units"].setdefault(
                    current_unit_id,
                    {"unit_id": current_unit_id, "label": current_unit_label, "levels": {"A": [], "B": [], "C": []}},
                )
            elif line.startswith("### "):
                level_match = re.search(r"([ABC])\s*级", line)
                current_level = level_match.group(1) if level_match else None
            elif current_level:
                question_ids = re.findall(r"\b\d+-\d+\b", line)
                if question_ids:
                    unit = book["units"].setdefault(
                        current_unit_id,
                        {"unit_id": current_unit_id, "label": current_unit_label, "levels": {"A": [], "B": [], "C": []}},
                    )
                    unit["levels"][current_level].extend(question_ids)
    return indexes


def records_by_question(book_record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {record.get("question_id"): record for record in book_record.get("history", []) if record.get("question_id")}


def enriched_history_records(book_record: dict[str, Any]) -> list[dict[str, Any]]:
    full_records = full_records_by_question(book_record)
    return [
        {**record, **full_records.get(record.get("question_id"), {})}
        for record in book_record.get("history", [])
    ]


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    error_counter: Counter[str] = Counter()
    level_counter: Counter[str] = Counter()
    tier_counter: Counter[str] = Counter()
    for record in records:
        if record.get("error_level"):
            level_counter.update([record["error_level"]])
        if record.get("target_score_tier"):
            tier_counter.update([str(record["target_score_tier"])])
        error_counter.update(record.get("error_tags", []))

    recent = records[-12:]
    return {
        "total": len(records),
        "average_mastery": round(sum(r.get("mastery", 0) for r in records) / len(records), 3) if records else 0,
        "recent": [
            {
                "question_id": item.get("question_id"),
                "mastery": item.get("mastery"),
                "performance_level": item.get("performance_level"),
                "difficulty_level": item.get("difficulty_level"),
                "target_score_tier": item.get("target_score_tier"),
                "error_level": item.get("error_level"),
            }
            for item in recent
        ],
        "error_tags": [{"name": name, "count": count} for name, count in error_counter.most_common(10)],
        "error_levels": {level: level_counter.get(level, 0) for level in ["A", "B", "C"]},
        "target_tiers": dict(tier_counter),
        "unit_accuracy": summarize_unit_accuracy(records),
    }


def unit_sort_key(unit_id: str) -> tuple[int, str]:
    match = re.search(r"(\d+)$", unit_id or "")
    return (int(match.group(1)) if match else 999, unit_id or "")


def summarize_unit_accuracy(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    units: dict[str, dict[str, Any]] = {}
    for record in records:
        unit_id = record.get("section") or record.get("unit") or "unknown"
        unit = units.setdefault(unit_id, {"unit_id": unit_id, "label": record.get("section"), "total": 0, "correct": 0})
        unit["total"] += 1
        if record.get("error_level") is None:
            unit["correct"] += 1

    results = []
    for unit in sorted(units.values(), key=lambda item: unit_sort_key(item["unit_id"])):
        total = unit["total"]
        correct = unit["correct"]
        unit_number = re.search(r"(\d+)$", unit["unit_id"] or "")
        label = f"第{unit_number.group(1)}单元" if unit_number else unit.get("label") or unit["unit_id"]
        results.append(
            {
                "unit_id": unit["unit_id"],
                "label": label,
                "total": total,
                "correct": correct,
                "accuracy": round(correct / total, 4) if total else 0,
            }
        )
    return results


def build_books(index: dict[str, Any], book_records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    books = []
    for book_id, book_record in book_records.items():
        unit_meta = index.get("units", {}).get(book_id, {})
        history = book_record.get("history", [])
        enriched_history = enriched_history_records(book_record)
        books.append(
            {
                "book_id": book_id,
                "label": display_book_label(book_id),
                "status": unit_meta.get("status") or book_record.get("status"),
                "total": len(history),
                "recorded_range": book_record.get("recorded_range") or unit_meta.get("recorded_range"),
                "current_target_score_tier": unit_meta.get("current_target_score_tier"),
                "score_tiers": score_tiers_for_book(book_id, index),
                "summary": summarize_records(enriched_history),
            }
        )
    return sorted(books, key=lambda item: (item["status"] != "active", item["label"]))


def build_coverage() -> list[dict[str, str]]:
    coverage = []
    for path in sorted(RECORDS_DIR.glob("unit_*_coverage.md")):
        text = path.read_text(encoding="utf-8")
        title_match = re.search(r"#\s*(.+)", text)
        conclusion_match = re.search(r"## 覆盖结论.*?\n(.+)", text, flags=re.S)
        conclusion = ""
        if conclusion_match:
            conclusion = conclusion_match.group(1).strip().splitlines()[0]
        coverage.append(
            {
                "unit_id": path.stem.replace("_coverage", ""),
                "title": title_match.group(1) if title_match else path.stem,
                "conclusion": conclusion,
            }
        )
    return coverage


def git_command(args: list[str], cwd: Path | None = None, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def records_dirty_files() -> list[str]:
    result = git_command(["status", "--porcelain"], cwd=RECORDS_DIR)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def sync_records_repo() -> dict[str, Any]:
    if not AUTO_SYNC_RECORDS:
        return {"status": "disabled", "message": "自动同步已关闭"}

    if not RECORDS_DIR.exists():
        if not RECORDS_REPO_URL:
            return {"status": "missing", "message": "records 目录不存在，且未配置 MATH_RECORDS_REPO_URL"}
        result = git_command(["clone", RECORDS_REPO_URL, str(RECORDS_DIR)], cwd=BASE_DIR.parent, timeout=60)
        if result.returncode != 0:
            return {"status": "error", "message": result.stderr.strip() or "clone records 失败"}
        return {"status": "cloned", "message": "已自动 clone records 仓库"}

    if not (RECORDS_DIR / ".git").exists():
        return {"status": "skipped", "message": "records 目录不是 Git 仓库，跳过自动同步"}

    dirty_files = records_dirty_files()
    if dirty_files:
        return {
            "status": "dirty",
            "message": "records 有未提交改动，跳过自动同步",
            "dirty_count": len(dirty_files),
        }

    fetch_result = git_command(["fetch", "--prune", "origin"], cwd=RECORDS_DIR, timeout=60)
    if fetch_result.returncode != 0:
        return {"status": "error", "message": fetch_result.stderr.strip() or "fetch records 失败"}

    count_result = git_command(["rev-list", "--left-right", "--count", "HEAD...@{u}"], cwd=RECORDS_DIR)
    if count_result.returncode != 0:
        return {"status": "skipped", "message": "records 未配置 upstream，跳过自动同步"}

    ahead_text, behind_text = count_result.stdout.strip().split()
    ahead = int(ahead_text)
    behind = int(behind_text)
    if behind == 0:
        return {"status": "up_to_date", "message": "records 已是最新", "ahead": ahead, "behind": behind}
    if ahead > 0:
        return {"status": "diverged", "message": "records 本地和远端都有新提交，请手动处理", "ahead": ahead, "behind": behind}

    pull_result = git_command(["pull", "--ff-only"], cwd=RECORDS_DIR, timeout=60)
    if pull_result.returncode != 0:
        return {"status": "error", "message": pull_result.stderr.strip() or "pull records 失败", "ahead": ahead, "behind": behind}
    return {"status": "pulled", "message": f"已自动同步 records：拉取 {behind} 个提交", "ahead": ahead, "behind": behind}


def build_dashboard_payload() -> dict[str, Any]:
    records_sync = sync_records_repo()
    index = load_index()
    book_records = load_all_book_records(index)
    abc_indexes = parse_abc_indexes()
    books = []

    for book in build_books(index, book_records):
        abc = abc_indexes.get(book["book_id"], {"units": {}})
        level_counts = {"A": 0, "B": 0, "C": 0}
        if book["book_id"] == "workbook_880":
            level_counts = book["summary"]["error_levels"]
        else:
            for unit in abc.get("units", {}).values():
                for level in level_counts:
                    level_counts[level] += len(unit["levels"].get(level, []))
        books.append({**book, "abc_counts": level_counts, "error_total": sum(level_counts.values())})

    all_records = [record for book in book_records.values() for record in enriched_history_records(book)]
    return {
        "version": index.get("version"),
        "records_dir": str(RECORDS_DIR),
        "records_sync": records_sync,
        "active_workbook": index.get("active_workbook"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "totals": {
            "records": len(all_records),
            "books": len(books),
            "units": len(index.get("units", {})),
        },
        "books": books,
        "overall": summarize_records(all_records),
        "coverage": build_coverage(),
    }


def build_book_errors(book_id: str) -> dict[str, Any]:
    if book_id == "workbook_880":
        return build_structured_book_errors(book_id)

    abc = parse_abc_indexes().get(book_id)
    if not abc:
        raise HTTPException(status_code=404, detail="没有找到该题册的 ABC 索引")

    book_record = load_book_record(book_id)
    full_records = records_by_question(book_record)
    units = []
    for unit in abc["units"].values():
        levels: dict[str, list[dict[str, Any]]] = {"A": [], "B": [], "C": []}
        for level, question_ids in unit["levels"].items():
            for question_id in question_ids:
                record = full_records.get(question_id, {})
                levels[level].append(
                    {
                        "book_id": book_id,
                        "question_id": question_id,
                        "display_id": record.get("display_id") or question_id,
                        "level": level,
                        "unit": record.get("unit") or unit["unit_id"],
                        "mastery": record.get("mastery"),
                        "performance_level": record.get("performance_level"),
                        "difficulty_level": record.get("difficulty_level"),
                        "target_score_tier": record.get("target_score_tier"),
                        "required_for_scores": record.get("required_for_scores", []),
                        "error_tags": record.get("error_tags", []),
                        "weakness_focus": record.get("weakness_focus", []),
                        "summary": record.get("student_answer_summary", ""),
                    }
                )
        units.append({"unit_id": unit["unit_id"], "label": unit["label"], "levels": levels})

    return {
        "book_id": book_id,
        "label": display_book_label(book_id),
        "structured": False,
        "filters": {"sections": [], "question_types": [], "pages": []},
        "units": units,
    }


def structured_error_item(book_id: str, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "book_id": book_id,
        "question_id": record.get("question_id"),
        "display_id": record.get("display_id") or record.get("question_id"),
        "display_label": record.get("display_label"),
        "level": record.get("error_level"),
        "unit": record.get("unit"),
        "section": record.get("section"),
        "question_type": record.get("question_type"),
        "page": record.get("page"),
        "record_order": record.get("record_order"),
        "card_structure": record.get("card_structure"),
        "parent_display_id": record.get("parent_display_id"),
        "subquestion": record.get("subquestion"),
        "mastery": record.get("mastery"),
        "performance_level": record.get("performance_level"),
        "difficulty_level": record.get("difficulty_level"),
        "target_score_tier": record.get("target_score_tier"),
        "required_for_scores": record.get("required_for_scores", []),
        "error_tags": record.get("error_tags", []),
        "weakness_focus": record.get("weakness_focus", []),
        "summary": record.get("student_answer_summary", ""),
    }


def build_structured_book_errors(book_id: str) -> dict[str, Any]:
    book_record = load_book_record(book_id)
    records = [record for record in enriched_history_records(book_record) if record.get("error_level") in {"A", "B", "C"}]
    sections = book_record.get("section_schema") or sorted({record.get("section") for record in records if record.get("section")})
    question_types = book_record.get("question_type_schema") or sorted(
        {record.get("question_type") for record in records if record.get("question_type")}
    )
    pages = sorted({record.get("page") for record in records if record.get("page") is not None})
    units = []
    for section in sections:
        levels: dict[str, list[dict[str, Any]]] = {"A": [], "B": [], "C": []}
        section_records = sorted(
            (record for record in records if record.get("section") == section),
            key=lambda record: (record.get("record_order") or 999999, record.get("question_id") or ""),
        )
        for record in section_records:
            levels[record["error_level"]].append(structured_error_item(book_id, record))
        if any(levels.values()):
            units.append({"unit_id": section, "label": section, "levels": levels})

    return {
        "book_id": book_id,
        "label": display_book_label(book_id),
        "structured": True,
        "filters": {"sections": sections, "question_types": question_types, "pages": pages},
        "units": units,
    }


def default_review_state() -> dict[str, Any]:
    return {
        "version": "1.0",
        "settings": DEFAULT_REVIEW_SETTINGS.copy(),
        "items": {},
    }


def load_review_state() -> dict[str, Any]:
    if not REVIEW_STATE_FILE.exists():
        return default_review_state()
    state = read_json(REVIEW_STATE_FILE)
    stored_settings = state.get("settings", {})
    settings = {**DEFAULT_REVIEW_SETTINGS, **stored_settings}
    settings["intervals"] = {**DEFAULT_REVIEW_SETTINGS["intervals"], **settings.get("intervals", {})}
    selected_tiers = normalize_tiers(settings.get("selected_tiers"))
    if int(stored_settings.get("tier_schema_version", 1)) < 2:
        for tier in DEFAULT_TIER_OPTIONS_BY_BOOK["workbook_880"]:
            if tier not in selected_tiers:
                selected_tiers.append(tier)
    settings["selected_tiers"] = selected_tiers
    settings["tier_schema_version"] = 2
    state["settings"] = settings
    state.setdefault("items", {})
    return state


def save_review_state(state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(REVIEW_STATE_FILE, state)


def default_review_schedule() -> dict[str, Any]:
    return {
        "version": "1.0",
        "timezone": "Asia/Shanghai",
        "policy": {
            "description": "按日期 bucket 持久化复盘计划；每天只读取当天题号索引，过期 bucket 直接删除，是否迁移由用户手动决定。",
            "key_format": "book_id:question_id",
        },
        "buckets": {},
        "daily_plans": {},
    }


def load_review_schedule() -> dict[str, Any]:
    if not REVIEW_SCHEDULE_FILE.exists():
        return default_review_schedule()
    schedule = read_json(REVIEW_SCHEDULE_FILE)
    schedule.setdefault("version", "1.0")
    schedule.setdefault("timezone", "Asia/Shanghai")
    schedule.setdefault("policy", default_review_schedule()["policy"])
    schedule.setdefault("buckets", {})
    schedule.setdefault("daily_plans", {})
    schedule["buckets"] = normalize_schedule_buckets(schedule["buckets"])
    schedule["daily_plans"] = normalize_schedule_buckets(schedule["daily_plans"])
    return schedule


def schedule_key_from_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        key = value.get("key")
        if key:
            return key
        book_id = value.get("book_id")
        question_id = value.get("question_id")
        if book_id and question_id:
            return schedule_key(book_id, question_id)
    return None


def normalize_schedule_buckets(buckets: dict[str, Any]) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    for due_at, values in buckets.items():
        keys = []
        for value in values or []:
            key = schedule_key_from_value(value)
            if key and key not in keys:
                keys.append(key)
        if keys:
            normalized[due_at] = keys
    return normalized


def save_review_schedule(schedule: dict[str, Any]) -> None:
    schedule["updated_at"] = datetime.now().isoformat(timespec="seconds")
    buckets = normalize_schedule_buckets(schedule.get("buckets", {}))
    schedule["buckets"] = {
        due_at: buckets[due_at]
        for due_at in sorted(buckets)
    }
    daily_plans = normalize_schedule_buckets(schedule.get("daily_plans", {}))
    schedule["daily_plans"] = {
        due_at: daily_plans[due_at]
        for due_at in sorted(daily_plans)
    }
    write_json(REVIEW_SCHEDULE_FILE, schedule)


def parse_question_number(question_id: str) -> int:
    match = re.search(r"-(\d+)$", question_id)
    return int(match.group(1)) if match else 0


def split_schedule_key(key: str) -> tuple[str, str]:
    if ":" not in key:
        return "", key
    return tuple(key.split(":", 1))


def record_sort_order(book_id: str, question_id: str, record: dict[str, Any] | None = None) -> int:
    if book_id == "workbook_880":
        return int((record or {}).get("record_order") or 0)
    return parse_question_number(question_id)


def sort_schedule_keys(keys: list[str]) -> list[str]:
    record_maps: dict[str, dict[str, dict[str, Any]]] = {}
    for key in keys:
        book_id, _ = split_schedule_key(key)
        if not book_id or book_id in record_maps:
            continue
        try:
            record_maps[book_id] = records_by_question(load_book_record(book_id))
        except HTTPException:
            record_maps[book_id] = {}

    return sorted(
        keys,
        key=lambda key: (
            split_schedule_key(key)[0],
            record_sort_order(
                split_schedule_key(key)[0],
                split_schedule_key(key)[1],
                record_maps.get(split_schedule_key(key)[0], {}).get(split_schedule_key(key)[1]),
            ),
            split_schedule_key(key)[1],
        ),
    )


def normalize_tiers(values: list[TierValue] | None, index: dict[str, Any] | None = None) -> list[TierValue]:
    available = all_review_tiers(index)
    if not values:
        return available
    normalized_values: list[TierValue] = []
    for value in values:
        if isinstance(value, str) and value.isdigit():
            normalized_values.append(int(value))
        else:
            normalized_values.append(value)
    return [tier for tier in available if tier in normalized_values]


def date_from_iso(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def schedule_key(book_id: str, question_id: str) -> str:
    return f"{book_id}:{question_id}"


def question_id_from_schedule_key(key: str) -> str:
    return split_schedule_key(key)[1]


def record_timestamp_date(record: dict[str, Any] | None) -> date | None:
    if not record:
        return None
    timestamp = record.get("timestamp")
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def full_records_by_question(book_record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {record.get("question_id"): record for record in book_record.get("records", []) if record.get("question_id")}


def build_record_catalog(book_records: dict[str, dict[str, Any]]) -> dict[str, tuple[str, dict[str, Any]]]:
    catalog: dict[str, tuple[str, dict[str, Any]]] = {}
    for book_id, book_record in book_records.items():
        for question_id, record in records_by_question(book_record).items():
            catalog[question_id] = (book_id, record)
    return catalog


def resolve_state_item_book_id(
    question_id: str,
    item: dict[str, Any],
    catalog: dict[str, tuple[str, dict[str, Any]]],
) -> str | None:
    return item.get("book_id") or (catalog.get(question_id) or (None, {}))[0]


def iter_scheduled_entries(schedule: dict[str, Any]):
    for due_at, keys in schedule.get("buckets", {}).items():
        for key in keys:
            yield due_at, key


def scheduled_keys(schedule: dict[str, Any]) -> set[str]:
    return {key for _, key in iter_scheduled_entries(schedule) if key}


def remove_schedule_key(schedule: dict[str, Any], key: str) -> bool:
    changed = False
    buckets = schedule.setdefault("buckets", {})
    for due_at in list(buckets.keys()):
        kept = [scheduled_key for scheduled_key in buckets.get(due_at, []) if scheduled_key != key]
        if len(kept) != len(buckets.get(due_at, [])):
            changed = True
        if kept:
            buckets[due_at] = kept
        else:
            buckets.pop(due_at, None)
    return changed


def add_schedule_key(schedule: dict[str, Any], due_at: date, key: str, replace: bool = True) -> bool:
    changed = False
    if replace and key:
        changed = remove_schedule_key(schedule, key)
    bucket = schedule.setdefault("buckets", {}).setdefault(due_at.isoformat(), [])
    if key in bucket:
        return changed
    bucket.append(key)
    bucket[:] = sort_schedule_keys(bucket)
    return True


def add_daily_plan_keys(schedule: dict[str, Any], target_date: date, keys: list[str]) -> bool:
    plan = schedule.setdefault("daily_plans", {}).setdefault(target_date.isoformat(), [])
    changed = False
    for key in keys:
        if key and key not in plan:
            plan.append(key)
            changed = True
    if changed:
        plan[:] = sort_schedule_keys(plan)
    return changed


def reviewed_keys_on_date(
    book_records: dict[str, dict[str, Any]],
    state: dict[str, Any],
    target_date: date,
) -> list[str]:
    catalog = build_record_catalog(book_records)
    keys = []
    for question_id, item in state.get("items", {}).items():
        for event in item.get("history", []):
            if event_review_date(event) == target_date:
                book_id = event.get("book_id") or resolve_state_item_book_id(question_id, item, catalog)
                if book_id:
                    keys.append(schedule_key(book_id, question_id))
                break
    return keys


def discard_overdue_buckets(schedule: dict[str, Any], today: date) -> bool:
    buckets = schedule.setdefault("buckets", {})
    today_key = today.isoformat()
    changed = False
    for due_at in sorted([key for key in buckets if key < today_key]):
        changed = bool(buckets.pop(due_at, [])) or changed
    return changed


def ensure_review_schedule(
    book_records: dict[str, dict[str, Any]],
    state: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    schedule = load_review_schedule()
    changed = discard_overdue_buckets(schedule, today)
    scheduled_due = {
        key: due_at
        for due_at, key in iter_scheduled_entries(schedule)
    }
    known_keys = set(scheduled_due)
    for book_id, book_record in book_records.items():
        history_records = records_by_question(book_record)
        full_records = full_records_by_question(book_record)

        for question_id, record in history_records.items():
            if not record.get("error_level"):
                continue
            key = schedule_key(book_id, question_id)
            state_item = state.get("items", {}).get(question_id, {})
            next_due = date_from_iso(state_item.get("next_due_at"))
            if next_due and next_due >= today:
                due_at = next_due.isoformat()
                if scheduled_due.get(key) != due_at:
                    changed = add_schedule_key(schedule, next_due, key, replace=True) or changed
                    scheduled_due[key] = due_at
                    known_keys.add(key)
            elif key not in known_keys:
                if next_due:
                    continue
                recorded_date = record_timestamp_date(full_records.get(question_id)) or today
                due_at = recorded_date + timedelta(days=1)
                if due_at < today:
                    continue
                changed = add_schedule_key(schedule, due_at, key, replace=False) or changed
                scheduled_due[key] = due_at.isoformat()
                known_keys.add(key)

    today_keys = schedule_entries_for_date(schedule, today)
    reviewed_today_keys = reviewed_keys_on_date(book_records, state, today)
    changed = add_daily_plan_keys(schedule, today, [*today_keys, *reviewed_today_keys]) or changed

    if changed:
        save_review_schedule(schedule)
    return schedule


def schedule_entries_for_date(schedule: dict[str, Any], target_date: date) -> list[str]:
    return schedule.get("buckets", {}).get(target_date.isoformat(), [])


def schedule_plan_for_date(schedule: dict[str, Any], target_date: date) -> list[str]:
    return schedule.get("daily_plans", {}).get(target_date.isoformat(), [])


def review_item_from_record(
    book_id: str,
    record: dict[str, Any],
    state: dict[str, Any],
    today: date,
    scheduled_due: date | None = None,
) -> dict[str, Any] | None:
    question_id = record.get("question_id")
    base_level = record.get("error_level")
    if not question_id or not base_level:
        return None

    state_item = state.get("items", {}).get(question_id, {})
    level = state_item.get("error_level") or base_level
    last_reviewed = state_item.get("last_reviewed_at")
    history = state_item.get("history", [])
    next_due = date_from_iso(state_item.get("next_due_at"))
    if next_due is None:
        next_due = scheduled_due or (today if history else today + timedelta(days=1))
    review_fail_count = sum(1 for event in history if event.get("outcome") != "pass")
    fail_count = 1 + review_fail_count
    recent_fail_count = sum(1 for event in history[-5:] if event.get("outcome") != "pass")
    overdue_days = max((today - next_due).days, 0)
    recorded_date = record_timestamp_date(record)
    sort_order = record_sort_order(book_id, question_id, record)

    return {
        "book_id": book_id,
        "book_label": display_book_label(book_id),
        "question_id": question_id,
        "display_id": record.get("display_id") or question_id,
        "display_label": record.get("display_label"),
        "page": record.get("page"),
        "section": record.get("section"),
        "question_type": record.get("question_type"),
        "record_order": record.get("record_order"),
        "card_structure": record.get("card_structure"),
        "parent_display_id": record.get("parent_display_id"),
        "subquestion": record.get("subquestion"),
        "level": level,
        "original_level": base_level,
        "target_score_tier": record.get("target_score_tier"),
        "required_for_scores": record.get("required_for_scores", []),
        "mastery": record.get("mastery"),
        "performance_level": record.get("performance_level"),
        "unit": record.get("unit"),
        "summary": record.get("student_answer_summary", ""),
        "next_due_at": next_due.isoformat(),
        "last_reviewed_at": last_reviewed,
        "interval_index": state_item.get("interval_index", -1),
        "review_count": len(history),
        "review_fail_count": review_fail_count,
        "fail_count": fail_count,
        "recent_fail_count": recent_fail_count,
        "overdue_days": overdue_days,
        "is_due": next_due <= today,
        "is_new": not history,
        "question_number": parse_question_number(question_id),
        "sort_order": sort_order,
        "recorded_ordinal": recorded_date.toordinal() if recorded_date else 0,
    }


def review_sort_key(item: dict[str, Any]) -> tuple:
    tier_ranks = {
        "workbook_660": {90: 0, 110: 1, 135: 2},
        "workbook_880": {"120以下": 0, "120+": 1},
    }
    tier_rank = tier_ranks.get(item.get("book_id"), {}).get(item.get("target_score_tier"), 9)
    level_rank = {"A": 0, "B": 1, "C": 2}.get(item.get("level"), 9)
    return (
        -item.get("recorded_ordinal", 0),
        -item.get("sort_order", 0),
        tier_rank,
        -item.get("recent_fail_count", 0),
        tier_rank,
        -item.get("fail_count", 0),
        -item.get("overdue_days", 0),
        tier_rank,
        level_rank,
    )


def reviewed_on(item: dict[str, Any], target_date: date) -> bool:
    for event in item.get("state_history", []):
        if event_review_date(event) == target_date:
            return True
    return False


def build_review_payload(
    selected_tiers: list[TierValue] | None = None,
    daily_limit: int | None = None,
) -> dict[str, Any]:
    index = load_index()
    state = load_review_state()
    settings = state["settings"]
    selected_tiers = normalize_tiers(selected_tiers or settings.get("selected_tiers"), index)
    daily_limit = daily_limit or int(settings.get("daily_limit", 10))
    today = date.today()
    book_records = load_reviewable_book_records(index)
    schedule = ensure_review_schedule(book_records, state, today)
    scheduled_today = schedule_entries_for_date(schedule, today)
    planned_today = schedule_plan_for_date(schedule, today)

    history_maps = {book_id: records_by_question(record) for book_id, record in book_records.items()}
    full_maps = {book_id: full_records_by_question(record) for book_id, record in book_records.items()}

    def item_for_key(key: str) -> dict[str, Any] | None:
        book_id, question_id = split_schedule_key(key)
        if book_id not in book_records or not question_id:
            return None
        history_record = history_maps[book_id].get(question_id)
        if not history_record:
            return None
        record = {**history_record, **full_maps[book_id].get(question_id, {})}
        item = review_item_from_record(book_id, record, state, today, scheduled_due=today)
        if item and item.get("target_score_tier") in selected_tiers:
            item["schedule_key"] = key
            item["state_history"] = state.get("items", {}).get(question_id, {}).get("history", [])
            return item
        return None

    candidates = [item for key in scheduled_today if (item := item_for_key(key))]

    due_items = candidates
    planned_items_by_key = {item["schedule_key"]: item for key in planned_today if (item := item_for_key(key))}
    planned_items = list(planned_items_by_key.values())

    due_items.sort(key=review_sort_key)
    selected = due_items[:daily_limit]
    deferred = due_items[daily_limit:]

    book_counts = {}
    for group in tier_groups(index):
        book_id = group["book_id"]
        book_planned = [item for item in planned_items if item["book_id"] == book_id]
        book_due = [item for item in due_items if item["book_id"] == book_id]
        book_selected = [item for item in selected if item["book_id"] == book_id]
        book_deferred = [item for item in deferred if item["book_id"] == book_id]
        book_counts[book_id] = {
            "label": group["label"],
            "due_total": len(book_planned),
            "pending_total": len(book_due),
            "selected_total": len(book_selected),
            "deferred_total": len(book_deferred),
            "tier_counts": {
                str(tier): sum(1 for item in book_planned if item.get("target_score_tier") == tier)
                for tier in group["tiers"]
            },
        }

    for item in candidates:
        item.pop("state_history", None)
    for item in planned_items:
        item.pop("state_history", None)

    return {
        "book_id": "all",
        "label": " + ".join(display_book_label(book_id) for book_id in book_records),
        "book_ids": list(book_records),
        "today": today.isoformat(),
        "settings": {
            "daily_limit": daily_limit,
            "selected_tiers": selected_tiers,
            "tier_groups": tier_groups(index),
            "first_pass_interval": int(settings.get("first_pass_interval", DEFAULT_REVIEW_SETTINGS["first_pass_interval"])),
            "intervals": settings.get("intervals", DEFAULT_REVIEW_SETTINGS["intervals"]),
        },
        "summary": {
            "due_total": len(planned_items),
            "pending_total": len(due_items),
            "selected_total": len(selected),
            "deferred_total": len(deferred),
            "overflow_total": max(len(planned_items) - daily_limit, 0),
            "book_counts": book_counts,
        },
        "activity": build_activity(state),
        "schedule_file": str(REVIEW_SCHEDULE_FILE),
        "queue": selected,
        "deferred": deferred,
    }


def progress_index_for_interval(schedule: list[int], interval_days: int) -> int:
    eligible_indexes = [index for index, days in enumerate(schedule) if days <= interval_days]
    return max(eligible_indexes) if eligible_indexes else 0


def next_interval_for(
    level: str,
    current_index: int,
    intervals: dict[str, list[int]],
    passed: bool,
    first_pass_interval: int = 5,
) -> tuple[int, int]:
    schedule = intervals.get(level) or DEFAULT_REVIEW_SETTINGS["intervals"].get(level, [1])
    if passed:
        if current_index < 0:
            return progress_index_for_interval(schedule, first_pass_interval), first_pass_interval
        next_index = min(current_index + 1, len(schedule) - 1)
    else:
        next_index = 0
    return next_index, schedule[next_index]


def event_review_date(event: dict[str, Any]) -> date:
    value = event.get("reviewed_at", "")
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return date.today()


def build_activity(state: dict[str, Any], days: int = 112) -> list[dict[str, Any]]:
    today = date.today()
    start = today - timedelta(days=days - 1)
    counts: Counter[str] = Counter()
    for item in state.get("items", {}).values():
        for event in item.get("history", []):
            event_date = event_review_date(event)
            if start <= event_date <= today:
                counts.update([event_date.isoformat()])

    return [
        {
            "date": (start + timedelta(days=offset)).isoformat(),
            "count": counts.get((start + timedelta(days=offset)).isoformat(), 0),
        }
        for offset in range(days)
    ]


def flatten_review_history(
    state: dict[str, Any],
    limit: int | None = 40,
    target_date: date | None = None,
) -> list[dict[str, Any]]:
    events = []
    index = load_index()
    book_records = load_all_book_records(index)
    catalog = build_record_catalog(book_records)
    full_maps = {book_id: full_records_by_question(record) for book_id, record in book_records.items()}
    for question_id, item in state.get("items", {}).items():
        book_id = resolve_state_item_book_id(question_id, item, catalog)
        if not book_id:
            continue
        history_record = (catalog.get(question_id) or (book_id, {}))[1]
        record = {**history_record, **full_maps.get(book_id, {}).get(question_id, {})}
        cumulative_fail_count = 1 if record.get("error_level") else 0
        for event_index, event in enumerate(item.get("history", [])):
            if event.get("outcome") != "pass":
                cumulative_fail_count += 1
            if target_date and event_review_date(event) != target_date:
                continue
            events.append(
                {
                    "book_id": event.get("book_id") or book_id,
                    "book_label": display_book_label(book_id),
                    "question_id": question_id,
                    "display_id": record.get("display_id") or question_id,
                    "display_label": record.get("display_label"),
                    "page": record.get("page"),
                    "section": record.get("section"),
                    "question_type": record.get("question_type"),
                    "record_order": record.get("record_order"),
                    "card_structure": record.get("card_structure"),
                    "parent_display_id": record.get("parent_display_id"),
                    "subquestion": record.get("subquestion"),
                    "event_index": event_index,
                    "review_count": event_index + 1,
                    "fail_count": cumulative_fail_count,
                    "target_score_tier": record.get("target_score_tier"),
                    "required_for_scores": record.get("required_for_scores", []),
                    "reviewed_at": event.get("reviewed_at"),
                    "outcome": event.get("outcome"),
                    "error_level": event.get("error_level"),
                    "note": event.get("note", ""),
                    "next_due_at": event.get("next_due_at"),
                }
            )
    events.sort(key=lambda item: item.get("reviewed_at") or "", reverse=True)
    return events[:limit] if limit is not None else events


def count_review_events(state: dict[str, Any]) -> int:
    return sum(len(item.get("history", [])) for item in state.get("items", {}).values())


def recalculate_review_item(book_id: str, question_id: str, item: dict[str, Any], state: dict[str, Any]) -> None:
    intervals = state["settings"].get("intervals", DEFAULT_REVIEW_SETTINGS["intervals"])
    first_pass_interval = int(state["settings"].get("first_pass_interval", DEFAULT_REVIEW_SETTINGS["first_pass_interval"]))
    record = records_by_question(load_book_record(book_id)).get(question_id, {})
    current_level = item.get("error_level") or record.get("error_level") or "B"
    interval_index = -1
    last_reviewed = None
    next_due = None

    for event in item.get("history", []):
        if event.get("outcome") == "wrong":
            current_level = event.get("error_level") or current_level
        if event.get("outcome") == "wrong" and not event.get("error_level"):
            raise HTTPException(status_code=422, detail="做错记录必须包含 A/B/C 等级")
        interval_index, interval_days = next_interval_for(
            current_level,
            interval_index,
            intervals,
            event.get("outcome") == "pass",
            first_pass_interval,
        )
        reviewed_date = event_review_date(event)
        next_due = reviewed_date + timedelta(days=interval_days)
        event["next_due_at"] = next_due.isoformat()
        last_reviewed = reviewed_date.isoformat()

    item["error_level"] = current_level
    item["interval_index"] = interval_index
    item["last_reviewed_at"] = last_reviewed
    item["next_due_at"] = next_due.isoformat() if next_due else None


def sync_schedule_for_question(
    book_id: str,
    question_id: str,
    level: str | None,
    next_due: date | None,
) -> None:
    if not next_due:
        return
    book_record = load_book_record(book_id)
    record = records_by_question(book_record).get(question_id)
    if not record:
        return
    schedule = load_review_schedule()
    add_schedule_key(schedule, next_due, schedule_key(book_id, question_id), replace=True)
    save_review_schedule(schedule)


def update_review_feedback(payload: ReviewFeedbackRequest) -> dict[str, Any]:
    state = load_review_state()
    today = date.today()
    settings = state["settings"]
    intervals = settings.get("intervals", DEFAULT_REVIEW_SETTINGS["intervals"])
    first_pass_interval = int(settings.get("first_pass_interval", DEFAULT_REVIEW_SETTINGS["first_pass_interval"]))
    if payload.book_id not in reviewable_book_ids():
        raise HTTPException(status_code=422, detail="该题册当前不参与回滚复习")
    record = records_by_question(load_book_record(payload.book_id)).get(payload.question_id)
    if not record:
        raise HTTPException(status_code=404, detail="没有在指定题册中找到该题")
    items = state.setdefault("items", {})
    current = items.setdefault(payload.question_id, {"history": [], "interval_index": -1})
    existing_book_id = current.get("book_id")
    if existing_book_id and existing_book_id != payload.book_id:
        raise HTTPException(status_code=409, detail="该题的复盘状态属于另一题册")

    if payload.outcome == "wrong" and not payload.error_level:
        raise HTTPException(status_code=422, detail="做错时必须提供 A/B/C 等级")

    current_level = payload.error_level or current.get("error_level")
    if not current_level:
        current_level = record.get("error_level") or "B"

    next_index, interval_days = next_interval_for(
        current_level,
        int(current.get("interval_index", -1)),
        intervals,
        payload.outcome == "pass",
        first_pass_interval,
    )
    next_due = today + timedelta(days=interval_days)

    event = {
        "book_id": payload.book_id,
        "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        "outcome": payload.outcome,
        "error_level": payload.error_level,
        "note": payload.note or "",
        "next_due_at": next_due.isoformat(),
    }
    current["book_id"] = payload.book_id
    current["error_level"] = current_level
    current["interval_index"] = next_index
    current["last_reviewed_at"] = today.isoformat()
    current["next_due_at"] = next_due.isoformat()
    current.setdefault("history", []).append(event)
    items[payload.question_id] = current
    save_review_state(state)
    sync_schedule_for_question(
        payload.book_id,
        payload.question_id,
        current_level,
        next_due,
    )

    return {
        "book_id": payload.book_id,
        "question_id": payload.question_id,
        "outcome": payload.outcome,
        "error_level": current_level,
        "next_due_at": next_due.isoformat(),
        "interval_days": interval_days,
    }


def update_review_event(question_id: str, event_index: int, payload: ReviewEventUpdateRequest) -> dict[str, Any]:
    state = load_review_state()
    item = state.get("items", {}).get(question_id)
    if not item:
        raise HTTPException(status_code=404, detail="没有找到该题的复盘记录")
    history = item.get("history", [])
    if event_index < 0 or event_index >= len(history):
        raise HTTPException(status_code=404, detail="没有找到该条复盘记录")
    if payload.outcome == "wrong" and not payload.error_level:
        raise HTTPException(status_code=422, detail="做错时必须提供 A/B/C 等级")
    record = records_by_question(load_book_record(payload.book_id)).get(question_id)
    if not record:
        raise HTTPException(status_code=404, detail="没有在指定题册中找到该题")
    existing_book_id = item.get("book_id")
    if existing_book_id and existing_book_id != payload.book_id:
        raise HTTPException(status_code=409, detail="该题的复盘状态属于另一题册")

    event = history[event_index]
    event["book_id"] = payload.book_id
    event["outcome"] = payload.outcome
    event["error_level"] = payload.error_level
    event["note"] = payload.note or ""
    item["book_id"] = payload.book_id
    recalculate_review_item(payload.book_id, question_id, item, state)
    save_review_state(state)
    if item.get("next_due_at"):
        sync_schedule_for_question(
            payload.book_id,
            question_id,
            item.get("error_level") or payload.error_level,
            date_from_iso(item.get("next_due_at")),
        )
    return {
        "book_id": payload.book_id,
        "question_id": question_id,
        "event_index": event_index,
        "event": history[event_index],
        "item": item,
    }


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/books")
async def api_books():
    index = load_index()
    return JSONResponse(content={"books": build_books(index, load_all_book_records(index))})


@app.get("/api/dashboard")
async def api_dashboard():
    return JSONResponse(content=build_dashboard_payload())


@app.get("/api/books/{book_id}/errors")
async def api_book_errors(book_id: str):
    return JSONResponse(content=build_book_errors(book_id))


@app.get("/api/review/today")
async def api_review_today(
    tiers: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=200),
):
    selected_tiers: list[TierValue] | None = None
    if tiers:
        selected_tiers = [int(value) if value.isdigit() else value for value in tiers.split(",") if value]
    return JSONResponse(content=build_review_payload(selected_tiers, limit))


@app.post("/api/review/settings")
async def api_review_settings(payload: ReviewSettingsRequest):
    state = load_review_state()
    state["settings"]["daily_limit"] = payload.daily_limit
    state["settings"]["selected_tiers"] = normalize_tiers(payload.selected_tiers)
    state["settings"]["tier_schema_version"] = 2
    save_review_state(state)
    return JSONResponse(content={"settings": state["settings"]})


@app.post("/api/review/feedback")
async def api_review_feedback(payload: ReviewFeedbackRequest):
    return JSONResponse(content=update_review_feedback(payload))


@app.get("/api/review/history")
async def api_review_history():
    state = load_review_state()
    today = date.today()
    return JSONResponse(
        content={
            "date": today.isoformat(),
            "history": flatten_review_history(state, limit=None, target_date=today),
            "activity": build_activity(state),
            "total_reviews": count_review_events(state),
        }
    )


@app.patch("/api/review/history/{question_id}/{event_index}")
async def api_review_history_update(question_id: str, event_index: int, payload: ReviewEventUpdateRequest):
    return JSONResponse(content=update_review_event(question_id, event_index, payload))
