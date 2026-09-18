"""Source discovery: propose new lead sources from data already stored.

Two signals, both computed without calling the provider or the LLM:

- **Locations** (``kind='location'``): communities over-represented in the
  stored post history (``profile_items.subreddit``) of *qualified* authors
  compared with all analysed authors, ranked by lift.
- **External hosts** (``kind='external_host'``): hosts that link-only posts
  and qualified authors' items keep pointing at, which are not in the
  external-listing registry. They are reported as "worth a parser" and are
  never fetched.

A human decides everything: candidates are trialled (a bounded run through
the normal scout pipeline on a hidden ``is_trial`` watch that never
auto-promotes), accepted into a real watch, snoozed, or dismissed. Mining reads
community names, URL hosts, and verdicts only — never inbox or message tables.
"""

import logging
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit

from sqlalchemy import and_, case, distinct, func, literal, or_, select, union
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    AnalysisEvaluation,
    DoNotContact,
    ExternalAccount,
    Job,
    LeadAnalysis,
    LeadPost,
    ProfileItem,
    ScoutWatch,
    ScoutWatchPost,
    SourceCandidate,
    SourceLinkSighting,
    SourceTrial,
)
from rediska_core.domain.services.external_listing import (
    canonicalize_url,
    is_registered_domain,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

KIND_LOCATION = "location"
KIND_EXTERNAL_HOST = "external_host"

ORIGIN_MINED = "mined"
ORIGIN_MANUAL = "manual"

STATUS_NEW = "new"
STATUS_TRIALLED = "trialled"
STATUS_ACCEPTED = "accepted"
STATUS_DISMISSED = "dismissed"
STATUS_SNOOZED = "snoozed"
CANDIDATE_STATUSES = (
    STATUS_NEW, STATUS_TRIALLED, STATUS_ACCEPTED, STATUS_DISMISSED, STATUS_SNOOZED,
)

# Candidates whose trial evidence must survive history cleanup.
UNRESOLVED_STATUSES = (STATUS_NEW, STATUS_TRIALLED, STATUS_SNOOZED)

ACTIVE_TRIAL_STATUSES = ("queued", "running")
TRIAL_SAMPLE_HARD_CAP = 50
TRIAL_JOB_TYPE = "discovery.run_trial"

RECOMMENDATIONS = ("suitable", "needs_review", "not_recommended")

# Location prefix each provider uses in `source_location` / `profile_items`.
PROVIDER_LOCATION_PREFIX = {"reddit": "r/"}

# Hosts that are the provider itself or generic media hosting, never listing
# sites. Excluded from the outbound-host tally so they don't drown it.
IGNORED_HOST_SUFFIXES = (
    "reddit.com",
    "redd.it",
    "redditmedia.com",
    "redditstatic.com",
    "imgur.com",
    "redgifs.com",
    "gfycat.com",
)

# Pseudo-authors at the base qualified rate added to every community before
# computing lift (evidence-weighted shrinkage; see compute_lift).
LIFT_PRIOR_AUTHORS = 10

MAX_EXAMPLE_URLS = 5
URL_PATTERN = re.compile(r"https?://[^\s<>\"'\])]+", re.IGNORECASE)

# Lazily fetched location info is refreshed after this long.
LOCATION_INFO_TTL_DAYS = 30


# =============================================================================
# EXCEPTIONS
# =============================================================================


class DiscoveryError(Exception):
    """Invalid source-discovery request."""


class DiscoveryNotFoundError(DiscoveryError):
    """Candidate or trial not found."""


class DiscoveryConflictError(DiscoveryError):
    """Request conflicts with current state (running trial, watched location...)."""


# =============================================================================
# NORMALIZATION HELPERS
# =============================================================================


def _utcnow() -> datetime:
    return datetime.utcnow()


def normalize_location(name: Optional[str], provider_id: str = "reddit") -> Optional[str]:
    """Canonical, lower-cased location name ('r/foo'), or None when empty."""
    if not name:
        return None
    value = name.strip().strip("/").lower()
    if not value:
        return None
    prefix = PROVIDER_LOCATION_PREFIX.get(provider_id, "")
    if prefix and not value.startswith(prefix):
        value = f"{prefix}{value}"
    return value


def host_of(url: Optional[str]) -> Optional[str]:
    """Lower-cased host of an absolute http(s) URL, without 'www.' or port."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def is_ignored_host(host: Optional[str]) -> bool:
    if not host:
        return True
    return any(host == s or host.endswith(f".{s}") for s in IGNORED_HOST_SUFFIXES)


def is_outbound_candidate_url(url: Optional[str]) -> bool:
    """An absolute URL whose host could become an external-host candidate."""
    host = host_of(url)
    return bool(host) and not is_ignored_host(host) and not is_registered_domain(host)


def compute_lift(q: int, q_total: int, a: int, a_total: int) -> float:
    """How much likelier an author here is to be qualified than the base rate.

    Equivalent to (share among qualified authors) / (share among analysed
    authors), but the community's qualified rate ``q / a`` is first pulled
    toward the base rate ``q_total / a_total`` by ``LIFT_PRIOR_AUTHORS``
    pseudo-authors. Without that, any small community whose few authors all
    happen to qualify (3 of 3) hits the maximum lift and outranks communities
    with far more evidence; with it, lift only rises as evidence accumulates.
    """
    if q_total <= 0 or a_total <= 0:
        return 1.0
    base_rate = q_total / a_total
    shrunk_rate = (q + LIFT_PRIOR_AUTHORS * base_rate) / (a + LIFT_PRIOR_AUTHORS)
    return round(shrunk_rate / base_rate, 4)


# =============================================================================
# TRIAL-WATCH FILTER (shared by every surface that must not see trials)
# =============================================================================


def trial_watch_ids_select():
    """SELECT of the ids of hidden trial watches."""
    return select(ScoutWatch.id).where(ScoutWatch.is_trial.is_(True))


def not_trial_post(watch_id_column=ScoutWatchPost.watch_id):
    """Filter clause excluding posts that belong to a trial watch."""
    return ~watch_id_column.in_(trial_watch_ids_select())


def unresolved_trial_watch_ids(db: Session) -> set[int]:
    """Trial watches whose candidate is still undecided (history-cleanup exempt)."""
    rows = db.execute(
        select(SourceCandidate.watch_id)
        .join(ScoutWatch, ScoutWatch.id == SourceCandidate.watch_id)
        .where(
            ScoutWatch.is_trial.is_(True),
            SourceCandidate.status.in_(UNRESOLVED_STATUSES),
        )
    ).all()
    return {r[0] for r in rows if r[0] is not None}


# =============================================================================
# LINK SIGHTINGS
# =============================================================================


def record_link_sighting(
    db: Session,
    provider_id: str,
    external_post_id: Optional[str],
    url: Optional[str],
    source: str,
) -> bool:
    """Record an outbound URL seen on a link-only post (metadata only).

    Registered and ignored hosts are not recorded. Never fetches anything.
    Returns True when a new sighting was stored.
    """
    if not external_post_id or not is_outbound_candidate_url(url):
        return False
    exists = db.execute(
        select(SourceLinkSighting.id).where(
            SourceLinkSighting.provider_id == provider_id,
            SourceLinkSighting.external_post_id == external_post_id,
        )
    ).first()
    if exists:
        return False
    try:
        with db.begin_nested():
            db.add(
                SourceLinkSighting(
                    provider_id=provider_id,
                    external_post_id=external_post_id,
                    host=host_of(url),
                    url=canonicalize_url(url)[:1024],  # type: ignore[arg-type]
                    source=source,
                    seen_at=_utcnow(),
                )
            )
    except IntegrityError:
        return False
    return True


# =============================================================================
# QUALIFIED AUTHORS
# =============================================================================


def qualified_account_ids(db: Session, provider_id: str = "reddit") -> set[int]:
    """Authors whose presence in a community is evidence for it.

    An author is qualified when any of these holds:
    - a non-deleted lead whose latest analysis is ``suitable`` (unless the
      human's effective final verdict on that analysis is ``disagree``);
    - the account was contacted or engaged (a human action outranks the
      agent, so this counts even when the agent said ``needs_review``);
    - an effective human ``agree`` on a ``suitable`` final verdict (lead
      analysis or scout post).

    Authors on the do-not-contact list never qualify. When the configurable
    match profile lands, only this function changes.
    """
    effective = _effective_final_evaluations(db)
    disagreed_analyses = {
        sid for (stype, sid), row in effective.items()
        if stype == "lead_analysis" and row.human_verdict == "disagree"
    }

    qualified: set[int] = set()

    for account_id, analysis_id in db.execute(
        select(LeadPost.author_account_id, LeadPost.latest_analysis_id).where(
            LeadPost.provider_id == provider_id,
            LeadPost.analysis_recommendation == "suitable",
            LeadPost.deleted_at.is_(None),
            LeadPost.author_account_id.isnot(None),
        )
    ).all():
        if analysis_id is not None and analysis_id in disagreed_analyses:
            continue
        qualified.add(account_id)

    qualified.update(
        r[0]
        for r in db.execute(
            select(ExternalAccount.id).where(
                ExternalAccount.provider_id == provider_id,
                or_(
                    ExternalAccount.contact_state == "contacted",
                    ExternalAccount.engagement_state == "engaged",
                ),
            )
        ).all()
    )

    qualified.update(_agreed_suitable_accounts(db, effective, provider_id))

    if not qualified:
        return qualified

    dnc = {
        r[0]
        for r in db.execute(
            select(DoNotContact.external_username).where(
                DoNotContact.provider_id == provider_id
            )
        ).all()
    }
    if dnc:
        blocked = {
            r[0]
            for r in db.execute(
                select(ExternalAccount.id).where(
                    ExternalAccount.id.in_(qualified),
                    ExternalAccount.external_username.in_(dnc),
                )
            ).all()
        }
        qualified -= blocked
    return qualified


def is_qualified_author(db: Session, account_id: int, provider_id: str = "reddit") -> bool:
    """Whether one author counts as qualified (see ``qualified_account_ids``)."""
    return account_id in qualified_account_ids(db, provider_id)


def _effective_final_evaluations(db: Session) -> dict[tuple[str, int], AnalysisEvaluation]:
    """Latest final-verdict (dimension NULL) evaluation per subject."""
    effective: dict[tuple[str, int], AnalysisEvaluation] = {}
    for row in db.scalars(
        select(AnalysisEvaluation)
        .where(AnalysisEvaluation.dimension.is_(None))
        .order_by(AnalysisEvaluation.created_at.desc(), AnalysisEvaluation.id.desc())
    ).all():
        effective.setdefault((row.subject_type, row.subject_id), row)
    return effective


def _agreed_suitable_accounts(
    db: Session,
    effective: dict[tuple[str, int], AnalysisEvaluation],
    provider_id: str,
) -> set[int]:
    agreed = [
        row for row in effective.values()
        if row.human_verdict == "agree"
        and isinstance(row.agent_snapshot_json, dict)
        and row.agent_snapshot_json.get("recommendation") == "suitable"
    ]
    if not agreed:
        return set()

    accounts: set[int] = set()
    analysis_ids = [r.subject_id for r in agreed if r.subject_type == "lead_analysis"]
    post_ids = [r.subject_id for r in agreed if r.subject_type == "scout_post"]

    if analysis_ids:
        # Soft-deleted leads do not qualify their author.
        for account_id, deleted_at in db.execute(
            select(LeadAnalysis.account_id, LeadPost.deleted_at)
            .join(LeadPost, LeadPost.id == LeadAnalysis.lead_id)
            .where(LeadAnalysis.id.in_(analysis_ids), LeadPost.provider_id == provider_id)
        ).all():
            if account_id is not None and deleted_at is None:
                accounts.add(account_id)

    if post_ids:
        by_post = {r.subject_id: r.account_id for r in agreed if r.subject_type == "scout_post"}
        accounts.update(a for a in by_post.values() if a is not None)
        missing = [pid for pid, a in by_post.items() if a is None]
        if missing:
            accounts.update(
                r[0]
                for r in db.execute(
                    select(ExternalAccount.id)
                    .join(
                        ScoutWatchPost,
                        ScoutWatchPost.post_author == ExternalAccount.external_username,
                    )
                    .where(
                        ScoutWatchPost.id.in_(missing),
                        ExternalAccount.provider_id == provider_id,
                    )
                ).all()
            )
    return accounts


def _analysed_account_ids_select(provider_id: str):
    """SELECT of authors the pipeline has analysed at least once."""
    return union(
        select(ExternalAccount.id).where(
            ExternalAccount.provider_id == provider_id,
            ExternalAccount.analysis_state != "not_analyzed",
        ),
        select(LeadAnalysis.account_id).where(LeadAnalysis.account_id.isnot(None)),
        select(ExternalAccount.id)
        .join(ScoutWatchPost, ScoutWatchPost.post_author == ExternalAccount.external_username)
        .where(
            ExternalAccount.provider_id == provider_id,
            ScoutWatchPost.analysis_recommendation.isnot(None),
        ),
    )


# =============================================================================
# SERVICE
# =============================================================================


@dataclass
class MiningSummary:
    qualified_authors: int
    analysed_authors: int
    location_candidates: int
    host_candidates: int
    created: int
    updated: int
    removed: int

    def to_dict(self) -> dict[str, int]:
        return self.__dict__.copy()


class SourceDiscoveryService:
    """Candidate mining, lifecycle, trials, and yield metrics."""

    def __init__(
        self,
        db: Session,
        min_qualified_authors: Optional[int] = None,
        window_days: Optional[int] = None,
        trial_sample: Optional[int] = None,
        provider_id: str = "reddit",
    ):
        from rediska_core.config import get_settings

        settings = get_settings()
        self.db = db
        self.provider_id = provider_id
        self.min_qualified_authors = (
            min_qualified_authors or settings.discovery_min_qualified_authors
        )
        self.window_days = window_days or settings.discovery_window_days
        self.trial_sample = min(
            trial_sample or settings.discovery_trial_sample, TRIAL_SAMPLE_HARD_CAP
        )

    # =========================================================================
    # MINING
    # =========================================================================

    def watched_locations(self) -> set[str]:
        """Normalized source locations of every real (non-trial) watch."""
        rows = self.db.execute(
            select(ScoutWatch.source_location).where(
                ScoutWatch.provider_id == self.provider_id,
                ScoutWatch.is_trial.is_(False),
            )
        ).all()
        return {n for n in (normalize_location(r[0], self.provider_id) for r in rows) if n}

    def _location_expr(self):
        prefix = PROVIDER_LOCATION_PREFIX.get(self.provider_id, "")
        lowered = func.lower(func.trim(ProfileItem.subreddit))
        if not prefix:
            return lowered
        return case(
            (lowered.like(f"{prefix}%"), lowered),
            else_=literal(prefix) + lowered,
        )

    def _item_window(self, cutoff: datetime):
        return and_(
            ProfileItem.subreddit.isnot(None),
            ProfileItem.subreddit != "",
            ProfileItem.deleted_at.is_(None),
            or_(
                ProfileItem.item_created_at >= cutoff,
                and_(ProfileItem.item_created_at.is_(None), ProfileItem.created_at >= cutoff),
            ),
        )

    def _location_counts(self, cutoff: datetime, author_filter) -> tuple[dict[str, int], int]:
        """(distinct authors per location, distinct authors overall) for a population."""
        loc = self._location_expr().label("loc")
        window = self._item_window(cutoff)
        per_location = {
            name: count
            for name, count in self.db.execute(
                select(loc, func.count(distinct(ProfileItem.account_id)))
                .where(window, author_filter)
                .group_by(loc)
            ).all()
            if name
        }
        total = self.db.execute(
            select(func.count(distinct(ProfileItem.account_id))).where(window, author_filter)
        ).scalar() or 0
        return per_location, int(total)

    def mine(self, now: Optional[datetime] = None) -> MiningSummary:
        """Recompute location and external-host candidates from stored data.

        Updates evidence in place, never resurrects dismissed candidates,
        un-snoozes candidates whose snooze has passed, and drops mined `new`
        candidates that no longer clear the floor or became watched.
        No provider calls, no LLM calls, no HTTP requests of any kind.
        """
        now = now or _utcnow()
        cutoff = now - timedelta(days=self.window_days)

        qualified = qualified_account_ids(self.db, self.provider_id)
        if qualified:
            q_counts, q_total = self._location_counts(
                cutoff, ProfileItem.account_id.in_(qualified)
            )
            analysed_filter = or_(
                ProfileItem.account_id.in_(_analysed_account_ids_select(self.provider_id)),
                ProfileItem.account_id.in_(qualified),
            )
        else:
            q_counts, q_total = {}, 0
            analysed_filter = ProfileItem.account_id.in_(
                _analysed_account_ids_select(self.provider_id)
            )
        a_counts, a_total = self._location_counts(cutoff, analysed_filter)

        watched = self.watched_locations()
        location_evidence: dict[str, dict[str, Any]] = {}
        for name in set(q_counts) | set(a_counts):
            q = q_counts.get(name, 0)
            a = max(a_counts.get(name, 0), q)
            location_evidence[name] = {
                "qualified_authors": q,
                "analysed_authors": a,
                "qualified_total": q_total,
                "analysed_total": a_total,
                "lift": compute_lift(q, q_total, a, a_total),
                "window_days": self.window_days,
                "computed_at": now.isoformat(),
            }
        qualifying_locations = {
            name for name, ev in location_evidence.items()
            if ev["qualified_authors"] >= self.min_qualified_authors and name not in watched
        }

        host_evidence = self._host_evidence(qualified, cutoff, now)
        qualifying_hosts = {
            host for host, ev in host_evidence.items()
            if ev["occurrences"] >= self.min_qualified_authors
        }

        created, updated, removed = self._upsert(
            KIND_LOCATION, location_evidence, qualifying_locations, watched, now
        )
        c2, u2, r2 = self._upsert(
            KIND_EXTERNAL_HOST, host_evidence, qualifying_hosts, set(), now
        )
        self.db.flush()

        return MiningSummary(
            qualified_authors=q_total,
            analysed_authors=a_total,
            location_candidates=len(qualifying_locations),
            host_candidates=len(qualifying_hosts),
            created=created + c2,
            updated=updated + u2,
            removed=removed + r2,
        )

    def _host_evidence(
        self, qualified: set[int], cutoff: datetime, now: datetime
    ) -> dict[str, dict[str, Any]]:
        """Distinct canonical URLs per unregistered, non-ignored host."""
        urls: dict[str, set[str]] = defaultdict(set)
        sources: dict[str, Counter] = defaultdict(Counter)

        def add(url: Optional[str], source: str) -> None:
            if not is_outbound_candidate_url(url):
                return
            host = host_of(url)
            canonical = canonicalize_url(url)  # type: ignore[arg-type]
            if canonical not in urls[host]:  # type: ignore[index]
                urls[host].add(canonical)  # type: ignore[index]
                sources[host][source] += 1  # type: ignore[index]

        # Link posts saved as leads (browse saves and scout promotions).
        for (url,) in self.db.execute(
            select(LeadPost.post_url).where(
                LeadPost.provider_id == self.provider_id,
                LeadPost.created_at >= cutoff,
            )
        ).all():
            add(url, "lead")

        # Link-only posts seen by scout watches and browse.
        for url, source in self.db.execute(
            select(SourceLinkSighting.url, SourceLinkSighting.source).where(
                SourceLinkSighting.provider_id == self.provider_id,
                SourceLinkSighting.seen_at >= cutoff,
            )
        ).all():
            add(url, source)

        # URLs in qualified authors' stored items (only the URLs are used).
        if qualified:
            for (text,) in self.db.execute(
                select(ProfileItem.text_content).where(
                    ProfileItem.account_id.in_(qualified),
                    self._item_window_any(cutoff),
                    ProfileItem.text_content.like("%http%"),
                )
            ).all():
                for match in URL_PATTERN.findall(text or ""):
                    add(match.rstrip(".,;:!?"), "qualified_item")

        return {
            host: {
                "occurrences": len(found),
                "example_urls": sorted(found)[:MAX_EXAMPLE_URLS],
                "by_source": dict(sources[host]),
                "window_days": self.window_days,
                "computed_at": now.isoformat(),
            }
            for host, found in urls.items()
        }

    @staticmethod
    def _item_window_any(cutoff: datetime):
        return and_(
            ProfileItem.deleted_at.is_(None),
            or_(
                ProfileItem.item_created_at >= cutoff,
                and_(ProfileItem.item_created_at.is_(None), ProfileItem.created_at >= cutoff),
            ),
        )

    def _upsert(
        self,
        kind: str,
        evidence: dict[str, dict[str, Any]],
        qualifying: set[str],
        watched: set[str],
        now: datetime,
    ) -> tuple[int, int, int]:
        existing = {
            c.name: c
            for c in self.db.scalars(
                select(SourceCandidate).where(
                    SourceCandidate.provider_id == self.provider_id,
                    SourceCandidate.kind == kind,
                )
            ).all()
        }
        created = updated = removed = 0
        with_trials = {
            r[0]
            for r in self.db.execute(
                select(SourceTrial.candidate_id).where(
                    SourceTrial.candidate_id.in_([c.id for c in existing.values()])
                )
            ).all()
        } if existing else set()

        for name, candidate in existing.items():
            ev = evidence.get(name)
            if ev is None:
                ev = self._empty_evidence(kind, now)
            self._apply_evidence(candidate, kind, ev, name in qualifying, now)
            if candidate.status == STATUS_SNOOZED and (
                candidate.snoozed_until is None or candidate.snoozed_until <= now
            ):
                candidate.status = self._resting_status(candidate)
                candidate.snoozed_until = None

            stale = name not in qualifying or name in watched
            if (
                stale
                and candidate.origin == ORIGIN_MINED
                and candidate.status == STATUS_NEW
                and candidate.id not in with_trials
                and candidate.watch_id is None
            ):
                self.db.delete(candidate)
                removed += 1
            else:
                updated += 1

        for name in qualifying - set(existing):
            candidate = SourceCandidate(
                provider_id=self.provider_id,
                kind=kind,
                name=name,
                origin=ORIGIN_MINED,
                status=STATUS_NEW,
                created_at=now,
                updated_at=now,
            )
            self._apply_evidence(candidate, kind, evidence[name], True, now)
            self.db.add(candidate)
            created += 1

        return created, updated, removed

    def _empty_evidence(self, kind: str, now: datetime) -> dict[str, Any]:
        if kind == KIND_EXTERNAL_HOST:
            return {
                "occurrences": 0, "example_urls": [], "by_source": {},
                "window_days": self.window_days, "computed_at": now.isoformat(),
            }
        return {
            "qualified_authors": 0, "analysed_authors": 0,
            "qualified_total": 0, "analysed_total": 0, "lift": None,
            "window_days": self.window_days, "computed_at": now.isoformat(),
        }

    @staticmethod
    def _apply_evidence(
        candidate: SourceCandidate,
        kind: str,
        ev: dict[str, Any],
        meets_floor: bool,
        now: datetime,
    ) -> None:
        ev = dict(ev)
        ev["meets_floor"] = meets_floor
        candidate.evidence_json = ev
        candidate.computed_at = now
        if kind == KIND_EXTERNAL_HOST:
            candidate.lift = None
            candidate.evidence_count = int(ev.get("occurrences") or 0)
        else:
            candidate.lift = ev.get("lift")
            candidate.evidence_count = int(ev.get("qualified_authors") or 0)

    def _resting_status(self, candidate: SourceCandidate) -> str:
        """Status a candidate returns to after a snooze or a restore."""
        completed = self.db.execute(
            select(SourceTrial.id).where(
                SourceTrial.candidate_id == candidate.id,
                SourceTrial.status == "completed",
            )
        ).first()
        return STATUS_TRIALLED if completed else STATUS_NEW

    # =========================================================================
    # LISTING
    # =========================================================================

    def get(self, candidate_id: int) -> SourceCandidate:
        candidate = self.db.get(SourceCandidate, candidate_id)
        if candidate is None:
            raise DiscoveryNotFoundError(f"Candidate not found: {candidate_id}")
        return candidate

    def list_candidates(
        self,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        offset: int = 0,
        limit: int = 25,
        now: Optional[datetime] = None,
    ) -> tuple[list[SourceCandidate], int]:
        """Candidates sorted by lift (nulls last), then evidence count.

        Default (``status=None``): new and trialled candidates plus snoozed
        ones whose snooze has passed. ``status='all'`` lists everything.
        """
        now = now or _utcnow()
        stmt = select(SourceCandidate).where(SourceCandidate.provider_id == self.provider_id)
        if kind:
            stmt = stmt.where(SourceCandidate.kind == kind)
        if status is None:
            stmt = stmt.where(
                or_(
                    SourceCandidate.status.in_((STATUS_NEW, STATUS_TRIALLED)),
                    and_(
                        SourceCandidate.status == STATUS_SNOOZED,
                        SourceCandidate.snoozed_until <= now,
                    ),
                )
            )
        elif status != "all":
            stmt = stmt.where(SourceCandidate.status == status)

        total = self.db.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar() or 0
        rows = self.db.scalars(
            stmt.order_by(
                SourceCandidate.lift.is_(None),
                SourceCandidate.lift.desc(),
                SourceCandidate.evidence_count.desc(),
                SourceCandidate.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()
        return list(rows), int(total)

    def latest_trials(self, candidate_ids: Iterable[int]) -> dict[int, SourceTrial]:
        """Newest trial per candidate, in one query."""
        ids = list(candidate_ids)
        if not ids:
            return {}
        latest: dict[int, SourceTrial] = {}
        for trial in self.db.scalars(
            select(SourceTrial)
            .where(SourceTrial.candidate_id.in_(ids))
            .order_by(SourceTrial.id.desc())
        ).all():
            latest.setdefault(trial.candidate_id, trial)
        return latest

    def needs_location_info(self, candidate: SourceCandidate, now: Optional[datetime] = None) -> bool:
        if candidate.kind != KIND_LOCATION:
            return False
        if candidate.location_info_fetched_at is None:
            return True
        now = now or _utcnow()
        return candidate.location_info_fetched_at < now - timedelta(days=LOCATION_INFO_TTL_DAYS)

    @staticmethod
    def store_location_info(candidate: SourceCandidate, info: Optional[dict[str, Any]]) -> None:
        """Cache location info; ``None`` records that the location is unavailable."""
        candidate.location_info_json = info if info is not None else {"unavailable": True}
        candidate.location_info_fetched_at = _utcnow()

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def dismiss(self, candidate: SourceCandidate) -> SourceCandidate:
        if candidate.status == STATUS_ACCEPTED:
            raise DiscoveryConflictError("An accepted candidate cannot be dismissed")
        if self._active_trial(candidate) is not None:
            raise DiscoveryConflictError("Cancel the running trial before dismissing")
        candidate.status = STATUS_DISMISSED
        candidate.snoozed_until = None
        self.db.flush()
        return candidate

    def restore(self, candidate: SourceCandidate) -> SourceCandidate:
        if candidate.status != STATUS_DISMISSED:
            raise DiscoveryConflictError("Only a dismissed candidate can be restored")
        candidate.status = self._resting_status(candidate)
        self.db.flush()
        return candidate

    def snooze(self, candidate: SourceCandidate, until: datetime) -> SourceCandidate:
        if candidate.status in (STATUS_ACCEPTED, STATUS_DISMISSED):
            raise DiscoveryConflictError(f"A {candidate.status} candidate cannot be snoozed")
        until = until.replace(tzinfo=None) if until.tzinfo else until
        if until <= _utcnow():
            raise DiscoveryError("Snooze date must be in the future")
        candidate.status = STATUS_SNOOZED
        candidate.snoozed_until = until
        self.db.flush()
        return candidate

    def accept(
        self,
        candidate: SourceCandidate,
        search_query: Optional[str] = None,
        sort_by: str = "new",
        time_filter: str = "day",
        identity_id: Optional[int] = None,
        auto_analyze: bool = True,
        min_confidence: float = 0.7,
    ) -> ScoutWatch:
        """Create (or convert the trial watch into) a real scout watch.

        A trial watch is converted in place so the posts it already analysed
        are not analysed again.
        """
        from rediska_core.domain.services.scout_watch import (
            VALID_SORTS,
            VALID_TIME_FILTERS,
            ScoutWatchService,
        )

        if candidate.kind != KIND_LOCATION:
            raise DiscoveryError("Only a location candidate can become a watch")
        if candidate.status == STATUS_ACCEPTED:
            raise DiscoveryConflictError("Candidate already accepted")
        if candidate.status == STATUS_DISMISSED:
            raise DiscoveryConflictError("Restore the candidate before accepting it")
        if self._active_trial(candidate) is not None:
            raise DiscoveryConflictError("Cancel or wait for the running trial first")
        if sort_by not in VALID_SORTS:
            raise DiscoveryError(f"Invalid sort_by: {sort_by}")
        if time_filter not in VALID_TIME_FILTERS:
            raise DiscoveryError(f"Invalid time_filter: {time_filter}")

        search_query = search_query or None
        duplicate = self.db.scalars(
            select(ScoutWatch).where(
                ScoutWatch.provider_id == candidate.provider_id,
                ScoutWatch.is_trial.is_(False),
                ScoutWatch.search_query == search_query
                if search_query is not None
                else ScoutWatch.search_query.is_(None),
            )
        ).all()
        if any(normalize_location(w.source_location, candidate.provider_id) == candidate.name
               for w in duplicate):
            raise DiscoveryConflictError(
                f"A watch already exists for {candidate.name} with this search query"
            )

        trial_watch = self.candidate_watch(candidate)
        if trial_watch is not None and trial_watch.is_trial:
            service = ScoutWatchService(self.db)
            watch = service.update_watch(
                trial_watch.id,
                sort_by=sort_by,
                time_filter=time_filter,
                identity_id=identity_id,
                auto_analyze=auto_analyze,
                min_confidence=min_confidence,
            )
            watch.search_query = search_query
            watch.is_trial = False
            watch.is_active = True
        else:
            watch = ScoutWatchService(self.db).create_watch(
                source_location=candidate.name,
                search_query=search_query,
                sort_by=sort_by,
                time_filter=time_filter,
                identity_id=identity_id,
                auto_analyze=auto_analyze,
                min_confidence=min_confidence,
                provider_id=candidate.provider_id,
            )

        candidate.watch_id = watch.id
        candidate.status = STATUS_ACCEPTED
        candidate.snoozed_until = None
        self.db.flush()
        return watch

    def add_manual(
        self, name: str, location_info: Optional[dict[str, Any]] = None
    ) -> SourceCandidate:
        """Add a searched location as a `manual` candidate."""
        normalized = normalize_location(name, self.provider_id)
        if not normalized:
            raise DiscoveryError("Location name is required")
        if normalized in self.watched_locations():
            raise DiscoveryConflictError(f"{normalized} is already watched")
        existing = self.db.scalars(
            select(SourceCandidate).where(
                SourceCandidate.provider_id == self.provider_id,
                SourceCandidate.kind == KIND_LOCATION,
                SourceCandidate.name == normalized,
            )
        ).first()
        if existing is not None:
            raise DiscoveryConflictError(
                f"{normalized} is already a candidate ({existing.status})"
            )
        now = _utcnow()
        candidate = SourceCandidate(
            provider_id=self.provider_id,
            kind=KIND_LOCATION,
            name=normalized,
            origin=ORIGIN_MANUAL,
            status=STATUS_NEW,
            evidence_json={},
            evidence_count=0,
            created_at=now,
            updated_at=now,
        )
        if location_info is not None:
            self.store_location_info(candidate, location_info)
        self.db.add(candidate)
        self.db.flush()
        return candidate

    def annotate_locations(self, names: Iterable[str]) -> dict[str, dict[str, Any]]:
        """For search results: watched flag and candidate id/status per name."""
        normalized = {n: normalize_location(n, self.provider_id) for n in names}
        watched = self.watched_locations()
        wanted = [n for n in normalized.values() if n]
        candidates = {
            c.name: c
            for c in self.db.scalars(
                select(SourceCandidate).where(
                    SourceCandidate.provider_id == self.provider_id,
                    SourceCandidate.kind == KIND_LOCATION,
                    SourceCandidate.name.in_(wanted),
                )
            ).all()
        } if wanted else {}
        out: dict[str, dict[str, Any]] = {}
        for raw, norm in normalized.items():
            cand = candidates.get(norm) if norm else None
            out[raw] = {
                "watched": bool(norm and norm in watched),
                "candidate_id": cand.id if cand else None,
                "candidate_status": cand.status if cand else None,
            }
        return out

    # =========================================================================
    # TRIALS
    # =========================================================================

    def candidate_watch(self, candidate: SourceCandidate) -> Optional[ScoutWatch]:
        """The candidate's watch, read by id (the relationship can be stale
        within a session after ``watch_id`` changes)."""
        if candidate.watch_id is None:
            return None
        return self.db.get(ScoutWatch, candidate.watch_id)

    def _active_trial(self, candidate: SourceCandidate) -> Optional[SourceTrial]:
        return self.db.scalars(
            select(SourceTrial).where(
                SourceTrial.candidate_id == candidate.id,
                SourceTrial.status.in_(ACTIVE_TRIAL_STATUSES),
            )
        ).first()

    def running_trial(self) -> Optional[SourceTrial]:
        """The one queued or running trial, if any (only one runs at a time)."""
        return self.db.scalars(
            select(SourceTrial).where(SourceTrial.status.in_(ACTIVE_TRIAL_STATUSES))
        ).first()

    def start_trial(
        self,
        candidate: SourceCandidate,
        sample_size: Optional[int] = None,
        identity_id: Optional[int] = None,
    ) -> SourceTrial:
        """Create the trial row, its hidden watch (reused across trials) and job.

        The caller enqueues ``discovery.run_trial`` after committing.
        """
        if candidate.kind != KIND_LOCATION:
            raise DiscoveryError(
                "External hosts cannot be trialled: unregistered hosts are never fetched"
            )
        if candidate.status in (STATUS_ACCEPTED, STATUS_DISMISSED):
            raise DiscoveryConflictError(f"A {candidate.status} candidate cannot be trialled")
        if self.running_trial() is not None:
            raise DiscoveryConflictError("Another trial is already running")

        size = sample_size or self.trial_sample
        if size < 1 or size > TRIAL_SAMPLE_HARD_CAP:
            raise DiscoveryError(f"Sample size must be between 1 and {TRIAL_SAMPLE_HARD_CAP}")

        watch = self.candidate_watch(candidate)
        if watch is None or not watch.is_trial:
            watch = ScoutWatch(
                provider_id=candidate.provider_id,
                source_location=candidate.name,
                search_query=None,
                sort_by="new",
                time_filter="day",
                identity_id=identity_id,
                is_active=False,
                is_trial=True,
                auto_analyze=True,
                min_confidence=0.7,
            )
            self.db.add(watch)
            self.db.flush()
            candidate.watch_id = watch.id
        elif identity_id is not None:
            watch.identity_id = identity_id

        trial = SourceTrial(
            candidate_id=candidate.id,
            watch_id=watch.id,
            status="queued",
            sample_size=size,
            created_at=_utcnow(),
        )
        self.db.add(trial)
        self.db.flush()

        job = Job(
            queue_name="scout",
            job_type=TRIAL_JOB_TYPE,
            payload_json={"trial_id": trial.id, "candidate_id": candidate.id},
            dedupe_key=f"{TRIAL_JOB_TYPE}:{trial.id}",
            status="queued",
            max_attempts=1,
        )
        self.db.add(job)
        self.db.flush()
        trial.job_id = job.id
        if candidate.status == STATUS_SNOOZED:
            candidate.status = self._resting_status(candidate)
            candidate.snoozed_until = None
        self.db.flush()
        return trial

    def get_trial(self, trial_id: int) -> SourceTrial:
        trial = self.db.get(SourceTrial, trial_id)
        if trial is None:
            raise DiscoveryNotFoundError(f"Trial not found: {trial_id}")
        return trial

    def cancel_trial(self, trial: SourceTrial) -> SourceTrial:
        """Request cancellation; the worker stops between posts.

        A queued trial is cancelled immediately. A running trial is cancelled
        by the worker; asking a second time forces it (a worker that died
        mid-trial would otherwise leave it running forever).
        """
        if trial.status not in ACTIVE_TRIAL_STATUSES:
            raise DiscoveryConflictError(f"Trial is already {trial.status}")
        job = self.db.get(Job, trial.job_id) if trial.job_id else None
        already_requested = job is not None and job.status == "cancelled"
        if job is not None and job.status not in ("done", "failed"):
            job.status = "cancelled"
        if trial.status == "queued" or already_requested or job is None:
            trial.status = "cancelled"
            trial.finished_at = _utcnow()
        self.db.flush()
        return trial

    def build_trial_yield(
        self,
        trial: SourceTrial,
        posts_fetched: int,
        skipped_empty: int,
        link_only_resolved: int,
        post_ages_hours: list[float],
    ) -> dict[str, Any]:
        """Yield report for a trial, from its run's posts plus fetch stats."""
        posts = (
            self.db.scalars(
                select(ScoutWatchPost).where(ScoutWatchPost.run_id == trial.run_id)
            ).all()
            if trial.run_id is not None
            else []
        )
        by_rec: Counter = Counter()
        gate_failures: Counter = Counter()
        skipped = failed = 0
        for post in posts:
            if post.analysis_status == "analyzed" and post.analysis_recommendation:
                by_rec[post.analysis_recommendation] += 1
            elif post.analysis_status == "skipped":
                skipped += 1
            elif post.analysis_status == "failed":
                failed += 1
            results = post.dimension_results_json
            raw_gate = results.get("gate_verdict") if isinstance(results, dict) else None
            gate: dict[str, Any] = raw_gate if isinstance(raw_gate, dict) else {}
            for g in gate.get("gate_results") or []:
                if isinstance(g, dict) and g.get("status") == "fail" and g.get("gate"):
                    gate_failures[g["gate"]] += 1

        top_gate = gate_failures.most_common(1)
        return {
            "posts_fetched": posts_fetched,
            "posts_recorded": len(posts),
            "skipped_empty": skipped_empty,
            "link_only_resolved": link_only_resolved,
            "suitable": by_rec.get("suitable", 0),
            "needs_review": by_rec.get("needs_review", 0),
            "not_recommended": by_rec.get("not_recommended", 0),
            "skipped_prior_verdict": skipped,
            "failed": failed,
            "top_failing_gate": top_gate[0][0] if top_gate else None,
            "top_failing_gate_count": top_gate[0][1] if top_gate else 0,
            "gate_failures": dict(gate_failures),
            "median_post_age_hours": (
                round(statistics.median(post_ages_hours), 1) if post_ages_hours else None
            ),
        }

    # =========================================================================
    # WATCH YIELD
    # =========================================================================

    def watch_yields(
        self, watch_ids: Iterable[int], days: int = 30, now: Optional[datetime] = None
    ) -> dict[int, dict[str, Any]]:
        """Trailing-window yield per watch, in a constant number of queries.

        ``posts_seen`` counts retained sightings: analysis-free sightings older
        than the 3-day history retention are no longer stored.
        """
        ids = list(watch_ids)
        if not ids:
            return {}
        now = now or _utcnow()
        cutoff = now - timedelta(days=days)
        out: dict[int, dict[str, Any]] = {
            wid: {
                "window_days": days,
                "posts_seen": 0,
                "suitable": 0,
                "needs_review": 0,
                "not_recommended": 0,
                "leads_created": 0,
                "leads_contacted": 0,
                "leads_engaged": 0,
            }
            for wid in ids
        }

        for wid, rec, count in self.db.execute(
            select(
                ScoutWatchPost.watch_id,
                ScoutWatchPost.analysis_recommendation,
                func.count(ScoutWatchPost.id),
            )
            .where(ScoutWatchPost.watch_id.in_(ids), ScoutWatchPost.first_seen_at >= cutoff)
            .group_by(ScoutWatchPost.watch_id, ScoutWatchPost.analysis_recommendation)
        ).all():
            out[wid]["posts_seen"] += count
            if rec in RECOMMENDATIONS:
                out[wid][rec] += count

        for wid, created, contacted, engaged in self.db.execute(
            select(
                LeadPost.scout_watch_id,
                func.count(distinct(LeadPost.id)),
                func.sum(case((ExternalAccount.contact_state == "contacted", 1), else_=0)),
                func.sum(case((ExternalAccount.engagement_state == "engaged", 1), else_=0)),
            )
            .outerjoin(ExternalAccount, ExternalAccount.id == LeadPost.author_account_id)
            .where(
                LeadPost.scout_watch_id.in_(ids),
                LeadPost.created_at >= cutoff,
                LeadPost.deleted_at.is_(None),
            )
            .group_by(LeadPost.scout_watch_id)
        ).all():
            out[wid]["leads_created"] = int(created or 0)
            out[wid]["leads_contacted"] = int(contacted or 0)
            out[wid]["leads_engaged"] = int(engaged or 0)

        return out


__all__ = [
    "DiscoveryConflictError",
    "DiscoveryError",
    "DiscoveryNotFoundError",
    "KIND_EXTERNAL_HOST",
    "KIND_LOCATION",
    "MiningSummary",
    "SourceDiscoveryService",
    "TRIAL_SAMPLE_HARD_CAP",
    "compute_lift",
    "host_of",
    "is_outbound_candidate_url",
    "is_qualified_author",
    "normalize_location",
    "not_trial_post",
    "qualified_account_ids",
    "record_link_sighting",
    "trial_watch_ids_select",
    "unresolved_trial_watch_ids",
]
