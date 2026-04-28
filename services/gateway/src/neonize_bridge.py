from __future__ import annotations

import base64
import logging
from typing import Any

try:
    from .connection_status import GatewayConnectionStatus
    from .ingest_handler import BackendIngestClient
except ImportError:  # pragma: no cover - supports direct script imports
    from connection_status import GatewayConnectionStatus
    from ingest_handler import BackendIngestClient

logger = logging.getLogger(__name__)


class NeonizeUnavailableError(RuntimeError):
    """Raised when Neonize is not installed in the gateway runtime."""


def _load_neonize_runtime() -> tuple[Any, Any, Any, Any, Any, Any, Any, Any, Any]:
    try:
        from neonize.client import NewClient
        from neonize.events import (
            ConnectedEv,
            ConnectFailureEv,
            DisconnectedEv,
            KeepAliveRestoredEv,
            KeepAliveTimeoutEv,
            LoggedOutEv,
            QREv,
            MessageEv,
            event as neonize_wait,
        )
    except Exception as exc:  # pragma: no cover - depends on runtime image
        raise NeonizeUnavailableError(
            "Failed to load Neonize runtime. Ensure `neonize` is installed and system libs "
            f"(e.g. libmagic) are available. Original error: {exc}"
        ) from exc

    return (
        NewClient,
        ConnectedEv,
        QREv,
        MessageEv,
        DisconnectedEv,
        ConnectFailureEv,
        LoggedOutEv,
        KeepAliveTimeoutEv,
        KeepAliveRestoredEv,
        neonize_wait,
    )


class NeonizeEventBridge:
    def __init__(
        self,
        *,
        backend_client: BackendIngestClient,
        connection_status: GatewayConnectionStatus | None = None,
        qr_provider: Any | None = None,
    ) -> None:
        self.backend_client = backend_client
        self.connection_status = connection_status
        self.qr_provider = qr_provider

    def on_connected(self) -> None:
        if self.connection_status is not None:
            self.connection_status.mark_connected(event="connected")
        if self.qr_provider is not None:
            try:
                self.qr_provider.clear(reason="connected")
            except Exception:
                logger.exception("gateway_qr_clear_failed", extra={"reason": "connected"})
        logger.info("gateway_connected")

    def on_disconnected(self) -> None:
        if self.connection_status is not None:
            self.connection_status.mark_disconnected(event="disconnected")
        if self.qr_provider is not None:
            try:
                self.qr_provider.clear(reason="disconnected")
            except Exception:
                logger.exception("gateway_qr_clear_failed", extra={"reason": "disconnected"})
        logger.warning("gateway_disconnected")

    def on_connect_failure(self, neonize_event: Any) -> None:
        reason = getattr(neonize_event, "Message", None)
        normalized_reason = str(reason).strip() if reason is not None else None
        if self.connection_status is not None:
            self.connection_status.mark_disconnected(
                event="connect_failure",
                error=normalized_reason,
            )
        logger.warning("gateway_connect_failure", extra={"reason": normalized_reason})

    def on_logged_out(self) -> None:
        if self.connection_status is not None:
            self.connection_status.mark_disconnected(event="logged_out")
        if self.qr_provider is not None:
            try:
                self.qr_provider.clear(reason="logged_out")
            except Exception:
                logger.exception("gateway_qr_clear_failed", extra={"reason": "logged_out"})
        logger.warning("gateway_logged_out")

    def on_keepalive_timeout(self) -> None:
        if self.connection_status is not None:
            self.connection_status.mark_disconnected(event="keepalive_timeout")
        logger.warning("gateway_keepalive_timeout")

    def on_keepalive_restored(self) -> None:
        if self.connection_status is not None:
            self.connection_status.mark_connected(event="keepalive_restored")
        logger.info("gateway_keepalive_restored")

    def _attach_inline_image_payload(self, *, client: Any, neonize_event: Any, payload: dict[str, Any]) -> None:
        media_items = payload.get("message", {}).get("media", [])
        if not isinstance(media_items, list):
            return

        image_media = [
            item
            for item in media_items
            if isinstance(item, dict)
            and isinstance(item.get("mime_type"), str)
            and (
                item["mime_type"].lower().startswith("image/")
                or item["mime_type"].lower().endswith("/image")
            )
        ]

        if not image_media:
            return

        try:
            message_obj = getattr(neonize_event, "Message", None)
            if message_obj is None:
                return

            downloaded = client.download_any(message_obj)
            if not downloaded:
                return

            inline_data_base64 = base64.b64encode(downloaded).decode("ascii")
            image_media[0]["inline_data_base64"] = inline_data_base64
        except Exception:
            logger.exception("gateway_inline_image_download_failed")

    def on_message(self, *, client: Any, neonize_event: Any) -> None:
        try:
            payload = self.backend_client.build_inbound_payload(neonize_event)
            self._attach_inline_image_payload(client=client, neonize_event=neonize_event, payload=payload)
            response = self.backend_client.send_inbound_payload(payload)
        except Exception:
            logger.exception("gateway_inbound_forward_failed")
            return

        logger.info(
            "gateway_inbound_forwarded",
            extra={
                "trace_id": payload.get("trace_id"),
                "provider_group_id": payload.get("provider_group_id"),
                "provider_message_id": payload.get("provider_message_id"),
                "status_code": response.status_code,
            },
        )

    def register(
        self,
        *,
        client: Any,
        connected_event_type: Any,
        qr_event_type: Any | None = None,
        message_event_type: Any,
        disconnected_event_type: Any,
        connect_failure_event_type: Any,
        logged_out_event_type: Any,
        keepalive_timeout_event_type: Any,
        keepalive_restored_event_type: Any,
    ) -> None:
        if qr_event_type is not None:
            @client.event(qr_event_type)
            def _qr(_: Any, event: Any) -> None:
                codes = getattr(event, "Codes", None)
                if isinstance(codes, (list, tuple)) and codes:
                    code = str(codes[0]).strip()
                    if code and self.qr_provider is not None:
                        try:
                            self.qr_provider.set_qr(code)
                        except Exception:
                            logger.exception("gateway_qr_store_failed")

        @client.event(connected_event_type)
        def _connected(_: Any, __: Any) -> None:
            self.on_connected()

        @client.event(disconnected_event_type)
        def _disconnected(_: Any, __: Any) -> None:
            self.on_disconnected()

        @client.event(connect_failure_event_type)
        def _connect_failure(_: Any, event: Any) -> None:
            self.on_connect_failure(event)

        @client.event(logged_out_event_type)
        def _logged_out(_: Any, __: Any) -> None:
            self.on_logged_out()

        @client.event(keepalive_timeout_event_type)
        def _keepalive_timeout(_: Any, __: Any) -> None:
            self.on_keepalive_timeout()

        @client.event(keepalive_restored_event_type)
        def _keepalive_restored(_: Any, __: Any) -> None:
            self.on_keepalive_restored()

        @client.event(message_event_type)
        def _message(_: Any, event: Any) -> None:
            self.on_message(client=client, neonize_event=event)


