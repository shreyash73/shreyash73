#!/usr/bin/env python3
"""Build the profile README and its SVG panels from the GitHub API. Standard library only.

Run: python3 build/build.py   (uses GH_TOKEN, or `gh auth token` when run locally)
"""
import base64
import collections
import datetime as dt
import html
import json
import math
import os
import random
import subprocess
import textwrap
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "profile.json").read_text())
LOGIN = CFG["login"]
W = 840

SERIF = "Charter,'Bitstream Charter','Sitka Text',Cambria,Georgia,serif"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,'Liberation Mono',monospace"

THEMES = {
    "light": dict(
        ink="#1f2328", muted="#59636e", line="#d1d9e0", sea="#0f6f7a", coral="#c9462a",
        langs=["#0f6f7a", "#c9462a", "#c98a1b", "#5b5bd6", "#8b949e"],
        sky=["#fbe6c9", "#f8bd92", "#ee8267"], orb="#fff1cf", orb_y=212, orb_r=60,
        waves=["#1d7482", "#155f6d", "#0e4a57"], crest="#bfe6e6",
        name="#2b1710", tag="#5a3324", label="#8a442c", hull="#3a1c14", sail="#fff6e6",
    ),
    "dark": dict(
        ink="#f0f6fc", muted="#9198a1", line="#3d444d", sea="#56c7c1", coral="#ff9478",
        langs=["#56c7c1", "#ff9478", "#e9b949", "#9c9cf5", "#8b949e"],
        sky=["#070b1c", "#131c44", "#2a3970"], orb="#f3efdc", orb_y=92, orb_r=30,
        waves=["#12305a", "#0c2244", "#07162e"], crest="#7fa3d9",
        name="#f4f1e6", tag="#c3cbe0", label="#8fa0cf", hull="#04070f", sail="#c9d2ee",
    ),
}


# ---------- GitHub API ----------

def _token():
    t = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    return t or subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()


TOKEN = _token()


def api(path, data=None):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        data=json.dumps(data).encode() if data else None,
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
                 "User-Agent": "profile-build"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def avatar(owner):
    """Owner avatar as a data URI (SVGs shown through <img> cannot load outside images)."""
    req = urllib.request.Request(f"https://github.com/{owner}.png?size=64", headers={"User-Agent": "profile-build"})
    with urllib.request.urlopen(req, timeout=30) as r:
        kind = r.headers.get("Content-Type", "image/png").split(";")[0]
        return f"data:{kind};base64,{base64.b64encode(r.read()).decode()}"


def fetch():
    q = """query { user(login: "%s") { name createdAt
      contributionsCollection { contributionCalendar { totalContributions
        weeks { contributionDays { date contributionCount } } } }
      repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false) {
        nodes { name languages(first: 10) { edges { size node { name } } } } } } }""" % LOGIN
    u = api("/graphql", {"query": q})["data"]["user"]
    cal = u["contributionsCollection"]["contributionCalendar"]
    repos = [r for r in u["repositories"]["nodes"] if r["name"] != LOGIN]  # this profile repo is not a project
    langs = collections.Counter()
    for repo in repos:
        for e in repo["languages"]["edges"]:
            langs[e["node"]["name"]] += e["size"]

    def prs(state, date_of):
        query = urllib.parse.quote(f"author:{LOGIN} is:pr is:{state} -user:{LOGIN}")
        r = api(f"/search/issues?q={query}&per_page=100")
        items = [dict(repo=i["repository_url"].split("/repos/")[1], title=i["title"], url=i["html_url"],
                      date=dt.date.fromisoformat(date_of(i)[:10]), state=state) for i in r["items"]]
        return r["total_count"], sorted(items, key=lambda p: p["date"], reverse=True)

    merged_n, merged = prs("merged", lambda i: i["pull_request"]["merged_at"])
    open_n, opened = prs("open", lambda i: i["created_at"])
    created = dt.date.fromisoformat(u["createdAt"][:10])
    return dict(
        name=u["name"] or LOGIN, since=created.year,
        years=int((dt.date.today() - created).days / 365.25),
        repos=len(repos), total=cal["totalContributions"],
        weeks=[(dt.date.fromisoformat(w["contributionDays"][0]["date"]),
                sum(d["contributionCount"] for d in w["contributionDays"])) for w in cal["weeks"]],
        langs=langs, merged_n=merged_n, open_n=open_n, merged=merged, opened=opened,
    )


