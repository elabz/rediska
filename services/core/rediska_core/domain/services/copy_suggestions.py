"""Probable rewrites — semantic near-copies awaiting a human decision.

The fingerprint matcher in `post_copy` catches the same text reposted; it
cannot catch the same offer rewritten in different words. Vectors can. But a
high cosine is evidence, not proof — two people really can want the same thing
in the same city — so a semantic match never clusters, bans or hides anything
on its own. It becomes a row here, and the user accepts it (the two posts join
a copy cluster, exactly as a fingerprint match would have joined them) or
rejects it.

Everything here is deliberately conservative:

* only posts by *different* authors, at `REWRITE_MIN_SCORE` or above;
* never a pair that is already in one cluster, and never a pair the user has
  already decided about;
* accept and reject both write `audit_log`, and accept reuses the cluster
  machinery in `post_copy` so a semantically-joined cluster is indistinguishable
  from any other afterwards.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    AuditLog,
    CopyCluster,
    CopyClusterMember,
    CopySuggestion,
    PostFingerprint,
)
from rediska_core.domain.services import post_copy

STATUSES = ("new", "accepted", "rejected")

# Document types a rewrite can involve; a message or a profile summary is not
# a post and has no external post id to cluster on.
POST_DOC_TYPES = ("lead_post", "scout_post", "profile_item")


class SuggestionNotFound(LookupError):
    """Raised when a suggestion id does not exist."""


class SuggestionAlreadyDecided(ValueError):
    """Raised when a suggestion has already been accepted or rejected."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _audit(
    db: Session,
    action_type: str,
    suggestion: CopySuggestion,
    actor: str,
    response_json: Optional[dict] = None,
) -> None:
    db.add(
        AuditLog(
            ts=_utcnow(),
            actor=actor,
            action_type=action_type,
            provider_id=suggestion.provider_id,
            entity_type="copy_suggestion",
            entity_id=suggestion.id,
            request_json={
                "source_external_post_id": suggestion.source_external_post_id,
                "match_external_post_id": suggestion.match_external_post_id,
                "similarity": round(suggestion.similarity, 4),
                "embedding_model": suggestion.embedding_model,
            },
            response_json=response_json,
            result="ok",
        )
    )


def _fingerprint(
    db: Session, provider_id: str, external_post_id: str
) -> Optional[PostFingerprint]:
    return db.scalars(
        select(PostFingerprint).where(
            PostFingerprint.provider_id == provider_id,
            PostFingerprint.external_post_id == external_post_id,
        )
    ).first()


def _cluster_of(db: Session, fingerprint_id: int) -> Optional[int]:
    return db.scalar(
        select(CopyClusterMember.cluster_id).where(
            CopyClusterMember.fingerprint_id == fingerprint_id
        )
    )


def already_clustered_together(
    db: Session, provider_id: str, a_post_id: str, b_post_id: str
) -> bool:
    """True when both posts are already members of the same copy cluster."""
    a = _fingerprint(db, provider_id, a_post_id)
    b = _fingerprint(db, provider_id, b_post_id)
    if a is None or b is None:
        return False
    cluster_a = _cluster_of(db, a.id)
    return cluster_a is not None and cluster_a == _cluster_of(db, b.id)


