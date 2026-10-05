import re

from langchain_core.documents import Document

from src.collectors.github_releases import release_marker

# "v2.51.0", "V2.51.0" or "2.51.0", but not "2.51.0b3", "10.0.0.1" or "1.2"
_VERSION = re.compile(r"(?<![\w.])[vV]?(\d+\.\d+\.\d+)(?!\w|\.\d)")


def mentioned_versions(text: str) -> list[str]:
    """Release versions a question names, as '2.51.0', in order of appearance and without duplicates."""
    return list(dict.fromkeys(_VERSION.findall(text or "")))


def _named_release_filter(versions: list[str]) -> dict:
    """Chroma where_document filter for the chunks of these releases: their change lines start with the
    collector's marker, whether or not the tag has a 'v' prefix ('[v2.51.0]' or '[2.51.0]')."""
    markers = [release_marker(prefix + version) for version in versions for prefix in ("v", "")]
    return {"$or": [{"$contains": marker} for marker in markers]}


def chunks_of_named_release(vectorstore, query: str, source: str = "none") -> list[Document]:
    """All indexed chunks of the releases a question names, optionally within one source."""
    versions = mentioned_versions(query)
    if not versions:
        return []
    data = vectorstore.get(where={"source": source} if source and source != "none" else None,
                           where_document=_named_release_filter(versions))
    return [Document(page_content=text, metadata=meta) for text, meta in zip(data["documents"], data["metadatas"])]


def release_source(vectorstore, query: str) -> str | None:
    """The one source holding the releases a question names, or None (no version named, not indexed, or ambiguous)."""
    sources = {doc.metadata.get("source") for doc in chunks_of_named_release(vectorstore, query)}
    return sources.pop() if len(sources) == 1 else None
