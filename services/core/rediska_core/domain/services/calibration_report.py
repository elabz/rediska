"""Calibration report: compare analysis output with what the user actually did.

Computes a snapshot of precision signals per scout watch and overall, from
data that is already recorded — no LLM calls:

- lead verdicts: suitable -> ignored / contacted rates, contacted -> engaged
  (``lead_posts.status`` + the author's ``external_accounts`` states)
- needs-review triage: promoted / dismissed / pending counts and queue size
  (``scout_watch_posts`` triage markers)
- gate outcome distribution from stored structured gate verdicts
  (best-effort: posts analysed before deterministic gates carry none)
- dimension failure rates (``analysis_dimensions`` overall; per watch from the
  dimensions missing in a scout post's stored results)

Lead verdicts lag lead creation, so lead metrics use a longer cohort window
ending at ``period_end``; scout post and dimension metrics use the period.
Aggregation is plain Python over the selected rows (portable to SQLite tests).
"""

from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    AnalysisDimension,
    CalibrationReport,
    ExternalAccount,
    LeadPost,
    ScoutWatch,
    ScoutWatchPost,
)
from rediska_core.domain.services.lead_gates import GATES
from rediska_core.domain.services.source_discovery import not_trial_post

REPORT_PERIOD_DAYS = 7
LEAD_COHORT_DAYS = 28

DIMENSIONS = [
    "demographics",
    "preferences",
    "relationship_goals",
    "risk_flags",
    "sexual_preferences",
]

CONTACTED_LEAD_STATUSES = {"contact_queued", "contacted"}

# Key for leads that did not come from a watch (manual saves).
MANUAL_KEY = "manual"


def _rate(numerator: int, denominator: int) -> Optional[float]:
    return round(numerator / denominator, 4) if denominator else None


def _lead_metrics(leads: Iterable[LeadPost], accounts: dict[int, ExternalAccount]) -> dict:
    leads = list(leads)
    suitable = [lead for lead in leads if lead.analysis_recommendation == "suitable"]

    def author(lead: LeadPost) -> Optional[ExternalAccount]:
        return accounts.get(lead.author_account_id) if lead.author_account_id else None

    def contacted(lead: LeadPost) -> bool:
        account = author(lead)
        return lead.status in CONTACTED_LEAD_STATUSES or (
            account is not None and account.contact_state == "contacted"
        )

    def engaged(lead: LeadPost) -> bool:
        account = author(lead)
        return account is not None and account.engagement_state == "engaged"

    suitable_ignored = sum(1 for lead in suitable if lead.status == "ignored")
    suitable_contacted = sum(1 for lead in suitable if contacted(lead))
    contacted_leads = [lead for lead in leads if contacted(lead)]
    contacted_engaged = sum(1 for lead in contacted_leads if engaged(lead))

    by_priority: dict[str, int] = {}
    for lead in leads:
        key = lead.priority or "unranked"
        by_priority[key] = by_priority.get(key, 0) + 1

    return {
        "leads_created": len(leads),
        "suitable_leads": len(suitable),
        "suitable_ignored": suitable_ignored,
        "suitable_ignored_rate": _rate(suitable_ignored, len(suitable)),
        "suitable_contacted": suitable_contacted,
        "suitable_contacted_rate": _rate(suitable_contacted, len(suitable)),
        "contacted": len(contacted_leads),
        "contacted_engaged": contacted_engaged,
        "contacted_engaged_rate": _rate(contacted_engaged, len(contacted_leads)),
        "expired": sum(1 for lead in leads if lead.status == "expired"),
        "untouched": sum(1 for lead in leads if lead.status == "new"),
        "by_priority": by_priority,
    }


def _post_metrics(posts: Iterable[ScoutWatchPost]) -> dict:
    posts = [p for p in posts if p.analysis_status == "analyzed"]

    recommendations = {"suitable": 0, "needs_review": 0, "not_recommended": 0}
    for post in posts:
        if post.analysis_recommendation in recommendations:
            recommendations[post.analysis_recommendation] += 1

    needs_review = [p for p in posts if p.analysis_recommendation == "needs_review"]
    promoted = sum(1 for p in needs_review if p.lead_id is not None or p.triaged_at)
    dismissed = sum(1 for p in needs_review if p.dismissed_at and p.lead_id is None)

    gate_outcomes = {gate: {"fail": 0, "unclear": 0} for gate in GATES}
    without_gate_verdict = 0
    dimension_failures: dict[str, dict[str, Any]] = {
        dim: {"total": 0, "failed": 0} for dim in DIMENSIONS
    }

    for post in posts:
        stored = post.dimension_results_json
        if not isinstance(stored, dict) or not stored:
            without_gate_verdict += 1
            continue

        verdict = stored.get("gate_verdict")
        gate_results = verdict.get("gate_results") if isinstance(verdict, dict) else None
        if isinstance(gate_results, list) and gate_results:
            for gate in gate_results:
                if not isinstance(gate, dict):
                    continue
                outcome = gate_outcomes.setdefault(
                    str(gate.get("gate")), {"fail": 0, "unclear": 0}
                )
                if gate.get("status") in ("fail", "unclear"):
                    outcome[gate["status"]] += 1
        else:
            without_gate_verdict += 1

        # Only successful dimension outputs are stored on the post, so a
        # missing dimension means that agent failed for this post.
        for dim in DIMENSIONS:
            dimension_failures[dim]["total"] += 1
            if not isinstance(stored.get(dim), dict):
                dimension_failures[dim]["failed"] += 1

    for counts in dimension_failures.values():
        counts["rate"] = _rate(counts["failed"], counts["total"])

    return {
        "posts_analyzed": len(posts),
        "recommendations": recommendations,
        "needs_review": {
            "total": len(needs_review),
            "promoted": promoted,
            "dismissed": dismissed,
            "pending": len(needs_review) - promoted - dismissed,
        },
        "gate_outcomes": gate_outcomes,
        "posts_without_gate_verdict": without_gate_verdict,
        "dimension_failures": dimension_failures,
    }


