import hashlib
import json
from datetime import timezone

def fingerprint(source, theme, event_at):
    if event_at is not None:
        if event_at.tzinfo is None:
            event_at=event_at.replace(tzinfo=timezone.utc)
        event_at=event_at.astimezone(timezone.utc).isoformat()
    payload=json.dumps([source.strip(),theme,event_at],ensure_ascii=False,separators=(",",":"))
    return hashlib.sha256(payload.encode()).hexdigest()
