"""Agent tasks for LLM-powered analysis."""

from rediska_worker.celery_app import app


@app.task(name="agent.profile_summary")
def profile_summary(account_id: int) -> dict:
    """Generate a profile summary using LLM."""
    # TODO: Implement
    return {"status": "not_implemented", "account_id": account_id}


@app.task(name="agent.lead_scoring")
def lead_scoring(lead_post_id: int) -> dict:
    """Score a lead post using LLM."""
    # TODO: Implement
    return {"status": "not_implemented", "lead_post_id": lead_post_id}


@app.task(name="agent.draft_intro")
def draft_intro(target_account_id: int, context: str | None = None) -> dict:
    """Draft an introduction message using LLM."""
    # TODO: Implement
    return {"status": "not_implemented", "target_account_id": target_account_id}
