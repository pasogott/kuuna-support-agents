from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

try:
    from google.protobuf.json_format import MessageToDict
    from google.protobuf.message import Message as ProtobufMessage
except Exception:  # pragma: no cover - optional dependency in scaffold stage
    MessageToDict = None
    ProtobufMessage = None


def _is_protobuf_message(value: Any) -> bool:
    return ProtobufMessage is not None and isinstance(value, ProtobufMessage)


def _protobuf_to_dict(value: Any) -> dict[str, Any]:
    if MessageToDict is None:
        return {"_error": "protobuf runtime unavailable"}
    try:
        return MessageToDict(
            value,
            preserving_proto_field_name=True,
            always_print_fields_with_no_presence=True,
        )
    except TypeError:
        # compatibility with older protobuf versions
        return MessageToDict(value, preserving_proto_field_name=True)


def _to_jsonable(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return str(value)

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()

    if _is_protobuf_message(value):
        return _protobuf_to_dict(value)

    if is_dataclass(value):
        return _to_jsonable(asdict(value), depth=depth + 1)

    if isinstance(value, dict):
        return {str(k): _to_jsonable(v, depth=depth + 1) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v, depth=depth + 1) for v in value]

    if hasattr(value, "__dict__"):
        raw = {
            k: v
            for k, v in vars(value).items()
            if not k.startswith("_") and not callable(v)
        }
        return _to_jsonable(raw, depth=depth + 1)

    return str(value)


def _get_path(obj: Any, *path: str, default: Any = None) -> Any:
    current = obj
    for key in path:
        if current is None:
            return default
        if isinstance(current, dict):
            current = current.get(key)
            continue
        current = getattr(current, key, None)
    return default if current is None else current


def _jid_to_str(jid: Any) -> str | None:
    if jid is None:
        return None
    if isinstance(jid, str):
        return jid

    user = getattr(jid, "User", None) or getattr(jid, "user", None)
    server = getattr(jid, "Server", None) or getattr(jid, "server", None)
    if user and server:
        return f"{user}@{server}"

    return str(jid)


def _extract_text(message_obj: Any) -> str | None:
    direct = _get_path(message_obj, "conversation")
    if direct:
        return str(direct)

    extended = _get_path(message_obj, "extendedTextMessage", "text")
    if extended:
        return str(extended)

    return None


def _extract_reply_and_mentions(message_obj: Any) -> tuple[str | None, list[str]]:
    context = _get_path(message_obj, "extendedTextMessage", "contextInfo")
    if context is None:
        return None, []

    reply_to = _get_path(context, "stanzaID") or _get_path(context, "stanzaId")

    mentioned = _get_path(context, "mentionedJID", default=[])
    mentions = [_jid_to_str(item) or str(item) for item in (mentioned or [])]

    return (str(reply_to) if reply_to else None), mentions


def _get_present_field(obj: Any, *keys: str) -> Any:
    if obj is None:
        return None

    if isinstance(obj, dict):
        for key in keys:
            if key in obj and obj[key] is not None:
                return obj[key]
        lowered = {str(key).lower(): value for key, value in obj.items()}
        for key in keys:
            candidate = lowered.get(key.lower())
            if candidate is not None:
                return candidate
        return None

    if _is_protobuf_message(obj):
        descriptor = getattr(obj, "DESCRIPTOR", None)
        field_names = {field.name for field in getattr(descriptor, "fields", [])}
        for key in keys:
            if key not in field_names:
                continue
            try:
                if obj.HasField(key):
                    return getattr(obj, key)
            except ValueError:
                value = getattr(obj, key, None)
                if value is not None:
                    return value
        return None

    for key in keys:
        value = getattr(obj, key, None)
        if value is not None:
            return value

    return None


