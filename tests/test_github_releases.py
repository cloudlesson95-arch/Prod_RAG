import os

import pytest
import requests

from src.collectors import github_releases
from src.ingestion.extract import safe_upload_name

# Shaped like GitHub's API response, newest first: a prerelease, a release with generated notes, one without notes
RELEASES = [
    {"tag_name": "v2.1.0rc1", "name": "v2.1.0rc1", "draft": False, "prerelease": True, "body": "rc"},
    {"tag_name": "v2.0.0", "name": "v2.0.0 (2026-10-02)", "draft": False, "prerelease": False,
     "body": "<!-- Release notes generated using configuration in .github/release.yml at main -->\r\n\r\n"
             "## What's Changed\r\n### 🚀 Features\r\n"
             "* Add `OpenAILiveModel` by @dsfaccini in https://github.com/pydantic/pydantic-ai/pull/8390\r\n"
             "* Map JSON decode errors by [@pydanty](https://github.com/apps/pydanty) in https://github.com/pydantic/pydantic-ai/pull/8846\r\n"
             "* Bump packages by @dependabot[bot] in https://github.com/pydantic/pydantic-ai/pull/9076\r\n\r\n"
             "## New Contributors\r\n"
             "* @newbie made their first contribution in https://github.com/pydantic/pydantic-ai/pull/9000\r\n\r\n\r\n"
             "**Full Changelog**: https://github.com/pydantic/pydantic-ai/compare/v1.9.0...v2.0.0\r\n"},
    {"tag_name": "v1.9.1", "name": "", "draft": False, "prerelease": False, "body": ""},
]


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} Client Error")


@pytest.fixture
def github(monkeypatch):
    """Fake GitHub API serving RELEASES. Returns the recorded requests."""
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return FakeResponse(RELEASES)

    monkeypatch.setattr(github_releases.requests, "get", fake_get)
    return calls


def test_fetch_skips_prereleases_and_sends_the_token(github):
    """Verify only published releases come back, newest first, and the token is sent as a Bearer header."""
    releases = github_releases.fetch_releases("pydantic/pydantic-ai", token="ghs_example")

    assert [r["tag_name"] for r in releases] == ["v2.0.0", "v1.9.1"]
    assert github[0]["url"] == "https://api.github.com/repos/pydantic/pydantic-ai/releases"
    assert github[0]["headers"]["Authorization"] == "Bearer ghs_example"
    assert github[0]["timeout"]


def test_limit_counts_published_releases_and_token_is_optional(github):
    """Verify the limit applies after skipping prereleases, and no Authorization header is sent without a token."""
    assert [r["tag_name"] for r in github_releases.fetch_releases("pydantic/pydantic-ai", limit=1)] == ["v2.0.0"]
    assert "Authorization" not in github[0]["headers"]


def test_render_strips_generated_noise_and_nests_headings():
    """Verify credits, PR links, the contributor list and the changelog link go, body headings nest under the release,
    and every change line carries its release tag."""
    text = github_releases.render_release_notes("pydantic/pydantic-ai", RELEASES[1:])

    assert text == (
        "# pydantic/pydantic-ai release notes\n\nSource: https://github.com/pydantic/pydantic-ai/releases\n\n"
        "## v2.0.0 (2026-10-02)\n\n"
        "### What's Changed\n#### 🚀 Features\n"
        "* [v2.0.0] Add `OpenAILiveModel` (#8390)\n* [v2.0.0] Map JSON decode errors (#8846)\n* [v2.0.0] Bump packages (#9076)\n\n"
        "## v1.9.1\n"
    )


def test_collect_writes_one_safe_file_with_stable_bytes(github, tmp_path):
    """Verify one safe-named file per repo, and identical bytes on a re-run (ingest-batch then sees it as unchanged)."""
    path, count = github_releases.collect_releases("pydantic/pydantic-ai", str(tmp_path / "inbox"))
    with open(path, "rb") as f:
        first = f.read()

    github_releases.collect_releases("pydantic/pydantic-ai", str(tmp_path / "inbox"))

    with open(path, "rb") as f:
        assert f.read() == first
    name = os.path.basename(path)
    assert (name, count) == ("pydantic-pydantic-ai-releases.md", 2)
    assert safe_upload_name(name) == name


def test_repo_without_releases_writes_nothing(monkeypatch, tmp_path):
    """Verify a repo with no published releases (likely a typo) raises before creating the inbox."""
    monkeypatch.setattr(github_releases.requests, "get", lambda *args, **kwargs: FakeResponse([]))

    with pytest.raises(ValueError):
        github_releases.collect_releases("someone/empty", str(tmp_path / "inbox"))
    assert not (tmp_path / "inbox").exists()


def test_api_errors_propagate(monkeypatch):
    """Verify a 404 (unknown repo) or 403 (rate limit) surfaces as a requests error for the CLI to report."""
    monkeypatch.setattr(github_releases.requests, "get", lambda *args, **kwargs: FakeResponse({}, status=404))

    with pytest.raises(requests.HTTPError):
        github_releases.fetch_releases("someone/missing")
