"""Recall and volume audit: tag variants, location terms, reposts, long OR queries.

Read-only. Prints counts plus title tags / location tokens only (no post text).
"""
import asyncio, json, os, re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from rediska_worker.tasks.scout import _get_reddit_adapter

import importlib.util
spec = importlib.util.spec_from_file_location("a1", "/tmp/search_audit.py")
# reuse parse/ev/tokens/collect without running main
src = open("/tmp/search_audit.py").read().split("async def main")[0]
ns = {}
exec(src, ns)
parse, ev, tokens, collect = ns["parse"], ns["ev"], ns["tokens"], ns["collect"]

# Any "who4whom" code, tolerant of brackets, glued ages (29F4M), spacing (F 4 M), case, suffixes.
CODE = re.compile(r"(?<![a-z])(\d{0,2})\s*([mftnb]{1,3}(?:tf|tm)?)\s*4\s*([a-z]{1,4})", re.I)
FEM_POSTER = re.compile(r"^(f|fm|mf|ff|tf|mtf|ftf)$", re.I)  # poster includes a woman
SEEKS_OK = re.compile(r"^(m|a|r|mf|fm|mm|any)s?$", re.I)      # seeks man/any/couple

CUR_LOC = {"pa", "nj", "phila", "philly"}
EXT_LOC = CUR_LOC | {"philadelphia", "pennsylvania", "jersey", "delaware", "de", "phl",
                     "southjersey", "sj", "lehigh", "allentown", "bucks", "montco",
                     "harrisburg", "lancaster", "wilmington", "trenton", "camden",
                     "nyc", "ny", "newyork", "brooklyn", "baltimore", "md", "maryland",
                     "dc", "dmv", "newjersey"}

TARGET_Q = ("(F4M OR F4A OR F4R OR F4MF OR FM4M OR MF4M OR FM4A OR MF4A OR FM4FM "
            "OR MF4MF OR FM4MF OR MF4FM)")


def codes(title):
    out = []
    for age, who, whom in CODE.findall(title or ""):
        out.append((age, who.lower(), whom.lower()))
    return out


def classify(title):
    cs = codes(title)
    if not cs:
        return "no_code", None
    for age, who, whom in cs:
        if FEM_POSTER.match(who) and SEEKS_OK.match(whom):
            return "target", (age, who, whom)
    return "other", cs[0]


async def main():
    db = sessionmaker(bind=create_engine(os.environ["MYSQL_URL"]))()
    watches = db.execute(text("select id, source_location, search_query from scout_watches "
                              "where is_trial=0 and is_active=1 order by id")).all()
    adapter = _get_reddit_adapter(db)
    now = datetime.now(timezone.utc)
    totals = defaultdict(float)
    for wid, sub, q in watches:
        new = await collect(adapter, sub)
        oldest = min(p.created_at for p in new)
        win_h = min((now - oldest).total_seconds() / 3600, 7 * 24)
        start = now - timedelta(hours=win_h)
        posts = [p for p in new if p.created_at >= start]
        per_day = 24 / max(win_h, 1)
        cls = Counter()
        variant = Counter()      # target posts the current gender clause misses, by form
        targets = []
        for p in posts:
            c, info = classify(p.title)
            cls[c] += 1
            if c == "target":
                targets.append(p)
                age, who, whom = info
                tok = tokens(p.title)
                if not ({"f4m", "f4a"} & tok):
                    form = "glued_age" if age else f"{who}4{whom}"
                    variant[form] += 1
        loc_clause = "PA" in q
        cur_ok = ext_ok = 0
        missing_loc_tokens = Counter()
        for p in targets:
            tk = tokens(p.title) | tokens(p.body_text)
            if CUR_LOC & tk:
                cur_ok += 1
            if EXT_LOC & tk:
                ext_ok += 1
            else:
                for h in re.findall(r"#([A-Za-z]+)|\[([A-Za-z ]+)\]", p.title or ""):
                    w = (h[0] or h[1]).strip().lower()
                    if w and not CODE.search(w):
                        missing_loc_tokens[w] += 1
        authors = Counter(p.author_username for p in targets)
        # Long OR group: does Reddit search agree with local evaluation?
        long_q = TARGET_Q + (" AND (PA OR NJ OR PHILA OR PHILLY)" if loc_clause else "")
        t = "day" if win_h <= 24 else "week"
        found = await collect(adapter, sub, query=long_q, t=t)
        tree = parse(long_q)
        s_ids = {p.external_id for p in found if p.created_at >= start}
        l_ids = {p.external_id for p in posts
                 if ev(tree, tokens(p.title) | tokens(p.body_text))}
        row = {
            "sub": sub, "window_h": round(win_h, 1), "posts_per_day": round(len(posts) * per_day),
            "per_day": {k: round(v * per_day, 1) for k, v in cls.items()},
            "target_missed_by_current_gender_clause_per_day": {k: round(v * per_day, 1)
                                                               for k, v in variant.items()},
            "target_per_day": round(len(targets) * per_day, 1),
            "target_distinct_authors_per_day": round(len(authors) * per_day, 1),
            "location_clause": loc_clause,
            "target_with_current_loc_terms_per_day": round(cur_ok * per_day, 1),
            "target_with_extended_loc_terms_per_day": round(ext_ok * per_day, 1),
            "unmatched_title_tags_sample": missing_loc_tokens.most_common(12) if loc_clause else None,
            "long_or_query_len": len(long_q),
            "long_or_search": len(s_ids), "long_or_local": len(l_ids),
            "long_or_search_missed": len(l_ids - s_ids), "long_or_search_extra": len(s_ids - l_ids),
        }
        print(json.dumps(row), flush=True)
        totals["posts"] += len(posts) * per_day
        totals["target"] += len(targets) * per_day
        totals["no_code"] += cls["no_code"] * per_day
        totals["target_authors"] += len(authors) * per_day
    await adapter.aclose()
    print("TOTALS/day", {k: round(v) for k, v in totals.items()})
    print("RATE", adapter.ratelimit_remaining)


asyncio.run(main())
