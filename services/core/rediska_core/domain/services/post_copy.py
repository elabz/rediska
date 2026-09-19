"""Post copy detection: the same text posted by different accounts.

Every post that reaches the system gets a ``post_fingerprints`` row holding an
exact hash of the normalised body and a bottom-k MinHash sketch over 5-word
shingles — never the text itself, so detection survives scout history cleanup.

At ingest a new fingerprint is compared against stored ones that share a sketch
band; a post by a *different* author at estimated Jaccard >= the threshold is a
copy and joins (or creates, or merges) a copy cluster. Same-author matches are
reposts: recorded on the fingerprint, never clustered.

Clusters are classified from stored facts only (no LLM, embeddings or provider
call): ``ring_suspect`` / ``returning_author`` / ``unclassified``. A human
decision (``confirmed_ring`` / ``same_person`` / ``coincidence``) overrides the
computed kind; ``coincidence`` dissolves the cluster and suppresses its texts.

Content is fingerprinted verbatim — nothing is filtered or redacted.
"""

from __future__ import annotations

import hashlib
import logging
import re
import struct
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rediska_core.config import get_settings
from rediska_core.domain.models import (
    AuditLog,
    CopyCluster,
    CopyClusterMember,
    CopyClusterSuppression,
    ExternalAccount,
    PostFingerprint,
    PostFingerprintBand,
    ProfileItem,
)
from rediska_core.domain.services.external_listing import DETAILS_BLOCK_MARKER

logger = logging.getLogger(__name__)

SHINGLE_WORDS = 5
SKETCH_SIZE = 64
BAND_COUNT = 8
# A band shared by more fingerprints than this is boilerplate (rules text,
# sign-offs) and is ignored for candidate generation.
BOILERPLATE_BAND_LIMIT = 200
_HASH_MASK = (1 << 63) - 1  # band keys live in a signed BIGINT column
_TOKEN_RE = re.compile(r"[a-z0-9']+")

KIND_RING_SUSPECT = "ring_suspect"
KIND_RETURNING_AUTHOR = "returning_author"
KIND_UNCLASSIFIED = "unclassified"
KINDS = (KIND_RING_SUSPECT, KIND_RETURNING_AUTHOR, KIND_UNCLASSIFIED)

DECISION_CONFIRMED_RING = "confirmed_ring"
DECISION_SAME_PERSON = "same_person"
DECISION_COINCIDENCE = "coincidence"
DECISIONS = (DECISION_CONFIRMED_RING, DECISION_SAME_PERSON, DECISION_COINCIDENCE)

# Effective kinds that skip scout analysis and never auto-promote.
RING_KINDS = (KIND_RING_SUSPECT, DECISION_CONFIRMED_RING)

DEAD_ACCOUNT_STATUSES = ("deleted", "suspended")

SOURCES = ("scout", "trial", "browse", "lead", "profile_item")


# =============================================================================
# PURE FINGERPRINTING
# =============================================================================


@dataclass(frozen=True)
class Features:
    """What gets stored for one body: lengths, exact hash, optional sketch."""

    char_len: int
    token_count: int
    exact_hash: bytes
    sketch: Optional[tuple[int, ...]]


def strip_details_block(text: Optional[str]) -> str:
    """Drop the structured external-listing details block, if it leads the body.

    The block (location/age/kinks facts prepended for weheartbdsm listings) is
    boilerplate-shaped; fingerprinting it would cluster unrelated listings.
    """
    if not text:
        return ""
    stripped = text.lstrip()
    if stripped.startswith(DETAILS_BLOCK_MARKER):
        parts = stripped.split("\n\n", 1)
        return parts[1] if len(parts) > 1 else ""
    return text


def normalise(text: Optional[str]) -> list[str]:
    """Lower-cased ``[a-z0-9']+`` tokens."""
    return _TOKEN_RE.findall((text or "").lower())


def _hash64(value: str) -> int:
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & _HASH_MASK


def shingle_hashes(tokens: list[str], size: int = SHINGLE_WORDS) -> set[int]:
    """Hashes of every ``size``-word shingle (one shingle for shorter texts)."""
    if not tokens:
        return set()
    if len(tokens) < size:
        return {_hash64(" ".join(tokens))}
    return {_hash64(" ".join(tokens[i:i + size])) for i in range(len(tokens) - size + 1)}


def bottom_k(hashes: Iterable[int], k: int = SKETCH_SIZE) -> tuple[int, ...]:
    """The ``k`` smallest hash values, ascending."""
    return tuple(sorted(set(hashes))[:k])


def exact_hash_of(tokens: list[str]) -> bytes:
    return hashlib.blake2b(" ".join(tokens).encode("utf-8"), digest_size=16).digest()


def compute_features(body_text: Optional[str], min_chars: Optional[int] = None) -> Optional[Features]:
    """Features of a post body, or None when it has no tokens at all.

    Bodies shorter than ``min_chars`` get an exact hash only: short posts
    collide on stock phrases.
    """
    if min_chars is None:
        min_chars = get_settings().copy_min_chars
    body = strip_details_block(body_text).strip()
    tokens = normalise(body)
    if not tokens:
        return None
    sketch = bottom_k(shingle_hashes(tokens)) if len(body) >= min_chars else None
    return Features(
        char_len=len(body),
        token_count=len(tokens),
        exact_hash=exact_hash_of(tokens),
        sketch=sketch,
    )


def pack_sketch(sketch: Optional[Iterable[int]]) -> Optional[bytes]:
    if sketch is None:
        return None
    values = list(sketch)
    return struct.pack(f">{len(values)}Q", *values)


def unpack_sketch(blob: Optional[bytes]) -> Optional[tuple[int, ...]]:
    if not blob:
        return None
    return struct.unpack(f">{len(blob) // 8}Q", blob)


def band_keys(sketch: Optional[Iterable[int]], bands: int = BAND_COUNT) -> list[int]:
    """The smallest sketch values, used as lookup keys."""
    if sketch is None:
        return []
    return list(sketch)[:bands]


