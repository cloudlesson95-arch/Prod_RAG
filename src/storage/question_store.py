import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from src.config import DB_PATH
from src.storage.doc_registry import init_registry_db


def init_question_db(conn: sqlite3.Connection) -> None:
    """Ensure the doc_questions table exists, next to ingested_documents, which it joins with."""
    init_registry_db(conn)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS doc_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            context TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()


@contextmanager
def _connection(db_path: str):
    """Open the database with both tables in place; commit on success and always close."""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        init_question_db(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def replace_questions(source: str, file_hash: str, items: list[dict], db_path: str = DB_PATH) -> None:
    """Store the generated questions for one version of a document, replacing every earlier one for that source.

    Args:
        items: Dicts with 'question', 'answer' and 'context' (the chunk they were written from).
            An empty list leaves the document without questions, so a later batch fills it in.
    """
    now_utc = datetime.now(timezone.utc).isoformat()
    with _connection(db_path) as conn:
        conn.execute("DELETE FROM doc_questions WHERE source = ?", (source,))
        conn.executemany(
            "INSERT INTO doc_questions (source, file_hash, question, answer, context, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(source, file_hash, item["question"], item["answer"], item["context"], now_utc) for item in items],
        )


def get_current_questions(db_path: str = DB_PATH) -> list[dict]:
    """Questions whose document is still indexed in the version they were written for.

    The join on (source, file_hash) drops questions of modified or deleted documents without a cleanup step,
    and keeps them through `index --rebuild`, which re-registers every document with the same hash.
    """
    with _connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT q.source, q.question, q.answer, q.context
            FROM doc_questions q
            JOIN ingested_documents d ON d.filename = q.source AND d.file_hash = q.file_hash
            ORDER BY q.source, q.id
        """).fetchall()
    return [dict(row) for row in rows]


def sources_missing_questions(db_path: str = DB_PATH) -> list[str]:
    """Indexed documents without questions for their current version: new, changed, or generation failed."""
    with _connection(db_path) as conn:
        rows = conn.execute("""
            SELECT d.filename FROM ingested_documents d
            WHERE NOT EXISTS (
                SELECT 1 FROM doc_questions q WHERE q.source = d.filename AND q.file_hash = d.file_hash
            )
            ORDER BY d.filename
        """).fetchall()
    return [row[0] for row in rows]
