"""Render a GitHub-native "Open-source contributions" showcase.

Public API:
    build_assets(data)                 -> {filename: svg_text} (light + dark)
    build_readme_block(data, asset_dir) -> Markdown/HTML for the README markers

Everything is pure standard library and deterministic for a given input.
The SVGs avoid web fonts, scripts, external references and foreignObject so
they render correctly when GitHub embeds them through <img>.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from html import escape as html_escape
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape, quoteattr

# --------------------------------------------------------------------------
# Design tokens
# --------------------------------------------------------------------------

THEMES = {
    "light": {
        "canvas": "#ffffff",
        "subtle": "#f6f8fa",
        "border": "#d0d7de",
        "track": "#eaeef2",
        "fg": "#1f2328",
        "muted": "#59636e",
        "merged": "#8250df",
        "open": "#1a7f37",
        "closed": "#d1242f",
        "draft": "#59636e",
        "accent": "#0969da",
        "star": "#9a6700",
    },
    "dark": {
        "canvas": "#0d1117",
        "subtle": "#151b23",
        "border": "#3d444d",
        "track": "#262c36",
        "fg": "#f0f6fc",
        "muted": "#9198a1",
        "merged": "#ab7df8",
        "open": "#3fb950",
        "closed": "#f85149",
        "draft": "#9198a1",
        "accent": "#4493f8",
        "star": "#d29922",
    },
}

LANGUAGE_COLORS = {
    "Python": "#3572A5",
    "C++": "#f34b7d",
    "C": "#555555",
    "Dart": "#00B4AB",
    "Jupyter Notebook": "#DA5B0B",
    "Go": "#00ADD8",
    "Rust": "#dea584",
    "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a",
    "Java": "#b07219",
}

FONT = ('-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",'
        'Helvetica,Arial,sans-serif')

# Octicons (16px grid), MIT licensed, https://primer.style/octicons
OCTICONS = {
    "pr": (
        "M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372"
        "A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854"
        "V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0"
        "-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354Z"
        "M3.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm0 9.5a.75.75 0 1 0 0"
        " 1.5.75.75 0 0 0 0-1.5Zm8.25.75a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Z"
    ),
    "merged": (
        "M5.45 5.154A4.25 4.25 0 0 0 9.25 7.5h1.378a2.251 2.251 0 1 1 0 1.5H9.25"
        "A5.734 5.734 0 0 1 5 7.123v3.505a2.25 2.25 0 1 1-1.5 0V5.372a2.25 2.25"
        " 0 1 1 1.95-.218ZM4.25 13.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm8.5"
        "-4.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5ZM5 3.25a.75.75 0 1 0 0 .005"
        "V3.25Z"
    ),
    "closed": (
        "M3.25 1A2.25 2.25 0 0 1 4 5.372v5.256a2.251 2.251 0 1 1-1.5 0V5.372"
        "A2.251 2.251 0 0 1 3.25 1Zm9.5 5.5a.75.75 0 0 1 .75.75v3.378a2.251"
        " 2.251 0 1 1-1.5 0V7.25a.75.75 0 0 1 .75-.75Zm-2.03-5.273a.75.75 0 0 1"
        " 1.06 0l.97.97.97-.97a.748.748 0 0 1 1.265.332.75.75 0 0 1-.205.729"
        "l-.97.97.97.97a.751.751 0 0 1-.018 1.042.751.751 0 0 1-1.042.018l-.97"
        "-.97-.97.97a.749.749 0 0 1-1.275-.326.749.749 0 0 1 .215-.734l.97-.97"
        "-.97-.97a.75.75 0 0 1 0-1.06ZM2.5 12.25a.75.75 0 1 0 1.5 0 .75.75 0 0"
        " 0-1.5 0ZM3.25 3.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm9.5 9.5a.75.75"
        " 0 1 0 0-1.5.75.75 0 0 0 0 1.5Z"
    ),
    "draft": (
        "M3.25 1A2.25 2.25 0 0 1 4 5.372v5.256a2.251 2.251 0 1 1-1.5 0V5.372"
        "A2.251 2.251 0 0 1 3.25 1Zm9.5 14a2.25 2.25 0 1 1 0-4.5 2.25 2.25 0 0 1"
        " 0 4.5ZM2.5 3.25a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0ZM3.25 12a.75.75"
        " 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm9.5 0a.75.75 0 1 0 0 1.5.75.75 0 0 0 0"
        "-1.5ZM14 7.5a1.25 1.25 0 1 1-2.5 0 1.25 1.25 0 0 1 2.5 0Zm0-4.25a1.25"
        " 1.25 0 1 1-2.5 0 1.25 1.25 0 0 1 2.5 0Z"
    ),
    "repo": (
        "M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1"
        "-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0"
        " 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708"
        "A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0"
        " 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4"
        " 15.7a.25.25 0 0 1-.4-.2Z"
    ),
    "star": (
        "M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416"
        " 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766"
        " 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416"
        "-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z"
    ),
}
OCTICONS["open"] = OCTICONS["pr"]

STATES = ("merged", "open", "closed")          # drafts are counted as open
STATE_LABELS = {"merged": "Merged", "open": "Open",
                "closed": "Closed", "draft": "Draft"}

WIDTH = 840          # viewBox width; README column is ~830px
PAD = 24             # inner horizontal padding
MAX_REPO_ROWS = 8
RECENT_PRS = 8
TITLE_CHARS = 90     # recent-PR titles longer than this are shortened

# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------


@dataclass
class RepoStats:
    full_name: str
    stars: int
    language: "str | None"
    counts: Counter = field(default_factory=Counter)

    @property
    def total(self):
        return sum(self.counts[s] for s in STATES)


@dataclass
class Stats:
    login: str
    total: int              # headline number (GitHub search total)
    loaded: int             # PRs actually present in data["prs"]
    counts: Counter         # merged / open (incl. drafts) / closed
    repos: list             # [RepoStats], most PRs first
    stars: int              # combined stars of contributed repos
    first: "datetime | None"
    monthly: list           # [(month_start, count)] oldest -> newest, 12 items
    now: datetime
    recent: list            # raw PR dicts, most recent activity first

    @property
    def merge_rate(self):
        decided = self.counts["merged"] + self.counts["closed"]
        return None if decided == 0 else self.counts["merged"] / decided


def parse_time(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ") if value else None


def bucket(state):
    """Map a PR state onto the three headline buckets."""
    return "open" if state == "draft" else state


def activity_time(pr):
    """When the PR last changed state: merged/closed date, else opened."""
    return pr.get("merged_at") or pr.get("closed_at") or pr["created_at"]


def shift_month(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def compute_stats(data):
    prs = data.get("prs") or []
    repo_meta = data.get("repos") or {}
    now = parse_time(data["generated_at"])

    counts = Counter(bucket(pr["state"]) for pr in prs)
    repos = {}
    for pr in prs:
        name = pr["repo"]
        if name not in repos:
            meta = repo_meta.get(name) or {}
            repos[name] = RepoStats(name, int(meta.get("stars") or 0),
                                    meta.get("language"))
        repos[name].counts[bucket(pr["state"])] += 1
    ordered = sorted(repos.values(), key=lambda r: (
        -r.total, -r.counts["merged"], -r.stars, r.full_name.lower()))

    months = [shift_month(now.year, now.month, -i) for i in range(11, -1, -1)]
    per_month = Counter((t.year, t.month) for t in
                        (parse_time(pr["created_at"]) for pr in prs))
    monthly = [(datetime(y, m, 1), per_month[(y, m)]) for y, m in months]

    created = [parse_time(pr["created_at"]) for pr in prs]
    recent = sorted(prs, key=lambda pr: (activity_time(pr), pr["repo"],
                                         pr["number"]), reverse=True)

    return Stats(
        login=data["user"]["login"],
        total=max(int(data.get("total_count") or 0), len(prs)),
        loaded=len(prs),
        counts=counts,
        repos=ordered,
        stars=sum(r.stars for r in ordered),
        first=min(created) if created else None,
        monthly=monthly,
        now=now,
        recent=recent,
    )

# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------


def fmt_int(n):
    return f"{n:,}"


def fmt_compact(n):
    """32326 -> 32.3k, 458000 -> 458k, 1234567 -> 1.2M."""
    for divisor, suffix in ((1_000_000, "M"), (1_000, "k")):
        if n >= divisor:
            value = n / divisor
            text = f"{value:.0f}" if value >= 100 else f"{value:.1f}"
            return text.removesuffix(".0") + suffix
    return str(n)


def fmt_rate(rate):
    return "—" if rate is None else f"{rate * 100:.0f}%"


def fmt_month(dt):
    return dt.strftime("%b %Y") if dt else "—"


def fmt_day(dt, now):
    """GitHub style: "Oct 12" this year, "Aug 25, 2025" otherwise."""
    day = f"{dt.strftime('%b')} {dt.day}"
    return day if dt.year == now.year else f"{day}, {dt.year}"


def fmt_date(dt):
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}"


def plural(n, word, words=None):
    return word if n == 1 else (words or word + "s")

# --------------------------------------------------------------------------
# Text measurement (conservative, font metrics are unknown at build time)
# --------------------------------------------------------------------------

# Helvetica/Arial advance widths in 1/1000 em for printable ASCII (32..126).
_ASCII_WIDTHS = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333,
    278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278,
    584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278,
    500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944,
    667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556,
    278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500,
    278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
]
SAFETY = 1.15        # system fonts differ by up to ~15% from Helvetica


def text_width(text, size, bold=False):
    units = 0
    for ch in text:
        code = ord(ch)
        if 32 <= code <= 126:
            units += _ASCII_WIDTHS[code - 32]
        else:
            units += 1000 if code >= 0x2E80 else 650
    return units / 1000 * size * (1.07 if bold else 1.0) * SAFETY


def truncate(text, max_width, size, bold=False):
    if text_width(text, size, bold) <= max_width:
        return text
    while text and text_width(text + "…", size, bold) > max_width:
        text = text[:-1]
    return text.rstrip() + "…"

# --------------------------------------------------------------------------
# SVG primitives
# --------------------------------------------------------------------------


def attrs(**kwargs):
    """Render keyword args as XML attributes (foo_bar -> foo-bar)."""
    return "".join(f" {k.rstrip('_').replace('_', '-')}={quoteattr(str(v))}"
                   for k, v in kwargs.items() if v is not None)


def text(x, y, content, size, fill, weight=None, anchor=None, **extra):
    return (f"<text{attrs(x=x, y=y, font_size=size, fill=fill, font_weight=weight, text_anchor=anchor, **extra)}>"
            f"{content}</text>")


def tspan(content, fill=None, weight=None, size=None, dx=None):
    return (f"<tspan{attrs(dx=dx, fill=fill, font_weight=weight, font_size=size)}>"
            f"{xml_escape(content)}</tspan>")


def icon(name, x, y, size, fill):
    scale = size / 16
    return (f'<path transform="translate({x} {y}) scale({scale:g})" '
            f'fill="{fill}" d="{OCTICONS[name]}"/>')


def fmt_num(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def segmented_bar(x, y, width, height, parts, track, clip_id, gap=2,
                  min_part=4):
    """A rounded bar split into coloured parts: [(value, colour), ...].

    The parts fill `width` pixels; `track` = (colour, track_width) draws the
    empty rail behind them so bars of different lengths share one scale.
    """
    track_color, track_width = track
    radius = height / 2
    out = [f'<rect{attrs(x=x, y=y, width=fmt_num(track_width), height=height, rx=radius, fill=track_color)}/>']
    parts = [(v, c) for v, c in parts if v > 0]
    total = sum(v for v, _ in parts)
    if not total or width <= 0:
        return "".join(out)

    # Distribute pixels, guaranteeing every non-zero part stays visible.
    usable = width - gap * (len(parts) - 1)
    sizes = [max(min_part, usable * v / total) for v, _ in parts]
    overflow = sum(sizes) - usable
    if overflow > 0:
        biggest = sizes.index(max(sizes))
        sizes[biggest] -= overflow

    out.append(f'<clipPath id="{clip_id}"><rect{attrs(x=x, y=y, width=fmt_num(width), height=height, rx=radius)}/></clipPath>')
    out.append(f'<g clip-path="url(#{clip_id})">')
    cursor = x
    for size, (_, color) in zip(sizes, parts):
        out.append(f'<rect{attrs(x=fmt_num(cursor), y=y, width=fmt_num(size), height=height, fill=color)}/>')
        cursor += size + gap
    out.append("</g>")
    return "".join(out)


def svg_document(height, title, desc, body, theme):
    """Wrap `body` in a bordered card. Deliberately static: GitHub's mobile
    app and image caches can show the first frame of any animation."""
    t = THEMES[theme]
    card = (f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{height - 1}" '
            f'rx="6" fill="{t["canvas"]}" stroke="{t["border"]}"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img" aria-labelledby="title desc"'
        f'{attrs(font_family=FONT)}>'
        f'<title id="title">{xml_escape(title)}</title>'
        f'<desc id="desc">{xml_escape(desc)}</desc>'
        f'{card}{body}</svg>\n'
    )

# --------------------------------------------------------------------------
# Visual 1: summary card
# --------------------------------------------------------------------------


def summary_description(s):
    if s.total == 0:
        return f"{s.login} has no public open-source pull requests yet."
    c = s.counts
    return (f"{s.login} has opened {fmt_int(s.total)} open-source pull "
            f"{plural(s.total, 'request')}: {fmt_int(c['merged'])} merged, "
            f"{fmt_int(c['open'])} open and {fmt_int(c['closed'])} closed, "
            f"across {fmt_int(len(s.repos))} "
            f"{plural(len(s.repos), 'repository', 'repositories')} with "
            f"{fmt_compact(s.stars)} combined stars. Merge rate "
            f"{fmt_rate(s.merge_rate)}; contributing since "
            f"{fmt_month(s.first)}.")


def render_activity(s, t, x0, x1, base_y):
    """Twelve monthly columns of PRs opened, with a caption above."""
    gap, max_h = 8, 40
    bar_w = (x1 - x0 - gap * 11) / 12
    peak = max(count for _, count in s.monthly)
    year_total = sum(count for _, count in s.monthly)

    out = [
        text(x0, base_y - max_h - 14, "Last 12 months", 14, t["muted"]),
        text(x1, base_y - max_h - 14,
             tspan(fmt_int(year_total), t["fg"], 600)
             + tspan(" " + plural(year_total, "PR"), t["muted"]),
             14, t["muted"], anchor="end"),
    ]
    for i, (_, count) in enumerate(s.monthly):
        x = fmt_num(x0 + i * (bar_w + gap))
        if count:
            h = max(4, round(max_h * count / peak))
            out.append(f'<rect{attrs(x=x, y=base_y - h, width=fmt_num(bar_w), height=h, rx=2, fill=t["accent"])}/>')
        else:
            out.append(f'<rect{attrs(x=x, y=base_y - 3, width=fmt_num(bar_w), height=3, rx=1.5, fill=t["track"])}/>')
    first, last = s.monthly[0][0], s.monthly[-1][0]
    out.append(text(x0, base_y + 22, first.strftime("%b %Y"), 13, t["muted"]))
    out.append(text(x1, base_y + 22, last.strftime("%b %Y"), 13, t["muted"], anchor="end"))
    return "".join(out)


def render_summary(s, theme):
    t = THEMES[theme]
    height = 316
    right = WIDTH - PAD
    out = []

    # Header
    out.append(icon("pr", PAD, 23, 18, t["muted"]))
    out.append(text(PAD + 28, 38, "Open-source contributions", 17, t["fg"], 600))
    out.append(text(right, 38, f"Updated {fmt_date(s.now)}", 14, t["muted"],
                    anchor="end"))

    # Headline number, label flows after it in the same <text> element
    out.append(text(PAD - 2, 132,
                    tspan(fmt_int(s.total), t["fg"], 600, 64)
                    + tspan(" " + plural(s.total, "pull request"), t["muted"], 400, 22, dx=4),
                    64, t["fg"]))
    out.append(render_activity(s, t, 420, right, 132))

    # State bar + legend
    bar_y, legend_y = 176, 208
    parts = [(s.counts[st], t[st]) for st in STATES]
    out.append(segmented_bar(PAD, bar_y, right - PAD, 10, parts,
                             (t["track"], right - PAD), clip_id="state-bar"))
    if s.loaded:
        for i, st in enumerate(STATES):
            x = PAD + i * 150
            out.append(f'<circle{attrs(cx=x + 5, cy=legend_y - 5, r=5, fill=t[st])}/>')
            out.append(text(x + 17, legend_y,
                            tspan(STATE_LABELS[st], t["fg"], 600)
                            + tspan(" " + fmt_int(s.counts[st]), t["muted"]),
                            14, t["fg"]))
        if s.loaded < s.total:
            out.append(text(right, legend_y,
                            f"Breakdown of the latest {fmt_int(s.loaded)}",
                            13, t["muted"], anchor="end"))
    else:
        out.append(text(PAD, legend_y,
                        "No public pull requests yet — they will appear "
                        "here automatically.", 14, t["muted"]))

    # Footer stats on a subtle band
    band_y = 234
    out.append(f'<path d="M1 {band_y}H{WIDTH - 1}V{height - 7}a6 6 0 0 1-6 6'
               f'H7a6 6 0 0 1-6-6Z" fill="{t["subtle"]}"/>')
    out.append(f'<path d="M1 {band_y}H{WIDTH - 1}" stroke="{t["border"]}"/>')
    stats = [
        ("Repositories", fmt_int(len(s.repos)), None),
        ("Merge rate", fmt_rate(s.merge_rate), None),
        ("Combined stars", fmt_compact(s.stars), "star"),
        ("Contributing since", fmt_month(s.first), None),
    ]
    col = (WIDTH - 2 * PAD) / 4
    for i, (label, value, glyph) in enumerate(stats):
        x = round(PAD + i * col)
        out.append(text(x, band_y + 32, label, 14, t["muted"]))
        vx = x
        if glyph:
            out.append(icon(glyph, x, band_y + 46, 20, t["star"]))
            vx = x + 27
        out.append(text(vx, band_y + 66, xml_escape(value), 26, t["fg"], 600))

    title = f"Open-source contributions by {s.login}"
    return svg_document(height, title, summary_description(s), "".join(out), theme)

# --------------------------------------------------------------------------
# Visual 2: repository breakdown
# --------------------------------------------------------------------------


def repo_name_spans(full_name, budget, t):
    """owner/ (muted) + name (bold), truncated to fit `budget` pixels."""
    owner, _, name = full_name.partition("/")
    owner += "/"
    size = 16
    owner_w = text_width(owner, size)
    if owner_w + text_width(name, size, True) > budget:
        owner = truncate(owner, min(owner_w, budget * 0.4), size)
        if not owner.endswith("/"):
            owner += "/"
        name = truncate(name, budget - text_width(owner, size), size, True)
    return tspan(owner, t["muted"]) + tspan(name, t["fg"], 600)


def state_breakdown_spans(repo, budget, t):
    """e.g. "5 merged · 1 open", dropping parts that would overflow."""
    parts = [(repo.counts[st], st) for st in STATES if repo.counts[st]]
    while parts:
        plain = " · ".join(f"{fmt_int(n)} {st}" for n, st in parts)
        if text_width(plain, 13) <= budget:
            break
        parts = parts[:-1]
    spans = []
    for i, (n, st) in enumerate(parts):
        if i:
            spans.append(tspan(" · ", t["muted"]))
        spans.append(tspan(fmt_int(n), t["fg"], 600) + tspan(" " + st, t["muted"]))
    return "".join(spans)


def render_repos(s, theme):
    t = THEMES[theme]
    right = WIDTH - PAD
    header_h, row_h, footer_h = 56, 66, 48
    shown = s.repos[:MAX_REPO_ROWS]
    hidden = s.repos[MAX_REPO_ROWS:]
    height = header_h + row_h * len(shown) + (footer_h if hidden else 0)

    bar_x, bar_w = 488, 232
    name_budget = bar_x - 24 - PAD
    peak = max(r.total for r in shown)

    out = [
        icon("repo", PAD, 21, 18, t["muted"]),
        text(PAD + 28, 36, "Repositories", 17, t["fg"], 600),
        text(right, 36, "Pull requests", 14, t["muted"], anchor="end"),
    ]
    for i, repo in enumerate(shown):
        top = header_h + i * row_h
        line1, line2 = top + 28, top + 51
        out.append(f'<path d="M1 {top}H{WIDTH - 1}" stroke="{t["border"]}"/>')
        out.append(text(PAD, line1, repo_name_spans(repo.full_name, name_budget, t), 16, t["fg"]))

        # Meta line: fixed columns so nothing can collide.
        out.append(icon("star", PAD, line2 - 12, 14, t["star"]))
        out.append(text(PAD + 19, line2, fmt_compact(repo.stars), 14, t["muted"]))
        if repo.language:
            dot = LANGUAGE_COLORS.get(repo.language, t["muted"])
            lang_x = PAD + 84
            out.append(f'<circle{attrs(cx=lang_x + 6, cy=line2 - 5, r=6, fill=dot)}/>')
            lang = truncate(repo.language, name_budget - 100, 14)
            out.append(text(lang_x + 18, line2, xml_escape(lang), 14, t["muted"]))

        filled = max(8, bar_w * repo.total / peak)
        parts = [(repo.counts[st], t[st]) for st in STATES]
        out.append(segmented_bar(bar_x, line1 - 9, filled, 8, parts,
                                 (t["track"], bar_w), clip_id=f"repo-bar-{i}"))
        out.append(text(bar_x, line2, state_breakdown_spans(repo, bar_w + 40, t), 13, t["muted"]))
        out.append(text(right, line1, fmt_int(repo.total), 18, t["fg"], 600, anchor="end"))

    if hidden:
        top = header_h + row_h * len(shown)
        more_prs = sum(r.total for r in hidden)
        out.append(f'<path d="M1 {top}H{WIDTH - 1}" stroke="{t["border"]}"/>')
        out.append(text(PAD, top + 30,
                        tspan(f"+{fmt_int(len(hidden))} more "
                              f"{plural(len(hidden), 'repository', 'repositories')}", t["fg"], 600)
                        + tspan(f" with {fmt_int(more_prs)} pull "
                                f"{plural(more_prs, 'request')}", t["muted"]),
                        14, t["muted"]))

    listed = ", ".join(f"{r.full_name} ({r.total})" for r in s.repos)
    desc = (f"Pull requests by repository, most first: {listed}.")
    title = f"Repositories {s.login} has contributed to"
    return svg_document(height, title, desc, "".join(out), theme)

# --------------------------------------------------------------------------
# Visual 3: PR state icons for the HTML list
# --------------------------------------------------------------------------


def render_state_icon(state, theme):
    color = THEMES[theme][state]
    label = STATE_LABELS[state]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
            f'viewBox="0 0 16 16" role="img" aria-labelledby="title">'
            f'<title id="title">{label} pull request</title>'
            f'<path fill="{color}" d="{OCTICONS[state]}"/></svg>\n')

# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def build_assets(data):
    s = compute_stats(data)
    assets = {}
    for theme in THEMES:
        assets[f"pr-summary-{theme}.svg"] = render_summary(s, theme)
        if s.repos:
            assets[f"pr-repos-{theme}.svg"] = render_repos(s, theme)
            for state in ("merged", "open", "draft", "closed"):
                assets[f"pr-{state}-{theme}.svg"] = render_state_icon(state, theme)
    return assets


def themed_image(asset_dir, stem, alt, width=None, height=None):
    size = attrs(width=width, height=height)
    return (f'<picture><source media="(prefers-color-scheme: dark)" '
            f'srcset="{html_escape(f"{asset_dir}/{stem}-dark.svg")}">'
            f'<img src="{html_escape(f"{asset_dir}/{stem}-light.svg")}"'
            f'{size} alt="{html_escape(alt)}"></picture>')


def safe_pr_url(pr):
    url = pr.get("url") or ""
    if url.startswith("https://github.com/"):
        return url
    return f"https://github.com/{pr['repo']}/pull/{int(pr['number'])}"


STATE_VERBS = {"merged": "merged", "open": "opened", "draft": "opened",
               "closed": "closed"}


def recent_table(s, asset_dir):
    """GitHub-style PR list: state icon | title, then repo#number · date."""
    rows = ["<table>"]
    for pr in s.recent[:RECENT_PRS]:
        state = pr["state"] if pr["state"] in STATE_LABELS else "open"
        url = html_escape(safe_pr_url(pr))
        repo_url = html_escape(f"https://github.com/{pr['repo']}")
        title = " ".join(pr["title"].split())
        if len(title) > TITLE_CHARS:
            title = title[:TITLE_CHARS - 1].rstrip() + "…"
        title = html_escape(title)
        when = fmt_day(parse_time(activity_time(pr)), s.now)
        badge = themed_image(asset_dir, f"pr-{state}", STATE_LABELS[state], 16, 16)
        rows.append(
            f'<tr><td><a href="{url}">{badge}</a></td>'
            f'<td><a href="{url}">{title}</a><br>'
            f'<sub><a href="{repo_url}">{html_escape(pr["repo"])}</a>'
            f'#{int(pr["number"])} · {STATE_VERBS[state]} {html_escape(when)}'
            f'</sub></td></tr>')
    rows.append("</table>")
    return "\n".join(rows)


