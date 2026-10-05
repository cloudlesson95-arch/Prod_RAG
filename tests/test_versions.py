from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

from src.retrieval import versions


class ConstantEmbeddings(Embeddings):
    """Same vector for every text: these tests only exercise metadata and document filters."""

    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


def test_mentioned_versions_normalizes_and_ignores_lookalikes():
    """Verify 'v2.51.0' and '2.52.0' are found once each, while prereleases, 4-part and 2-part numbers are not."""
    text = "What changed in v2.51.0 and 2.52.0? Not 2.51.0b3, 10.0.0.1 or 1.2, and v2.51.0 again."
    assert versions.mentioned_versions(text) == ["2.51.0", "2.52.0"]


def test_named_release_chunks_and_source_come_from_the_marker(tmp_path):
    """Verify only chunks carrying a release's marker count; prose that merely mentions the version doesn't."""
    vectorstore = Chroma(persist_directory=str(tmp_path), embedding_function=ConstantEmbeddings())
    vectorstore.add_texts(
        ["* [v2.51.0] Add OpenAI GPT-Live support (#8390)", "* [v2.52.0] Fix `web_fetch` (#8985)",
         "Upgrading from v2.51.0 needs no code changes."],
        metadatas=[{"source": "ingested/batch/releases.md"}, {"source": "ingested/batch/releases.md"},
                   {"source": "pydantic.llms-full.txt"}],
    )

    chunks = versions.chunks_of_named_release(vectorstore, "What changed in Pydantic AI 2.51.0?")

    assert [doc.page_content for doc in chunks] == ["* [v2.51.0] Add OpenAI GPT-Live support (#8390)"]
    assert versions.release_source(vectorstore, "What changed in v2.51.0?") == "ingested/batch/releases.md"
    assert versions.release_source(vectorstore, "What changed in v9.9.9?") is None
    assert versions.release_source(vectorstore, "What changed recently?") is None