def record_suggestions(
    db: Session,
    provider_id: str,
    doc_type: str,
    entity_id: int,
    external_post_id: Optional[str],
    author_username: Optional[str],
    matches: list[dict[str, Any]],
    embedding_model: Optional[str] = None,
) -> dict[str, int]:
    """Store the neighbours of a just-embedded post as pending suggestions.

    Idempotent: a pair already suggested (whatever its status) is left alone,
    so re-embedding a post does not resurrect a rejection.

    Args:
        db: Session.
        provider_id: Provider of the source post.
        doc_type: Source document type.
        entity_id: Source entity id.
        external_post_id: Source post's provider id, needed to cluster.
        author_username: Source author, lower-cased.
        matches: `SimilarityService.probable_rewrites` results.
        embedding_model: The model both vectors came from.

    Returns:
        Counts: created, skipped_clustered, skipped_existing, skipped_unusable.
    """
    counts = {
        "created": 0,
        "skipped_clustered": 0,
        "skipped_existing": 0,
        "skipped_unusable": 0,
    }
    if not external_post_id or doc_type not in POST_DOC_TYPES:
        return counts

    source_author = (author_username or "").lower() or None

    for match in matches:
        match_post_id = _external_post_id_of(db, match)
        match_author = (match.get("author_username") or "").lower() or None
        if not match_post_id or match_post_id == external_post_id:
            counts["skipped_unusable"] += 1
            continue
        if source_author and match_author and source_author == match_author:
            # Same person reposting themselves is a repost, not a copy.
            counts["skipped_unusable"] += 1
            continue
        if already_clustered_together(db, provider_id, external_post_id, match_post_id):
            counts["skipped_clustered"] += 1
            continue
        if _existing(db, provider_id, external_post_id, match_post_id) is not None:
            counts["skipped_existing"] += 1
            continue

        db.add(
            CopySuggestion(
                provider_id=provider_id,
                source_external_post_id=external_post_id,
                source_doc_type=doc_type,
                source_entity_id=entity_id,
                source_author=source_author,
                match_external_post_id=match_post_id,
                match_doc_type=match.get("doc_type") or "",
                match_entity_id=match.get("entity_id") or 0,
                match_author=match_author,
                similarity=float(match.get("similarity") or 0.0),
                embedding_model=embedding_model,
                status="new",
                created_at=_utcnow(),
            )
        )
        counts["created"] += 1

    if counts["created"]:
        db.flush()
    return counts


def _existing(
    db: Session, provider_id: str, source_post_id: str, match_post_id: str
) -> Optional[CopySuggestion]:
    """A suggestion for this pair in either direction, whatever its status."""
    return db.scalars(
        select(CopySuggestion).where(
            CopySuggestion.provider_id == provider_id,
            CopySuggestion.source_external_post_id.in_([source_post_id, match_post_id]),
            CopySuggestion.match_external_post_id.in_([source_post_id, match_post_id]),
        )
    ).first()


def _external_post_id_of(db: Session, match: dict[str, Any]) -> Optional[str]:
    """The provider post id behind a similarity hit, from its owning row."""
    from rediska_core.domain.models import LeadPost, ProfileItem, ScoutWatchPost

    doc_type = match.get("doc_type")
    entity_id = match.get("entity_id")
    if entity_id is None:
        return None
    model = {
        "lead_post": LeadPost,
        "scout_post": ScoutWatchPost,
        "profile_item": ProfileItem,
    }.get(doc_type or "")
    if model is None:
        return None
    row = db.get(model, entity_id)
    return getattr(row, "external_post_id", None) if row is not None else None


def list_suggestions(
    db: Session,
    status: Optional[str] = "new",
    provider_id: Optional[str] = None,
    external_post_id: Optional[str] = None,
    limit: int = 50,
) -> list[CopySuggestion]:
    """Suggestions, newest first; by default the undecided ones."""
    stmt = select(CopySuggestion)
    if status and status != "all":
        stmt = stmt.where(CopySuggestion.status == status)
    if provider_id:
        stmt = stmt.where(CopySuggestion.provider_id == provider_id)
    if external_post_id:
        stmt = stmt.where(
            (CopySuggestion.source_external_post_id == external_post_id)
            | (CopySuggestion.match_external_post_id == external_post_id)
        )
    stmt = stmt.order_by(
        CopySuggestion.similarity.desc(), CopySuggestion.id.desc()
    ).limit(min(limit, 200))
    return list(db.scalars(stmt).all())


def suggestions_for_posts(
    db: Session, provider_id: str, external_post_ids: list[str]
) -> dict[str, list[CopySuggestion]]:
    """Pending suggestions touching each post, for the read models.

    One query per page; a post appears whether it is the source or the match,
    because "this reads like an older ad" is worth knowing from either side.
    """
    ids = [pid for pid in external_post_ids if pid]
    if not ids:
        return {}
    rows = db.scalars(
        select(CopySuggestion).where(
            CopySuggestion.provider_id == provider_id,
            CopySuggestion.status == "new",
            (CopySuggestion.source_external_post_id.in_(ids))
            | (CopySuggestion.match_external_post_id.in_(ids)),
        )
    ).all()
    found: dict[str, list[CopySuggestion]] = {}
    wanted = set(ids)
    for row in rows:
        for post_id in (row.source_external_post_id, row.match_external_post_id):
            if post_id in wanted:
                found.setdefault(post_id, []).append(row)
    return found


