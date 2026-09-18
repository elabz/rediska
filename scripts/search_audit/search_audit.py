"""Compare Reddit search results with the full /new feed for each scout watch.

Read-only. Records post ids, timestamps, and title gender/location tags only.
"""
import asyncio, json, os, re, sys, time
from collections import Counter
from datetime import datetime, timezone, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from rediska_worker.tasks.scout import _get_reddit_adapter

TAG_RE = re.compile(r"[\[\(\{]?\b([MFTANBC]{1,3}4[MFTANBCR]{1,3})\b[\]\)\}]?", re.I)


def tokens(s):
    return set(t.lower() for t in re.findall(r"[A-Za-z0-9]+", s or ""))


def parse(q):
    toks = re.findall(r"\(|\)|[^\s()]+", q)
    pos = 0

    def expr():
        nonlocal pos
        node = term()
        while pos < len(toks) and toks[pos] == "OR":
            pos += 1
            node = ("or", node, term())
        return node

    def term():
        nonlocal pos
        node = factor()
        while pos < len(toks) and toks[pos] not in (")", "OR"):
            if toks[pos] == "AND":
                pos += 1
            node = ("and", node, factor())
        return node

    def factor():
        nonlocal pos
        t = toks[pos]; pos += 1
        if t == "(":
            n = expr(); pos += 1
            return n
        return ("w", t.lower())
    return expr()


def ev(node, toks):
    k = node[0]
    if k == "w":
        return node[1] in toks
    if k == "and":
        return ev(node[1], toks) and ev(node[2], toks)
    return ev(node[1], toks) or ev(node[2], toks)


async def collect(adapter, sub, query=None, t=None, pages=10):
    out, after = [], None
    for _ in range(pages):
        r = await adapter.browse_location(location=sub, sort="new", limit=100,
                                          cursor=after, query=query, time_filter=t)
        out.extend(r.items)
        after = r.next_cursor
        if not after:
            break
    return out


async def main():
    db = sessionmaker(bind=create_engine(os.environ["MYSQL_URL"]))()
    watches = db.execute(text(
        "select id, source_location, search_query from scout_watches "
        "where is_trial=0 and is_active=1 order by id")).all()
    adapter = _get_reddit_adapter(db)
    now = datetime.now(timezone.utc)
    report = []
    for wid, sub, q in watches:
        new = await collect(adapter, sub)
        oldest = min(p.created_at for p in new) if new else now
        coverage_h = (now - oldest).total_seconds() / 3600
        window_h = min(coverage_h, 7 * 24)
        t = "day" if window_h <= 24 else "week"
        window_start = now - timedelta(hours=window_h)
        found = await collect(adapter, sub, query=q, t=t)
        tree = parse(q)
        in_win = [p for p in new if p.created_at >= window_start]
        search_ids = {p.external_id for p in found if p.created_at >= window_start}
        local = [p for p in in_win if ev(tree, tokens(p.title) | tokens(p.body_text))]
        local_title = [p for p in in_win if ev(tree, tokens(p.title))]
        missed = [p for p in local if p.external_id not in search_ids]
        missed_old = [p for p in missed if now - p.created_at > timedelta(hours=2)]
        extra = [pid for pid in search_ids if pid not in {p.external_id for p in local}]
        tag_counts = Counter()
        for p in in_win:
            tags = {m.upper() for m in TAG_RE.findall(p.title or "")}
            if not tags:
                tag_counts["<no tag>"] += 1
            for tg in tags:
                tag_counts[tg] += 1
        empty = sum(1 for p in in_win if not (p.body_text or "").strip())
        report.append({
            "watch": wid, "sub": sub, "query": q,
            "new_fetched": len(new), "coverage_hours": round(coverage_h, 1),
            "window_hours": round(window_h, 1), "t": t,
            "posts_in_window": len(in_win),
            "posts_per_day": round(len(in_win) / max(window_h, 1) * 24, 1),
            "empty_body_in_window": empty,
            "local_match": len(local), "local_match_title_only": len(local_title),
            "search_results_in_window": len(search_ids),
            "missed_by_search": len(missed), "missed_older_than_2h": len(missed_old),
            "search_not_local": len(extra),
            "missed_examples_tags": [sorted({m.upper() for m in TAG_RE.findall(p.title or '')})
                                     for p in missed[:10]],
            "top_tags": tag_counts.most_common(20),
        })
        print(json.dumps(report[-1]), flush=True)
    await adapter.aclose()
    print("RATE", adapter.ratelimit_remaining, adapter.ratelimit_reset)


asyncio.run(main())
