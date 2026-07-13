from __future__ import annotations

import json
import mimetypes
import re
import sqlite3
import sys
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from importer import DB_PATH, import_all


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


def ensure_database() -> None:
    if not DB_PATH.exists():
        import_all(DB_PATH)
    ensure_runtime_schema()


def ensure_runtime_schema() -> None:
    with db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS wrong_questions (
                id INTEGER PRIMARY KEY,
                question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                bucket TEXT NOT NULL CHECK(bucket IN ('test', 'trial')),
                wrong_count INTEGER NOT NULL DEFAULT 1,
                last_mode TEXT NOT NULL DEFAULT 'unknown',
                last_selected_answer TEXT,
                last_wrong_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                UNIQUE(question_id, bucket)
            );

            CREATE INDEX IF NOT EXISTS idx_attempts_question ON attempts(question_id);
            CREATE INDEX IF NOT EXISTS idx_attempts_created_at ON attempts(created_at);
            CREATE INDEX IF NOT EXISTS idx_wrong_questions_bucket ON wrong_questions(bucket);
            CREATE INDEX IF NOT EXISTS idx_wrong_questions_question ON wrong_questions(question_id);
            """
        )


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def row_to_question(row: sqlite3.Row) -> dict[str, object]:
    keys = row.keys()
    display = (
        f"Deneme {row['trial_no']} / Soru {row['trial_question_no']}"
        if row["source"] == "trial"
        else f"Soru {row['source_question_no']}"
    )
    return {
        "id": row["id"],
        "questionKey": row["question_key"],
        "source": row["source"],
        "sourceLabel": "Deneme" if row["source"] == "trial" else "Soru Bankası",
        "display": display,
        "sourceQuestionNo": row["source_question_no"],
        "categoryId": row["category_id"],
        "categoryTitle": row["category_title"] if "category_title" in keys else None,
        "trialNo": row["trial_no"],
        "trialQuestionNo": row["trial_question_no"],
        "pageNo": row["page_no"],
        "prompt": row["prompt"],
        "options": {
            "A": row["option_a"],
            "B": row["option_b"],
            "C": row["option_c"],
            "D": row["option_d"],
            "E": row["option_e"],
        },
        "correctAnswer": row["correct_answer"],
        "explanation": row["explanation"],
        "rawText": row["raw_text"],
        "needsReview": bool(row["needs_review"]),
        "reviewNotes": json.loads(row["review_notes"] or "[]"),
        "isSeen": bool(row["is_seen"]) if "is_seen" in keys else False,
        "lastSelectedAnswer": row["last_selected_answer"] if "last_selected_answer" in keys else None,
    }


def json_response(handler: SimpleHTTPRequestHandler, payload, status=HTTPStatus.OK) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: SimpleHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if not length:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw)


def question_select_sql(where: str = "", order: str = "", extra_select: str = "") -> str:
    return f"""
        SELECT q.*, c.title AS category_title{extra_select}
        FROM questions q
        LEFT JOIN categories c ON c.id = q.category_id
        {where}
        {order}
    """


def wrong_bucket_for_source(source: str) -> str:
    return "trial" if source == "trial" else "test"


def percent(part: int, total: int) -> float:
    if not total:
        return 0.0
    return round((part / total) * 100, 1)


def update_wrong_state(
    con: sqlite3.Connection,
    question_id: int,
    selected: str | None,
    is_correct: bool,
    mode: str,
    now: str,
) -> None:
    row = con.execute("SELECT source FROM questions WHERE id = ?", (question_id,)).fetchone()
    if not row:
        return
    bucket = wrong_bucket_for_source(row["source"])
    if is_correct:
        con.execute(
            "DELETE FROM wrong_questions WHERE question_id = ? AND bucket = ?",
            (question_id, bucket),
        )
    elif selected:
        con.execute(
            """
            INSERT INTO wrong_questions (
                question_id, bucket, wrong_count, last_mode, last_selected_answer, last_wrong_at, updated_at
            ) VALUES (?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(question_id, bucket) DO UPDATE SET
                wrong_count = wrong_questions.wrong_count + 1,
                last_mode = excluded.last_mode,
                last_selected_answer = excluded.last_selected_answer,
                last_wrong_at = excluded.last_wrong_at,
                updated_at = excluded.updated_at
            """,
            (question_id, bucket, mode, selected, now, now),
        )


class KPSSHandler(SimpleHTTPRequestHandler):
    server_version = "KPSSLocal/1.0"

    def log_message(self, format, *args):  # noqa: A003 - inherited name
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/"):
            self.handle_api_get(path, parse_qs(parsed.query))
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/"):
            self.handle_api_post(path)
            return
        json_response(self, {"error": "Bulunamadi"}, HTTPStatus.NOT_FOUND)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/"):
            self.handle_api_patch(path)
            return
        json_response(self, {"error": "Bulunamadi"}, HTTPStatus.NOT_FOUND)

    def serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            target = STATIC_DIR / "index.html"
        else:
            safe_path = path.lstrip("/")
            target = (BASE_DIR / safe_path).resolve()
            if not str(target).startswith(str(BASE_DIR.resolve())) or not target.exists():
                target = STATIC_DIR / "index.html"
        if target.is_dir():
            target = target / "index.html"
        if not target.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/api/summary":
            self.api_summary()
        elif path == "/api/categories":
            self.api_categories()
        elif path == "/api/trials":
            self.api_trials()
        elif path == "/api/questions":
            self.api_questions(query)
        elif path == "/api/review":
            self.api_review(query)
        elif path == "/api/report":
            self.api_report()
        elif path == "/api/karma-state":
            self.api_karma_state()
        elif path == "/api/wrong-summary":
            self.api_wrong_summary()
        else:
            json_response(self, {"error": "Bulunamadi"}, HTTPStatus.NOT_FOUND)

    def handle_api_post(self, path: str) -> None:
        if path == "/api/attempts":
            self.api_attempts()
        elif path == "/api/karma-used":
            self.api_karma_used()
        elif path == "/api/reimport":
            self.api_reimport()
        else:
            json_response(self, {"error": "Bulunamadi"}, HTTPStatus.NOT_FOUND)

    def handle_api_patch(self, path: str) -> None:
        match = re.fullmatch(r"/api/questions/(\d+)", path)
        if match:
            self.api_update_question(int(match.group(1)))
        else:
            json_response(self, {"error": "Bulunamadi"}, HTTPStatus.NOT_FOUND)

    def api_summary(self) -> None:
        with db() as con:
            payload = {
                "totalQuestions": con.execute("SELECT COUNT(*) FROM questions").fetchone()[0],
                "questionBankQuestions": con.execute(
                    "SELECT COUNT(*) FROM questions WHERE source = 'question_bank'"
                ).fetchone()[0],
                "trialQuestions": con.execute("SELECT COUNT(*) FROM questions WHERE source = 'trial'").fetchone()[0],
                "reviewCount": con.execute("SELECT COUNT(*) FROM questions WHERE needs_review = 1").fetchone()[0],
                "wrongTestCount": con.execute(
                    "SELECT COUNT(*) FROM wrong_questions WHERE bucket = 'test'"
                ).fetchone()[0],
                "wrongTrialCount": con.execute(
                    "SELECT COUNT(*) FROM wrong_questions WHERE bucket = 'trial'"
                ).fetchone()[0],
                "categoryCount": con.execute("SELECT COUNT(*) FROM categories").fetchone()[0],
                "trialCount": con.execute("SELECT COUNT(DISTINCT trial_no) FROM questions WHERE source = 'trial'").fetchone()[0],
            }
        json_response(self, payload)

    def api_categories(self) -> None:
        with db() as con:
            rows = con.execute(
                """
                SELECT
                    c.*,
                    COUNT(DISTINCT q.id) AS question_count,
                    COUNT(DISTINCT a.question_id) AS seen_count
                FROM categories c
                LEFT JOIN questions q ON q.category_id = c.id
                LEFT JOIN attempts a ON a.question_id = q.id
                GROUP BY c.id
                ORDER BY c.start_question
                """
            ).fetchall()
        json_response(
            self,
            [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "startQuestion": row["start_question"],
                    "endQuestion": row["end_question"],
                    "questionCount": row["question_count"],
                    "seenCount": row["seen_count"],
                    "remainingCount": max(0, row["question_count"] - row["seen_count"]),
                    "progressPercent": percent(row["seen_count"], row["question_count"]),
                }
                for row in rows
            ],
        )

    def api_trials(self) -> None:
        with db() as con:
            rows = con.execute(
                """
                SELECT trial_no, COUNT(*) AS question_count
                FROM questions
                WHERE source = 'trial'
                GROUP BY trial_no
                ORDER BY trial_no
                """
            ).fetchall()
        json_response(
            self,
            [{"trialNo": row["trial_no"], "questionCount": row["question_count"]} for row in rows],
        )

    def api_questions(self, query: dict[str, list[str]]) -> None:
        mode = query.get("mode", [""])[0]
        with db() as con:
            if mode == "test":
                category_id = int(query.get("categoryId", ["0"])[0])
                rows = con.execute(
                    question_select_sql(
                        "WHERE q.source = 'question_bank' AND q.category_id = ?",
                        "ORDER BY q.source_question_no",
                        """,
                        EXISTS(
                            SELECT 1
                            FROM attempts a
                            WHERE a.question_id = q.id
                        ) AS is_seen,
                        (
                            SELECT a.selected_answer
                            FROM attempts a
                            WHERE a.question_id = q.id
                            ORDER BY a.created_at DESC, a.id DESC
                            LIMIT 1
                        ) AS last_selected_answer
                        """,
                    ),
                    (category_id,),
                ).fetchall()
            elif mode == "trial":
                trial_no = int(query.get("trialNo", ["0"])[0])
                rows = con.execute(
                    question_select_sql(
                        "WHERE q.source = 'trial' AND q.trial_no = ?",
                        "ORDER BY q.trial_question_no",
                    ),
                    (trial_no,),
                ).fetchall()
            elif mode == "karma":
                rows = con.execute(question_select_sql("", "ORDER BY q.id")).fetchall()
            elif mode == "wrong":
                bucket = query.get("bucket", ["karma"])[0]
                if bucket == "test":
                    where = """
                        JOIN wrong_questions w ON w.question_id = q.id
                        WHERE w.bucket = 'test'
                    """
                elif bucket == "trial":
                    where = """
                        JOIN wrong_questions w ON w.question_id = q.id
                        WHERE w.bucket = 'trial'
                    """
                else:
                    where = "JOIN wrong_questions w ON w.question_id = q.id"
                rows = con.execute(
                    question_select_sql(where, "ORDER BY w.updated_at DESC, q.source, q.source_question_no, q.trial_no, q.trial_question_no")
                ).fetchall()
            else:
                json_response(self, {"error": "Gecersiz mod"}, HTTPStatus.BAD_REQUEST)
                return
        json_response(self, [row_to_question(row) for row in rows])

    def api_wrong_summary(self) -> None:
        with db() as con:
            payload = {
                "test": con.execute("SELECT COUNT(*) FROM wrong_questions WHERE bucket = 'test'").fetchone()[0],
                "trial": con.execute("SELECT COUNT(*) FROM wrong_questions WHERE bucket = 'trial'").fetchone()[0],
            }
            payload["karma"] = payload["test"] + payload["trial"]
        json_response(self, payload)

    def api_review(self, query: dict[str, list[str]]) -> None:
        limit = min(int(query.get("limit", ["200"])[0]), 500)
        with db() as con:
            rows = con.execute(
                question_select_sql("WHERE q.needs_review = 1", "ORDER BY q.source, q.page_no, q.id LIMIT ?"),
                (limit,),
            ).fetchall()
        json_response(self, [row_to_question(row) for row in rows])

    def api_report(self) -> None:
        with db() as con:
            total_all = con.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
            total_test = con.execute(
                "SELECT COUNT(*) FROM questions WHERE source = 'question_bank'"
            ).fetchone()[0]
            total_trial = con.execute("SELECT COUNT(*) FROM questions WHERE source = 'trial'").fetchone()[0]

            seen_all = con.execute("SELECT COUNT(DISTINCT question_id) FROM attempts").fetchone()[0]
            seen_by_source = {
                "question_bank": 0,
                "trial": 0,
            }
            for row in con.execute(
                """
                SELECT q.source, COUNT(DISTINCT a.question_id) AS seen_count
                FROM attempts a
                JOIN questions q ON q.id = a.question_id
                GROUP BY q.source
                """
            ).fetchall():
                seen_by_source[row["source"]] = row["seen_count"]

            today = datetime.now().date().isoformat()
            today_row = con.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN selected_answer IS NOT NULL THEN 1 ELSE 0 END) AS answered,
                    SUM(CASE WHEN selected_answer IS NOT NULL AND is_correct = 1 THEN 1 ELSE 0 END) AS correct,
                    SUM(CASE WHEN selected_answer IS NOT NULL AND is_correct = 0 THEN 1 ELSE 0 END) AS wrong,
                    SUM(CASE WHEN selected_answer IS NULL THEN 1 ELSE 0 END) AS empty
                FROM attempts
                WHERE created_at LIKE ?
                """,
                (f"{today}%",),
            ).fetchone()
            all_time_row = con.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN selected_answer IS NOT NULL THEN 1 ELSE 0 END) AS answered,
                    SUM(CASE WHEN selected_answer IS NOT NULL AND is_correct = 1 THEN 1 ELSE 0 END) AS correct,
                    SUM(CASE WHEN selected_answer IS NOT NULL AND is_correct = 0 THEN 1 ELSE 0 END) AS wrong,
                    SUM(CASE WHEN selected_answer IS NULL THEN 1 ELSE 0 END) AS empty
                FROM attempts
                """
            ).fetchone()

            wrong_test = con.execute("SELECT COUNT(*) FROM wrong_questions WHERE bucket = 'test'").fetchone()[0]
            wrong_trial = con.execute("SELECT COUNT(*) FROM wrong_questions WHERE bucket = 'trial'").fetchone()[0]

            top_wrong_row = con.execute(
                """
                SELECT
                    CASE
                        WHEN q.source = 'question_bank' THEN c.title
                        ELSE 'Deneme ' || q.trial_no
                    END AS title,
                    q.source AS source,
                    COUNT(*) AS wrong_count
                FROM attempts a
                JOIN questions q ON q.id = a.question_id
                LEFT JOIN categories c ON c.id = q.category_id
                WHERE a.selected_answer IS NOT NULL AND a.is_correct = 0
                GROUP BY title, q.source
                ORDER BY wrong_count DESC, title
                LIMIT 1
                """
            ).fetchone()

            report_rows = con.execute(
                "SELECT key, value, updated_at FROM import_report ORDER BY key"
            ).fetchall()

        import_report = {row["key"]: json.loads(row["value"]) for row in report_rows}
        question_bank_report = import_report.get("question_bank") or {}
        trials_report = import_report.get("trials") or {}

        def attempt_block(row: sqlite3.Row) -> dict[str, object]:
            total = row["total"] or 0
            answered = row["answered"] or 0
            correct = row["correct"] or 0
            return {
                "attempts": total,
                "answered": answered,
                "correct": correct,
                "wrong": row["wrong"] or 0,
                "empty": row["empty"] or 0,
                "accuracy": percent(correct, answered),
            }

        payload = {
            "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "totals": {
                "all": total_all,
                "test": total_test,
                "trial": total_trial,
            },
            "coverage": {
                "all": {
                    "seen": seen_all,
                    "total": total_all,
                    "percent": percent(seen_all, total_all),
                },
                "test": {
                    "seen": seen_by_source["question_bank"],
                    "total": total_test,
                    "percent": percent(seen_by_source["question_bank"], total_test),
                },
                "trial": {
                    "seen": seen_by_source["trial"],
                    "total": total_trial,
                    "percent": percent(seen_by_source["trial"], total_trial),
                },
            },
            "today": attempt_block(today_row),
            "allTime": attempt_block(all_time_row),
            "wrong": {
                "test": wrong_test,
                "trial": wrong_trial,
                "karma": wrong_test + wrong_trial,
            },
            "mostWrongCategory": {
                "title": top_wrong_row["title"],
                "source": "Deneme" if top_wrong_row["source"] == "trial" else "Test",
                "wrongCount": top_wrong_row["wrong_count"],
            }
            if top_wrong_row
            else None,
            "import": {
                "createdAt": import_report.get("created_at"),
                "totalQuestions": import_report.get("total_questions", total_all),
                "reviewCount": import_report.get("total_needs_review", 0),
                "questionBank": {
                    "questionsFound": question_bank_report.get("questions_found", 0),
                    "answersFound": question_bank_report.get("answers_found", 0),
                    "needsReview": question_bank_report.get("needs_review", 0),
                },
                "trials": {
                    "questionsFound": trials_report.get("questions_found", 0),
                    "answersFound": trials_report.get("answers_found", 0),
                    "needsReview": trials_report.get("needs_review", 0),
                },
            },
        }
        json_response(self, payload)

    def api_attempts(self) -> None:
        payload = read_json(self)
        answers = payload.get("answers", [])
        session_id = str(payload.get("sessionId") or datetime.now().timestamp())
        mode = str(payload.get("mode") or "unknown")
        now = datetime.now().isoformat(timespec="seconds")
        with db() as con:
            for item in answers:
                question_id = int(item["questionId"])
                selected = item.get("selectedAnswer")
                correct = con.execute(
                    "SELECT correct_answer FROM questions WHERE id = ?", (question_id,)
                ).fetchone()
                if not correct:
                    continue
                is_correct = 1 if selected == correct["correct_answer"] else 0
                con.execute(
                    """
                    INSERT INTO attempts (question_id, session_id, mode, selected_answer, is_correct, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (question_id, session_id, mode, selected, is_correct, now),
                )
                update_wrong_state(con, question_id, selected, bool(is_correct), mode, now)
        json_response(self, {"ok": True})

    def api_karma_state(self) -> None:
        with db() as con:
            row = con.execute("SELECT value FROM study_state WHERE key = 'karma_used_ids'").fetchone()
            used_ids = json.loads(row["value"]) if row else []
            total = con.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        json_response(self, {"usedIds": used_ids, "total": total})

    def api_karma_used(self) -> None:
        payload = read_json(self)
        question_id = int(payload.get("questionId"))
        with db() as con:
            row = con.execute("SELECT value FROM study_state WHERE key = 'karma_used_ids'").fetchone()
            used_ids = json.loads(row["value"]) if row else []
            total_ids = [item["id"] for item in con.execute("SELECT id FROM questions ORDER BY id")]
            if question_id not in used_ids:
                used_ids.append(question_id)
            if len(set(used_ids)) >= len(total_ids):
                used_ids = []
            now = datetime.now().isoformat(timespec="seconds")
            con.execute(
                """
                INSERT INTO study_state (key, value, updated_at)
                VALUES ('karma_used_ids', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (json.dumps(used_ids), now),
            )
        json_response(self, {"ok": True, "usedIds": used_ids})

    def api_update_question(self, question_id: int) -> None:
        payload = read_json(self)
        allowed = {
            "prompt": "prompt",
            "correctAnswer": "correct_answer",
            "explanation": "explanation",
            "needsReview": "needs_review",
        }
        option_map = {
            "A": "option_a",
            "B": "option_b",
            "C": "option_c",
            "D": "option_d",
            "E": "option_e",
        }
        updates: list[str] = []
        values: list[object] = []
        for key, column in allowed.items():
            if key in payload:
                value = payload[key]
                if key == "needsReview":
                    value = 1 if value else 0
                updates.append(f"{column} = ?")
                values.append(value)
        if "options" in payload:
            for letter, value in payload["options"].items():
                if letter in option_map:
                    updates.append(f"{option_map[letter]} = ?")
                    values.append(value)
        if "reviewNotes" in payload:
            updates.append("review_notes = ?")
            values.append(json.dumps(payload["reviewNotes"], ensure_ascii=False))
        if not updates:
            json_response(self, {"ok": False, "error": "Guncellenecek alan yok"}, HTTPStatus.BAD_REQUEST)
            return
        updates.append("updated_at = ?")
        values.append(datetime.now().isoformat(timespec="seconds"))
        values.append(question_id)
        with db() as con:
            con.execute(f"UPDATE questions SET {', '.join(updates)} WHERE id = ?", values)
            row = con.execute(question_select_sql("WHERE q.id = ?"), (question_id,)).fetchone()
        json_response(self, row_to_question(row))

    def api_reimport(self) -> None:
        report = import_all(DB_PATH)
        json_response(self, report)


def main() -> None:
    ensure_database()
    port = 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), KPSSHandler)
    print(f"KPSS uygulamasi hazir: http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nKapatiliyor...")


if __name__ == "__main__":
    main()
