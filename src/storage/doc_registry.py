import sqlite3
import os
from datetime import datetime, timezone
from typing import Dict, Any
from src.config import DB_PATH
from src.logging_config import setup_logging

logger = setup_logging(__name__)


def init_registry_db(conn: sqlite3.Connection) -> None:
    """Ensure the ingested_documents table exists."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingested_documents (
            filename TEXT PRIMARY KEY,
            file_hash TEXT NOT NULL,
            chunk_count INTEGER NOT NULL,
            file_size INTEGER NOT NULL,
            ingested_at TEXT NOT NULL
        )
    """)
    conn.commit()


def get_registered_documents(db_path: str = DB_PATH) -> Dict[str, Dict[str, Any]]:
    """Retrieve all ingested documents indexed by filename."""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        init_registry_db(conn)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT filename, file_hash, chunk_count, file_size, ingested_at FROM ingested_documents")
        rows = cursor.fetchall()
        return {
            row["filename"]: {
                "file_hash": row["file_hash"],
                "chunk_count": row["chunk_count"],
                "file_size": row["file_size"],
                "ingested_at": row["ingested_at"],
            }
            for row in rows
        }


def upsert_document_record(
    filename: str,
    file_hash: str,
    chunk_count: int,
    file_size: int,
    db_path: str = DB_PATH
) -> None:
    """Insert or update a document record in the registry."""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    now_utc = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        init_registry_db(conn)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ingested_documents (filename, file_hash, chunk_count, file_size, ingested_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                file_hash = excluded.file_hash,
                chunk_count = excluded.chunk_count,
                file_size = excluded.file_size,
                ingested_at = excluded.ingested_at
        """, (filename, file_hash, chunk_count, file_size, now_utc))
        conn.commit()


def delete_document_record(filename: str, db_path: str = DB_PATH) -> None:
    """Remove a document record from the registry."""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        init_registry_db(conn)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ingested_documents WHERE filename = ?", (filename,))
        conn.commit()


def clear_document_registry(db_path: str = DB_PATH) -> None:
    """Clear all records from the document registry."""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        init_registry_db(conn)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ingested_documents")
        conn.commit()
