## Generative AI Study Planner

An AI-assisted study planning web app that generates a personalized learning guide, daily schedule, and resource suggestions based on your subjects, goals, available hours, off-days, and fixed commitments.

### Features

- Smart AI plan generation (Gemini) with resilient JSON extraction and fallbacks
- Day-by-day schedule between selected start and end dates
- Learning guide and resources alongside the schedule
- Weekly calendar view (FullCalendar) with export to image and PDF
- Stores plans and optional subject marks in SQLite
- Light/dark theme toggle, responsive UI

### Tech Stack

- Backend: Python 3, Flask, SQLite, `google-generativeai`
- Frontend: Jinja2, HTML, CSS, JavaScript, FullCalendar (CDN), jsPDF, html2canvas

---

## Project Structure

```
/home/zen/Code/study-planner/
├── app.py                   # Flask app, routes, AI integration, helpers
├── requirements.txt         # Python dependencies
├── database/
│   ├── schema.sql           # SQLite schema for plans and subject_marks
│   └── planner.db           # Created at runtime (after init-db)
├── static/
│   ├── css/style.css        # Styles with light/dark theme
│   └── js/main.js           # Theme toggle, small helpers
├── templates/
│   ├── base.html            # Base layout
│   ├── index.html           # Landing page
│   ├── generate.html        # Plan generation form
│   ├── plans.html           # Saved plans list
│   ├── plan.html            # Plan detail + calendar + exports
│   ├── 404.html             # Not found
│   └── 500.html             # Server error
└── logs/
    └── ai-planner.log       # Rotating app log (created at runtime)
```

---

## Prerequisites

- Python 3.9+
- A Google Generative AI API key (optional; the app works with fallbacks if not set)

---

## Setup

1) Clone and enter the project directory

```bash
git clone <your-repo-url> study-planner
cd study-planner
```

2) Create and activate a virtual environment

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

3) Install dependencies

```bash
pip install -r requirements.txt
```

4) Configure environment variables

Create a `.env` file in the project root:

```
FLASK_SECRET_KEY=your_secret_key
GEMINI_API_KEY=your_gemini_api_key  # optional; app falls back without it
```

5) Initialize the database

```bash
flask --app app init-db
```

6) Run the application

```bash
flask --app app run
# or for auto-reload during development
FLASK_DEBUG=1 flask --app app run
```

Visit `http://127.0.0.1:5000/`.

---

## Push to GitHub (safe)

This repo includes a `.gitignore` that excludes `.env`, `venv/`, `logs/`, and `database/*.db`.

1) Initialize git and commit

```bash
git init
git add .
git commit -m "feat: AI study planner initial version"
```

2) Create a new GitHub repository and push

```bash
git remote add origin https://github.com/<your-user>/<your-repo>.git
git branch -M main
git push -u origin main
```

Ensure `.env` is not committed.

---

## Deploy on Render (recommended)

Files included: `render.yaml`, `Procfile`, `gunicorn_config.py`.

1) Push your code to GitHub
2) In Render, New → Blueprint, select your repo
3) Confirm settings and click Deploy
4) Set environment variables in Render → Environment
   - `FLASK_SECRET_KEY`
   - `GEMINI_API_KEY`
5) Initialize the database once (via Shell or one-off command)

```bash
flask --app app init-db
```

6) Open your Render service URL

Note: Free plans have ephemeral disks. For persistence, attach a Render Disk or migrate to a managed DB.

---

## Docker (build and run)

```bash
docker build -t study-planner .
docker run -p 8080:8080 \
  -e FLASK_SECRET_KEY=your_secret_key \
  -e GEMINI_API_KEY=your_gemini_api_key \
  study-planner
```

Open `http://localhost:8080`.

---

## Usage

- On the landing page, click "Create a Plan" to open the generation form.
- Provide title, subjects, date range, hours/day, off-days, optional marks JSON, and any fixed/class schedule.
- Submit to generate; view the guide, resources, and schedule on the plan page.
- Use buttons to switch Day/Week/Month/List/Raw. Use Print/Save to export.
- If the schedule fails to render, click "Attempt to Fix JSON" to repair it.

---

## Endpoints

- `GET /` — Landing page
- `GET, POST /generate` — Plan creation form and generation
- `GET /plans` — List saved plans
- `GET /plan/<id>` — View a plan (guide, resources, calendar)
- `POST /fix-schedule/<id>` — Attempt to repair malformed schedule JSON
  (download endpoint removed; use Raw view or Print/Save)

---

## Data Model (SQLite)

- `plans`
  - `title`, `description`, `start_date`, `end_date`
  - `subjects` (comma-separated string)
  - `learning_goal`, `difficulty_feedback`
  - `hours_per_day` (REAL)
  - `off_days` (comma-separated)
  - `class_schedule` (TEXT)
  - `generated_guide` (TEXT)
  - `generated_schedule` (TEXT, JSON string)
  - `resources` (TEXT)
  - `created_at`

- `subject_marks`
  - `plan_id`, `subject_name`, `component_type`, `assessment_name`, `max_marks`, `obtained_marks`

Schedule format stored in `generated_schedule`:

```json
{
  "YYYY-MM-DD": [
    { "start_time": "HH:MM", "end_time": "HH:MM", "subject": "...", "task": "..." }
  ]
}
```

Off-days are present with an empty array for that date.

---

## AI Integration and Resilience

- Uses `google-generativeai` to request a strict JSON object with keys: `learning_guide`, `resources`, `schedule`.
- If the response includes formatting or extra text, the app attempts to extract JSON.
- If extraction fails or no key is set, the app falls back to a simple time-block schedule across subjects.

---

## Troubleshooting

- No API key: The app still runs using fallback guide/resources and a basic schedule.
- Schedule not rendering: On a plan page, click "Attempt to Fix JSON" to re-extract or rebuild.
- Dates/times: Ensure dates are `YYYY-MM-DD` and times are `HH:MM`.
- Reset DB (dev only): `rm database/planner.db && flask --app app init-db`
- Logs: Check `logs/ai-planner.log` for warnings/errors.

---

## License

MIT License. See `LICENSE` if present in your repository.


