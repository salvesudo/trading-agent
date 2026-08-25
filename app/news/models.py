"""News/sentiment models -- Phase 8."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    published_at: Optional[datetime]  # None if the feed omitted/malformed pubDate
    summary: str
    source: str


__all__ = ["NewsItem"]
