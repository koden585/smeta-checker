"""Public contracts for the Nuxt audit workspace."""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from audit_models import AuditStatus, ReportStatus, VorPosition


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("created_at", "finished_at", check_fields=False)
    @classmethod
    def _utc_datetimes(cls, value):
        # Contract datetimes are UTC (Z-suffixed); storage may carry any zone.
        if isinstance(value, datetime) and value.tzinfo is not None:
            return value.astimezone(timezone.utc)
        return value


class ProjectDTO(DTO):
    id: str
    name: str
    archived: bool = False
    created_at: datetime | None = None


class ProjectCreate(DTO):
    name: str = Field(min_length=1, max_length=256)




class ProjectUpdate(DTO):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    archived: bool | None = None


class MetadataSourceDTO(DTO):
    sheet: str = ""
    cell: str = ""
    raw: str = ""


class DocumentMetadataDTO(DTO):
    construction_title: str = ""
    raw_title: str = ""
    document_code: str = ""
    pd_reference: str = ""
    sources: dict[str, MetadataSourceDTO] = Field(default_factory=dict)
    extractor_version: str = ""


class VersionDTO(DTO):
    id: str
    project_id: str
    document_id: str
    filename: str
    kind: Literal["vor", "pdf"]
    number: int
    sha256: str
    size: int
    created_at: datetime
    metadata: DocumentMetadataDTO
    metadata_overrides: dict[str, str]
    format_status: dict[str, Any] = Field(default_factory=dict)
    title: str = ""


class RunDTO(DTO):
    run_id: str
    project_id: str
    vor_version_id: str
    vor_filename: str
    status: Literal["running", "done", "failed", "cancelled"]
    stage: Literal["preparing", "auditing", "finalizing", "done", "failed"]
    total: int | None
    done: int
    failed: int
    running: int
    queued: int
    created_at: datetime | None
    finished_at: datetime | None
    preparation_done: int = 0
    preparation_total: int | None = None


class DocumentDTO(DTO):
    id: str
    project_id: str
    kind: Literal["vor", "pdf"]
    title: str
    archived: bool = False
    current_version_id: str | None = None
    versions: list[VersionDTO]
    last_run: RunDTO | None = None
    pd_updated: bool = False


class DocumentPatch(DTO):
    title: str | None = Field(default=None, max_length=2048)
    archived: bool | None = None
    current_version_id: str | None = None


class VersionMetadataPatch(DTO):
    fields: dict[str, str] = Field(default_factory=dict)


class VersionDeletedDTO(DTO):
    deleted: bool


class ResultDTO(DTO):
    id: str
    position_index: int
    number: str
    name: str
    unit: str
    declared_quantity: str
    found_quantity: str | None
    found_unit: str | None
    formula: str
    sheet: str
    source_row: int | None
    cells: dict[str, str]
    audit_status: AuditStatus
    report_status: ReportStatus
    queue: Literal["fix", "review", "missing", "ok"]
    problem: str
    action: str
    work_found: bool
    volume_confirmed: bool
    unit_confirmed: bool
    comment_confirmed: bool
    details: str


class RowsDTO(DTO):
    run_id: str
    total: int
    offset: int
    limit: int
    rows: list[ResultDTO]


class SummaryDTO(DTO):
    run: RunDTO
    project: ProjectDTO
    queues: dict[str, int]
    documents: list[VersionDTO]


class HighlightDTO(DTO):
    bbox: list[float]
    kind: str
    text: str


class PdfRegionDTO(DTO):
    width: float
    height: float
    highlights: list[HighlightDTO]
    reason: str


class EvidenceDTO(DTO):
    version_id: str
    filename: str
    page: int
    quote: str
    kind: str
    region: PdfRegionDTO | None
    confirmed: bool


class ExcelCellDTO(DTO):
    coordinate: str
    value: str
    column_span: int = 1
    row_span: int = 1
    highlight: bool = False


class ExcelRowDTO(DTO):
    number: int
    selected: bool
    cells: list[ExcelCellDTO]


class ExcelDTO(DTO):
    sheet: str
    columns: list[str]
    rows: list[ExcelRowDTO]


class WorkspaceDTO(DTO):
    row: ResultDTO
    position: VorPosition
    vor_version_id: str
    excel: ExcelDTO | None
    evidence: list[EvidenceDTO]


class StructureNodeDTO(DTO):
    model_config = ConfigDict(extra="ignore")
    id: str
    parent_id: str
    title: str
    kind: Literal["section", "appendix", "table"]
    number: str | None
    level: int
    physical_start: int
    physical_end: int
    start_bbox: list[float]
    children: list[str]
    confidence: Literal["high", "medium"]
    sources: list[str]


class StructurePageDTO(DTO):
    model_config = ConfigDict(extra="ignore")
    physical_page: int
    printed_page: str | None
    width: float
    height: float
    node_ids: list[str]


class StructureDTO(DTO):
    model_config = ConfigDict(extra="ignore")
    sha256: str
    page_count: int
    roots: list[str]
    nodes: list[StructureNodeDTO]
    pages: list[StructurePageDTO]
    quantity_confirmation: Literal[False] = False
    ocr_dispatched: Literal[False] = False


class FormatIssueDTO(DTO):
    coord: str
    type: str
    expected: str
    actual: str
    status: str
    error: str
    group: str = ""
    group_title: str = ""
    group_hint: str = ""


class FormatDTO(DTO):
    version_id: str
    sheet: str = ""
    sheets: list[str] = Field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    issues: list[FormatIssueDTO]


class NoteDTO(DTO):
    id: str
    page: int
    rect: list[float]
    text: str
    deleted: bool
    position_id: str
