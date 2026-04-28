from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from kuuna_backend.api.deps import get_db
from kuuna_backend.db.models import (
    AgentInstance,
    AuditEvent,
    GroupAssignment,
    GroupBinding,
    GroupTemplate,
    KnowledgeCommonDoc,
    ToolCatalogEntry,
    KnowledgeGroupDoc,
    KnowledgeVersion,
    MediaAsset,
    Message,
    MessageVersion,
    OutboundIntent,
    Role,
    RuntimeRun,
    TemplateBuild,
    TemplateVersion,
    Transcript,
    User,
    UserRole,
)
from kuuna_backend.main import create_app


@pytest.fixture
def test_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    User.__table__.create(bind=engine)
    Role.__table__.create(bind=engine)
    UserRole.__table__.create(bind=engine)
    GroupAssignment.__table__.create(bind=engine)
    AuditEvent.__table__.create(bind=engine)

    GroupTemplate.__table__.create(bind=engine)
    ToolCatalogEntry.__table__.create(bind=engine)
    TemplateVersion.__table__.create(bind=engine)
    TemplateBuild.__table__.create(bind=engine)
    RuntimeRun.__table__.create(bind=engine)
    GroupBinding.__table__.create(bind=engine)
    AgentInstance.__table__.create(bind=engine)

    Message.__table__.create(bind=engine)
    MessageVersion.__table__.create(bind=engine)
    MediaAsset.__table__.create(bind=engine)
    Transcript.__table__.create(bind=engine)
    KnowledgeCommonDoc.__table__.create(bind=engine)
    KnowledgeGroupDoc.__table__.create(bind=engine)
    KnowledgeVersion.__table__.create(bind=engine)
    OutboundIntent.__table__.create(bind=engine)

    return sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


@pytest.fixture
def client(test_session_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        db = test_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
