PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    subjects TEXT NOT NULL,         -- comma-separated string
    learning_goal TEXT,             -- free text
    difficulty_feedback TEXT,       -- free text
    hours_per_day REAL NOT NULL,
    off_days TEXT,                  -- comma-separated days
    class_schedule TEXT,            -- free text
    generated_guide TEXT,           -- AI guide text
    generated_schedule TEXT NOT NULL, -- JSON string (date -> [blocks])
    resources TEXT,                 -- AI resources text or JSON
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subject_marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    subject_name TEXT NOT NULL,
    component_type TEXT,            -- e.g., exam, assignment, quiz
    assessment_name TEXT,           -- label/name
    max_marks REAL,
    obtained_marks REAL
);

