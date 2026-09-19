"""Contact ban list (the `do_not_contact` table).

One ban predicate for every outreach path and every reader:
- ``is_banned`` / ``active_ban`` for a single username
- ``banned_usernames`` for a batch (one query)
- ``banned_account_ids_select`` as a subquery for list exclusion

Usernames are stored lower-cased and matched case-insensitively (Reddit
usernames are case-insensitive). Rows are never deleted: lifting sets
``status='lifted'``; banning a lifted username reactivates the same row.

A ban withdraws the author from the work queues: their active leads
(``new``/``saved``/``contact_queued``) move to ``ignored`` with the prior status
remembered in ``status_before_ban`` and restored on lift. Nothing else is
touched — analyses, evaluations, conversations and messages stay as they are.

Nothing here bans automatically. Copy-ring suggestions are a read-only query;
every ban is a user action and writes ``audit_log``.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import func, inspect, or_, select, text
from sqlalchemy.orm import Session

from rediska_core.domain.models import AuditLog, DoNotContact, ExternalAccount, LeadPost

STATUS_ACTIVE = "active"
STATUS_LIFTED = "lifted"
BAN_STATUSES = {STATUS_ACTIVE, STATUS_LIFTED}

SOURCE_MANUAL = "manual"
SOURCE_COPY_RING = "copy_ring"
SOURCE_IMPORT = "import"
BAN_SOURCES = {SOURCE_MANUAL, SOURCE_COPY_RING, SOURCE_IMPORT}

# Reason presets offered by the UI; any non-empty reason is accepted.
REASON_PRESETS = ("scam", "copy_ring", "hostile", "asked_not_to_contact", "other")

# Lead statuses a ban withdraws; `contacted` is history and is left alone.
BANNABLE_LEAD_STATUSES = ("new", "saved", "contact_queued")
BANNED_LEAD_STATUS = "ignored"

# Effective copy-cluster kinds that produce ban suggestions.
RING_KINDS = ("ring_suspect", "confirmed_ring")

# Error code the API returns (HTTP 409) and the UI renders as a banner.
COUNTERPART_BANNED = "counterpart_banned"


class BanListError(Exception):
    """Base error for ban list operations."""


class BanNotFoundError(BanListError):
    """Raised when a ban entry does not exist."""


class BanValidationError(BanListError):
    """Raised on invalid ban input."""


class CounterpartBannedError(Exception):
    """Raised by an outreach path when the counterpart has an active ban."""

    def __init__(self, username: str, ban_id: Optional[int] = None):
        self.username = username
        self.ban_id = ban_id
        super().__init__(f"u/{username} is on the ban list; outreach is refused")

    def detail(self) -> dict[str, Any]:
        """HTTP 409 detail body shared by every route."""
        return {
            "code": COUNTERPART_BANNED,
            "message": str(self),
            "username": self.username,
            "ban_id": self.ban_id,
        }


def normalize_username(username: str) -> str:
    """Canonical ban-list key: trimmed, no ``u/`` prefix, lower-cased."""
    name = (username or "").strip()
    for prefix in ("/u/", "u/"):
        if name.lower().startswith(prefix):
            name = name[len(prefix):]
            break
    return name.strip().lower()


# =============================================================================
# PREDICATE
# =============================================================================


def active_ban(db: Session, provider_id: str, username: Optional[str]) -> Optional[DoNotContact]:
    """The active ban row for a username, or None."""
    name = normalize_username(username or "")
    if not name:
        return None
    return (
        db.query(DoNotContact)
        .filter(
            DoNotContact.provider_id == provider_id,
            DoNotContact.external_username == name,
            DoNotContact.status == STATUS_ACTIVE,
        )
        .first()
    )


def is_banned(db: Session, provider_id: str, username: Optional[str]) -> bool:
    """The single ban predicate used by every outreach path and reader."""
    return active_ban(db, provider_id, username) is not None


def ensure_not_banned(db: Session, provider_id: str, username: Optional[str]) -> None:
    """Raise ``CounterpartBannedError`` when the username has an active ban."""
    ban = active_ban(db, provider_id, username)
    if ban is not None:
        raise CounterpartBannedError(ban.external_username, ban.id)


def banned_usernames(
    db: Session,
    provider_id: str,
    usernames: Optional[Iterable[str]] = None,
) -> set[str]:
    """Lower-cased actively banned usernames, in one query.

    With ``usernames`` given, only those (case-insensitively) are checked.
    """
    stmt = select(DoNotContact.external_username).where(
        DoNotContact.provider_id == provider_id,
        DoNotContact.status == STATUS_ACTIVE,
    )
    if usernames is not None:
        names = {normalize_username(u) for u in usernames if u}
        names.discard("")
        if not names:
            return set()
        stmt = stmt.where(DoNotContact.external_username.in_(names))
    return {r[0].lower() for r in db.execute(stmt).all()}


def banned_account_ids_select(provider_id: Optional[str] = None):
    """Subquery of external_accounts ids with an active ban (for list exclusion)."""
    conditions = [
        DoNotContact.status == STATUS_ACTIVE,
        DoNotContact.provider_id == ExternalAccount.provider_id,
        func.lower(ExternalAccount.external_username) == DoNotContact.external_username,
    ]
    if provider_id is not None:
        conditions.append(ExternalAccount.provider_id == provider_id)
    return select(ExternalAccount.id).where(select(DoNotContact.id).where(*conditions).exists())


def username_not_banned(username_column):
    """Condition: the (raw-case) username column has no active ban."""
    return ~select(DoNotContact.id).where(
        DoNotContact.status == STATUS_ACTIVE,
        DoNotContact.external_username == func.lower(username_column),
    ).exists()


def exclude_banned_authors(query, author_column, provider_id: Optional[str] = None):
    """Filter a query to rows whose author is not actively banned.

    Rows without an author account are kept (nothing to match on).
    """
    return query.filter(
        or_(
            author_column.is_(None),
            author_column.not_in(banned_account_ids_select(provider_id)),
        )
    )


# =============================================================================
# SERVICE
# =============================================================================


@dataclass
class BanResult:
    entry: DoNotContact
    created: bool
    reactivated: bool
    leads_withdrawn: list[int] = field(default_factory=list)


class BanListService:
    """Create, reactivate, lift and bulk-create bans; move/restore leads."""

    def __init__(self, db: Session):
        self.db = db

    # --- reads ---------------------------------------------------------------

    def get(self, ban_id: int) -> DoNotContact:
        entry = self.db.get(DoNotContact, ban_id)
        if entry is None:
            raise BanNotFoundError(f"Ban {ban_id} not found")
        return entry

    def list_entries(
        self,
        provider_id: Optional[str] = None,
        status: Optional[str] = None,
        source: Optional[str] = None,
        q: Optional[str] = None,
        cursor: Optional[int] = None,
        limit: int = 50,
    ) -> tuple[list[DoNotContact], Optional[int]]:
        """Newest first, keyset cursor on id."""
        query = self.db.query(DoNotContact)
        if provider_id:
            query = query.filter(DoNotContact.provider_id == provider_id)
        if status:
            query = query.filter(DoNotContact.status == status)
        if source:
            query = query.filter(DoNotContact.source == source)
        if q:
            like = f"%{q.strip().lower()}%"
            query = query.filter(
                or_(
                    DoNotContact.external_username.like(like),
                    func.lower(DoNotContact.reason).like(like),
                    func.lower(DoNotContact.notes).like(like),
                )
            )
        if cursor:
            query = query.filter(DoNotContact.id < cursor)
        rows = query.order_by(DoNotContact.id.desc()).limit(limit + 1).all()
        next_cursor = rows[limit - 1].id if len(rows) > limit else None
        return rows[:limit], next_cursor

    def accounts_for(self, entries: list[DoNotContact]) -> dict[tuple[str, str], ExternalAccount]:
        """(provider_id, lower username) -> account, in one query."""
        names = {e.external_username for e in entries}
        if not names:
            return {}
        rows = (
            self.db.query(ExternalAccount)
            .filter(func.lower(ExternalAccount.external_username).in_(names))
            .all()
        )
        return {(a.provider_id, a.external_username.lower()): a for a in rows}

    def lead_ids_for(self, account_ids: Iterable[int]) -> dict[int, list[int]]:
        """account id -> non-deleted lead ids, in one query."""
        ids = list(set(account_ids))
        if not ids:
            return {}
        out: dict[int, list[int]] = {}
        for lead_id, author_id in self.db.execute(
            select(LeadPost.id, LeadPost.author_account_id)
            .where(LeadPost.author_account_id.in_(ids), LeadPost.deleted_at.is_(None))
            .order_by(LeadPost.id.desc())
        ).all():
            out.setdefault(author_id, []).append(lead_id)
        return out

    # --- mutations -----------------------------------------------------------

    def ban(
        self,
        provider_id: str,
        username: str,
        reason: str,
        notes: Optional[str] = None,
        source: str = SOURCE_MANUAL,
        cluster_id: Optional[int] = None,
        created_by: Optional[str] = "user",
        audit: bool = True,
    ) -> BanResult:
        """Ban a username (create or reactivate). Idempotent on an active ban."""
        name = normalize_username(username)
        reason = (reason or "").strip()
        if not name:
            raise BanValidationError("Username is required")
        if not reason:
            raise BanValidationError("A reason is required")
        if source not in BAN_SOURCES:
            raise BanValidationError(f"Unknown source '{source}'")

        now = _now()
        entry = (
            self.db.query(DoNotContact)
            .filter(
                DoNotContact.provider_id == provider_id,
                DoNotContact.external_username == name,
            )
            .first()
        )
        created = reactivated = False
        if entry is None:
            entry = DoNotContact(
                provider_id=provider_id,
                external_username=name,
                reason=reason[:255],
                notes=notes or None,
                source=source,
                status=STATUS_ACTIVE,
                cluster_id=cluster_id,
                created_by=created_by,
                created_at=now,
            )
            self.db.add(entry)
            created = True
        elif entry.status != STATUS_ACTIVE:
            entry.status = STATUS_ACTIVE
            entry.lifted_at = None
            entry.reason = reason[:255]
            entry.source = source
            if cluster_id is not None:
                entry.cluster_id = cluster_id
            entry.notes = _append_note(
                entry.notes, f"Re-banned {now:%Y-%m-%d} ({reason})" + (f": {notes}" if notes else "")
            )
            reactivated = True
        self.db.flush()

        withdrawn = self._withdraw_leads(provider_id, name) if (created or reactivated) else []
        if audit and (created or reactivated):
            self._audit(
                "ban.create",
                entry.id,
                provider_id,
                request_json={
                    "username": name,
                    "reason": reason,
                    "source": source,
                    "cluster_id": cluster_id,
                    "has_notes": bool(notes),
                },
                response_json={
                    "created": created,
                    "reactivated": reactivated,
                    "leads_withdrawn": withdrawn,
                },
            )
        return BanResult(entry, created, reactivated, withdrawn)

    def lift(self, ban_id: int, notes: Optional[str] = None) -> tuple[DoNotContact, list[int]]:
        """Lift an active ban and restore the leads it withdrew."""
        entry = self.get(ban_id)
        if entry.status != STATUS_ACTIVE:
            return entry, []
        now = _now()
        entry.status = STATUS_LIFTED
        entry.lifted_at = now
        if notes:
            entry.notes = _append_note(entry.notes, f"Lifted {now:%Y-%m-%d}: {notes}")
        self.db.flush()
        restored = self._restore_leads(entry.provider_id, entry.external_username)
        self._audit(
            "ban.lift",
            entry.id,
            entry.provider_id,
            request_json={"username": entry.external_username, "has_notes": bool(notes)},
            response_json={"leads_restored": restored},
        )
        return entry, restored

    def bulk_ban(
        self,
        provider_id: str,
        usernames: Iterable[str],
        reason: str,
        cluster_id: Optional[int] = None,
        exclude_usernames: Iterable[str] = (),
        notes: Optional[str] = None,
        source: str = SOURCE_COPY_RING,
    ) -> list[BanResult]:
        """Ban many usernames as one audited batch (``ban.bulk_create``)."""
        excluded = {normalize_username(u) for u in exclude_usernames}
        names: list[str] = []
        for u in usernames:
            n = normalize_username(u)
            if n and n not in excluded and n not in names:
                names.append(n)
        if not names:
            raise BanValidationError("No usernames left to ban")
        results = [
            self.ban(
                provider_id, n, reason, notes=notes, source=source,
                cluster_id=cluster_id, audit=False,
            )
            for n in names
        ]
        self._audit(
            "ban.bulk_create",
            cluster_id,
            provider_id,
            entity_type="copy_cluster" if cluster_id is not None else "do_not_contact",
            request_json={
                "cluster_id": cluster_id,
                "reason": reason,
                "source": source,
                "exclude_usernames": sorted(excluded),
            },
            response_json={
                "banned": [
                    {
                        "id": r.entry.id,
                        "username": r.entry.external_username,
                        "created": r.created,
                        "reactivated": r.reactivated,
                        "leads_withdrawn": r.leads_withdrawn,
                    }
                    for r in results
                ],
            },
        )
        return results

    # --- lead consequences ---------------------------------------------------

    def _author_account_ids(self, provider_id: str, name: str) -> list[int]:
        return [
            r[0]
            for r in self.db.execute(
                select(ExternalAccount.id).where(
                    ExternalAccount.provider_id == provider_id,
                    func.lower(ExternalAccount.external_username) == name,
                )
            ).all()
        ]

    def _withdraw_leads(self, provider_id: str, name: str) -> list[int]:
        account_ids = self._author_account_ids(provider_id, name)
        if not account_ids:
            return []
        leads = (
            self.db.query(LeadPost)
            .filter(
                LeadPost.author_account_id.in_(account_ids),
                LeadPost.status.in_(BANNABLE_LEAD_STATUSES),
                LeadPost.deleted_at.is_(None),
            )
            .all()
        )
        for lead in leads:
            lead.status_before_ban = lead.status
            lead.status = BANNED_LEAD_STATUS
        self.db.flush()
        return [lead.id for lead in leads]

    def _restore_leads(self, provider_id: str, name: str) -> list[int]:
        account_ids = self._author_account_ids(provider_id, name)
        if not account_ids:
            return []
        leads = (
            self.db.query(LeadPost)
            .filter(
                LeadPost.author_account_id.in_(account_ids),
                LeadPost.status_before_ban.is_not(None),
            )
            .all()
        )
        restored = []
        for lead in leads:
            # Only undo our own move; a status the user changed since wins.
            if lead.status == BANNED_LEAD_STATUS and lead.status_before_ban:
                lead.status = lead.status_before_ban
                restored.append(lead.id)
            lead.status_before_ban = None
        self.db.flush()
        return restored

    # --- copy-ring suggestions -----------------------------------------------

    def suggestions(self, provider_id: str = "reddit") -> list[dict[str, Any]]:
        """Authors of ring clusters who are not banned and not dismissed.

        Grouped per cluster with evidence. Empty when the copy-detection tables
        (post-fingerprint-dedupe) are absent.
        """
        if not copy_tables_present(self.db):
            return []
        rows = self.db.execute(
            text(
                """
                SELECT c.id AS cluster_id,
                       COALESCE(c.decision, c.kind) AS effective_kind,
                       m.id AS member_id,
                       f.author_username AS author_username,
                       COALESCE(f.posted_at, f.first_seen_at) AS posted_at,
                       m.ban_suggestion_dismissed_at AS dismissed_at
                FROM copy_clusters c
                JOIN copy_cluster_members m ON m.cluster_id = c.id
                JOIN post_fingerprints f ON f.id = m.fingerprint_id
                WHERE COALESCE(c.decision, c.kind) IN :kinds
                  AND f.provider_id = :provider_id
                ORDER BY c.id, posted_at
                """
            ).bindparams(_expanding("kinds")),
            {"kinds": list(RING_KINDS), "provider_id": provider_id},
        ).mappings().all()
        if not rows:
            return []

        names = {r["author_username"].lower() for r in rows if r["author_username"]}
        banned = banned_usernames(self.db, provider_id, names)
        accounts = {
            a.external_username.lower(): a
            for a in self.db.query(ExternalAccount)
            .filter(
                ExternalAccount.provider_id == provider_id,
                func.lower(ExternalAccount.external_username).in_(names),
            )
            .all()
        }

        clusters: dict[int, dict[str, Any]] = {}
        for r in rows:
            cluster = clusters.setdefault(
                r["cluster_id"],
                {
                    "cluster_id": r["cluster_id"],
                    "kind": r["effective_kind"],
                    "authors": {},
                },
            )
            name = (r["author_username"] or "").lower()
            if not name:
                continue
            author = cluster["authors"].get(name)
            if author is None:
                account = accounts.get(name)
                author = cluster["authors"][name] = {
                    "username": name,
                    "account_id": account.id if account else None,
                    "remote_status": account.remote_status if account else None,
                    "first_posted_at": r["posted_at"],
                    "post_count": 0,
                    "banned": name in banned,
                    "dismissed": False,
                    "member_ids": [],
                }
            author["post_count"] += 1
            author["member_ids"].append(r["member_id"])
            if r["dismissed_at"] is not None:
                author["dismissed"] = True
            if r["posted_at"] and (
                author["first_posted_at"] is None or r["posted_at"] < author["first_posted_at"]
            ):
                author["first_posted_at"] = r["posted_at"]

        out = []
        for cluster in clusters.values():
            authors = sorted(
                cluster["authors"].values(),
                key=lambda a: (a["first_posted_at"] is None, a["first_posted_at"] or datetime.min),
            )
            if authors:
                authors[0]["earliest"] = True
            for a in authors[1:]:
                a["earliest"] = False
            suggested = [a for a in authors if not a["banned"] and not a["dismissed"]]
            if not suggested:
                continue
            out.append(
                {
                    "cluster_id": cluster["cluster_id"],
                    "kind": cluster["kind"],
                    "authors": authors,
                    "suggested_usernames": [a["username"] for a in suggested],
                }
            )
        return out

    def cluster_usernames(self, cluster_id: int, provider_id: str = "reddit") -> list[str]:
        """Distinct authors of a copy cluster (empty when copy tables are absent)."""
        if not copy_tables_present(self.db):
            return []
        rows = self.db.execute(
            text(
                """
                SELECT DISTINCT LOWER(f.author_username)
                FROM copy_cluster_members m
                JOIN post_fingerprints f ON f.id = m.fingerprint_id
                WHERE m.cluster_id = :cluster_id AND f.provider_id = :provider_id
                """
            ),
            {"cluster_id": cluster_id, "provider_id": provider_id},
        ).all()
        return [r[0] for r in rows if r[0]]

    def dismiss_suggestion(self, cluster_id: int, username: str) -> int:
        """Dismiss one author's suggestion within a cluster. Returns rows touched."""
        if not copy_tables_present(self.db):
            raise BanNotFoundError("Copy detection is not installed")
        name = normalize_username(username)
        result = self.db.execute(
            text(
                """
                UPDATE copy_cluster_members
                SET ban_suggestion_dismissed_at = :now
                WHERE cluster_id = :cluster_id
                  AND ban_suggestion_dismissed_at IS NULL
                  AND fingerprint_id IN (
                      SELECT f.id FROM post_fingerprints f
                      WHERE LOWER(f.author_username) = :name
                  )
                """
            ),
            {"now": _now(), "cluster_id": cluster_id, "name": name},
        )
        touched = getattr(result, "rowcount", 0) or 0
        if not touched:
            raise BanNotFoundError(f"No open suggestion for u/{name} in cluster {cluster_id}")
        self._audit(
            "ban.suggestion_dismiss",
            cluster_id,
            None,
            entity_type="copy_cluster",
            request_json={"cluster_id": cluster_id, "username": name},
            response_json={"members": touched},
        )
        return touched

    # --- helpers -------------------------------------------------------------

    def _audit(
        self,
        action_type: str,
        entity_id: Optional[int],
        provider_id: Optional[str],
        request_json: Optional[dict] = None,
        response_json: Optional[dict] = None,
        entity_type: str = "do_not_contact",
    ) -> None:
        self.db.add(
            AuditLog(
                ts=_now(),
                actor="user",
                action_type=action_type,
                provider_id=provider_id,
                entity_type=entity_type,
                entity_id=entity_id,
                request_json=request_json,
                response_json=response_json,
                result="ok",
            )
        )


def copy_tables_present(db: Session) -> bool:
    """Whether post-fingerprint-dedupe's tables exist in this database."""
    # Inspect through the session's own connection: a separate pooled
    # connection's reset-on-return can roll back this session's work.
    tables = set(inspect(db.connection()).get_table_names())
    return {"copy_clusters", "copy_cluster_members", "post_fingerprints"} <= tables


def _expanding(name: str):
    from sqlalchemy import bindparam

    return bindparam(name, expanding=True)


def _append_note(existing: Optional[str], line: str) -> str:
    return f"{existing}\n{line}" if existing else line


def _now() -> datetime:
    # Naive UTC, matching the DateTime columns elsewhere.
    return datetime.now(timezone.utc).replace(tzinfo=None)
