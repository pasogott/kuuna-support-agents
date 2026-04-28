from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from kuuna_backend.db.base import Base, TimestampMixin


class RoleName(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class TemplateVersionStatus(str, enum.Enum):
    DRAFT = "draft"
    READY = "ready"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class BindingStatus(str, enum.Enum):
    DRAFT = "draft"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"


class RuntimeMode(str, enum.Enum):
    ON_DEMAND = "on_demand"
    HOT = "hot"


class RuntimeStatus(str, enum.Enum):
    PROVISIONING = "provisioning"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STOPPED = "stopped"


class MessageEventType(str, enum.Enum):
    CREATED = "message_created"
    EDITED = "message_edited"
    DELETED = "message_deleted"


class MediaStatus(str, enum.Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class KnowledgeScope(str, enum.Enum):
    COMMON = "common"
    GROUP = "group"


class OutboundStatus(str, enum.Enum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


class ToolRiskClass(str, enum.Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class TemplateBuildStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RuntimeRunStatus(str, enum.Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"


def db_enum(enum_cls: type[enum.Enum], *, name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        values_callable=lambda members: [member.value for member in members],
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[RoleName] = mapped_column(db_enum(RoleName, name="role_name"), nullable=False, unique=True)


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_id_role_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )


class GroupAssignment(Base, TimestampMixin):
    __tablename__ = "group_assignments"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider_group_id",
            name="uq_group_assignments_user_id_provider_group_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider_group_id: Mapped[str] = mapped_column(String(255), nullable=False)


class GroupTemplate(Base, TimestampMixin):
    __tablename__ = "group_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)


class ToolCatalogEntry(Base, TimestampMixin):
    __tablename__ = "tool_catalog_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tool_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    risk_class: Mapped[ToolRiskClass] = mapped_column(
        db_enum(ToolRiskClass, name="tool_risk_class"),
        nullable=False,
        default=ToolRiskClass.READ,
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="runtime")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TemplateVersion(Base, TimestampMixin):
    __tablename__ = "template_versions"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "version_no",
            name="uq_template_versions_template_id_version_no",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("group_templates.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[TemplateVersionStatus] = mapped_column(
        db_enum(TemplateVersionStatus, name="template_version_status"),
        nullable=False,
        default=TemplateVersionStatus.DRAFT,
    )
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    tools_config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    egress_policy: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class TemplateBuild(Base, TimestampMixin):
    __tablename__ = "template_builds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("group_templates.id", ondelete="CASCADE"), nullable=False
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("template_versions.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[TemplateBuildStatus] = mapped_column(
        db_enum(TemplateBuildStatus, name="template_build_status"),
        nullable=False,
        default=TemplateBuildStatus.QUEUED,
    )
    image_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    build_inputs: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    logs_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class RuntimeRun(Base, TimestampMixin):
    __tablename__ = "runtime_runs"
    __table_args__ = (
        Index("ix_runtime_runs_provider_group_id_started_at", "provider_group_id", "started_at"),
        Index("ix_runtime_runs_message_id_started_at", "message_id", "started_at"),
        Index("ix_runtime_runs_binding_id_started_at", "binding_id", "started_at"),
        Index(
            "ix_runtime_runs_template_version_id_started_at",
            "template_version_id",
            "started_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_group_id: Mapped[str] = mapped_column(String(255), nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    binding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("group_bindings.id", ondelete="CASCADE"), nullable=False
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("template_versions.id", ondelete="RESTRICT"), nullable=False
    )
    template_build_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("template_builds.id", ondelete="SET NULL"), nullable=True
    )
    image_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[RuntimeRunStatus] = mapped_column(
        db_enum(RuntimeRunStatus, name="runtime_run_status"),
        nullable=False,
        default=RuntimeRunStatus.STARTED,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    execution: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class GroupBinding(Base, TimestampMixin):
    __tablename__ = "group_bindings"
    __table_args__ = (
        Index(
            "uq_group_bindings_provider_group_id_active",
            "provider_group_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_group_id: Mapped[str] = mapped_column(String(255), nullable=False)
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("template_versions.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[BindingStatus] = mapped_column(
        db_enum(BindingStatus, name="binding_status"), nullable=False, default=BindingStatus.DRAFT
    )


class AgentInstance(Base, TimestampMixin):
    __tablename__ = "agent_instances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_binding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("group_bindings.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    runtime_mode: Mapped[RuntimeMode] = mapped_column(
        db_enum(RuntimeMode, name="runtime_mode"), nullable=False, default=RuntimeMode.ON_DEMAND
    )
    status: Mapped[RuntimeStatus] = mapped_column(
        db_enum(RuntimeStatus, name="runtime_status"),
        nullable=False,
        default=RuntimeStatus.PROVISIONING,
    )


class Message(Base, TimestampMixin):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "provider_group_id",
            "provider_message_id",
            name="uq_messages_provider_group_id_provider_message_id",
        ),
        Index("ix_messages_provider_group_id_created_at", "provider_group_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_group_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_provider_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latest_version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class MessageVersion(Base):
    __tablename__ = "message_versions"
    __table_args__ = (
        UniqueConstraint(
            "message_id", "version_no", name="uq_message_versions_message_id_version_no"
        ),
        Index("ix_message_versions_message_id_version_no", "message_id", "version_no"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[MessageEventType] = mapped_column(
        db_enum(MessageEventType, name="message_event_type"), nullable=False
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_event: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MediaAsset(Base, TimestampMixin):
    __tablename__ = "media_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    provider_media_id: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[MediaStatus] = mapped_column(
        db_enum(MediaStatus, name="media_status"), nullable=False, default=MediaStatus.PENDING
    )
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class Transcript(Base, TimestampMixin):
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    media_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[MediaStatus] = mapped_column(
        db_enum(MediaStatus, name="transcript_status"), nullable=False, default=MediaStatus.PENDING
    )


class KnowledgeCommonDoc(Base, TimestampMixin):
    __tablename__ = "knowledge_common_docs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)


class KnowledgeGroupDoc(Base, TimestampMixin):
    __tablename__ = "knowledge_group_docs"
    __table_args__ = (
        UniqueConstraint(
            "provider_group_id", "doc_key", name="uq_knowledge_group_docs_provider_group_id_doc_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_group_id: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_key: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)


class KnowledgeVersion(Base, TimestampMixin):
    __tablename__ = "knowledge_versions"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "doc_ref_id",
            "version_no",
            name="uq_knowledge_versions_scope_doc_ref_id_version_no",
        ),
        Index("ix_knowledge_versions_status_scope", "status", "scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[KnowledgeScope] = mapped_column(
        db_enum(KnowledgeScope, name="knowledge_scope"), nullable=False
    )
    doc_ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[TemplateVersionStatus] = mapped_column(
        db_enum(TemplateVersionStatus, name="knowledge_version_status"),
        nullable=False,
        default=TemplateVersionStatus.DRAFT,
    )
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)


class Embedding(Base, TimestampMixin):
    __tablename__ = "embeddings"
    __table_args__ = (Index("ix_embeddings_source_version_chunk", "source_version_id", "chunk_no"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[KnowledgeScope] = mapped_column(
        db_enum(KnowledgeScope, name="embedding_scope"), nullable=False
    )
    source_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_versions.id", ondelete="CASCADE"), nullable=False
    )
    chunk_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)


class OutboundIntent(Base, TimestampMixin):
    __tablename__ = "outbound_intents"
    __table_args__ = (
        UniqueConstraint("outbound_intent_id", name="uq_outbound_intents_outbound_intent_id"),
        Index("ix_outbound_intents_provider_group_id_created_at", "provider_group_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outbound_intent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider_group_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[OutboundStatus] = mapped_column(
        db_enum(OutboundStatus, name="outbound_status"), nullable=False, default=OutboundStatus.PENDING
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
