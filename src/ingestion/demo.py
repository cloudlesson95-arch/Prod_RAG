import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass

from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import CHUNK_SIZE, CHUNK_OVERLAP, DEMO_TTL_SECONDS, DEMO_MAX_DOCS
from src.core.rag_agent import Passage, retrieve_chunks, score_passages
from src.logging_config import setup_logging

logger = setup_logging(__name__)

DEMO_ANSWER_PROMPT = """Answer ONLY based on the provided context.
If the answer is not in the context, say "I don't know."

Context:
{context}

Question: {question}
Answer:"""


@dataclass
class DemoDocument:
    doc_id: str
    filename: str
    chunks: int
    vectorstore: Chroma
    last_used: float


class DemoStore:
    """Uploaded demo documents, each in its own in-memory Chroma collection.

    Per instance and never persisted: nothing here touches DATA_DIR, the shared index,
    the routers, the semantic cache or the state snapshot. A document is dropped after
    ttl_seconds without use; at max_docs the least recently used one is dropped.
    """

    def __init__(self, embeddings, ttl_seconds: float = DEMO_TTL_SECONDS,
                 max_docs: int = DEMO_MAX_DOCS, clock=time.monotonic):
        self._embeddings = embeddings
        self._ttl_seconds = ttl_seconds
        self._max_docs = max_docs
        self._clock = clock
        self._docs: OrderedDict[str, DemoDocument] = OrderedDict()  # least recently used first
        self._lock = threading.Lock()

    def add(self, filename: str, text: str) -> DemoDocument:
        """Chunk and embed text into a new collection and return the stored document."""
        doc_id = secrets.token_hex(16)
        splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        chunks = splitter.create_documents([text], metadatas=[{"source": filename}])

        # Embedding is the slow part: do it before taking the lock so other requests aren't blocked.
        vectorstore = Chroma(collection_name=f"demo-{doc_id}", embedding_function=self._embeddings)
        vectorstore.add_documents(chunks)
        doc = DemoDocument(doc_id, filename, len(chunks), vectorstore, self._clock())

        with self._lock:
            self._evict_expired()
            while len(self._docs) >= self._max_docs:
                _, oldest = self._docs.popitem(last=False)
                self._drop(oldest)
            self._docs[doc_id] = doc
            held = len(self._docs)
        logger.info(f"[Demo] Stored '{filename}' as {doc_id} ({len(chunks)} chunks, {held} held)")
        return doc

    def get(self, doc_id: str) -> DemoDocument | None:
        """Return a live document and mark it as just used, or None if it's unknown or expired."""
        with self._lock:
            self._evict_expired()
            doc = self._docs.get(doc_id)
            if doc is not None:
                doc.last_used = self._clock()
                self._docs.move_to_end(doc_id)
            return doc

    def _evict_expired(self) -> None:
        """Drop documents unused for ttl_seconds or longer. The caller holds the lock."""
        cutoff = self._clock() - self._ttl_seconds
        while self._docs:
            oldest = next(iter(self._docs.values()))
            if oldest.last_used > cutoff:
                break
            del self._docs[oldest.doc_id]
            self._drop(oldest)

    def _drop(self, doc: DemoDocument) -> None:
        try:
            doc.vectorstore.delete_collection()
        except Exception as e:
            logger.warning(f"[Demo] Could not delete the collection of {doc.doc_id}: {e}")
        logger.info(f"[Demo] Dropped {doc.doc_id} ('{doc.filename}')")


def answer_from_document(doc: DemoDocument, question: str, answer_llm) -> dict:
    """Answer a question from one demo document: hybrid search and rerank over its chunks only.

    No routing, multi-hop or semantic cache: the user already chose the document.

    Returns:
        dict: {"answer": str, "groundedness_score": float | None, "passages": list[dict]}
    """
    results = retrieve_chunks(question, "none", doc.vectorstore)
    context_text = "\n---\n".join(d.page_content for d in results)
    answer = answer_llm.invoke(DEMO_ANSWER_PROMPT.format(context=context_text, question=question)).content

    passages = [Passage(d.metadata.get("source", doc.filename), d.page_content) for d in results]
    groundedness = None
    if passages and "I don't know" not in answer:
        groundedness = score_passages(passages, answer, doc.vectorstore.embeddings)
    return {"answer": answer, "groundedness_score": groundedness, "passages": [asdict(p) for p in passages]}
