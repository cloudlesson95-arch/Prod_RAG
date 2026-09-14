import os
import hashlib
import shutil
from typing import Dict, List, Tuple, Set, Any
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from src.config import (
    CHUNK_SIZE, CHUNK_OVERLAP, DATA_DIR, CHROMA_PERSIST_DIR,
    EMBEDDING_LOCAL_MODEL, DB_PATH
)
from src.storage.doc_registry import (
    get_registered_documents, upsert_document_record,
    delete_document_record, clear_document_registry
)
from src.logging_config import setup_logging

logger = setup_logging(__name__)

def compute_file_hash(filepath: str) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

def get_disk_documents(data_dir: str = DATA_DIR) -> Dict[str, Dict[str, Any]]:
    """Scan data directory and return details for supported files."""
    disk_docs = {}
    if not os.path.exists(data_dir):
        logger.warning(f"Data directory '{data_dir}' does not exist.")
        return disk_docs

    for root, _, files in os.walk(data_dir):
        for file in files:
            if file.endswith((".txt", ".md", ".json")):
                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, data_dir).replace("\\", "/")
                disk_docs[rel_path] = {
                    "path": filepath,
                    "hash": compute_file_hash(filepath),
                    "size": os.path.getsize(filepath)
                }
    return disk_docs

def compute_index_delta(
    disk_docs: Dict[str, Dict[str, Any]],
    registered_docs: Dict[str, Dict[str, Any]]
) -> Tuple[List[str], List[str], List[str], List[str]]:
    """Classify files into added, modified, deleted, and unchanged."""
    added = []
    modified = []
    deleted = []
    unchanged = []

    for filename, info in disk_docs.items():
        if filename not in registered_docs:
            added.append(filename)
        elif info["hash"] != registered_docs[filename]["file_hash"]:
            modified.append(filename)
        else:
            unchanged.append(filename)

    for filename in registered_docs:
        if filename not in disk_docs:
            deleted.append(filename)

    return added, modified, deleted, unchanged

def chunk_single_document(filename: str, filepath: str) -> Tuple[List[Any], List[str]]:
    """Split a single document into chunks with deterministic IDs."""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
    )
    chunks = splitter.create_documents([text], metadatas=[{"source": filename}])
    ids = [f"{filename}_chunk_{i}" for i in range(len(chunks))]
    return chunks, ids

def sync_incremental_index(force_rebuild: bool = False) -> Tuple[Chroma, Set[str]]:
    """Incrementally synchronize documents in DATA_DIR with ChromaDB and SQLite registry.
    
    Returns:
        Tuple[Chroma, Set[str]]: The updated vectorstore and a set of filenames that changed.
    """
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_LOCAL_MODEL)

    if force_rebuild:
        logger.info(f"Force rebuild requested. Clearing ChromaDB at '{CHROMA_PERSIST_DIR}' and DB registry...")
        if os.path.exists(CHROMA_PERSIST_DIR):
            shutil.rmtree(CHROMA_PERSIST_DIR)
        clear_document_registry()

    os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
    vectorstore = Chroma(persist_directory=CHROMA_PERSIST_DIR, embedding_function=embeddings)
    
    disk_docs = get_disk_documents(DATA_DIR)
    registered_docs = get_registered_documents()

    added, modified, deleted, unchanged = compute_index_delta(disk_docs, registered_docs)
    logger.info(
        f"[Index Sync] Delta: {len(added)} added, {len(modified)} modified, "
        f"{len(deleted)} deleted, {len(unchanged)} unchanged"
    )

    # Process Deletions and Modifications
    for filename in deleted + modified:
        logger.info(f"Removing old vectors for document: '{filename}'")
        try:
            vectorstore.delete(where={"source": filename})
        except Exception as e:
            logger.warning(f"Exception on vector deletion for '{filename}': {e}")

        if filename in deleted:
            delete_document_record(filename)

    # Process Additions and Modifications
    for filename in added + modified:
        info = disk_docs[filename]
        chunks, ids = chunk_single_document(filename, info["path"])
        logger.info(f"Indexing '{filename}': adding {len(chunks)} chunks")

        batch_size = 1000
        for i in range(0, len(chunks), batch_size):
            chunk_batch = chunks[i : i + batch_size]
            id_batch = ids[i : i + batch_size]
            vectorstore.add_documents(documents=chunk_batch, ids=id_batch)
            
        upsert_document_record(
            filename=filename,
            file_hash=info["hash"],
            chunk_count=len(chunks),
            file_size=info["size"]
        )

    changed_sources = set(added + modified + deleted)
    return vectorstore, changed_sources

def create_or_get_vectorstore(embeddings=None) -> Chroma:
    """Get or create the vector store.
    
    Args:
        embeddings: Optional custom embeddings (uses default if None)
        
    Returns:
        Chroma: The vector store instance
    """
    if embeddings is None:
        embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_LOCAL_MODEL)
        
    if os.path.exists(CHROMA_PERSIST_DIR):
        return Chroma(persist_directory=CHROMA_PERSIST_DIR, embedding_function=embeddings)
    else:
        logger.info("Chroma database not found. Performing initial sync...")
        vectorstore, _ = sync_incremental_index(force_rebuild=False)
        return vectorstore
