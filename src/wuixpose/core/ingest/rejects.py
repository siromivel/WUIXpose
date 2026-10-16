"""Record features an ingest turns away, as RejectedFeature rows (a dead-letter table)."""

import hashlib
import json
import logging
from typing import Any

from django.utils import timezone

from wuixpose.core.constants import DB_BATCH_SIZE
from wuixpose.core.models import RejectedFeature

logger = logging.getLogger(__name__)


def reject(
    layer: str,
    feature: dict[str, Any],
    reason: RejectedFeature.Reason,
    *,
    source_id: str | None = None,
    detail: str = "",
) -> RejectedFeature:
    """Log a rejected feature and return its row, unsaved; the load saves them with record()."""
    # Missing IDs and stray non-polygons are routine in county data; unreadable geometry isn't.
    level = logging.WARNING if reason == RejectedFeature.Reason.UNREADABLE_GEOMETRY else logging.INFO
    logger.log(level, "Rejected %s feature %s (%s) %s", layer, source_id or "without ID", reason.label, detail)
    canonical = json.dumps(feature, sort_keys=True, separators=(",", ":"))
    return RejectedFeature(
        layer=layer,
        source_id=source_id,
        reason=reason,
        detail=detail,
        feature=feature,
        feature_hash=hashlib.sha256(canonical.encode()).hexdigest(),
    )


def record(rejected: list[RejectedFeature]) -> None:
    """Save rejected features; one already on file just has last_seen_at and reason updated."""
    now = timezone.now()
    # Postgres refuses an upsert that hits the same row twice, as identical features in one load would.
    unique = {(r.layer, r.feature_hash): r for r in rejected}
    for r in unique.values():
        r.first_seen_at = r.last_seen_at = now
    RejectedFeature.objects.bulk_create(
        unique.values(),
        update_conflicts=True,
        unique_fields=("layer", "feature_hash"),
        update_fields=("source_id", "reason", "detail", "last_seen_at"),
        batch_size=DB_BATCH_SIZE,
    )
