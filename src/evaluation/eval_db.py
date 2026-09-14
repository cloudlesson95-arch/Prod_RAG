import sqlite3
import os
from datetime import datetime, timezone
from typing import List, Dict, Any


def init_db(conn: sqlite3.Connection) -> None:
    """Ensure database schema exists using an active connection."""
    cursor = conn.cursor()
    
    # Table 1: Run-level metrics and configuration metadata
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS eval_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            main_model TEXT,
            eval_model TEXT,
            routing_method TEXT,
            k_retrieval INTEGER,
            precision_score REAL NOT NULL,
            total_questions INTEGER NOT NULL,
            successful_questions INTEGER NOT NULL,
            passed_threshold BOOLEAN NOT NULL
        )
    """)
    
    # Table 2: Detailed per-question results for each run
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS eval_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            question_id INTEGER,
            query TEXT NOT NULL,
            passed BOOLEAN NOT NULL,
            llm_answer TEXT,
            FOREIGN KEY (run_id) REFERENCES eval_runs (id) ON DELETE CASCADE
        )
    """)
    conn.commit()


def save_eval_run(
    db_path: str,
    main_model: str,
    eval_model: str,
    routing_method: str,
    k_retrieval: int,
    precision_score: float,
    total_questions: int,
    successful_questions: int,
    passed_threshold: bool,
    question_results: List[Dict[str, Any]]
) -> int:
    """Save evaluation metrics and results using a single connection & transaction."""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    now_utc = datetime.now(timezone.utc).isoformat()
    
    with sqlite3.connect(db_path) as conn:
        init_db(conn)  
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO eval_runs (
                timestamp, main_model, eval_model, routing_method, k_retrieval,
                precision_score, total_questions, successful_questions, passed_threshold
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now_utc, main_model, eval_model, routing_method, k_retrieval,
            precision_score, total_questions, successful_questions, passed_threshold
        ))
        
        run_id = cursor.lastrowid
        
        # Batch insert all per-question results in a single call
        results_data = [
            (run_id, q.get("id"), q["query"], q["passed"], q.get("llm_answer"))
            for q in question_results
        ]
        cursor.executemany("""
            INSERT INTO eval_results (
                run_id, question_id, query, passed, llm_answer
            ) VALUES (?, ?, ?, ?, ?)
        """, results_data)
            
        conn.commit()
        return run_id


def get_eval_history(db_path: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieve recent evaluation runs for CLI output using a single connection."""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        init_db(conn)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, timestamp, main_model, routing_method, k_retrieval,
                   precision_score, successful_questions, total_questions, passed_threshold
            FROM eval_runs
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