# ---------- SVG helpers ----------

def esc(s):
    return html.escape(str(s), quote=True)


def text(x, y, s, size, fill, font=SANS, anchor="start", extra=""):
    return (f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" {extra}>{esc(s)}</text>')


def label(x, y, s, fill, anchor="start", size=10.5):
    return text(x, y, s.upper(), size, fill, MONO, anchor, 'letter-spacing="2"')


def fit(s, size, width, k=0.5):
    """Cut a string to roughly fit a pixel width (fonts differ by system, so this is an estimate)."""
    n = int(width / (size * k))
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def svg(h, body, title, w=W):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="{esc(title)}"><title>{esc(title)}</title>{body}</svg>')


# ---------- Panels ----------

def hero(t, d, dark):
    H, horizon, cx = 320, 212, 636
    rnd = random.Random(7)
    o = [f'<defs><clipPath id="c"><rect width="{W}" height="{H}" rx="14"/></clipPath>'
         f'<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t["sky"][0]}"/>'
         f'<stop offset=".6" stop-color="{t["sky"][1]}"/><stop offset="1" stop-color="{t["sky"][2]}"/></linearGradient>'
         f'<radialGradient id="glow"><stop offset="0" stop-color="{t["orb"]}" stop-opacity=".7"/>'
         f'<stop offset="1" stop-color="{t["orb"]}" stop-opacity="0"/></radialGradient></defs><g clip-path="url(#c)">',
         f'<rect width="{W}" height="{horizon + 6}" fill="url(#sky)"/>']
    if dark:
        for i in range(80):
            x, y, r, a = rnd.uniform(8, W - 8), rnd.uniform(8, horizon - 14), rnd.uniform(.4, 1.3), rnd.uniform(.3, .9)
            twinkle = (f'<animate attributeName="opacity" values="{a:.2f};.1;{a:.2f}" dur="{rnd.uniform(2.5, 6):.1f}s" '
                       f'repeatCount="indefinite"/>') if i % 5 == 0 else ""
            o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.2f}" fill="#fff" opacity="{a:.2f}">{twinkle}</circle>')
    else:
        for x, y, s in ((716, 62, 1), (746, 80, .7), (692, 86, .6)):
            o.append(f'<path transform="translate({x},{y}) scale({s})" d="M0,0 q5,-6 10,0 q5,-6 10,0" fill="none" '
                     f'stroke="{t["label"]}" stroke-width="1.6" stroke-linecap="round" opacity=".7"/>')
    o.append(f'<circle cx="{cx}" cy="{t["orb_y"]}" r="{t["orb_r"] * 2.9:.0f}" fill="url(#glow)"/>'
             f'<circle cx="{cx}" cy="{t["orb_y"]}" r="{t["orb_r"]}" fill="{t["orb"]}"/>')

    def wave(y, amp, period, secs, fill, direction):
        n = math.ceil((W + 2 * period) / period)
        dpath = f"M{-period},{y}" + f" q{period / 4},{-amp} {period / 2},0 t{period / 2},0" * n + f" V{H + 10} H{-period} Z"
        return (f'<path d="{dpath}" fill="{fill}" stroke="{t["crest"]}" stroke-opacity=".3">'
                f'<animateTransform attributeName="transform" type="translate" from="0 0" to="{direction * period} 0" '
                f'dur="{secs}s" repeatCount="indefinite"/></path>')

    o.append(wave(horizon, 3, 120, 14, t["waves"][0], 1))
    o.append(f'<g transform="translate(250,{horizon - 3})"><g>'
             f'<animateTransform attributeName="transform" type="rotate" values="-2.5;2.5;-2.5" dur="5s" repeatCount="indefinite"/>'
             f'<path d="M-17,0 h34 l-6,8 h-22 z" fill="{t["hull"]}"/><path d="M1,-3 V-30 L17,-3 Z" fill="{t["sail"]}"/>'
             f'<path d="M-2,-4 V-22 L-13,-4 Z" fill="{t["sail"]}" opacity=".8"/></g></g>')
    o.append(wave(horizon + 26, 5, 160, 11, t["waves"][1], -1))
    o.append(wave(horizon + 60, 7, 220, 9, t["waves"][2], 1))
    for k in range(9):
        w = 16 + k * 8 + rnd.uniform(-4, 4)
        x = cx - w / 2 + rnd.uniform(-6, 6)
        o.append(f'<rect x="{x:.1f}" y="{horizon + 10 + k * 10}" width="{w:.1f}" height="2.2" rx="1.1" fill="{t["orb"]}" opacity=".5">'
                 f'<animate attributeName="opacity" values=".15;.7;.15" dur="{2.4 + k * .35:.2f}s" repeatCount="indefinite"/></rect>')
    o.append(label(40, 58, f'{CFG["place"]}  ·  on GitHub since {d["since"]}', t["label"], size=11))
    o.append(text(38, 124, d["name"], 56, t["name"], SERIF, extra='letter-spacing="-.5"'))
    for i, line in enumerate(textwrap.wrap(CFG["tagline"], 54)[:2]):
        o.append(text(40, 160 + i * 25, line, 17, t["tag"]))
    o.append("</g>")
    return svg(H, "".join(o), f'{d["name"]}. {CFG["tagline"]}')


