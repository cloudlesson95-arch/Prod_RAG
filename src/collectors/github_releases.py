import os
import re

import requests

from src.logging_config import setup_logging

logger = setup_logging(__name__)

GITHUB_API = "https://api.github.com"
# GitHub's generated release notes credit every change: "... by @user in <PR URL>" (also "[@app](url)" and "@name[bot]")
_AUTHOR_SUFFIX = re.compile(
    r" by (?:\[@[\w-]+\]\([^)\s]*\)|@[\w-]+(?:\[bot\])?) in https://github\.com/[\w.-]+/[\w.-]+/pull/(\d+)"
)
_DROPPED_LINE_PREFIXES = ("<!--", "**Full Changelog**", "## New Contributors")


def fetch_releases(repo: str, limit: int = 10, token: str | None = None) -> list[dict]:
    """Return the newest `limit` published releases of a GitHub repo, newest first. Drafts and prereleases are skipped.

    One page of 100 is plenty for a window of the newest releases.

    Raises:
        requests.RequestException: The API call failed (network, 403 rate limit, 404 unknown repo, ...).
    """
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.get(f"{GITHUB_API}/repos/{repo}/releases", params={"per_page": 100},
                            headers=headers, timeout=30)
    response.raise_for_status()
    releases = [r for r in response.json() if not r.get("draft") and not r.get("prerelease")]
    return releases[:limit]


def clean_release_body(body: str) -> str:
    """Strip generated-notes noise (author and PR links, contributor list, changelog link) and keep the change lines.

    Body headings move down one level so they nest under each release's '##' heading.
    """
    lines = []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        if line.startswith(_DROPPED_LINE_PREFIXES) or "made their first contribution" in line:
            continue
        line = _AUTHOR_SUFFIX.sub(r" (#\1)", line)
        lines.append("#" + line if line.startswith("#") else line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def render_release_notes(repo: str, releases: list[dict]) -> str:
    """Render releases as one Markdown document, newest first.

    Nothing run-dependent (such as a fetch time) goes in, so unchanged releases render byte-identically
    and ingest-batch reports the file as unchanged, which publishes nothing.
    """
    parts = [f"# {repo} release notes\n\nSource: https://github.com/{repo}/releases"]
    for release in releases:
        title = release.get("name") or release["tag_name"]
        body = clean_release_body(release.get("body") or "")
        parts.append(f"## {title}\n\n{body}" if body else f"## {title}")
    return "\n\n".join(parts) + "\n"


def release_notes_filename(repo: str) -> str:
    """'pydantic/pydantic-ai' -> 'pydantic-pydantic-ai-releases.md', which is already a safe batch filename."""
    return repo.replace("/", "-").lower() + "-releases.md"


def collect_releases(repo: str, inbox_dir: str, limit: int = 10, token: str | None = None) -> tuple[str, int]:
    """Write a repo's newest releases into inbox_dir as one Markdown file for ingest-batch.

    One file per repo, not per release: the centroid router keeps one centroid per file, and
    near-identical per-release files would split routing between them.

    Returns:
        tuple: (path of the written file, number of releases in it)

    Raises:
        requests.RequestException: The GitHub API call failed.
        ValueError: The repo has no published releases (probably a wrong repo name).
    """
    releases = fetch_releases(repo, limit, token)
    if not releases:
        raise ValueError(f"No published releases found for '{repo}'")

    os.makedirs(inbox_dir, exist_ok=True)
    path = os.path.join(inbox_dir, release_notes_filename(repo))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(render_release_notes(repo, releases))
    logger.info(f"[Collector] Wrote {len(releases)} releases of {repo} to {path}")
    return path, len(releases)
