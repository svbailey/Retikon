import os

from retikon_core.compaction import run_compaction
from retikon_core.logging import configure_logging, get_logger

SERVICE_NAME = "retikon-compaction-service"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)


def _graph_uri() -> str:
    graph_uri = os.getenv("GRAPH_URI")
    if graph_uri:
        return graph_uri
    graph_bucket = os.getenv("GRAPH_BUCKET")
    graph_prefix = os.getenv("GRAPH_PREFIX", "")
    if graph_bucket:
        prefix = graph_prefix.strip("/")
        if prefix:
            return f"gs://{graph_bucket.strip('/')}/{prefix}"
        return f"gs://{graph_bucket.strip('/')}"
    local_root = os.getenv("LOCAL_GRAPH_ROOT")
    if local_root:
        return local_root
    raise ValueError("GRAPH_URI or GRAPH_BUCKET is required")


def main() -> None:
    report = run_compaction(
        base_uri=_graph_uri(),
        delete_source=os.getenv("COMPACTION_DELETE_SOURCE", "0") == "1",
        retention_apply=os.getenv("RETENTION_APPLY", "0") == "1",
        dry_run=os.getenv("COMPACTION_DRY_RUN", "0") == "1",
        strict=os.getenv("COMPACTION_STRICT", "1") == "1",
    )
    logger.info(
        "Compaction job finished",
        extra={
            "run_id": report.run_id,
            "outputs": len(report.outputs),
            "manifest_uri": report.manifest_uri,
            "audit_uri": report.audit_uri,
            "duration_seconds": report.duration_seconds,
        },
    )


if __name__ == "__main__":
    main()
