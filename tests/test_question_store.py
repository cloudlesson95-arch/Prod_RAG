from src.storage import question_store
from src.storage.doc_registry import delete_document_record, upsert_document_record


def _qa(question):
    return {"question": question, "answer": f"answer to {question}", "context": f"chunk for {question}"}


def _register(db, filename, file_hash):
    upsert_document_record(filename, file_hash, chunk_count=3, file_size=100, db_path=db)


def test_questions_follow_the_indexed_version(tmp_path):
    """Verify questions count only while their document's hash matches, and a new version starts without any."""
    db = str(tmp_path / "rag.db")
    _register(db, "ingested/batch/quokkas.md", "h1")
    question_store.replace_questions("ingested/batch/quokkas.md", "h1", [_qa("Q1"), _qa("Q2")], db_path=db)
    assert [q["question"] for q in question_store.get_current_questions(db_path=db)] == ["Q1", "Q2"]

    _register(db, "ingested/batch/quokkas.md", "h2")  # the document changed

    assert question_store.get_current_questions(db_path=db) == []
    assert question_store.sources_missing_questions(db_path=db) == ["ingested/batch/quokkas.md"]

    question_store.replace_questions("ingested/batch/quokkas.md", "h2", [_qa("Q3")], db_path=db)

    assert question_store.get_current_questions(db_path=db) == [
        {"source": "ingested/batch/quokkas.md", "question": "Q3", "answer": "answer to Q3", "context": "chunk for Q3"}
    ]
    assert question_store.sources_missing_questions(db_path=db) == []


def test_deleted_document_drops_out_of_both_views(tmp_path):
    """Verify a deleted document's questions no longer count, and it isn't reported as missing questions either."""
    db = str(tmp_path / "rag.db")
    _register(db, "ingested/batch/quokkas.md", "h1")
    question_store.replace_questions("ingested/batch/quokkas.md", "h1", [_qa("Q1")], db_path=db)

    delete_document_record("ingested/batch/quokkas.md", db_path=db)

    assert question_store.get_current_questions(db_path=db) == []
    assert question_store.sources_missing_questions(db_path=db) == []


def test_replacing_drops_earlier_questions_and_empty_means_missing(tmp_path):
    """Verify a replace keeps only the new questions, and an empty replace leaves the document to be filled in later."""
    db = str(tmp_path / "rag.db")
    _register(db, "cat-facts.txt", "h1")
    _register(db, "ingested/batch/quokkas.md", "h1")
    question_store.replace_questions("cat-facts.txt", "h1", [_qa("Q1"), _qa("Q2")], db_path=db)
    question_store.replace_questions("cat-facts.txt", "h1", [_qa("Q3")], db_path=db)

    assert [q["question"] for q in question_store.get_current_questions(db_path=db)] == ["Q3"]
    assert question_store.sources_missing_questions(db_path=db) == ["ingested/batch/quokkas.md"]

    question_store.replace_questions("cat-facts.txt", "h1", [], db_path=db)

    assert question_store.sources_missing_questions(db_path=db) == ["cat-facts.txt", "ingested/batch/quokkas.md"]


def test_fresh_database_creates_both_tables(tmp_path):
    """Verify reads work on an empty database, as at image build time before any document is registered."""
    db = str(tmp_path / "new" / "rag.db")
    assert question_store.get_current_questions(db_path=db) == []
    assert question_store.sources_missing_questions(db_path=db) == []
