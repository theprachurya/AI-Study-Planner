import os
import re
import json
import logging
from logging.handlers import RotatingFileHandler
import sqlite3
from datetime import datetime, timedelta

from flask import Flask, render_template, request, redirect, url_for, send_file, flash
from werkzeug.exceptions import NotFound
from dotenv import load_dotenv
import google.generativeai as genai


def create_app() -> Flask:
    load_dotenv()

    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")
    app.config["DATABASE_PATH"] = os.path.join(os.getcwd(), "database", "planner.db")
    app.config["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY", "")
    app.config["LOGS_DIR"] = os.path.join(os.getcwd(), "logs")

    os.makedirs(os.path.dirname(app.config["DATABASE_PATH"]), exist_ok=True)
    os.makedirs(app.static_folder, exist_ok=True)
    os.makedirs(app.template_folder, exist_ok=True)
    os.makedirs(app.config["LOGS_DIR"], exist_ok=True)

    # Logging
    log_path = os.path.join(app.config["LOGS_DIR"], "ai-planner.log")
    handler = RotatingFileHandler(log_path, maxBytes=512_000, backupCount=3)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(fmt)
    app.logger.setLevel(logging.INFO)
    app.logger.addHandler(handler)

    def get_db_connection():
        conn = sqlite3.connect(app.config["DATABASE_PATH"]) 
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_database_schema():
        """Ensure DB schema exists in production environments (first deploy)."""
        try:
            with get_db_connection() as conn:
                exists = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='plans'"
                ).fetchone()
                if exists:
                    return
                schema_path = os.path.join(os.getcwd(), "database", "schema.sql")
                if os.path.exists(schema_path):
                    with open(schema_path, "r", encoding="utf-8") as f:
                        conn.executescript(f.read())
                    app.logger.info("Database schema created from schema.sql")
                else:
                    # Fallback: inline schema (in case schema.sql is not packaged)
                    conn.executescript(
                        (
                            "PRAGMA foreign_keys = ON;\n"
                            "CREATE TABLE IF NOT EXISTS plans (\n"
                            "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
                            "    title TEXT NOT NULL,\n"
                            "    description TEXT,\n"
                            "    start_date TEXT NOT NULL,\n"
                            "    end_date TEXT NOT NULL,\n"
                            "    subjects TEXT NOT NULL,\n"
                            "    learning_goal TEXT,\n"
                            "    difficulty_feedback TEXT,\n"
                            "    hours_per_day REAL NOT NULL,\n"
                            "    off_days TEXT,\n"
                            "    class_schedule TEXT,\n"
                            "    generated_guide TEXT,\n"
                            "    generated_schedule TEXT NOT NULL,\n"
                            "    resources TEXT,\n"
                            "    created_at TEXT NOT NULL\n"
                            ");\n"
                            "CREATE TABLE IF NOT EXISTS subject_marks (\n"
                            "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
                            "    plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,\n"
                            "    subject_name TEXT NOT NULL,\n"
                            "    component_type TEXT,\n"
                            "    assessment_name TEXT,\n"
                            "    max_marks REAL,\n"
                            "    obtained_marks REAL\n"
                            ");\n"
                        )
                    )
                    app.logger.info("Database schema created from inline fallback")
        except Exception as e:
            app.logger.warning("Failed to ensure schema: %s", e)

    @app.cli.command("init-db")
    def init_db_command():
        schema_path = os.path.join(os.getcwd(), "database", "schema.sql")
        os.makedirs(os.path.dirname(schema_path), exist_ok=True)
        if not os.path.exists(schema_path):
            with open(schema_path, "w", encoding="utf-8") as f:
                f.write(
                    """
                    PRAGMA foreign_keys = ON;
                    CREATE TABLE IF NOT EXISTS plans (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        description TEXT,
                        start_date TEXT NOT NULL,
                        end_date TEXT NOT NULL,
                        subjects TEXT NOT NULL,
                        learning_goal TEXT,
                        difficulty_feedback TEXT,
                        hours_per_day REAL NOT NULL,
                        off_days TEXT,
                        class_schedule TEXT,
                        generated_guide TEXT,
                        generated_schedule TEXT NOT NULL,
                        resources TEXT,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS subject_marks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
                        subject_name TEXT NOT NULL,
                        component_type TEXT,
                        assessment_name TEXT,
                        max_marks REAL,
                        obtained_marks REAL
                    );
                    """.strip()
                )
        with get_db_connection() as conn:
            with open(schema_path, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
        print("Initialized the database.")

    # Ensure schema exists at startup (safe on repeated calls)
    ensure_database_schema()

    @app.route("/")
    def index():
        with get_db_connection() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM plans").fetchone()["c"]
        return render_template("index.html", has_plans=total > 0)

    @app.route("/generate", methods=["GET", "POST"]) 
    def generate():
        if request.method == "GET":
            return render_template("generate.html")

        # POST: handle generation
        form = request.form
        title = form.get("title", "My Study Plan").strip() or "My Study Plan"
        description = form.get("description", "").strip()
        subjects_str = form.get("subjects", "").strip()
        start_date = form.get("start_date", "").strip()
        end_date = form.get("end_date", "").strip()
        hours_per_day = float(form.get("hours_per_day", "2") or 2)
        off_days = form.getlist("off_days")
        class_schedule = form.get("class_schedule", "").strip()
        learning_goal = form.get("learning_goal", "").strip()
        difficulty_feedback = form.get("difficulty_feedback", "").strip()
        # Subject-specific difficulties
        subject_difficulties_text = form.get("subject_difficulties", "").strip()
        subject_difficulties: dict[str, str] = {}
        if subject_difficulties_text:
            try:
                maybe = json.loads(subject_difficulties_text)
                if isinstance(maybe, dict):
                    subject_difficulties = {str(k).strip(): str(v).strip().lower() for k, v in maybe.items()}
            except Exception:
                # Parse line format "Subject: level"
                for line in subject_difficulties_text.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        subject_difficulties[k.strip()] = v.strip().lower()

        subjects = [s.strip() for s in subjects_str.split(",") if s.strip()]

        # Marks parsing: accepts a textarea JSON or repeated fields (future)
        marks_json_text = form.get("marks_json", "").strip()
        marks_records = []
        if marks_json_text:
            try:
                raw = json.loads(marks_json_text)
                for rec in raw:
                    marks_records.append({
                        "subject_name": rec.get("subject_name"),
                        "component_type": rec.get("component_type"),
                        "assessment_name": rec.get("assessment_name"),
                        "max_marks": rec.get("max_marks"),
                        "obtained_marks": rec.get("obtained_marks"),
                    })
            except Exception as e:
                app.logger.warning("Invalid marks JSON: %s", e)

        prompt = {
            "title": title,
            "description": description,
            "start_date": start_date,
            "end_date": end_date,
            "subjects": subjects,
            "hours_per_day": hours_per_day,
            "off_days": off_days,
            "class_schedule": class_schedule,
            "learning_goal": learning_goal,
            "difficulty_feedback": difficulty_feedback,
            "marks_summary": summarize_marks(marks_records) if marks_records else None,
            "format_requirements": {
                "schedule_format": "object mapping YYYY-MM-DD -> array of blocks {start_time, end_time, subject, task}",
                "off_day_value": "use empty array for off days"
            },
            "subject_difficulties": subject_difficulties
        }

        guide_text, resources_text, schedule_obj = generate_with_gemini(app, prompt)

        if schedule_obj is None:
            schedule_obj = generate_fallback_schedule(start_date, end_date, subjects, hours_per_day, off_days)
            if guide_text is None:
                guide_text = "Basic learning guide: rotate subjects daily and focus on weak areas."
            if resources_text is None:
                resources_text = "Resources will be suggested when AI is available."
        
        # Normalize schedule to expected map shape and ensure varied daily topics
        schedule_obj = normalize_schedule(schedule_obj, start_date, end_date, subjects, hours_per_day, off_days, subject_difficulties)

        with get_db_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO plans (title, description, start_date, end_date, subjects, learning_goal, difficulty_feedback, hours_per_day, off_days, class_schedule, generated_guide, generated_schedule, resources, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    description,
                    start_date,
                    end_date,
                    subjects_str,
                    learning_goal,
                    difficulty_feedback,
                    hours_per_day,
                    ",".join(off_days),
                    class_schedule,
                    guide_text or "",
                    json.dumps(schedule_obj),
                    resources_text or "",
                    datetime.utcnow().isoformat(),
                ),
            )
            plan_id = cur.lastrowid

            # Save marks
            for rec in marks_records:
                conn.execute(
                    """
                    INSERT INTO subject_marks (plan_id, subject_name, component_type, assessment_name, max_marks, obtained_marks)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan_id,
                        rec.get("subject_name"), rec.get("component_type"), rec.get("assessment_name"),
                        rec.get("max_marks"), rec.get("obtained_marks")
                    )
                )
            conn.commit()

        flash("Study plan created.")
        return redirect(url_for("view_plan", plan_id=plan_id))

    @app.route("/plans")
    def list_plans():
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, title, created_at FROM plans ORDER BY id DESC"
            ).fetchall()
        return render_template("plans.html", plans=rows)

    @app.route("/plan/<int:plan_id>")
    def view_plan(plan_id: int):
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
        if not row:
            raise NotFound()
        schedule = json.loads(row["generated_schedule"]) if row["generated_schedule"] else {}
        subjects = [s.strip() for s in (row["subjects"] or "").split(",") if s.strip()]
        return render_template(
            "plan.html",
            plan=row,
            schedule=schedule,
            subjects=subjects,
        )

    @app.post("/fix-schedule/<int:plan_id>")
    def fix_schedule(plan_id: int):
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
            if not row:
                raise NotFound()
            current = row["generated_schedule"] or ""

        repaired = extract_json_from_text(current)
        if repaired is None:
            repaired = generate_fallback_schedule(row["start_date"], row["end_date"], [s.strip() for s in (row["subjects"] or "").split(",") if s.strip()], row["hours_per_day"], (row["off_days"] or "").split(",") if row["off_days"] else [])

        with get_db_connection() as conn:
            conn.execute("UPDATE plans SET generated_schedule = ? WHERE id = ?", (json.dumps(repaired), plan_id))
            conn.commit()
        flash("Schedule repaired.")
        return redirect(url_for("view_plan", plan_id=plan_id))

    # download endpoint removed per requirements

    # --- Helpers ---
    def summarize_marks(marks: list[dict]) -> str:
        if not marks:
            return ""
        summary_lines = []
        by_subject: dict[str, list[dict]] = {}
        for rec in marks:
            if not rec.get("subject_name"):
                continue
            by_subject.setdefault(rec["subject_name"], []).append(rec)
        for subject, recs in by_subject.items():
            parts = []
            for r in recs:
                if r.get("obtained_marks") is not None and r.get("max_marks"):
                    parts.append(f"{r.get('assessment_name','Assessment')}: {r['obtained_marks']}/{r['max_marks']}")
            if parts:
                summary_lines.append(f"{subject}: " + "; ".join(parts))
        return " | ".join(summary_lines)

    def extract_json_from_text(text: str):
        if not text:
            return None
        # Try direct JSON
        try:
            obj = json.loads(text)
            return obj
        except Exception:
            pass
        # Regex extract first {...} or [...] block
        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                return None
        return None

    def generate_fallback_schedule(start_date: str, end_date: str, subjects: list[str], hours_per_day: float, off_days: list[str]):
        # Build date range
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except Exception:
            start = datetime.utcnow().date()
            end = start + timedelta(days=6)
        if end < start:
            end = start
        schedule: dict[str, list] = {}
        day_index = 0
        date = start
        while date <= end:
            weekday = date.strftime("%a")
            date_key = date.isoformat()
            blocks = []
            if weekday not in off_days:
                remaining = hours_per_day
                start_hour = 9
                subject_idx = day_index % max(1, len(subjects))
                while remaining > 0:
                    duration = min(2.0, remaining)
                    end_hour = start_hour + int(duration)
                    blocks.append({
                        "start_time": f"{start_hour:02d}:00",
                        "end_time": f"{end_hour:02d}:00",
                        "subject": subjects[subject_idx] if subjects else "General",
                        "task": f"Deep dive Day {day_index+1}"
                    })
                    remaining -= duration
                    start_hour = end_hour + 1
                    subject_idx = (subject_idx + 1) % max(1, len(subjects))
            schedule[date_key] = blocks
            date += timedelta(days=1)
            day_index += 1
        return schedule

    def normalize_schedule(schedule_obj, start_date: str, end_date: str, subjects: list[str], hours_per_day: float, off_days: list[str], subject_difficulties: dict[str, str] | None = None):
        """Coerce AI/fallback schedule into a date->blocks map, ensure tasks vary per day."""
        # Prepare date range
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except Exception:
            start = datetime.utcnow().date()
            end = start + timedelta(days=6)
        if end < start:
            end = start

        # Transform list-shaped schedules to map
        schedule_map: dict[str, list] = {}
        if isinstance(schedule_obj, dict):
            for k, v in schedule_obj.items():
                schedule_map[str(k)] = list(v or [])
        elif isinstance(schedule_obj, list):
            for day in schedule_obj:
                date_key = str(day.get("date")) if isinstance(day, dict) else None
                if not date_key:
                    continue
                items = []
                for item in (day.get("items") or []):
                    # Convert legacy duration_hours into start/end slots
                    dur = float(item.get("duration_hours") or 2)
                    items.append({
                        "start_time": "09:00",
                        "end_time": f"{9+int(min(2,dur)):02d}:00",
                        "subject": item.get("subject") or "Study",
                        "task": item.get("task") or "Focus block",
                    })
                schedule_map[date_key] = items
        else:
            schedule_map = {}

        # Ensure every date in range has blocks or [] if off day; vary topics
        seen_subject_day = {}
        day_counter = 0
        date = start
        while date <= end:
            date_key = date.isoformat()
            weekday = date.strftime("%a")
            blocks = schedule_map.get(date_key)
            if weekday in off_days:
                schedule_map[date_key] = []
            else:
                if not blocks:
                    # Create minimal rotating block if missing
                    subject = subjects[day_counter % max(1, len(subjects))] if subjects else "Study"
                    duration = 2
                    # Weight by difficulty: hard 2h, medium 1.5h, easy 1h blocks where possible
                    diff = (subject_difficulties or {}).get(subject, "")
                    if diff == "hard":
                        duration = 2
                    elif diff == "medium":
                        duration = 1
                    elif diff == "easy":
                        duration = 1
                    schedule_map[date_key] = [{
                        "start_time": "09:00",
                        "end_time": f"{9+int(duration):02d}:00",
                        "subject": subject,
                        "task": f"Core practice — Day {day_counter+1}",
                    }]
                else:
                    # Ensure tasks are labeled distinctly per day
                    new_blocks = []
                    for idx, b in enumerate(blocks):
                        subject = b.get("subject") or "Study"
                        task = b.get("task") or "Focus block"
                        # Append day index to make topic distinct day-to-day
                        if isinstance(task, str):
                            task = f"{task} — Day {day_counter+1}"
                        # Adjust duration by difficulty if hours can be derived
                        start_time = b.get("start_time") or "09:00"
                        end_time = b.get("end_time") or "11:00"
                        try:
                            sh, sm = [int(x) for x in start_time.split(":")[:2]]
                            eh, em = [int(x) for x in end_time.split(":")[:2]]
                            duration_hours = max(1, (eh + em/60) - (sh + sm/60))
                        except Exception:
                            duration_hours = 2
                        diff = (subject_difficulties or {}).get(subject, "")
                        if diff == "hard" and duration_hours < 2:
                            end_time = f"{sh+2:02d}:00"
                        elif diff == "easy" and duration_hours > 1:
                            end_time = f"{sh+1:02d}:00"
                        new_blocks.append({
                            "start_time": start_time,
                            "end_time": end_time,
                            "subject": subject,
                            "task": task,
                        })
                    schedule_map[date_key] = new_blocks
            date += timedelta(days=1)
            day_counter += 1
        return schedule_map

    def generate_with_gemini(app: Flask, prompt: dict):
        guide_text = None
        resources_text = None
        schedule_obj = None
        if not app.config["GEMINI_API_KEY"]:
            return guide_text, resources_text, schedule_obj
        try:
            genai.configure(api_key=app.config["GEMINI_API_KEY"]) 
            model = genai.GenerativeModel("gemini-2.0-flash")
            system = (
                "You are an expert study-planning assistant. Respond with STRICT JSON only. Keys: "
                "learning_guide (string), resources (string), schedule (object mapping YYYY-MM-DD -> array of blocks {start_time:'HH:MM', end_time:'HH:MM', subject, task}). "
                "Vary the task topics day-to-day. Prioritize weaker subjects if marks are provided. "
                "If 'subject_difficulties' is provided, allocate more time to 'hard', moderate to 'medium', and less to 'easy' subjects proportionally across the schedule."
            )
            user_prompt = (
                f"Title: {prompt.get('title')}\n"
                f"Dates: {prompt.get('start_date')} to {prompt.get('end_date')}\n"
                f"Subjects: {', '.join(prompt.get('subjects') or [])}\n"
                f"Hours/day: {prompt.get('hours_per_day')}\n"
                f"Off-days: {', '.join(prompt.get('off_days') or [])}\n"
                f"Class schedule: {prompt.get('class_schedule') or 'None'}\n"
                f"Learning goal: {prompt.get('learning_goal') or ''}\n"
                f"Difficulty feedback: {prompt.get('difficulty_feedback') or ''}\n"
                f"Marks summary: {prompt.get('marks_summary') or 'None'}\n\n"
                f"Subject difficulties: {json.dumps(prompt.get('subject_difficulties') or {}, ensure_ascii=False)}\n\n"
                "Output strictly the JSON object with the three keys described."
            )
            result = model.generate_content([system, user_prompt])
            raw = result.text.strip()
            data = extract_json_from_text(raw)
            if isinstance(data, dict):
                guide_text = data.get("learning_guide")
                resources_text = data.get("resources")
                schedule_obj = data.get("schedule")
        except Exception as e:
            app.logger.warning("Gemini error: %s", e)
        return guide_text, resources_text, schedule_obj

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)

