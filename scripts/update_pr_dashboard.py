#!/usr/bin/env python3
"""Refresh the open-source pull-request dashboard in README.md."""

from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import json
import os
import sys

from pr_dashboard_svg import build_assets, build_readme_block

README = Path("README.md")
ASSET_DIR = "assets/pr-dashboard"
START = "<!-- PR-DASHBOARD:START -->"
END = "<!-- PR-DASHBOARD:END -->"

API_ROOT = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OWNER = (
    os.environ.get("GITHUB_USERNAME")
    or os.environ.get("GITHUB_REPOSITORY_OWNER")
    or os.environ.get("GITHUB_ACTOR", "")
)
# PRs to your own repositories are not open-source contributions, so they are
# left out unless INCLUDE_OWN_REPOS=true.
INCLUDE_OWN_REPOS = os.environ.get("INCLUDE_OWN_REPOS", "").lower() in {
    "1", "true", "yes",
}

SEARCH_PAGE_SIZE = 100
SEARCH_RESULT_CAP = 1000  # The Search API never returns more than this.
REPO_METADATA_LIMIT = 50  # One REST call per repository; keep it bounded.


def github_get(path, params=None):
    """GET a GitHub REST API path and return the decoded JSON body."""
    url = f"{API_ROOT}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "profile-pr-dashboard",
    }

    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    try:
        with urlopen(Request(url, headers=headers), timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API returned HTTP {error.code} for {path}: {details}"
        ) from error


def pr_state(item):
    if (item.get("pull_request") or {}).get("merged_at"):
        return "merged"
    if item.get("state") == "open":
        return "draft" if item.get("draft") else "open"
    return "closed"


def fetch_pull_requests():
    """Return (total_count, PRs) for public PRs authored by OWNER."""
    # is:public keeps private PRs out even when run with a personal token.
    query = f"is:pr is:public author:{OWNER}"
    if not INCLUDE_OWN_REPOS:
        query += f" -user:{OWNER}"

    items, total_count = [], 0
    for page in range(1, SEARCH_RESULT_CAP // SEARCH_PAGE_SIZE + 1):
        result = github_get("/search/issues", {
            "q": query,
            "sort": "created",
            "order": "desc",
            "per_page": SEARCH_PAGE_SIZE,
            "page": page,
        })
        total_count = result.get("total_count", 0)
        batch = result.get("items", [])
        items.extend(batch)

        if len(batch) < SEARCH_PAGE_SIZE or len(items) >= total_count:
            break

    prefix = f"{API_ROOT}/repos/"
    prs = []

    for item in items:
        repo_url = item.get("repository_url", "")

        if not repo_url.startswith(prefix):
            continue

        prs.append({
            "repo": repo_url.removeprefix(prefix),
            "number": item["number"],
            "title": item.get("title", ""),
            "url": item["html_url"],
            "state": pr_state(item),
            "created_at": item["created_at"],
            "updated_at": item.get("updated_at"),
            "closed_at": item.get("closed_at"),
            "merged_at": (item.get("pull_request") or {}).get("merged_at"),
        })

    return total_count, prs


def fetch_repo_metadata(names):
    """Primary language per repository; unreachable repos are skipped."""
    repos = {}

    for name in names[:REPO_METADATA_LIMIT]:
        try:
            repo = github_get(f"/repos/{quote(name)}")
        except RuntimeError as error:
            print(f"Skipping metadata for {name}: {error}", file=sys.stderr)
            continue

        repos[name] = {"language": repo.get("language")}

    return repos


def collect_data():
    if not OWNER:
        raise RuntimeError("Could not determine the GitHub username.")

    total_count, prs = fetch_pull_requests()

    counts = {}
    for pr in prs:
        counts[pr["repo"]] = counts.get(pr["repo"], 0) + 1
    busiest_first = sorted(counts, key=lambda name: -counts[name])

    return {
        "user": {"login": OWNER},
        "generated_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "total_count": total_count,
        "prs": prs,
        "repos": fetch_repo_metadata(busiest_first),
    }


def main():
    if not README.exists():
        raise RuntimeError("README.md was not found.")

    content = README.read_text(encoding="utf-8")
    start = content.find(START)
    end = content.find(END)

    if start == -1 or end == -1 or end < start:
        raise RuntimeError(
            "README dashboard markers are missing or out of order."
        )

    data = collect_data()

    asset_dir = Path(ASSET_DIR)
    asset_dir.mkdir(parents=True, exist_ok=True)
    for name, svg in build_assets(data).items():
        (asset_dir / name).write_text(svg, encoding="utf-8")

    end += len(END)
    dashboard = build_readme_block(data, ASSET_DIR)
    replacement = f"{START}\n{dashboard}{END}"

    updated = content[:start] + replacement + content[end:]
    README.write_text(updated, encoding="utf-8")

    print("README.md dashboard updated successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Dashboard update failed: {error}", file=sys.stderr)
        sys.exit(1)
