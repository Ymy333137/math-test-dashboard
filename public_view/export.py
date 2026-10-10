"""Export only approved review-page fields; never serialize full private payloads."""
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

CARD_FIELDS = (
    "book_id", "book_label", "display_id", "page", "section", "question_type",
    "level", "target_score_tier", "summary", "review_count", "fail_count",
    "is_new", "is_starved", "is_final_review", "is_maintenance",
)
HISTORY_FIELDS = (
    "book_id", "book_label", "display_id", "page", "section", "question_type",
    "target_score_tier", "review_count", "fail_count", "reviewed_at", "outcome",
    "error_level", "note", "next_due_at",
)


def pick(source, fields):
    return {field: source.get(field) for field in fields
            if source.get(field) is None or type(source.get(field)) in (str, int, float, bool)}


def project(review, state, history):
    def card(item):
        result = pick(item, CARD_FIELDS)
        events = state.get("items", {}).get(item.get("question_id"), {}).get("history", [])
        note = events[-1].get("note", "") if events else ""
        result["note"] = note if isinstance(note, str) else ""
        return result

    summary = pick(review["summary"], ("due_total", "pending_total", "overflow_total", "backlog_total"))
    summary["daily_limit"] = review["settings"]["daily_limit"]
    books = []
    for book_id, counts in review["summary"].get("book_counts", {}).items():
        books.append({"book_id": book_id, **pick(counts, ("label", "due_total", "pending_total")),
                      "tier_counts": {str(tier): count for tier, count in counts.get("tier_counts", {}).items()
                                      if type(count) is int}})
    return {
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "date": review["today"],
        "summary": summary,
        "books": books,
        "activity": [pick(day, ("date", "count", "planned", "completed", "ratio"))
                     for day in review.get("activity", [])],
        "queue": [card(item) for item in review.get("queue", [])],
        "backlog": [card(item) for item in review.get("backlog", [])],
        "history": [pick(event, HISTORY_FIELDS) for event in history
                    if event.get("book_id") in review.get("book_ids", [])],
        "total_reviews": app.count_review_events(state),
    }


def main():
    state = app.load_review_state()
    review = app.build_review_payload(read_only=True)
    today = date.today()
    history = app.flatten_review_history(state, limit=None, target_date=today, start_date=today - timedelta(days=1))
    destination = Path(os.environ.get("PUBLIC_OUTPUT_DIR", "/public")) / "snapshot.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(project(review, state, history), ensure_ascii=False), encoding="utf-8")
    temporary.chmod(0o644)
    temporary.replace(destination)
    print("Public snapshot updated", flush=True)


if __name__ == "__main__":
    main()