def jaccard_estimate(a: Optional[Iterable[int]], b: Optional[Iterable[int]], k: int = SKETCH_SIZE) -> float:
    """Bottom-k estimate of the Jaccard similarity of two shingle sets."""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    union_k = sorted(sa | sb)[:k]
    if not union_k:
        return 0.0
    both = sum(1 for v in union_k if v in sa and v in sb)
    return both / len(union_k)


# =============================================================================
# CLASSIFICATION (pure)
# =============================================================================


@dataclass
class AuthorFacts:
    """What classification knows about one author of a cluster."""

    username: str
    post_times: list[datetime]  # this author's posts in the cluster
    dead: bool = False  # account deleted or suspended
    # Earliest / latest stored activity of any kind (fingerprints, profile items).
    first_activity: Optional[datetime] = None
    last_activity: Optional[datetime] = None

    @property
    def first_post(self) -> Optional[datetime]:
        return min(self.post_times) if self.post_times else None

    @property
    def last_post(self) -> Optional[datetime]:
        return max(self.post_times) if self.post_times else None


def classify(authors: list[AuthorFacts], window_days: int) -> str:
    """Kind of a cluster from its authors (see module docstring)."""
    authors = [a for a in authors if a.post_times]
    if len(authors) >= 3:
        return KIND_RING_SUSPECT
    if len(authors) < 2:
        return KIND_UNCLASSIFIED

    window = timedelta(days=window_days)
    a, b = authors
    gap = min(abs(x - y) for x in a.post_times for y in b.post_times)
    if not a.dead and not b.dead and gap <= window:
        return KIND_RING_SUSPECT
    if gap <= window:
        return KIND_UNCLASSIFIED

    earlier, later = sorted(authors, key=lambda f: f.first_post)  # type: ignore[arg-type,return-value]
    if earlier.dead:
        return KIND_RETURNING_AUTHOR
    later_first = min(t for t in (later.first_activity, later.first_post) if t is not None)
    earlier_last = max(t for t in (earlier.last_activity, earlier.last_post) if t is not None)
    if earlier_last <= later_first:
        return KIND_RETURNING_AUTHOR
    return KIND_UNCLASSIFIED


def is_handled(
    kind: str,
    decision: Optional[str],
    author_count: int,
    avg_char_len: int,
    min_authors: int,
    min_chars: int,
) -> bool:
    """Whether a cluster is a spam ring handled without a human.

    A confirmed ring always is. A computed ring suspect is when it has at least
    ``min_authors`` distinct authors and its posts average ``min_chars`` or
    more (short posts may be a community's posting template). Any other
    decision (``same_person``, ``coincidence``) takes the cluster out.
    Handled clusters are skipped by the scout and hidden from the lead list
    and needs-review queue; nothing is deleted or banned.
    """
    if decision is not None:
        return decision == DECISION_CONFIRMED_RING
    return (
        kind == KIND_RING_SUSPECT
        and author_count >= min_authors
        and avg_char_len >= min_chars
    )


def refresh_handled(cluster: CopyCluster) -> bool:
    settings = get_settings()
    cluster.handled = is_handled(
        cluster.kind,
        cluster.decision,
        cluster.author_count,
        cluster.avg_char_len or 0,
        settings.copy_ring_min_authors,
        settings.copy_ring_min_chars,
    )
    return cluster.handled


# =============================================================================
# INGEST
# =============================================================================


@dataclass
class Match:
    fingerprint: PostFingerprint
    similarity: float
    suppressed: bool = False


@dataclass
class FingerprintOutcome:
    fingerprint: PostFingerprint
    created: bool
    cluster_id: Optional[int] = None
    repost_of_id: Optional[int] = None
    suppressed: bool = False
    matches: list[int] = field(default_factory=list)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _author_key(username: Optional[str]) -> str:
    return (username or "").strip().lower()


def post_time(fp: PostFingerprint) -> datetime:
    """Best known time of a post: provider post time, else first seen."""
    return fp.posted_at or fp.first_seen_at


