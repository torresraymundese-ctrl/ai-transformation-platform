"""Fixed reviewed-source ingestion entry point; never publishes content."""

from ingestion_service import run_enabled_sources
from ingestion_sources import SOURCE_ADAPTERS


INGESTION_QUEUE_NOT_READY = "ingestion_queue_not_ready"

class IngestionQueueNotReadyError(RuntimeError):
    """Raised when no reviewed source is explicitly enabled."""


def run_scraper(*, registry_path=None, transport=None, adapters=None, now=None):
    """Fetch enabled fixed sources into the private candidate queue."""
    result = run_enabled_sources(
        registry_path=registry_path,
        transport=transport,
        adapters=SOURCE_ADAPTERS if adapters is None else adapters,
        now=now,
    )
    if result.attempted_sources == 0:
        raise IngestionQueueNotReadyError(INGESTION_QUEUE_NOT_READY)
    return result


if __name__ == "__main__":
    run_scraper()
