"""Thin wrapper around the GitHub Issues REST API.

The backlog lives in one GitHub repo. This file is the only place that talks to GitHub.
"""

import os

import httpx
from dotenv import load_dotenv

load_dotenv()

API = "https://api.github.com"


def _client() -> httpx.Client:
    token = os.environ["GITHUB_TOKEN"]
    return httpx.Client(
        base_url=f"{API}/repos/{os.environ['GITHUB_REPO']}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=20,
    )


def list_open_issues(search_terms: str | None = None, limit: int = 25) -> list[dict]:
    """Open issues, newest first. Keyword filtering happens here rather than in
    GitHub search, because search indexing lags and would hide a ticket filed seconds ago."""
    with _client() as gh:
        r = gh.get("/issues", params={"state": "open", "per_page": 100})
        r.raise_for_status()
    issues = [i for i in r.json() if "pull_request" not in i]

    if search_terms:
        words = [w.lower() for w in search_terms.split() if len(w) > 2]
        issues = [
            i for i in issues
            if any(w in f"{i['title']} {i.get('body') or ''}".lower() for w in words)
        ]

    return [
        {
            "number": i["number"],
            "title": i["title"],
            "labels": [label["name"] for label in i["labels"]],
            "url": i["html_url"],
            "created_at": i["created_at"],
            "body_excerpt": (i.get("body") or "")[:300],
        }
        for i in issues[:limit]
    ]


def create_issue(title: str, body: str, labels: list[str]) -> dict:
    with _client() as gh:
        r = gh.post("/issues", json={"title": title, "body": body, "labels": labels})
        r.raise_for_status()
    i = r.json()
    return {"number": i["number"], "url": i["html_url"], "title": i["title"]}


def comment_on_issue(issue_number: int, comment: str) -> dict:
    with _client() as gh:
        r = gh.post(f"/issues/{issue_number}/comments", json={"body": comment})
        r.raise_for_status()
    return {"url": r.json()["html_url"]}