def _protocol_type_name(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.upper()

    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name.upper()

    rendered = str(value)
    return rendered.upper() if rendered else None


def _is_deleted_indication(message_obj: Any) -> bool:
    protocol_message = _get_present_field(message_obj, "protocolMessage")
    if protocol_message is None:
        return False

    protocol_type = _get_present_field(protocol_message, "type")
    if isinstance(protocol_type, int):
        return protocol_type == 0

    protocol_type_name = _protocol_type_name(protocol_type)
    if protocol_type_name is None:
        return False

    return "REVOKE" in protocol_type_name or (
        "DELETE" in protocol_type_name and "EDIT" not in protocol_type_name
    )


def _is_edited_indication(message_obj: Any) -> bool:
    if _get_present_field(message_obj, "editedMessage") is not None:
        return True

    protocol_message = _get_present_field(message_obj, "protocolMessage")
    if protocol_message is None:
        return False

    if _get_present_field(protocol_message, "editedMessage") is not None:
        return True

    protocol_type = _get_present_field(protocol_message, "type")
    if isinstance(protocol_type, int):
        return protocol_type == 14

    protocol_type_name = _protocol_type_name(protocol_type)
    return protocol_type_name is not None and "EDIT" in protocol_type_name


def _classify_event_type(message_obj: Any) -> str:
    if _is_deleted_indication(message_obj):
        return "message_deleted"
    if _is_edited_indication(message_obj):
        return "message_edited"
    return "message_created"


def _extract_deleted_target_message_id(message_obj: Any) -> str | None:
    """For WhatsApp protocol revoke/delete events, try to return the *original* message ID.

    Neonize delivers delete events as protocol messages; the outer event Info.ID is the protocol
    event id, not the id of the message being deleted. If we persist that as provider_message_id,
    the backend will create a *new* Message row, which shows up as a new bubble in the UI.
    """
    protocol_message = _get_present_field(message_obj, "protocolMessage")
    if protocol_message is None:
        return None

    key_obj = _get_present_field(protocol_message, "key", "Key")
    if key_obj is None:
        return None

    # common shapes: key.id, key.ID, key.stanzaId
    candidate = (
        _get_path(key_obj, "id")
        or _get_path(key_obj, "ID")
        or _get_path(key_obj, "Id")
        or _get_path(key_obj, "stanzaId")
        or _get_path(key_obj, "stanzaID")
    )
    if not candidate:
        return None
    return str(candidate)


def _resolve_message_content(message_obj: Any) -> Any:
    direct_edited_message = _get_present_field(message_obj, "editedMessage")
    if direct_edited_message is not None:
        nested_message = _get_present_field(direct_edited_message, "message")
        if nested_message is not None:
            return nested_message

    protocol_message = _get_present_field(message_obj, "protocolMessage")
    if protocol_message is not None:
        nested_message = _get_present_field(protocol_message, "editedMessage")
        if nested_message is not None:
            return nested_message

    return message_obj


def _extract_media(message_obj: Any, provider_message_id: str) -> list[dict[str, Any]]:
    media_fields: list[tuple[list[str], str]] = [
        (["imageMessage", "ImageMessage"], "image"),
        (["videoMessage", "VideoMessage"], "video"),
        (["audioMessage", "AudioMessage"], "audio"),
        (["documentMessage", "DocumentMessage"], "document"),
        (["stickerMessage", "StickerMessage"], "sticker"),
    ]

    def _field_value(media_obj: Any, *keys: str) -> Any:
        if isinstance(media_obj, dict):
            for key in keys:
                if key in media_obj:
                    return media_obj[key]
            lowered = {str(key).lower(): value for key, value in media_obj.items()}
            for key in keys:
                candidate = lowered.get(key.lower())
                if candidate is not None:
                    return candidate
            return None

        for key in keys:
            value = _get_path(media_obj, key)
            if value is not None:
                return value
        return None

    def _is_empty_value(value: Any) -> bool:
        if value in (None, "", b""):
            return True
        if isinstance(value, str) and value.strip() in {"0", "0.0", "b''", "[]", "{}"}:
            return True
        if isinstance(value, (int, float)) and value <= 0:
            return True
        return False

    def _has_media_payload(media_obj: Any) -> bool:
        if media_obj is None:
            return False

        if isinstance(media_obj, dict) and not media_obj:
            return False

        def _signal_present(value: Any) -> bool:
            return not _is_empty_value(value)

        payload_signals = [
            _field_value(media_obj, "url", "URL"),
            _field_value(media_obj, "directPath", "DirectPath"),
            _field_value(media_obj, "mediaKey", "MediaKey"),
            _field_value(media_obj, "fileLength", "FileLength"),
            _field_value(media_obj, "mimetype", "mimeType", "Mimetype", "MimeType"),
            _field_value(media_obj, "fileSha256", "FileSha256", "fileSHA256", "FileSHA256"),
            _field_value(media_obj, "fileEncSha256", "FileEncSha256", "fileEncSHA256", "FileEncSHA256"),
            _field_value(media_obj, "jpegThumbnail", "JPEGThumbnail"),
            _field_value(media_obj, "fileName", "FileName"),
            _field_value(media_obj, "caption", "Caption"),
        ]
        return any(_signal_present(signal) for signal in payload_signals)

    def _parse_byte_size(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    media_items: list[dict[str, Any]] = []
    for field_names, kind in media_fields:
        media_obj = None
        for field_name in field_names:
            candidate = _get_path(message_obj, field_name)
            if candidate is not None:
                media_obj = candidate
                break

        normalized_media_obj = _to_jsonable(media_obj)

        if not _has_media_payload(normalized_media_obj):
            continue

        mime_type = _field_value(normalized_media_obj, "mimetype", "mimeType", "Mimetype", "MimeType")
        file_name = _field_value(normalized_media_obj, "fileName", "FileName")
        size = _field_value(normalized_media_obj, "fileLength", "FileLength")
        url = _field_value(normalized_media_obj, "url", "URL")
        media_key = _field_value(normalized_media_obj, "mediaKey", "MediaKey")

        provider_media_id = (
            str(media_key) if not _is_empty_value(media_key) else f"{provider_message_id}:{kind}"
        )

        media_items.append(
            {
                "provider_media_id": provider_media_id,
                "mime_type": str(mime_type) if mime_type else f"application/{kind}",
                "file_name": str(file_name) if file_name else None,
                "byte_size": _parse_byte_size(size),
                "download_url": str(url) if url else None,
            }
        )

    return media_items


def map_neonize_message_event(event: Any) -> dict[str, Any]:
    """Map a Neonize MessageEv object to the backend inbound contract.

    The full provider event is preserved in `raw_event` for durable storage.
    """

    info = _get_path(event, "Info")
    message = _get_path(event, "Message")

    provider_message_id = _get_path(info, "ID") or _get_path(info, "Id") or str(uuid4())
    chat = _get_path(info, "MessageSource", "Chat")
    sender = _get_path(info, "MessageSource", "Sender")

    provider_group_id = _jid_to_str(chat) or ""
    sender_provider_user_id = _jid_to_str(sender)

    timestamp = _get_path(info, "Timestamp")
    if isinstance(timestamp, datetime):
        occurred_at = timestamp.astimezone(UTC).isoformat()
    else:
        occurred_at = datetime.now(UTC).isoformat()

    event_type = _classify_event_type(message)
    if event_type == "message_deleted":
        deleted_target_id = _extract_deleted_target_message_id(message)
        if deleted_target_id:
            provider_message_id = deleted_target_id
    content_message = _resolve_message_content(message)
    reply_to, mentions = _extract_reply_and_mentions(content_message)

    payload = {
        "trace_id": str(uuid4()),
        "provider": "whatsapp-neonize",
        "provider_group_id": provider_group_id,
        "provider_message_id": str(provider_message_id),
        "sender_provider_user_id": sender_provider_user_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "message": {
            "text": _extract_text(content_message),
            "reply_to_provider_message_id": reply_to,
            "mentions": mentions,
            "media": _extract_media(content_message, str(provider_message_id)),
        },
        "raw_event": _to_jsonable(event),
    }

    return payload
