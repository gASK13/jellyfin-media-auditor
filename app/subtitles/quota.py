from __future__ import annotations

from datetime import UTC, datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ApiUsage

PROVIDER = "opensubtitles"

def _today() -> str:
    return datetime.now(UTC).date().isoformat()

def downloads_remaining(session: Session, limit: int) -> int:
    usage = session.scalar(select(ApiUsage).where(ApiUsage.provider == PROVIDER, ApiUsage.usage_date == _today()))
    return max(0, limit - (usage.downloads if usage else 0))

def record_download(session: Session) -> None:
    usage = session.scalar(select(ApiUsage).where(ApiUsage.provider == PROVIDER, ApiUsage.usage_date == _today()))
    if usage is None:
        usage = ApiUsage(provider=PROVIDER, usage_date=_today(), downloads=0); session.add(usage)
    usage.downloads += 1