def build_readme_block(data, asset_dir):
    s = compute_stats(data)
    search = ("https://github.com/search?type=pullrequests&q="
              + quote(f"is:pr is:public author:{s.login} -user:{s.login}"))
    search_attr = html_escape(search)

    blocks = [
        f'<a href="{search_attr}">'
        + themed_image(asset_dir, "pr-summary", summary_description(s), width="100%")
        + "</a>"
    ]
    if s.repos:
        top = ", ".join(f"{r.full_name} ({r.total})" for r in s.repos[:MAX_REPO_ROWS])
        blocks.append(
            f'<a href="{search_attr}">'
            + themed_image(asset_dir, "pr-repos",
                           f"Pull requests by repository: {top}", width="100%")
            + "</a>")
        shown = min(RECENT_PRS, len(s.recent))
        blocks.append(
            "<details>\n"
            f"<summary><b>Recent pull requests</b> · latest {shown} of "
            f"{fmt_int(s.total)}</summary>\n<br>\n\n"
            + recent_table(s, asset_dir)
            + f'\n\n<p><a href="{search_attr}">See all {fmt_int(s.total)} '
            f'pull {plural(s.total, "request")} on GitHub →</a></p>\n'
            "</details>")

    note = (f"Updated {fmt_date(s.now)} · public pull "
            "requests to repositories on GitHub, drafts counted as open")
    if s.loaded < s.total:
        note += (f" · breakdowns cover the {fmt_int(s.loaded)} most "
                 f"recent of {fmt_int(s.total)}")
    blocks.append(f"<sub>{html_escape(note)}.</sub>")
    return "\n\n".join(blocks) + "\n"