def fingerprint_post(
    db: Session,
    *,
    provider_id: str,
    external_post_id: str,
    author_username: Optional[str],
    body_text: Optional[str],
    source: str,
    posted_at: Optional[datetime] = None,
    location: Optional[str] = None,
    account_id: Optional[int] = None,
    audit: bool = True,
    link: bool = True,
    first_seen_at: Optional[datetime] = None,
) -> Optional[FingerprintOutcome]:
    """Get or create the fingerprint of one post and link it to copies.

    Idempotent per ``(provider_id, external_post_id)``: a post already
    fingerprinted through another path is returned as is (missing account and
    post time are filled in). Returns None for a body with no tokens.
    ``link=False`` stores the fingerprint without matching (backfill does the
    linking in a second pass). ``first_seen_at`` defaults to now; backfill
    passes the stored sighting time.
    """
    if not external_post_id or source not in SOURCES:
        return None
    existing = db.execute(
        select(PostFingerprint).where(
            PostFingerprint.provider_id == provider_id,
            PostFingerprint.external_post_id == external_post_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.account_id is None and account_id is not None:
            existing.account_id = account_id
        if existing.posted_at is None and posted_at is not None:
            existing.posted_at = _naive(posted_at)
        return FingerprintOutcome(existing, created=False, repost_of_id=existing.repost_of_id)

    features = compute_features(body_text)
    if features is None:
        return None

    fp = PostFingerprint(
        provider_id=provider_id,
        external_post_id=external_post_id,
        author_username=(author_username or None) and author_username[:255],
        account_id=account_id,
        location=location[:255] if location else None,
        posted_at=_naive(posted_at),
        first_seen_at=_naive(first_seen_at) or _utcnow(),
        char_len=features.char_len,
        exact_hash=features.exact_hash,
        sketch=pack_sketch(features.sketch),
        source=source,
    )
    try:
        with db.begin_nested():
            db.add(fp)
            db.flush()
    except IntegrityError:
        # Another path fingerprinted the same post concurrently.
        existing = db.execute(
            select(PostFingerprint).where(
                PostFingerprint.provider_id == provider_id,
                PostFingerprint.external_post_id == external_post_id,
            )
        ).scalar_one_or_none()
        if existing is None:
            raise
        return FingerprintOutcome(existing, created=False, repost_of_id=existing.repost_of_id)

    outcome = FingerprintOutcome(fp, created=True)
    if link:
        _link(db, fp, features.sketch, outcome, audit=audit)
    for key in band_keys(features.sketch):
        db.add(PostFingerprintBand(band_hash=key, fingerprint_id=fp.id))
    db.flush()
    return outcome


def safe_fingerprint_post(db: Session, **kwargs: Any) -> Optional[FingerprintOutcome]:
    """``fingerprint_post`` that never fails ingestion: errors log a warning.

    Runs in a savepoint so a failure leaves the caller's transaction intact.
    """
    try:
        with db.begin_nested():
            return fingerprint_post(db, **kwargs)
    except Exception as e:  # noqa: BLE001 - fingerprinting is best-effort
        logger.warning(
            "Post fingerprint failed for %s/%s: %s",
            kwargs.get("provider_id"), kwargs.get("external_post_id"), e,
        )
        return None


def link_existing(db: Session, fp: PostFingerprint, audit: bool = False) -> FingerprintOutcome:
    """Match an already-stored fingerprint against the others (backfill pass 2)."""
    outcome = FingerprintOutcome(fp, created=False)
    _link(db, fp, unpack_sketch(fp.sketch), outcome, audit=audit)
    return outcome


def find_matches(
    db: Session,
    fp: PostFingerprint,
    sketch: Optional[tuple[int, ...]],
    threshold: Optional[float] = None,
) -> list[Match]:
    """Stored fingerprints (other than ``fp``) whose text is a copy of ``fp``'s."""
    if sketch is None:
        return []  # short bodies never cluster
    if threshold is None:
        threshold = get_settings().copy_jaccard_threshold

    keys = band_keys(sketch)
    counts: dict[int, int] = {
        r[0]: r[1]
        for r in db.execute(
            select(PostFingerprintBand.band_hash, func.count())
            .where(PostFingerprintBand.band_hash.in_(keys))
            .group_by(PostFingerprintBand.band_hash)
        ).all()
    }
    usable = [k for k in keys if counts.get(k, 0) <= BOILERPLATE_BAND_LIMIT]
    candidate_ids: set[int] = set()
    if usable:
        candidate_ids.update(
            r[0]
            for r in db.execute(
                select(PostFingerprintBand.fingerprint_id)
                .where(PostFingerprintBand.band_hash.in_(usable))
                .distinct()
            ).all()
        )
    candidate_ids.update(
        r[0]
        for r in db.execute(
            select(PostFingerprint.id)
            .where(
                PostFingerprint.exact_hash == fp.exact_hash,
                PostFingerprint.sketch.is_not(None),
            )
            .limit(BOILERPLATE_BAND_LIMIT)
        ).all()
    )
    candidate_ids.discard(fp.id)
    if not candidate_ids:
        return []

    candidates = db.execute(
        select(PostFingerprint).where(
            PostFingerprint.id.in_(candidate_ids),
            PostFingerprint.provider_id == fp.provider_id,
        )
    ).scalars().all()
    suppressed = {
        r[0]
        for r in db.execute(
            select(CopyClusterSuppression.fingerprint_id).where(
                CopyClusterSuppression.fingerprint_id.in_([c.id for c in candidates])
            )
        ).all()
    }
    matches = []
    for cand in candidates:
        if cand.exact_hash == fp.exact_hash:
            sim = 1.0
        else:
            sim = jaccard_estimate(sketch, unpack_sketch(cand.sketch))
        if sim >= threshold:
            matches.append(Match(cand, sim, suppressed=cand.id in suppressed))
    return matches


def _link(
    db: Session,
    fp: PostFingerprint,
    sketch: Optional[tuple[int, ...]],
    outcome: FingerprintOutcome,
    audit: bool,
) -> None:
    matches = find_matches(db, fp, sketch)
    outcome.matches = [m.fingerprint.id for m in matches]
    if not matches:
        return

    me = _author_key(fp.author_username)
    same = [m for m in matches if _author_key(m.fingerprint.author_username) == me]
    if same and fp.repost_of_id is None:
        earliest = min(same, key=lambda m: post_time(m.fingerprint))
        if post_time(earliest.fingerprint) <= post_time(fp):
            fp.repost_of_id = earliest.fingerprint.id
            outcome.repost_of_id = fp.repost_of_id

    # A post whose best partner is a suppressed (coincidence) text is itself
    # suppressed, so every later copy of a template stays out of clusters.
    best = max(matches, key=lambda m: (m.similarity, m.suppressed))
    if best.suppressed:
        _suppress(db, fp, cluster_id=None)
        outcome.suppressed = True
        return
    matches = [m for m in matches if not m.suppressed]
    cross = [m for m in matches if _author_key(m.fingerprint.author_username) != me]

    # ``fp`` itself may already be a member (backfill links posts that an
    # earlier post in the same pass pulled into a cluster).
    member_rows = db.execute(
        select(CopyClusterMember).where(
            CopyClusterMember.fingerprint_id.in_([m.fingerprint.id for m in matches] + [fp.id])
        )
    ).scalars().all()
    clustered = {row.fingerprint_id: row.cluster_id for row in member_rows}
    cluster_ids = set(clustered.values())
    if not cluster_ids and not cross:
        return  # a repost of the author's own ad

    now = _utcnow()
    created = False
    merged_from: list[int] = []
    if cluster_ids:
        clusters = db.execute(
            select(CopyCluster).where(CopyCluster.id.in_(cluster_ids))
        ).scalars().all()
        target = max(clusters, key=lambda c: (c.member_count, -c.id))
        for other in clusters:
            if other.id != target.id:
                _merge(db, source=other, target=target, audit=audit)
                merged_from.append(other.id)
    else:
        target = CopyCluster(
            provider_id=fp.provider_id,
            kind=KIND_UNCLASSIFIED,
            created_at=now,
            updated_at=now,
        )
        db.add(target)
        db.flush()
        created = True

    best_sim = max(m.similarity for m in matches)
    if fp.id not in clustered:
        db.add(CopyClusterMember(
            cluster_id=target.id, fingerprint_id=fp.id, similarity=best_sim, joined_at=now,
        ))
    for m in matches:
        if m.fingerprint.id not in clustered:
            db.add(CopyClusterMember(
                cluster_id=target.id,
                fingerprint_id=m.fingerprint.id,
                similarity=m.similarity,
                joined_at=now,
            ))
    db.flush()
    recompute_cluster(db, target)
    outcome.cluster_id = target.id

    if audit:
        _audit(
            db,
            "copy_cluster.create" if created else "copy_cluster.join",
            target.id,
            fp.provider_id,
            actor="system",
            request_json={
                "fingerprint_id": fp.id,
                "external_post_id": fp.external_post_id,
                "author_username": fp.author_username,
                "matched_fingerprint_ids": [m.fingerprint.id for m in matches],
                "similarity": round(best_sim, 3),
            },
            response_json={
                "kind": target.kind,
                "author_count": target.author_count,
                "member_count": target.member_count,
                "merged_from": merged_from,
            },
        )


def _merge(db: Session, source: CopyCluster, target: CopyCluster, audit: bool) -> None:
    """Move every member of ``source`` into ``target`` and delete ``source``."""
    moved = db.execute(
        select(CopyClusterMember).where(CopyClusterMember.cluster_id == source.id)
    ).scalars().all()
    for row in moved:
        row.cluster_id = target.id
    if target.decision is None and source.decision is not None:
        target.decision = source.decision
        target.decision_notes = source.decision_notes
        target.decided_at = source.decided_at
    db.flush()
    if audit:
        _audit(
            db,
            "copy_cluster.merge",
            target.id,
            target.provider_id,
            actor="system",
            request_json={"source_cluster_id": source.id, "target_cluster_id": target.id},
            response_json={"members_moved": len(moved)},
        )
    db.delete(source)
    db.flush()


def _suppress(db: Session, fp: PostFingerprint, cluster_id: Optional[int]) -> None:
    exists = db.execute(
        select(CopyClusterSuppression.id).where(CopyClusterSuppression.fingerprint_id == fp.id)
    ).first()
    if exists is None:
        db.add(CopyClusterSuppression(
            fingerprint_id=fp.id,
            exact_hash=fp.exact_hash,
            cluster_id=cluster_id,
            created_at=_utcnow(),
        ))


# =============================================================================
# CLASSIFICATION (from stored facts)
# =============================================================================


def recompute_cluster(db: Session, cluster: CopyCluster) -> str:
    """Refresh a cluster's counts, time range and computed kind."""
    fps = db.execute(
        select(PostFingerprint)
        .join(CopyClusterMember, CopyClusterMember.fingerprint_id == PostFingerprint.id)
        .where(CopyClusterMember.cluster_id == cluster.id)
    ).scalars().all()
    by_author: dict[str, list[datetime]] = defaultdict(list)
    for fp in fps:
        by_author[_author_key(fp.author_username)].append(post_time(fp))

    facts = _author_facts(db, cluster.provider_id, by_author)
    times = [post_time(fp) for fp in fps]
    cluster.member_count = len(fps)
    cluster.author_count = len([a for a in by_author if a])
    cluster.first_posted_at = min(times) if times else None
    cluster.last_posted_at = max(times) if times else None
    cluster.avg_char_len = round(sum(fp.char_len for fp in fps) / len(fps)) if fps else 0
    cluster.kind = classify(facts, get_settings().copy_ring_window_days)
    refresh_handled(cluster)
    cluster.classified_at = _utcnow()
    cluster.updated_at = _utcnow()
    db.flush()
    return cluster.kind


def _author_facts(
    db: Session, provider_id: str, by_author: dict[str, list[datetime]]
) -> list[AuthorFacts]:
    names = [a for a in by_author if a]
    if not names:
        return []
    accounts = {
        a.external_username.lower(): a
        for a in db.execute(
            select(ExternalAccount).where(
                ExternalAccount.provider_id == provider_id,
                func.lower(ExternalAccount.external_username).in_(names),
            )
        ).scalars().all()
    }
    # Stored activity: every fingerprint of the author, plus profile items.
    fp_span = {
        r[0].lower(): (r[1], r[2])
        for r in db.execute(
            select(
                PostFingerprint.author_username,
                func.min(func.coalesce(PostFingerprint.posted_at, PostFingerprint.first_seen_at)),
                func.max(func.coalesce(PostFingerprint.posted_at, PostFingerprint.first_seen_at)),
            )
            .where(
                PostFingerprint.provider_id == provider_id,
                func.lower(PostFingerprint.author_username).in_(names),
            )
            .group_by(PostFingerprint.author_username)
        ).all()
        if r[0]
    }
    account_ids = {a.id: name for name, a in accounts.items()}
    item_span: dict[str, tuple[Any, Any]] = {}
    if account_ids:
        for account_id, lo, hi in db.execute(
            select(
                ProfileItem.account_id,
                func.min(ProfileItem.item_created_at),
                func.max(ProfileItem.item_created_at),
            )
            .where(ProfileItem.account_id.in_(list(account_ids)))
            .group_by(ProfileItem.account_id)
        ).all():
            item_span[account_ids[account_id]] = (lo, hi)

    facts = []
    for name in names:
        account = accounts.get(name)
        lows = [t for t in (fp_span.get(name, (None, None))[0], item_span.get(name, (None, None))[0]) if t]
        highs = [t for t in (fp_span.get(name, (None, None))[1], item_span.get(name, (None, None))[1]) if t]
        facts.append(AuthorFacts(
            username=name,
            post_times=by_author[name],
            dead=bool(account and account.remote_status in DEAD_ACCOUNT_STATUSES),
            first_activity=_naive(min(lows)) if lows else None,
            last_activity=_naive(max(highs)) if highs else None,
        ))
    return facts


def recompute_clusters_for_author(db: Session, provider_id: str, username: str) -> list[int]:
    """Reclassify every cluster an author belongs to (e.g. after a status change)."""
    cluster_ids = [
        r[0]
        for r in db.execute(
            select(CopyClusterMember.cluster_id)
            .join(PostFingerprint, PostFingerprint.id == CopyClusterMember.fingerprint_id)
            .where(
                PostFingerprint.provider_id == provider_id,
                func.lower(PostFingerprint.author_username) == _author_key(username),
            )
            .distinct()
        ).all()
    ]
    for cluster in db.execute(
        select(CopyCluster).where(CopyCluster.id.in_(cluster_ids))
    ).scalars().all():
        recompute_cluster(db, cluster)
    return cluster_ids


# =============================================================================
# HUMAN DECISIONS
# =============================================================================


class CopyClusterNotFound(LookupError):
    pass


class CopyDecisionError(ValueError):
    pass


def decide(
    db: Session, cluster_id: int, decision: Optional[str], notes: Optional[str] = None
) -> CopyCluster:
    """Record the human's reading of a cluster (``None`` clears it).

    Never touches leads, analyses or bans. ``coincidence`` dissolves the
    cluster: members are removed and their fingerprints suppressed.
    """
    cluster = db.get(CopyCluster, cluster_id)
    if cluster is None:
        raise CopyClusterNotFound(f"Copy cluster {cluster_id} not found")
    if decision is not None and decision not in DECISIONS:
        raise CopyDecisionError(f"Unknown decision '{decision}'")
    if cluster.decision == DECISION_COINCIDENCE:
        raise CopyDecisionError("A dissolved cluster cannot be re-decided")

    previous = cluster.decision
    now = _utcnow()
    cluster.decision = decision
    cluster.decision_notes = notes or None
    cluster.decided_at = now if decision else None
    cluster.updated_at = now

    dissolved: list[int] = []
    if decision == DECISION_COINCIDENCE:
        members = db.execute(
            select(CopyClusterMember).where(CopyClusterMember.cluster_id == cluster.id)
        ).scalars().all()
        fps = {
            fp.id: fp
            for fp in db.execute(
                select(PostFingerprint).where(
                    PostFingerprint.id.in_([m.fingerprint_id for m in members])
                )
            ).scalars().all()
        }
        for member in members:
            fp = fps.get(member.fingerprint_id)
            if fp is not None:
                _suppress(db, fp, cluster_id=cluster.id)
                dissolved.append(fp.id)
            db.delete(member)
        cluster.member_count = 0
    refresh_handled(cluster)
    db.flush()

    _audit(
        db,
        "copy_cluster.decision",
        cluster.id,
        cluster.provider_id,
        actor="user",
        request_json={"decision": decision, "has_notes": bool(notes)},
        response_json={
            "previous_decision": previous,
            "kind": cluster.kind,
            "handled": cluster.handled,
            "suppressed_fingerprints": dissolved,
        },
    )
    db.flush()
    return cluster


# =============================================================================
# READ MODELS
# =============================================================================


def copy_summaries(
    db: Session, provider_id: str, external_post_ids: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """``copy`` field per external post id, in two queries.

    Posts without a live (non-dissolved) cluster are absent from the result.
    """
    ids = list({i for i in external_post_ids if i})
    if not ids:
        return {}
    rows = db.execute(
        select(PostFingerprint.external_post_id, PostFingerprint.author_username, CopyCluster)
        .join(CopyClusterMember, CopyClusterMember.fingerprint_id == PostFingerprint.id)
        .join(CopyCluster, CopyCluster.id == CopyClusterMember.cluster_id)
        .where(
            PostFingerprint.provider_id == provider_id,
            PostFingerprint.external_post_id.in_(ids),
        )
    ).all()
    if not rows:
        return {}
    cluster_ids = {c.id for _, _, c in rows}
    # Earliest post per (cluster, author), to name the earliest *other* post.
    firsts: dict[int, list[tuple[str, datetime]]] = defaultdict(list)
    for cluster_id, author, first in db.execute(
        select(
            CopyClusterMember.cluster_id,
            func.lower(PostFingerprint.author_username),
            func.min(func.coalesce(PostFingerprint.posted_at, PostFingerprint.first_seen_at)),
        )
        .join(PostFingerprint, PostFingerprint.id == CopyClusterMember.fingerprint_id)
        .where(CopyClusterMember.cluster_id.in_(cluster_ids))
        .group_by(CopyClusterMember.cluster_id, func.lower(PostFingerprint.author_username))
    ).all():
        firsts[cluster_id].append((author or "", first))

    out = {}
    for ext_id, author, cluster in rows:
        me = _author_key(author)
        others = [t for a, t in firsts.get(cluster.id, []) if a != me and t is not None]
        out[ext_id] = {
            "cluster_id": cluster.id,
            "kind": cluster.effective_kind,
            "computed_kind": cluster.kind,
            "decision": cluster.decision,
            "author_count": cluster.author_count,
            "handled": cluster.handled,
            "earliest_other_posted_at": min(others) if others else None,
        }
    return out


def cluster_kind_for_post(db: Session, provider_id: str, external_post_id: str) -> Optional[str]:
    """Effective kind of a post's cluster, or None."""
    summary = copy_summaries(db, provider_id, [external_post_id]).get(external_post_id)
    return summary["kind"] if summary else None


def is_ring_post(db: Session, provider_id: str, external_post_id: Optional[str]) -> bool:
    """Any ring (suspect or confirmed): never auto-promoted."""
    if not external_post_id:
        return False
    return cluster_kind_for_post(db, provider_id, external_post_id) in RING_KINDS


def is_handled_post(db: Session, provider_id: str, external_post_id: Optional[str]) -> bool:
    """The post belongs to a spam ring handled automatically (scout skip)."""
    if not external_post_id:
        return False
    return db.execute(
        select(CopyCluster.id)
        .join(CopyClusterMember, CopyClusterMember.cluster_id == CopyCluster.id)
        .join(PostFingerprint, PostFingerprint.id == CopyClusterMember.fingerprint_id)
        .where(
            PostFingerprint.provider_id == provider_id,
            PostFingerprint.external_post_id == external_post_id,
            CopyCluster.handled.is_(True),
        )
    ).first() is not None


def not_in_handled_ring(external_post_id_column):
    """Condition: the post id belongs to no handled ring (list exclusion)."""
    return ~external_post_id_column.in_(
        select(PostFingerprint.external_post_id)
        .join(CopyClusterMember, CopyClusterMember.fingerprint_id == PostFingerprint.id)
        .join(CopyCluster, CopyCluster.id == CopyClusterMember.cluster_id)
        .where(CopyCluster.handled.is_(True))
    )


def recompute_all(db: Session) -> dict[str, int]:
    """Reclassify every live cluster (e.g. after a threshold change)."""
    counts: dict[str, int] = defaultdict(int)
    for cluster in db.execute(
        select(CopyCluster).where(
            (CopyCluster.decision.is_(None)) | (CopyCluster.decision != DECISION_COINCIDENCE)
        )
    ).scalars().all():
        recompute_cluster(db, cluster)
        counts[cluster.kind] += 1
        counts["handled"] += int(cluster.handled)
    db.flush()
    return dict(counts)


def list_clusters(
    db: Session,
    provider_id: Optional[str] = None,
    kind: Optional[str] = None,
    decision: Optional[str] = None,
    cursor: Optional[int] = None,
    limit: int = 50,
    author: Optional[str] = None,
    handled: Optional[bool] = None,
) -> tuple[list[CopyCluster], Optional[int]]:
    """Live clusters, most recently active first (keyset cursor on id).

    ``kind`` filters on the effective kind; ``decision='none'`` lists
    undecided clusters. Dissolved (``coincidence``) clusters are listed only
    when asked for by decision.
    """
    query = select(CopyCluster)
    if provider_id:
        query = query.where(CopyCluster.provider_id == provider_id)
    if kind:
        query = query.where(func.coalesce(CopyCluster.decision, CopyCluster.kind) == kind)
    if decision == "none":
        query = query.where(CopyCluster.decision.is_(None))
    elif decision:
        query = query.where(CopyCluster.decision == decision)
    if decision != DECISION_COINCIDENCE and kind != DECISION_COINCIDENCE:
        query = query.where(
            (CopyCluster.decision.is_(None)) | (CopyCluster.decision != DECISION_COINCIDENCE)
        )
    if handled is not None:
        query = query.where(CopyCluster.handled.is_(handled))
    if author:
        query = query.where(
            CopyCluster.id.in_(
                select(CopyClusterMember.cluster_id)
                .join(PostFingerprint, PostFingerprint.id == CopyClusterMember.fingerprint_id)
                .where(func.lower(PostFingerprint.author_username) == _author_key(author))
            )
        )
    if cursor:
        query = query.where(CopyCluster.id < cursor)
    rows = db.execute(query.order_by(CopyCluster.id.desc()).limit(limit + 1)).scalars().all()
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return list(rows[:limit]), next_cursor


def cluster_detail(db: Session, cluster_id: int) -> dict[str, Any]:
    """Members with what we already hold for each author, in batched queries."""
    from rediska_core.domain.models import (
        DoNotContact,
        LeadAnalysis,
        LeadPost,
        ScoutWatchPost,
    )
    from rediska_core.domain.services.analysis_evaluation import (
        FINAL_KEY,
        AnalysisEvaluationService,
    )

    cluster = db.get(CopyCluster, cluster_id)
    if cluster is None:
        raise CopyClusterNotFound(f"Copy cluster {cluster_id} not found")
    provider_id = cluster.provider_id

    rows = db.execute(
        select(CopyClusterMember, PostFingerprint)
        .join(PostFingerprint, PostFingerprint.id == CopyClusterMember.fingerprint_id)
        .where(CopyClusterMember.cluster_id == cluster.id)
    ).all()
    fps = [fp for _, fp in rows]
    names = {_author_key(fp.author_username) for fp in fps} - {""}
    ext_ids = [fp.external_post_id for fp in fps]

    accounts = {
        a.external_username.lower(): a
        for a in (
            db.execute(
                select(ExternalAccount).where(
                    ExternalAccount.provider_id == provider_id,
                    func.lower(ExternalAccount.external_username).in_(names),
                )
            ).scalars().all()
            if names else []
        )
    }
    account_ids = [a.id for a in accounts.values()]

    leads_by_post: dict[str, LeadPost] = {}
    leads_by_account: dict[int, list[LeadPost]] = defaultdict(list)
    if ext_ids or account_ids:
        conds = []
        if ext_ids:
            conds.append(LeadPost.external_post_id.in_(ext_ids))
        if account_ids:
            conds.append(LeadPost.author_account_id.in_(account_ids))
        from sqlalchemy import or_

        for lead in db.execute(
            select(LeadPost)
            .where(LeadPost.provider_id == provider_id, LeadPost.deleted_at.is_(None), or_(*conds))
            .order_by(LeadPost.id.desc())
        ).scalars().all():
            leads_by_post.setdefault(lead.external_post_id, lead)
            if lead.author_account_id is not None:
                leads_by_account[lead.author_account_id].append(lead)

    lead_ids = list({lead.id for ls in leads_by_account.values() for lead in ls} | {
        lead.id for lead in leads_by_post.values()
    })
    latest_analysis: dict[int, LeadAnalysis] = {}
    if lead_ids:
        for analysis in db.execute(
            select(LeadAnalysis)
            .where(LeadAnalysis.lead_id.in_(lead_ids))
            .order_by(LeadAnalysis.id.desc())
        ).scalars().all():
            latest_analysis.setdefault(analysis.lead_id, analysis)

    scout_by_post: dict[str, ScoutWatchPost] = {}
    if ext_ids:
        for post in db.execute(
            select(ScoutWatchPost)
            .where(ScoutWatchPost.external_post_id.in_(ext_ids))
            .order_by(ScoutWatchPost.id.desc())
        ).scalars().all():
            scout_by_post.setdefault(post.external_post_id, post)

    evals = AnalysisEvaluationService(db)
    lead_evals = evals.effective_for_subjects(
        "lead_analysis", [a.id for a in latest_analysis.values()]
    )
    scout_evals = evals.effective_for_subjects(
        "scout_post", [p.id for p in scout_by_post.values()]
    )

    bans = {
        d.external_username: d
        for d in (
            db.execute(
                select(DoNotContact).where(
                    DoNotContact.provider_id == provider_id,
                    DoNotContact.external_username.in_(names),
                )
            ).scalars().all()
            if names else []
        )
    }

    members = []
    for member, fp in sorted(rows, key=lambda r: post_time(r[1])):
        name = _author_key(fp.author_username)
        account = accounts.get(name)
        lead = leads_by_post.get(fp.external_post_id)
        if lead is None and account is not None and leads_by_account.get(account.id):
            lead = leads_by_account[account.id][0]
        analysis = latest_analysis.get(lead.id) if lead else None
        scout = scout_by_post.get(fp.external_post_id)
        verdict = None
        if analysis is not None and FINAL_KEY in lead_evals.get(analysis.id, {}):
            verdict = lead_evals[analysis.id][FINAL_KEY].human_verdict
        elif scout is not None and FINAL_KEY in scout_evals.get(scout.id, {}):
            verdict = scout_evals[scout.id][FINAL_KEY].human_verdict
        ban = bans.get(name)
        members.append({
            "member_id": member.id,
            "fingerprint_id": fp.id,
            "external_post_id": fp.external_post_id,
            "author_username": fp.author_username,
            "account_id": account.id if account else fp.account_id,
            "remote_status": account.remote_status if account else None,
            "posted_at": fp.posted_at,
            "first_seen_at": fp.first_seen_at,
            "location": fp.location,
            "source": fp.source,
            "char_len": fp.char_len,
            "similarity": member.similarity,
            "repost_of_id": fp.repost_of_id,
            "lead_id": lead.id if lead else None,
            "lead_status": lead.status if lead else None,
            "scout_post_id": scout.id if scout else None,
            "scout_watch_id": scout.watch_id if scout else None,
            "analysis_id": analysis.id if analysis else None,
            "recommendation": (
                analysis.final_recommendation if analysis
                else (scout.analysis_recommendation if scout else None)
            ),
            "human_verdict": verdict,
            "ban_id": ban.id if ban else None,
            "ban_status": ban.status if ban else None,
        })
    return {"cluster": cluster, "members": members}


# =============================================================================
# HELPERS
# =============================================================================


def _audit(
    db: Session,
    action_type: str,
    entity_id: Optional[int],
    provider_id: Optional[str],
    actor: str,
    request_json: Optional[dict] = None,
    response_json: Optional[dict] = None,
) -> None:
    db.add(AuditLog(
        ts=_utcnow(),
        actor=actor,
        action_type=action_type,
        provider_id=provider_id,
        entity_type="copy_cluster",
        entity_id=entity_id,
        request_json=request_json,
        response_json=response_json,
        result="ok",
    ))


# =============================================================================
# BACKFILL
# =============================================================================


@dataclass
class BackfillPost:
    provider_id: str
    external_post_id: str
    author_username: Optional[str]
    body_text: Optional[str]
    source: str
    posted_at: Optional[datetime]
    location: Optional[str]
    account_id: Optional[int]
    first_seen_at: Optional[datetime] = None


def _strip_title(text: Optional[str], title: Optional[str]) -> Optional[str]:
    """Profile items store ``title\\n\\nbody``; the title is not fingerprinted."""
    if text and title and text.startswith(title):
        return text[len(title):].lstrip("\n")
    return text


def stored_posts(db: Session) -> dict[tuple[str, str], BackfillPost]:
    """Every stored post body, deduplicated by provider post id.

    Preference when a post is stored more than once: lead (resolved body,
    post time) over scout post over profile item (title glued to the body).
    """
    from rediska_core.domain.models import LeadPost, ScoutWatch, ScoutWatchPost

    posts: dict[tuple[str, str], BackfillPost] = {}

    accounts = {
        a.id: (a.provider_id, a.external_username)
        for a in db.execute(select(ExternalAccount)).scalars().all()
    }
    for item in db.execute(
        select(ProfileItem).where(ProfileItem.item_type == "post")
    ).scalars().yield_per(1000):
        provider_id, username = accounts.get(item.account_id, ("reddit", None))
        if not item.external_item_id:
            continue
        posts[(provider_id, item.external_item_id)] = BackfillPost(
            provider_id=provider_id,
            external_post_id=item.external_item_id,
            author_username=username,
            body_text=_strip_title(item.text_content, item.link_title),
            source="profile_item",
            posted_at=item.item_created_at,
            location=f"r/{item.subreddit}" if item.subreddit else None,
            account_id=item.account_id,
            first_seen_at=item.item_created_at,
        )

    watches = {
        w.id: w for w in db.execute(select(ScoutWatch)).scalars().all()
    }
    for post in db.execute(select(ScoutWatchPost)).scalars().yield_per(1000):
        watch = watches.get(post.watch_id)
        provider_id = watch.provider_id if watch else "reddit"
        posts[(provider_id, post.external_post_id)] = BackfillPost(
            provider_id=provider_id,
            external_post_id=post.external_post_id,
            author_username=post.post_author,
            body_text=post.post_body,
            source="trial" if watch is not None and watch.is_trial else "scout",
            posted_at=None,
            location=watch.source_location if watch else None,
            account_id=None,
            first_seen_at=post.first_seen_at,
        )

    for lead in db.execute(select(LeadPost)).scalars().yield_per(1000):
        author = accounts.get(lead.author_account_id) if lead.author_account_id else None
        posts[(lead.provider_id, lead.external_post_id)] = BackfillPost(
            provider_id=lead.provider_id,
            external_post_id=lead.external_post_id,
            author_username=author[1] if author else None,
            body_text=lead.body_text,
            source="lead",
            posted_at=lead.post_created_at,
            location=lead.source_location,
            account_id=lead.author_account_id,
            first_seen_at=lead.created_at,
        )
    return posts


def estimate_clusters(
    items: list[tuple[str, tuple[int, ...], bytes]],
    threshold: Optional[float] = None,
) -> dict[str, int]:
    """In-memory copy of the matching rules, for a dry run that writes nothing.

    ``items`` are (author, sketch, exact_hash). Returns the number of clusters
    (components with two or more distinct authors) and authors in them.
    Suppressions are not considered.
    """
    if threshold is None:
        threshold = get_settings().copy_jaccard_threshold
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    bands: dict[int, list[int]] = defaultdict(list)
    exact: dict[bytes, list[int]] = defaultdict(list)
    for i, (_, sketch, digest) in enumerate(items):
        for key in band_keys(sketch):
            bands[key].append(i)
        exact[digest].append(i)
    for i, (author, sketch, digest) in enumerate(items):
        candidates: set[int] = set(exact[digest])
        for key in band_keys(sketch):
            if len(bands[key]) <= BOILERPLATE_BAND_LIMIT:
                candidates.update(bands[key])
        candidates.discard(i)
        for j in candidates:
            if j < i:
                continue
            sim = 1.0 if items[j][2] == digest else jaccard_estimate(sketch, items[j][1])
            if sim >= threshold:
                parent[find(i)] = find(j)

    members: dict[int, set[str]] = defaultdict(set)
    for i, (author, _, _) in enumerate(items):
        members[find(i)].add(author)
    clustered = [authors for authors in members.values() if len(authors) >= 2]
    return {
        "clusters": len(clustered),
        "authors_in_clusters": len(set().union(*clustered)) if clustered else 0,
    }


def backfill(db: Session, dry_run: bool = True, commit_every: int = 500) -> dict[str, Any]:
    """Fingerprint every stored post body and build clusters.

    Dry run: counts what would be created (clusters estimated in memory) and
    writes nothing. Live run: pass 1 stores fingerprints without linking,
    pass 2 links the new ones oldest first, then every cluster is
    reclassified; one ``copy.backfill`` audit entry covers the batch.
    """
    posts = stored_posts(db)
    existing = {
        (r[0], r[1])
        for r in db.execute(
            select(PostFingerprint.provider_id, PostFingerprint.external_post_id)
        ).all()
    }
    todo = [p for key, p in posts.items() if key not in existing]
    report: dict[str, Any] = {
        "dry_run": dry_run,
        "posts_stored": len(posts),
        "already_fingerprinted": len(posts) - len(todo),
        "by_source": dict(sorted(
            {s: sum(1 for p in todo if p.source == s) for s in SOURCES}.items()
        )),
    }

    if dry_run:
        items: list[tuple[str, tuple[int, ...], bytes]] = []
        with_sketch = no_text = 0
        for p in todo:
            features = compute_features(p.body_text)
            if features is None:
                no_text += 1
                continue
            if features.sketch is not None:
                with_sketch += 1
                items.append((_author_key(p.author_username), features.sketch, features.exact_hash))
        for fp in db.execute(
            select(PostFingerprint).where(PostFingerprint.sketch.is_not(None))
        ).scalars().yield_per(1000):
            stored = unpack_sketch(fp.sketch)
            if stored is not None:
                items.append((_author_key(fp.author_username), stored, fp.exact_hash))
        report.update({
            "would_fingerprint": len(todo) - no_text,
            "would_sketch": with_sketch,
            "skipped_no_text": no_text,
            **{f"estimated_{k}": v for k, v in estimate_clusters(items).items()},
        })
        return report

    created: list[int] = []
    for i, p in enumerate(todo, 1):
        outcome = fingerprint_post(
            db,
            provider_id=p.provider_id,
            external_post_id=p.external_post_id,
            author_username=p.author_username,
            body_text=p.body_text,
            source=p.source,
            posted_at=p.posted_at,
            location=p.location,
            account_id=p.account_id,
            audit=False,
            link=False,
            first_seen_at=p.first_seen_at,
        )
        if outcome is not None and outcome.created:
            created.append(outcome.fingerprint.id)
        if i % commit_every == 0:
            db.commit()
    db.commit()

    new_fps = list(db.execute(
        select(PostFingerprint)
        .where(PostFingerprint.id.in_(created), PostFingerprint.sketch.is_not(None))
    ).scalars().all()) if created else []
    new_fps.sort(key=post_time)
    for i, fp in enumerate(new_fps, 1):
        link_existing(db, fp, audit=False)
        if i % commit_every == 0:
            db.commit()
    db.commit()

    clusters = db.execute(
        select(CopyCluster).where(
            (CopyCluster.decision.is_(None)) | (CopyCluster.decision != DECISION_COINCIDENCE)
        )
    ).scalars().all()
    for cluster in clusters:
        recompute_cluster(db, cluster)
    kinds: dict[str, int] = defaultdict(int)
    for cluster in clusters:
        kinds[cluster.kind] += 1
    handled = sum(1 for c in clusters if c.handled)

    report.update({
        "fingerprints_created": len(created),
        "linked": len(new_fps),
        "clusters": len(clusters),
        "clusters_by_kind": dict(kinds),
        "clusters_handled": handled,
    })
    _audit(
        db, "copy.backfill", None, None, actor="system",
        request_json={"dry_run": False},
        response_json={k: v for k, v in report.items() if k != "dry_run"},
    )
    db.commit()
    return report