def numbers(t, d):
    cells = [(d["years"], "years on GitHub"), (d["repos"], "public projects"),
             (d["merged_n"], "PRs merged elsewhere"), (d["total"], "contributions, 12 months")]
    o = []
    for i, (n, name) in enumerate(cells):
        x = 40 + i * 195
        if i:
            o.append(f'<line x1="{x - 22}" y1="14" x2="{x - 22}" y2="84" stroke="{t["line"]}"/>')
        o.append(text(x, 54, n, 44, t["ink"], SERIF) + label(x, 80, name, t["muted"], size=10))
    total = sum(d["langs"].values()) or 1
    top = d["langs"].most_common(4)
    parts = top + ([("Other", total - sum(v for _, v in top))] if len(d["langs"]) > 4 else [])
    o.append(f'<clipPath id="bar"><rect x="40" y="116" width="760" height="10" rx="5"/></clipPath><g clip-path="url(#bar)">')
    x = 40.0
    for (name, size), colour in zip(parts, t["langs"]):
        w = 760 * size / total
        o.append(f'<rect x="{x:.1f}" y="116" width="{max(w - 2, 1):.1f}" height="10" fill="{colour}"/>')
        x += w
    o.append("</g>")
    x = 40
    for (name, size), colour in zip(parts, t["langs"]):
        pct = f"{name} {100 * size / total:.0f}%"
        o.append(f'<rect x="{x}" y="143" width="9" height="9" rx="2" fill="{colour}"/>' + text(x + 15, 152, pct, 12.5, t["muted"]))
        x += 15 + len(pct) * 7 + 26
    return svg(166, "".join(o), ", ".join(f"{n} {name}" for n, name in cells))


