"""Rediska Worker Tasks."""

# Import all tasks to register them with Celery
from rediska_worker.tasks import agent  # noqa: F401
from rediska_worker.tasks import embed  # noqa: F401
from rediska_worker.tasks import index  # noqa: F401
from rediska_worker.tasks import ingest  # noqa: F401
from rediska_worker.tasks import maintenance  # noqa: F401
from rediska_worker.tasks import message  # noqa: F401