def initialize_neonize_gateway(
    *,
    session_name: str,
    backend_base_url: str,
    service_token: str | None = None,
    database_path: str | None = None,
    connection_status: GatewayConnectionStatus | None = None,
    qr_status: Any | None = None,
) -> tuple[Any, Any]:
    (
        NewClient,
        ConnectedEv,
        QREv,
        MessageEv,
        DisconnectedEv,
        ConnectFailureEv,
        LoggedOutEv,
        KeepAliveTimeoutEv,
        KeepAliveRestoredEv,
        neonize_wait,
    ) = _load_neonize_runtime()

    db_name = database_path or "neonize.db"
    client = NewClient(db_name, uuid=session_name)
    backend_client = BackendIngestClient(
        backend_base_url=backend_base_url,
        service_token=service_token,
    )

    bridge = NeonizeEventBridge(
        backend_client=backend_client,
        connection_status=connection_status,
        qr_provider=qr_status,
    )
    bridge.register(
        client=client,
        connected_event_type=ConnectedEv,
        qr_event_type=QREv,
        message_event_type=MessageEv,
        disconnected_event_type=DisconnectedEv,
        connect_failure_event_type=ConnectFailureEv,
        logged_out_event_type=LoggedOutEv,
        keepalive_timeout_event_type=KeepAliveTimeoutEv,
        keepalive_restored_event_type=KeepAliveRestoredEv,
    )

    return client, neonize_wait


def run_neonize_gateway(
    *,
    session_name: str,
    backend_base_url: str,
    service_token: str | None = None,
    database_path: str | None = None,
    connection_status: GatewayConnectionStatus | None = None,
) -> None:
    client, neonize_wait = initialize_neonize_gateway(
        session_name=session_name,
        backend_base_url=backend_base_url,
        service_token=service_token,
        database_path=database_path,
        connection_status=connection_status,
    )

    logger.info("gateway_starting", extra={"session_name": session_name})
    client.connect()
    neonize_wait.wait()