def tide(t, d):
    weeks, base, top, x0, x1 = d["weeks"], 172, 86, 40, 800
    peak_i = max(range(len(weeks)), key=lambda i: weeks[i][1])
    peak = weeks[peak_i][1] or 1
    pts = [(x0 + (x1 - x0) * i / (len(weeks) - 1), base - (base - top) * v / peak) for i, (_, v) in enumerate(weeks)]
    curve = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for i in range(len(pts) - 1):  # Catmull-Rom spline, kept from dipping under the baseline
        p0, p1, p2, p3 = pts[max(i - 1, 0)], pts[i], pts[i + 1], pts[min(i + 2, len(pts) - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, min(p1[1] + (p2[1] - p0[1]) / 6, base))
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, min(p2[1] - (p3[1] - p1[1]) / 6, base))
        curve += f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"
    when = weeks[peak_i][0]
    o = [f'<defs><linearGradient id="f" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t["sea"]}" stop-opacity=".4"/>'
         f'<stop offset="1" stop-color="{t["sea"]}" stop-opacity=".03"/></linearGradient></defs>',
         label(40, 30, "The tide table", t["ink"], size=11.5),
         text(40, 54, f'{d["total"]} contributions in the last year. High tide: {weeks[peak_i][1]}, in the week of '
              f'{when.day} {when:%b}.', 14, t["muted"], extra='font-style="italic"'),
         f'<path d="{curve} V{base} H{x0} Z" fill="url(#f)"/>',
         f'<path d="{curve}" fill="none" stroke="{t["sea"]}" stroke-width="2" stroke-linejoin="round"/>',
         f'<line x1="{x0}" y1="{base + .5}" x2="{x1}" y2="{base + .5}" stroke="{t["line"]}"/>']
    for i in range(1, len(weeks)):
        if weeks[i][0].month != weeks[i - 1][0].month:
            x = pts[i][0]
            o.append(f'<line x1="{x:.1f}" y1="{base}" x2="{x:.1f}" y2="{base + 6}" stroke="{t["line"]}"/>')
            o.append(text(f"{x:.1f}", base + 22, f"{weeks[i][0]:%b}", 10.5, t["muted"], MONO, "middle"))
    px, py = pts[peak_i]
    o.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="{t["coral"]}"/>')
    o.append(text(f"{px + 10:.1f}", py + 4, weeks[peak_i][1], 12, t["coral"], MONO))
    return svg(204, "".join(o), f'{d["total"]} contributions in the last year, by week')


def card(t, p):
    cw, ch = (840, 172) if p.get("wide") else (420, 192)  # a wide card takes a full row
    waves = " q26,-9 52,0 t52,0" * (cw // 104 + 2)
    o = [f'<defs><clipPath id="k"><rect x="8" y="8" width="{cw - 16}" height="{ch - 16}" rx="12"/></clipPath></defs>',
         f'<g clip-path="url(#k)"><path d="M0,{ch - 22}{waves} V{ch} H0 Z" fill="{t["sea"]}" opacity=".13"/>'
         f'<path d="M-30,{ch - 14}{waves} V{ch} H-30 Z" fill="{t["sea"]}" opacity=".16"/></g>',
         f'<rect x="8.5" y="8.5" width="{cw - 17}" height="{ch - 17}" rx="12" fill="none" stroke="{t["line"]}"/>',
         label(28, 42, p["kind"], t["coral"], size=10),
         f'<path transform="translate({cw - 40},32)" d="M0,9 L9,0 M2,0 H9 V7" fill="none" stroke="{t["muted"]}" stroke-width="1.6"/>',
         text(28, 74, p["title"], 23, t["ink"], SERIF)]
    for i, line in enumerate(textwrap.wrap(p["about"], 108 if p.get("wide") else 52)[:3]):
        o.append(text(28, 99 + i * 19, line, 13.5, t["muted"]))
    return svg(ch, "".join(o), f'{p["title"]}: {p["about"]}', cw)


def pulls(t, d, avatars):
    rows = (d["opened"] + d["merged"])[:7]
    h = 76 + 40 * len(rows)
    o = [label(40, 30, "Pull requests into other people's projects", t["ink"], size=11.5),
         text(40, 54, f'{d["merged_n"]} merged, {d["open_n"]} open.', 14, t["muted"], extra='font-style="italic"'),
         '<defs><clipPath id="a" clipPathUnits="objectBoundingBox"><circle cx=".5" cy=".5" r=".5"/></clipPath></defs>']
    for i, p in enumerate(rows):
        y = 70 + 40 * i
        colour = t["coral"] if p["state"] == "open" else t["sea"]
        o.append(f'<line x1="40" y1="{y + .5}" x2="800" y2="{y + .5}" stroke="{t["line"]}"/>')
        o.append(f'<image href="{avatars[p["repo"].split("/")[0]]}" x="40" y="{y + 9}" width="22" height="22" clip-path="url(#a)"/>')
        o.append(text(72, y + 25, fit(p["repo"], 13.5, 190, .56), 13.5, t["ink"], extra='font-weight="600"'))
        o.append(text(272, y + 25, fit(p["title"], 13.5, 350), 13.5, t["muted"]))
        o.append(text(712, y + 24, f'{p["date"].day} {p["date"]:%b %Y}', 10.5, t["muted"], MONO, "end"))
        o.append(f'<rect x="728.5" y="{y + 10.5}" width="71" height="19" rx="9.5" fill="none" stroke="{colour}"/>')
        o.append(text(764, y + 23.5, p["state"].upper(), 9.5, colour, MONO, "middle", 'letter-spacing="1.2"'))
    o.append(f'<line x1="40" y1="{h - 5.5}" x2="800" y2="{h - 5.5}" stroke="{t["line"]}"/>')
    return svg(h, "".join(o), f'{d["merged_n"]} pull requests merged into other people\'s projects, {d["open_n"]} open')


# ---------- README ----------

def pic(name, alt, width="100%"):
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="assets/dark/{name}.svg">'
            f'<img src="assets/light/{name}.svg" width="{width}" alt="{esc(alt)}"></picture>')


