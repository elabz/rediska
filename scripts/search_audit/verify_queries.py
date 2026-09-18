"""Verify the expanded watch queries: Reddit search vs local evaluation on /new."""
import asyncio, json, os
from datetime import datetime, timezone, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from rediska_worker.tasks.scout import _get_reddit_adapter

src = open("/tmp/search_audit.py").read().split("async def main")[0]
ns = {}
exec(src, ns)
parse, ev, tokens, collect = ns["parse"], ns["ev"], ns["tokens"], ns["collect"]

GENDER = ("(F4M OR F4A OR F4Any OR F4R OR F4MF OR FM4M OR MF4M OR FM4A OR MF4A "
          "OR FM4FM OR MF4MF OR FM4MF OR MF4FM)")
LOCATION = ("(PA OR NJ OR PHILA OR PHILLY OR Philadelphia OR Pennsylvania OR Jersey "
            "OR Delaware OR NYC OR Baltimore)")
NEW_QUERIES = {1: GENDER, 2: GENDER, 3: f"{GENDER} AND {LOCATION}",
               4: f"{GENDER} AND {LOCATION}", 5: f"{GENDER} AND {LOCATION}",
               6: f"{GENDER} AND {LOCATION}"}


async def main():
    db = sessionmaker(bind=create_engine(os.environ["MYSQL_URL"]))()
    watches = db.execute(text("select id, source_location, search_query from scout_watches "
                              "where is_trial=0 order by id")).all()
    adapter = _get_reddit_adapter(db)
    now = datetime.now(timezone.utc)
    for wid, sub, old_q in watches:
        q = NEW_QUERIES[wid]
        new = await collect(adapter, sub)
        win_h = min((now - min(p.created_at for p in new)).total_seconds() / 3600, 168)
        start = now - timedelta(hours=win_h)
        posts = [p for p in new if p.created_at >= start]
        t = "day" if win_h <= 24 else "week"
        found = await collect(adapter, sub, query=q, t=t)
        s_ids = {p.external_id for p in found if p.created_at >= start}
        tree_new, tree_old = parse(q), parse(old_q)
        l_new = {p.external_id for p in posts if ev(tree_new, tokens(p.title) | tokens(p.body_text))}
        l_old = {p.external_id for p in posts if ev(tree_old, tokens(p.title) | tokens(p.body_text))}
        per_day = 24 / max(win_h, 1)
        print(json.dumps({
            "watch": wid, "sub": sub, "query_len": len(q), "window_h": round(win_h, 1),
            "search": len(s_ids), "local": len(l_new),
            "search_missed": len(l_new - s_ids), "search_extra": len(s_ids - l_new),
            "old_per_day": round(len(l_old) * per_day, 1),
            "new_per_day": round(len(l_new) * per_day, 1),
            "old_still_covered": l_old <= l_new,
        }), flush=True)
    await adapter.aclose()


asyncio.run(main())
