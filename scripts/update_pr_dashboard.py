#!/usr/bin/env python3
"""Generate a repository-wise dashboard of public PRs authored by a GitHub user."""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

USERNAME = os.environ.get("GITHUB_USERNAME", "").strip()
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
README = os.environ.get("README_PATH", "README.md")
START = "<!-- PR-DASHBOARD:START -->"
END = "<!-- PR-DASHBOARD:END -->"
PER_PAGE = 100
MAX_PAGES = 10  # GitHub Search API returns at most 1,000 results per query

if not USERNAME:
    sys.exit("Set GITHUB_USERNAME to the profile owner's GitHub username.")

def api_get(url):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-pr-profile-dashboard",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(url, headers=headers)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429) and attempt < 4:
                retry_after = exc.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else (2 ** (attempt + 1))
                time.sleep(min(wait, 60))
                continue
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            if attempt == 4:
                raise RuntimeError(f"Network error calling GitHub API: {exc}") from exc
            time.sleep(2 ** attempt)

def search_prs(status_query):
    query = urllib.parse.quote(f"author:{USERNAME} is:pr {status_query}")
    items = []
    for page in range(1, MAX_PAGES + 1):
        url = (
            "https://api.github.com/search/issues"
            f"?q={query}&per_page={PER_PAGE}&page={page}&sort=updated&order=desc"
        )
        data = api_get(url)
        batch = data.get("items", [])
        for item in batch:
            item["_dashboard_status"] = status_query
        items.extend(batch)
        if len(batch) < PER_PAGE or len(items) >= min(data.get("total_count", 0), 1000):
            break
    return items

def fetch_authored_prs():
    # Separate searches avoid relying on fields the Search API doesn't return
    # (the search result's pull_request object has no merged_at field).
    all_items = []
    for query in ("is:merged", "is:open", "is:closed -is:merged"):
        all_items.extend(search_prs(query))
    # Defensive deduplication in case GitHub search indexing overlaps briefly.
    unique = {}
    for pr in all_items:
        unique[pr["html_url"]] = pr
    return list(unique.values())

def status_of(pr):
    status = pr.get("_dashboard_status", "")
    if "is:merged" == status or status.endswith("is:merged"):
        return "merged"
    if "is:open" in status:
        return "open"
    return "closed"

def escape_cell(value):
    return str(value).replace("|", r"\|").replace("\n", " ").replace("\r", " ")

def render_dashboard(items):
    repos = defaultdict(list)
    for pr in items:
        repo = pr.get("repository_url", "").removeprefix("https://api.github.com/repos/")
        if repo:
            repos[repo].append(pr)

    merged_total = sum(1 for p in items if status_of(p) == "merged")
    open_total = sum(1 for p in items if status_of(p) == "open")
    closed_total = sum(1 for p in items if status_of(p) == "closed")

    lines = [
        "## Open-source PR dashboard",
        "",
        f"> Public pull requests authored by **[@{USERNAME}](https://github.com/{USERNAME})**. "
        "Updated automatically by GitHub Actions.",
        "",
        "| Total PRs | Merged | Open | Closed without merge | Repositories |",
        "|---:|---:|---:|---:|---:|",
        f"| {len(items)} | {merged_total} | {open_total} | {closed_total} | {len(repos)} |",
        "",
    ]

    if not repos:
        lines += ["_No public authored PRs were found for this account yet._", ""]
    else:
        lines += [
            "| Repository | Total | Merged | Open | Closed without merge | Recent PRs |",
            "|---|---:|---:|---:|---:|---|",
        ]
        sorted_repos = sorted(
            repos.items(),
            key=lambda pair: (
                sum(1 for p in pair[1] if status_of(p) == "merged"),
                len(pair[1]),
                pair[0].lower(),
            ),
            reverse=True,
        )
        for repo, prs in sorted_repos:
            merged = sum(1 for p in prs if status_of(p) == "merged")
            opened = sum(1 for p in prs if status_of(p) == "open")
            closed = sum(1 for p in prs if status_of(p) == "closed")
            recent = sorted(prs, key=lambda p: p.get("updated_at", ""), reverse=True)[:3]
            links = "<br>".join(
                f"[#{p['number']} {escape_cell(p.get('title', 'Pull request'))}]({p['html_url']})"
                for p in recent
            )
            lines.append(
                f"| [{escape_cell(repo)}](https://github.com/{repo}) | {len(prs)} | {merged} | "
                f"{opened} | {closed} | {links} |"
            )
        lines.append("")

    lines += [
        f"<sub>Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. "
        "Counts cover public PRs returned by GitHub Search API; each status query is capped "
        "at 1,000 results. Draft PRs are included.</sub>",
        "",
    ]
    return "\n".join(lines)

def update_readme(content):
    try:
        with open(README, "r", encoding="utf-8") as handle:
            readme = handle.read()
    except FileNotFoundError:
        readme = f"# {USERNAME}\n\n{START}\n{END}\n"

    if START not in readme or END not in readme:
        raise RuntimeError(
            f"README must contain these markers on separate lines:\n{START}\n{END}"
        )
    before, remainder = readme.split(START, 1)
    _, after = remainder.split(END, 1)
    updated = before + START + "\n" + content.rstrip() + "\n" + END + after
    with open(README, "w", encoding="utf-8") as handle:
        handle.write(updated)

if __name__ == "__main__":
    prs = fetch_authored_prs()
    update_readme(render_dashboard(prs))
    print(f"Updated {README}: {len(prs)} public PRs across the dashboard.")