def readme(d):
    def search(state):
        return "https://github.com/search?q=" + urllib.parse.quote(f"author:{LOGIN} is:pr is:{state} -user:{LOGIN}") + "&type=pullrequests"

    rows, pair = [], []
    for i, p in enumerate(CFG["projects"]):
        tag = f'<a href="{p["url"]}">{pic(f"project-{i}", p["title"] + ": " + p["about"], "100%" if p.get("wide") else "50%")}</a>'
        if p.get("wide"):
            rows.append(tag)
        else:
            pair.append(tag)
            if len(pair) == 2:
                rows.append("".join(pair))
                pair = []
    cards = "".join(r + "<br>\n" for r in rows + (["".join(pair)] if pair else []))
    table = "\n".join(f'| {p["repo"]} | [{p["title"].replace("|", "/")}]({p["url"]}) | {p["state"].capitalize()} | '
                      f'{p["date"].day} {p["date"]:%b %Y} |' for p in d["opened"] + d["merged"])
    return f"""<!-- Generated by build/build.py. Edit that file or profile.json, not this one. -->
<p align="center">
<a href="https://github.com/{LOGIN}?tab=repositories">{pic("hero", d["name"] + ". " + CFG["tagline"])}</a><br>
{pic("numbers", f'{d["years"]} years on GitHub, {d["repos"]} public projects, {d["merged_n"]} pull requests merged elsewhere')}<br>
{cards}<a href="{search("merged")}">{pic("pulls", "Pull requests into other people's projects")}</a><br>
{pic("tide", f'{d["total"]} contributions in the last year, by week')}
</p>

<details>
<summary><b>Pull requests as a list</b>, with links</summary>
<br>

| Project | Pull request | Status | Date |
|---|---|---|---|
{table}

</details>

<p align="center"><sub>Rebuilt daily from the GitHub API by <a href="build/build.py">build/build.py</a>.</sub></p>
"""


def main():
    d = fetch()
    avatars = {o: avatar(o) for o in {p["repo"].split("/")[0] for p in d["opened"] + d["merged"]}}
    for name, t in THEMES.items():
        out = ROOT / "assets" / name
        out.mkdir(parents=True, exist_ok=True)
        panels = {"hero": hero(t, d, name == "dark"), "numbers": numbers(t, d), "tide": tide(t, d),
                  "pulls": pulls(t, d, avatars)}
        panels.update({f"project-{i}": card(t, p) for i, p in enumerate(CFG["projects"])})
        for key, body in panels.items():
            (out / f"{key}.svg").write_text(body)
    (ROOT / "README.md").write_text(readme(d))
    print(f'built: {d["name"]}, {d["repos"]} repos, {d["merged_n"]} merged, {d["open_n"]} open, {d["total"]} contributions')


if __name__ == "__main__":
    main()
