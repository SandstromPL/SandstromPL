
#!/usr/bin/env python3
"""Refresh the public pull-request dashboard in README.md."""

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import os
import sys

README = Path("README.md")
START = "<!-- PR-DASHBOARD:START -->"
END = "<!-- PR-DASHBOARD:END -->"

API_URL = "https://api.github.com/search/issues"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OWNER = (
    os.environ.get("GITHUB_REPOSITORY_OWNER")
    or os.environ.get("GITHUB_ACTOR", "")
)


def search_prs(query):
    """Return up to 100 PRs matching a GitHub Search API query."""
    params = urlencode({
        "q": query,
        "sort": "updated",
        "order": "desc",
        "per_page": 100,
    })

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "profile-pr-dashboard",
    }

    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    request = Request(f"{API_URL}?{params}", headers=headers)

    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response).get("items", [])
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API returned HTTP {error.code}: {details}"
        ) from error


def get_status_prs(status):
    qualifiers = {
        "merged": "is:merged",
        "open": "is:open",
        "closed": "is:closed -is:merged",
    }

    return search_prs(f"is:pr author:{OWNER} {qualifiers[status]}")


def escape_markdown(text):
    """Keep PR titles from breaking the generated Markdown table."""
    return (
        str(text)
        .replace("|", "&#124;")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def build_dashboard():
    if not OWNER:
        raise RuntimeError("Could not determine the GitHub username.")

    statuses = {
        status: get_status_prs(status)
        for status in ("merged", "open", "closed")
    }

    # A repository entry contains counts and a deduplicated set of PRs.
    repositories = defaultdict(
        lambda: {
            "merged": 0,
            "open": 0,
            "closed": 0,
            "prs": {},
        }
    )

    for status, items in statuses.items():
        for pr in items:
            repo_url = pr.get("repository_url", "")
            prefix = "https://api.github.com/repos/"

            if not repo_url.startswith(prefix):
                continue

            repo = repo_url.removeprefix(prefix)
            entry = repositories[repo]
            entry[status] += 1
            entry["prs"][pr["html_url"]] = pr

    total_merged = sum(r["merged"] for r in repositories.values())
    total_open = sum(r["open"] for r in repositories.values())
    total_closed = sum(r["closed"] for r in repositories.values())

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"> **Last refreshed:** {now}",
        "",
        "| 🟢 Merged | 🔵 Open | 🟠 Closed (not merged) | Repositories |",
        "|:---:|:---:|:---:|:---:|",
        (
            f"| **{total_merged}** | **{total_open}** "
            f"| **{total_closed}** | **{len(repositories)}** |"
        ),
        "",
    ]

    if not repositories:
        lines.append(
            "No public pull requests were found for this account."
        )
        return "\n".join(lines)

    lines.extend([
        "### Repository breakdown",
        "",
        "| Repository | 🟢 Merged | 🔵 Open | 🟠 Closed | Recent pull requests |",
        "|---|---:|---:|---:|---|",
    ])

    ordered_repos = sorted(
        repositories.items(),
        key=lambda item: (
            sum(item[1][s] for s in ("merged", "open", "closed")),
            item[1]["merged"],
            item[0].lower(),
        ),
        reverse=True,
    )

    for repo, data in ordered_repos:
        repo_link = f"https://github.com/{repo}"

        recent = sorted(
            data["prs"].values(),
            key=lambda pr: pr.get("updated_at", ""),
            reverse=True,
        )[:3]

        if recent:
            links = "<br>".join(
                f"[#{pr['number']} {escape_markdown(pr['title'])}]"
                f"({pr['html_url']})"
                for pr in recent
            )
        else:
            links = "—"

        lines.append(
            f"| [{repo}]({repo_link}) "
            f"| {data['merged']} "
            f"| {data['open']} "
            f"| {data['closed']} "
            f"| {links} |"
        )

    lines.extend([
        "",
        (
            "<sub>Counts cover public PRs authored by this account. "
            "Recent links are ordered by last update. GitHub Search API "
            "returns at most 1,000 results per query.</sub>"
        ),
    ])

    return "\n".join(lines)


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

    end += len(END)
    dashboard = build_dashboard()
    replacement = f"{START}\n{dashboard}\n{END}"

    updated = content[:start] + replacement + content[end:]
    README.write_text(updated, encoding="utf-8")

    print("README.md dashboard updated successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Dashboard update failed: {error}", file=sys.stderr)
        sys.exit(1)