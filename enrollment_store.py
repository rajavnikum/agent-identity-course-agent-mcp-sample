"""Local enrollment persistence across the tutorial's short-lived MCP processes."""
from pathlib import Path
import json
import os
import sqlite3


def _connect():
    path = Path(os.getenv('ENROLLMENT_DB_PATH', str(Path(__file__).with_name('enrollments.sqlite3'))))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE IF NOT EXISTS enrollments (subject TEXT NOT NULL, course_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(subject, course_id))')
    return conn


def list_enrollments(subject, fixtures=()):
    with _connect() as conn:
        rows = conn.execute('SELECT payload FROM enrollments WHERE subject=? ORDER BY course_id', (subject,)).fetchall()
    combined = {course['id']: dict(course) for course in fixtures}
    combined.update({course['id']: course for (value,) in rows for course in [json.loads(value)]})
    return list(combined.values())


def enroll(subject, course):
    record = {'id': course['id'], 'title': course['title'], 'status': 'enrolled'}
    with _connect() as conn:
        cursor = conn.execute('INSERT OR IGNORE INTO enrollments VALUES (?, ?, ?)', (subject, course['id'], json.dumps(record)))
        return cursor.rowcount == 1


def delete_enrollments(subject):
    """Delete only this subject's recorded enrollments, after gateway authorization."""
    with _connect() as conn:
        cursor = conn.execute('DELETE FROM enrollments WHERE subject=?', (subject,))
        return cursor.rowcount
