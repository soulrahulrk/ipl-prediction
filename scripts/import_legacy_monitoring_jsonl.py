from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipl_predictor.config import get_settings
from ipl_predictor.db import get_db_session, init_db, init_engine
from ipl_predictor.models import MonitoringEvent, MonitoringOutcome
from ipl_predictor.monitoring import EVENT_LOG_PATH, OUTCOME_LOG_PATH


def _parse_iso(ts: str | None) -> datetime:
    if not ts:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return datetime.now(timezone.utc)


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                yield obj
        except Exception:
            continue


def _payload_hash(obj: dict) -> str:
    canonical = json.dumps(obj, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import legacy monitoring JSONL into Postgres/DB tables.")
    parser.add_argument("--events", default=str(EVENT_LOG_PATH), help="Path to prediction_events.jsonl")
    parser.add_argument("--outcomes", default=str(OUTCOME_LOG_PATH), help="Path to prediction_outcomes.jsonl")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    settings = get_settings()
    init_engine(settings.database_url)
    init_db()
    db_session = get_db_session()

    events_path = Path(args.events)
    outcomes_path = Path(args.outcomes)

    events_inserted = 0
    outcomes_inserted = 0

    for event in _iter_jsonl(events_path):
        event_id = str(event.get("event_id", "")).strip()
        if not event_id:
            continue
        exists = db_session.query(MonitoringEvent).filter(MonitoringEvent.event_id == event_id).one_or_none()
        if exists is not None:
            continue
        row = MonitoringEvent(
            event_id=event_id,
            event_payload=event,
            created_at=_parse_iso(str(event.get("timestamp_utc", ""))),
        )
        db_session.add(row)
        events_inserted += 1

    for outcome in _iter_jsonl(outcomes_path):
        payload_hash = _payload_hash(outcome)
        exists = (
            db_session.query(MonitoringOutcome)
            .filter(MonitoringOutcome.payload_hash == payload_hash)
            .one_or_none()
        )
        if exists is not None:
            continue
        row = MonitoringOutcome(
            event_id=str(outcome.get("event_id", "")).strip() or None,
            payload_hash=payload_hash,
            outcome_payload=outcome,
            created_at=_parse_iso(str(outcome.get("timestamp_utc", ""))),
        )
        db_session.add(row)
        outcomes_inserted += 1

    db_session.commit()

    print(
        json.dumps(
            {
                "ok": True,
                "events_path": str(events_path),
                "outcomes_path": str(outcomes_path),
                "events_inserted": events_inserted,
                "outcomes_inserted": outcomes_inserted,
            }
        )
    )


if __name__ == "__main__":
    main()
