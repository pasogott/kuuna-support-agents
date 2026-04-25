from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class GatewayQrStatus:
    """Stores the latest QR/pairing code string emitted by Neonize."""

    current_qr: str | None = None
    updated_at: str = field(default_factory=_utc_now_iso)

    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def set_qr(self, qr: str) -> None:
        qr = qr.strip()
        if not qr:
            return
        with self._lock:
            self.current_qr = qr
            self.updated_at = _utc_now_iso()

    def snapshot(self) -> dict[str, str | None]:
        with self._lock:
            return {"qr": self.current_qr, "updated_at": self.updated_at}

    def clear(self, *, reason: str | None = None) -> None:
        """Clear QR status on connection lifecycle changes.

        The QR code is only meaningful while disconnected / pairing.
        """
        with self._lock:
            self.current_qr = None
            self.updated_at = _utc_now_iso()