class CalibrationReportService:
    """Computes, stores and lists calibration reports."""

    def __init__(self, db: Session):
        self.db = db

    def compute(
        self,
        period_end: Optional[datetime] = None,
        period_days: int = REPORT_PERIOD_DAYS,
        lead_cohort_days: int = LEAD_COHORT_DAYS,
    ) -> dict[str, Any]:
        """Compute the report payload for the period ending at ``period_end``."""
        period_end = period_end or datetime.utcnow()
        period_start = period_end - timedelta(days=period_days)
        cohort_start = period_end - timedelta(days=lead_cohort_days)

        leads = (
            self.db.query(LeadPost)
            .filter(
                LeadPost.deleted_at.is_(None),
                LeadPost.created_at >= cohort_start,
                LeadPost.created_at < period_end,
            )
            .all()
        )
        account_ids = {lead.author_account_id for lead in leads if lead.author_account_id}
        accounts = (
            {
                a.id: a
                for a in self.db.query(ExternalAccount)
                .filter(ExternalAccount.id.in_(account_ids))
                .all()
            }
            if account_ids
            else {}
        )

        posts = (
            self.db.query(ScoutWatchPost)
            .filter(
                ScoutWatchPost.first_seen_at >= period_start,
                ScoutWatchPost.first_seen_at < period_end,
                # Source-discovery trial posts are not watch output.
                not_trial_post(),
            )
            .all()
        )

        watches = {w.id: w for w in self.db.query(ScoutWatch).all()}
        trial_watch_ids = {wid for wid, w in watches.items() if w.is_trial}

        leads_by_watch: dict[Any, list[LeadPost]] = {}
        for lead in leads:
            key = lead.scout_watch_id if lead.scout_watch_id is not None else MANUAL_KEY
            leads_by_watch.setdefault(key, []).append(lead)

        posts_by_watch: dict[int, list[ScoutWatchPost]] = {}
        for post in posts:
            posts_by_watch.setdefault(post.watch_id, []).append(post)

        watch_rows = []
        for watch_id in sorted(
            set(posts_by_watch) | {k for k in leads_by_watch if k != MANUAL_KEY}
        ):
            if watch_id in trial_watch_ids:
                continue
            watch = watches.get(watch_id)
            watch_rows.append(
                {
                    "watch_id": watch_id,
                    "source_location": watch.source_location if watch else None,
                    "search_query": watch.search_query if watch else None,
                    "min_confidence": watch.min_confidence if watch else None,
                    "leads": _lead_metrics(leads_by_watch.get(watch_id, []), accounts),
                    "posts": _post_metrics(posts_by_watch.get(watch_id, [])),
                }
            )

        return {
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "lead_cohort_start": cohort_start.isoformat(),
            "generated_at": datetime.utcnow().isoformat(),
            "gate_outcomes_best_effort": True,
            "overall": {
                "leads": _lead_metrics(leads, accounts),
                "manual_leads": _lead_metrics(leads_by_watch.get(MANUAL_KEY, []), accounts),
                "posts": _post_metrics(posts),
                "needs_review_queue_size": self.needs_review_queue_size(),
                "dimension_failures": self._analysis_dimension_failures(
                    period_start, period_end
                ),
            },
            "watches": watch_rows,
        }

    def needs_review_queue_size(self) -> int:
        """Current untriaged needs-review posts (not bound to the period)."""
        return (
            self.db.query(ScoutWatchPost)
            .filter(
                ScoutWatchPost.analysis_recommendation == "needs_review",
                ScoutWatchPost.dismissed_at.is_(None),
                ScoutWatchPost.triaged_at.is_(None),
                ScoutWatchPost.lead_id.is_(None),
                not_trial_post(),
            )
            .count()
        )

    def _analysis_dimension_failures(
        self, period_start: datetime, period_end: datetime
    ) -> dict[str, dict]:
        """Per-dimension failure rates from ``analysis_dimensions`` rows.

        Each attempt is a row, so a retried dimension counts twice.
        """
        rows = (
            self.db.query(AnalysisDimension.dimension, AnalysisDimension.status)
            .filter(
                AnalysisDimension.started_at >= period_start,
                AnalysisDimension.started_at < period_end,
            )
            .all()
        )
        result: dict[str, dict[str, Any]] = {}
        for dimension, status in rows:
            counts = result.setdefault(dimension, {"total": 0, "failed": 0})
            counts["total"] += 1
            if status == "failed":
                counts["failed"] += 1
        for counts in result.values():
            counts["rate"] = _rate(counts["failed"], counts["total"])
        return result

    def generate(self, period_end: Optional[datetime] = None) -> CalibrationReport:
        """Compute and store a report row."""
        payload = self.compute(period_end=period_end)
        report = CalibrationReport(
            period_start=datetime.fromisoformat(payload["period_start"]),
            period_end=datetime.fromisoformat(payload["period_end"]),
            report_json=payload,
            created_at=datetime.utcnow(),
        )
        self.db.add(report)
        self.db.flush()
        return report

    def list_reports(self, limit: int = 10) -> list[CalibrationReport]:
        """Stored reports, newest first."""
        return (
            self.db.query(CalibrationReport)
            .order_by(CalibrationReport.period_end.desc(), CalibrationReport.id.desc())
            .limit(limit)
            .all()
        )


__all__ = ["CalibrationReportService", "REPORT_PERIOD_DAYS", "LEAD_COHORT_DAYS"]
