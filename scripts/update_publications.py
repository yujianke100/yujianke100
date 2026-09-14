#!/usr/bin/env python3
"""更新 GitHub 主页 README (yujianke100/yujianke100) 里的 Publications 区块。

数据源：OpenAlex（按 ORCID），与个人主页同一套过滤规则：
  - 丢弃勘误/撤稿、非论文记录类型
  - 必须与已知合作者同现（防同名他人论文）
  - 标题去重（正式版优先于预印本）
  - 手工补充：scripts/extra_publications.yml（已接收但 OpenAlex 未收录）

读写目标：README.md 中
  <!-- PUBLICATIONS:START --> ... <!-- PUBLICATIONS:END -->
之间的内容（首次运行会自动在 "# 📝 Publications" 后插入标记并替换旧列表）。

用法：python3 scripts/update_publications.py [--check]
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

try:
    import yaml
except ImportError:
    sys.exit("需要 pyyaml：pip install pyyaml")

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
VENUES = ROOT / "scripts" / "venues.yml"
EXTRAS = ROOT / "scripts" / "extra_publications.yml"

ORCID = "0000-0002-2032-7727"
OWN_NAMES = {"jianke yu", "yu jianke", "j. yu", "jk yu"}
COAUTHOR_WHITELIST = {
    "Xiaoyang Wang", "Hanchen Wang", "Ying Zhang", "Lu Qin", "Wenjie Zhang",
    "Xuemin Lin", "Zhao Li", "Jian Liao", "Bailin Yang", "Chen Chen",
    "Xulu Gong", "Kecheng Wang", "Xubo Wang", "Xi Wang", "Qing Sima",
    "Min Pei", "Xianhang Zhang", "Yunkai Lou", "Shunyang Li", "Wenyuan Yu",
    "John Shepherd", "Zhengyi Yang", "Weiyuan Wang", "Xijuan Liu",
}
EXCLUDE_TITLE_RE = re.compile(r"^\s*(correction to|erratum|retraction|withdrawn)", re.I)
DROP_TYPES = {"repository", "dataset", "erratum", "editorial", "letter", "paratext",
              "peer-review", "dissertation", "libguides", "grant", "software"}
GENERIC_VENUE_RE = re.compile(
    r"^(lecture notes in computer science|lncs\b|figshare|zenodo|research square|ssrn|"
    r"preprints?\.?org|openreview|arxiv \(cornell university\)|arxiv|corr\b)", re.I)
PREPRINT_RE = re.compile(r"^(arxiv|corr\b|research square|ssrn|preprints?\.?org)", re.I)
MAX_ITEMS = 12
UA = {"User-Agent": "jianke-profile-readme/1.0 (mailto:yujianke100@gmail.com)"}
OPENALEX = "https://api.openalex.org/works"
CROSSREF = "https://api.crossref.org/works/"
START_MARK, END_MARK = "<!-- PUBLICATIONS:START -->", "<!-- PUBLICATIONS:END -->"


def http_json(url: str, tries: int = 4) -> dict:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 ** i * 2)
    raise RuntimeError(f"请求失败: {url} ({last})")


def clean(t: str | None) -> str:
    return html.unescape(html.unescape(t or "")).replace("\u2011", "-").replace("\u00a0", " ").strip()


def fix_name(n: str) -> str:
    n = clean(n)
    return " ".join(w.capitalize() for w in n.split()) if len(n) > 3 and n.isupper() else n


def load_cfg():
    d = yaml.safe_load(VENUES.read_text(encoding="utf-8")) or {}
    venues = {k: v for k, v in (d.get("venues") or {}).items() if isinstance(v, dict)}
    aliases = [(re.compile(a["pattern"], re.I), a["venue"]) for a in (d.get("aliases") or [])]
    return venues, aliases


def resolve_venue(name, venues, aliases):
    if not name:
        return ""
    for k in venues:
        if k.lower() == name.lower():
            return k
    for rx, canon in aliases:
        if rx.search(name):
            return canon
    for k in venues:
        if len(name) >= 6 and (k.lower() in name.lower() or name.lower() in k.lower()):
            return k
    return ""


def venue_of(work, venues, aliases):
    src = (work.get("primary_location") or {}).get("source") or {}
    name = clean(src.get("display_name", ""))
    otype = src.get("type") or ""
    kind = "conference" if otype in {"conference", "proceedings"} else "journal"
    doi = (work.get("doi") or "").replace("https://doi.org/", "")
    if (not name) or GENERIC_VENUE_RE.match(name):
        try:
            msg = http_json(CROSSREF + urllib.parse.quote(doi)).get("message", {}) if doi else {}
        except Exception:
            msg = {}
        cands = [clean(x) for x in (msg.get("container-title") or [])] + [clean((msg.get("event") or {}).get("name", ""))]
        for c in cands:
            if c and not GENERIC_VENUE_RE.match(c):
                name = c
                if msg.get("type") == "proceedings-article":
                    kind = "conference"
                break
    if PREPRINT_RE.match(name) or work.get("type") == "preprint":
        return "arXiv", "preprint"
    if work.get("type") == "proceedings-article":
        kind = "conference"
    # 归一化到 venues.yml 的规范名（否则 LNCS 反查出的原始会议名拿不到缩写与徽章）
    canon = resolve_venue(name, venues, aliases)
    if canon:
        if venues.get(canon, {}).get("kind") == "conference":
            kind = "conference"
        return canon, kind
    return name, kind


def badges(meta, kind):
    out = []
    if meta.get("ccf"):
        out.append(f"CCF-{meta['ccf']}")
    if kind != "conference":
        if meta.get("cas"):
            out.append(f"CAS Zone {meta['cas']}" + (" Top" if meta.get("cas_top") else ""))
        if meta.get("jcr"):
            out.append(f"JCR {meta['jcr']}")
    return out


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", "", t.lower())


def authors_pos(work):
    out, pos = [], 0
    for i, a in enumerate(work.get("authorships") or [], start=1):
        n = fix_name((a.get("author") or {}).get("display_name", ""))
        if n.lower() in OWN_NAMES:
            out.append("me")
            pos = pos or i
        else:
            out.append(n)
    return out, pos


def coauthor_ok(work):
    names = {fix_name((a.get("author") or {}).get("display_name", "")) for a in work.get("authorships") or []}
    return bool(names & COAUTHOR_WHITELIST)


def fetch_works():
    works, cursor = [], "*"
    fields = ("id,doi,title,publication_year,publication_date,type,authorships,primary_location,"
              "cited_by_count")
    while cursor:
        q = urllib.parse.urlencode({"filter": f"author.orcid:{ORCID}", "per-page": "200",
                                    "cursor": cursor, "select": fields})
        data = http_json(f"{OPENALEX}?{q}")
        works.extend(data.get("results") or [])
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not (data.get("results") or []):
            break
    return works


def extras_as_works(venues, aliases):
    if not EXTRAS.exists():
        return []
    data = yaml.safe_load(EXTRAS.read_text(encoding="utf-8")) or {}
    out = []
    for e in data.get("papers") or []:
        venue = e.get("venue", "")
        kind = "conference" if venues.get(resolve_venue(venue, venues, aliases), {}).get("kind") == "conference" else "journal"
        out.append({
            "title": e["title"], "publication_year": e.get("year"),
            "publication_date": str(e.get("date") or f"{e.get('year')}-01-01"),
            "type": "conference-paper" if kind == "conference" else "article",
            "authorships": [{"author": {"display_name": "Jianke Yu" if a == "me" else a}}
                            for a in (e.get("authors") or [])],
            "primary_location": {"source": {"display_name": venue, "type": "conference" if kind == "conference" else "journal"}},
            "doi": f"https://doi.org/{e['doi']}" if e.get("doi") else None,
            "cited_by_count": e.get("cited_by", 0),
        })
    return out


def short_venue(venue, year, meta):
    abbr = meta.get("abbr") or venue
    kind = meta.get("kind", "")
    if kind == "preprint":
        return f"arXiv {year}"
    return f"{abbr} {year}"


def build_block(works, venues, aliases):
    best = {}
    for w in works:
        t = clean(w.get("title") or "")
        if not t or EXCLUDE_TITLE_RE.match(t) or (w.get("type") or "") in DROP_TYPES:
            continue
        if not coauthor_ok(w):
            continue
        _, kind = venue_of(w, venues, aliases)
        rank = (0 if kind != "preprint" else 1, -(w.get("cited_by_count") or 0))
        key = norm_title(t)
        if key not in best or rank < best[key][0]:
            best[key] = (rank, w)
    for w in extras_as_works(venues, aliases):
        key = norm_title(clean(w["title"]))
        best.setdefault(key, ((0, 0), w))

    items = sorted((w for _, w in best.values()),
                   key=lambda w: (w.get("publication_date") or ""), reverse=True)[:MAX_ITEMS]

    lines = [START_MARK,
             "<!-- 本区块由 scripts/update_publications.py 自动生成，请勿手工编辑 -->"]
    for w in items:
        title = clean(w.get("title") or "")
        year = w.get("publication_year") or ""
        venue, kind = venue_of(w, venues, aliases)
        meta = venues.get(venue, {})
        _, pos = authors_pos(w)
        doi = (w.get("doi") or "").replace("https://doi.org/", "")
        label = f"**[{short_venue(venue, year, meta)}]**"
        link = f"[{title}](https://doi.org/{doi})" if doi else title
        tags = badges(meta, kind)
        if pos == 1:
            tags.insert(0, "⭐ first author")
        tail = f" · *{' · '.join(tags)}*" if tags else ""
        lines.append(f"- {label} {link}{tail}")
    lines.append("")
    lines.append(f"> 🤖 每日自动同步（OpenAlex/ORCID）· [完整列表与分区徽章](https://jianke-yu.online/publications/)")
    lines.append(END_MARK)
    return "\n".join(lines)


def update_readme(block: str, check: bool = False) -> bool:
    text = README.read_text(encoding="utf-8")
    if START_MARK in text and END_MARK in text:
        new = re.sub(re.escape(START_MARK) + r".*?" + re.escape(END_MARK), block, text, flags=re.S)
    else:
        # 首次运行：替换 "# 📝 Publications" 之后的旧列表，直到下一个 <br/> 或标题
        pat = re.compile(r"(#\s*📝?\s*Publications[^\n]*\n)(.*?)(?=\n\s*<br\s*/?>|\n#)", re.S)
        if not pat.search(text):
            print("✗ README 中找不到 Publications 区块，放弃"); return False
        new = pat.sub(lambda m: m.group(1) + "\n" + block + "\n", text, count=1)
    if new == text:
        print("README 无变化")
        return False
    if not check:
        README.write_text(new, encoding="utf-8")
    print("README 已更新" + ("（--check 模式，未写入）" if check else ""))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    venues, aliases = load_cfg()
    works = fetch_works()
    print(f"OpenAlex 返回 {len(works)} 条")
    block = build_block(works, venues, aliases)
    print("---- 生成的区块 ----")
    print(block)
    changed = update_readme(block, args.check)
    return 0 if changed or args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
