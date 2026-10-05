import pytest
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

from src.routing.corpus_probe import probe_corpus


class TableEmbeddings(Embeddings):
    """Fixed vectors per text, so similarities are known exactly."""

    def __init__(self, table):
        self.table = table

    def embed_documents(self, texts):
        return [self.table[t] for t in texts]

    def embed_query(self, text):
        return self.table[text]


def test_probe_returns_closest_chunk_source_and_cosine(tmp_path):
    """Verify the nearest chunk's source is returned with an exact cosine, even for an unnormalized query."""
    embeddings = TableEmbeddings({"Cats purr.": [1.0, 0.0, 0.0], "Quokkas smile.": [0.0, 1.0, 0.0]})
    vectorstore = Chroma(persist_directory=str(tmp_path), embedding_function=embeddings)
    vectorstore.add_texts(
        ["Cats purr.", "Quokkas smile."],
        metadatas=[{"source": "cat-facts.txt"}, {"source": "ingested/batch/quokka.txt"}],
    )

    source, similarity = probe_corpus([3.0, 4.0, 0.0], vectorstore)  # cosine 0.8 to quokka, 0.6 to cats

    assert source == "ingested/batch/quokka.txt"
    assert similarity == pytest.approx(0.8)


def test_probe_on_empty_index_returns_none(tmp_path):
    """Verify an empty index never triggers retrieval."""
    vectorstore = Chroma(persist_directory=str(tmp_path), embedding_function=TableEmbeddings({}))
    assert probe_corpus([1.0, 0.0, 0.0], vectorstore) == (None, 0.0)


def test_probe_sees_chunks_added_after_its_first_call(tmp_path):
    """Verify the cached matrix reloads when the collection grows, as it does inside an ingest-batch run."""
    embeddings = TableEmbeddings({"Cats purr.": [1.0, 0.0, 0.0], "Quokkas smile.": [0.0, 1.0, 0.0]})
    vectorstore = Chroma(persist_directory=str(tmp_path), embedding_function=embeddings)
    vectorstore.add_texts(["Cats purr."], metadatas=[{"source": "cat-facts.txt"}])
    assert probe_corpus([0.0, 1.0, 0.0], vectorstore)[0] == "cat-facts.txt"

    vectorstore.add_texts(["Quokkas smile."], metadatas=[{"source": "ingested/batch/quokka.txt"}])

    assert probe_corpus([0.0, 1.0, 0.0], vectorstore) == ("ingested/batch/quokka.txt", pytest.approx(1.0))
