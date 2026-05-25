from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

DIMENSION_SLUGS = ("pdlc", "ssc_ops", "customer_jv")
DIMENSION_LABELS = {
    "pdlc": "PDLC (Products & Tech)",
    "ssc_ops": "SSC Operations & RM",
    "customer_jv": "Customer / JV",
}


class Workspace(Base):
    __tablename__ = "workspace"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="Global Payments SSC")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    roles: Mapped[list[Role]] = relationship(back_populates="workspace")
    dimensions: Mapped[list[Dimension]] = relationship(back_populates="workspace")
    processes: Mapped[list[Process]] = relationship(back_populates="workspace")
    documents: Mapped[list[Document]] = relationship(back_populates="workspace")


class Role(Base):
    __tablename__ = "role"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"))
    name: Mapped[str] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(200))
    fte: Mapped[float | None] = mapped_column(Float)
    hris_external_id: Mapped[str | None] = mapped_column(String(100))
    in_hris: Mapped[bool] = mapped_column(default=True)

    workspace: Mapped[Workspace] = relationship(back_populates="roles")
    assignments: Mapped[list[ActivityRole]] = relationship(back_populates="role")


class Dimension(Base):
    __tablename__ = "dimension"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"))
    slug: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))

    workspace: Mapped[Workspace] = relationship(back_populates="dimensions")
    assignments: Mapped[list[ActivityRole]] = relationship(back_populates="dimension")

    __table_args__ = (UniqueConstraint("workspace_id", "slug", name="uq_dimension_slug"),)


class Process(Base):
    __tablename__ = "process"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"))
    domain: Mapped[str] = mapped_column(String(100), default="Finance")
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    owner_role_id: Mapped[int | None] = mapped_column(ForeignKey("role.id"), nullable=True)

    workspace: Mapped[Workspace] = relationship(back_populates="processes")
    activities: Mapped[list[Activity]] = relationship(back_populates="process", cascade="all, delete-orphan")
    owner: Mapped[Role | None] = relationship(foreign_keys=[owner_role_id])


class Activity(Base):
    __tablename__ = "activity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("process.id"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    inputs: Mapped[str | None] = mapped_column(Text)
    outputs: Mapped[str | None] = mapped_column(Text)
    systems: Mapped[str | None] = mapped_column(Text)
    sla: Mapped[str | None] = mapped_column(String(100))
    frequency: Mapped[str | None] = mapped_column(String(100))
    is_start: Mapped[bool] = mapped_column(default=False)
    predecessor_ids: Mapped[str | None] = mapped_column(String(500))

    process: Mapped[Process] = relationship(back_populates="activities")
    assignments: Mapped[list[ActivityRole]] = relationship(back_populates="activity", cascade="all, delete-orphan")


class ActivityRole(Base):
    __tablename__ = "activity_role"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activity.id"))
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"))
    dimension_id: Mapped[int] = mapped_column(ForeignKey("dimension.id"))
    letters: Mapped[str] = mapped_column(String(20), default="")

    activity: Mapped[Activity] = relationship(back_populates="assignments")
    role: Mapped[Role] = relationship(back_populates="assignments")
    dimension: Mapped[Dimension] = relationship(back_populates="assignments")

    __table_args__ = (
        UniqueConstraint("activity_id", "role_id", "dimension_id", name="uq_activity_role_dim"),
    )


class Document(Base):
    __tablename__ = "document"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"))
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    storage_path: Mapped[str] = mapped_column(String(500))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="uploaded")
    extraction_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    workspace: Mapped[Workspace] = relationship(back_populates="documents")