def _get(db: Session, suggestion_id: int) -> CopySuggestion:
    row = db.get(CopySuggestion, suggestion_id)
    if row is None:
        raise SuggestionNotFound(f"Copy suggestion {suggestion_id} not found")
    return row


def accept(db: Session, suggestion_id: int, actor: str = "user") -> CopySuggestion:
    """Join the two posts into a copy cluster, on the user's say-so.

    Reuses `post_copy`'s cluster machinery, so the result is an ordinary
    cluster: it recomputes its kind, feeds the ban suggestions, and is skipped
    by the scout if it turns out to be a ring.
    """
    suggestion = _get(db, suggestion_id)
    if suggestion.status != "new":
        raise SuggestionAlreadyDecided(
            f"Copy suggestion {suggestion_id} is already {suggestion.status}"
        )

    source = _fingerprint(
        db, suggestion.provider_id, suggestion.source_external_post_id
    )
    match = _fingerprint(db, suggestion.provider_id, suggestion.match_external_post_id)
    if source is None or match is None:
        raise SuggestionAlreadyDecided(
            "One of these posts is no longer fingerprinted, so it cannot be clustered"
        )

    cluster_id = _join(db, source, match, suggestion.similarity)

    suggestion.status = "accepted"
    suggestion.cluster_id = cluster_id
    suggestion.decided_at = _utcnow()
    suggestion.decided_by = actor
    _audit(db, "copy_suggestion.accept", suggestion, actor, {"cluster_id": cluster_id})
    db.flush()
    return suggestion


def reject(db: Session, suggestion_id: int, actor: str = "user") -> CopySuggestion:
    """Record that the user looked at this pair and said no.

    The row stays: it is why the pair will not be suggested again.
    """
    suggestion = _get(db, suggestion_id)
    if suggestion.status != "new":
        raise SuggestionAlreadyDecided(
            f"Copy suggestion {suggestion_id} is already {suggestion.status}"
        )
    suggestion.status = "rejected"
    suggestion.decided_at = _utcnow()
    suggestion.decided_by = actor
    _audit(db, "copy_suggestion.reject", suggestion, actor)
    db.flush()
    return suggestion


def _join(
    db: Session, source: PostFingerprint, match: PostFingerprint, similarity: float
) -> int:
    """Put two fingerprints in one cluster, creating or merging as needed."""
    now = _utcnow()
    source_cluster = _cluster_of(db, source.id)
    match_cluster = _cluster_of(db, match.id)

    if source_cluster and match_cluster and source_cluster != match_cluster:
        a = db.get(CopyCluster, source_cluster)
        b = db.get(CopyCluster, match_cluster)
        if a is not None and b is not None:
            target, other = (
                (a, b) if a.member_count >= b.member_count else (b, a)
            )
            post_copy._merge(db, source=other, target=target, audit=True)
            db.flush()
            post_copy.recompute_cluster(db, target)
            return target.id

    cluster_id = source_cluster or match_cluster
    if cluster_id is None:
        cluster = CopyCluster(
            provider_id=source.provider_id,
            kind=post_copy.KIND_UNCLASSIFIED,
            created_at=now,
            updated_at=now,
        )
        db.add(cluster)
        db.flush()
        cluster_id = cluster.id
    else:
        cluster = db.get(CopyCluster, cluster_id)

    for fingerprint in (source, match):
        if _cluster_of(db, fingerprint.id) is None:
            db.add(
                CopyClusterMember(
                    cluster_id=cluster_id,
                    fingerprint_id=fingerprint.id,
                    similarity=similarity,
                    joined_at=now,
                )
            )
    db.flush()
    if cluster is not None:
        post_copy.recompute_cluster(db, cluster)
    return cluster_id


__all__ = [
    "STATUSES",
    "POST_DOC_TYPES",
    "SuggestionNotFound",
    "SuggestionAlreadyDecided",
    "record_suggestions",
    "list_suggestions",
    "suggestions_for_posts",
    "already_clustered_together",
    "accept",
    "reject",
]
