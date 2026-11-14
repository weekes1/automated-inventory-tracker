"""Shared business entities and separate literal source observations."""

from datetime import date as CalendarDate
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, JsonValue,
    StrictStr, model_validator,
)


class AcceptanceLevel(str, Enum):
    """Internal acceptance categories; assignment rules remain pending."""

    HIGH = "high"
    MED = "med"
    LOW = "low"


class InventoryRow(BaseModel):
    """The eight business fields, defined once regardless of input layout.

    Aliases define output headers/order. None represents an unresolved value,
    not export permission. Required-field and approval policies are separate.
    """

    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, frozen=True, allow_inf_nan=False
    )

    quantity: Decimal | None = Field(default=None, alias="Quantity")
    price: Decimal | None = Field(default=None, alias="Price")
    description: StrictStr | None = Field(default=None, alias="Description")
    person_name: StrictStr | None = Field(default=None, alias="Person name")
    job_site: StrictStr | None = Field(default=None, alias="Job site")
    job_name: StrictStr | None = Field(default=None, alias="Job name")
    job_number: StrictStr | None = Field(default=None, alias="Job #")
    date: CalendarDate | None = Field(default=None, alias="Date")

    def to_output_dict(self) -> dict[str, object]:
        """Project only business fields, even on a processing subclass.

        Retains Decimal/date values for future CSV/XLSX writers. Does not
        enforce approval, format values, or escape spreadsheet text.
        """
        return {
            field.alias or name: getattr(self, name)
            for name, field in InventoryRow.model_fields.items()
        }


OUTPUT_COLUMNS: tuple[str, ...] = tuple(
    field.alias or name for name, field in InventoryRow.model_fields.items()
)


def _known_field_name(value: str) -> str:
    if value not in InventoryRow.model_fields:
        raise ValueError(f"Unknown inventory field: {value}")
    return value


InventoryFieldName = Annotated[StrictStr, AfterValidator(_known_field_name)]


class SourceReference(BaseModel):
    """Where an inherited value came from; no row number means a page header.

    Field names are Python names from InventoryRow, such as 'job_number'.
    References are evidence pointers; the resolver must verify their targets.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: StrictStr = Field(min_length=1)
    page_number: int = Field(gt=0, strict=True)
    row_number: int | None = Field(default=None, gt=0, strict=True)
    field_name: InventoryFieldName


class FieldInference(str, Enum):
    """Interpretations of visible evidence that require later review."""

    BLANK_AS_DITTO = "blank_as_ditto"


class SourceField(BaseModel):
    """Literal LLM observation, with uncertainty and optional inheritance hint.

    raw_text preserves visible marks; use None for unreadable text. An
    inherited_from reference is a model suggestion until verified by rules.
    notes hold short evidence-based explanations, not internal reasoning.
    A blank_as_ditto inference preserves the blank observation and requires
    uncertainty plus an evidence note; it never supplies a copied value.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_text: StrictStr | None
    kind: Literal["text", "blank", "ditto", "illegible"]
    uncertain: bool = False
    inference: FieldInference | None = None
    inherited_from: SourceReference | None = None
    notes: list[StrictStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_inference(self) -> "SourceField":
        if self.inference == FieldInference.BLANK_AS_DITTO:
            if self.kind != "blank" or self.raw_text != "":
                raise ValueError("blank_as_ditto must preserve a visibly blank cell")
            if not self.uncertain or not any(note.strip() for note in self.notes):
                raise ValueError("blank_as_ditto requires uncertainty and an evidence note")
        return self


class SourceRow(BaseModel):
    """One candidate row on a source page, including cancelled/uncertain rows.

    row_id is assigned by the application. row_number is one-based visual
    order across the page, including rows retained for cancellation review.
    Missing dictionary keys mean fields not observed, never inherited values.
    highlighted/crossed_out describe visible marks, not approval/cancellation.
    None means unclear or not assessed, including older extraction records.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    row_id: StrictStr = Field(min_length=1)
    row_number: int = Field(gt=0, strict=True)
    fields: dict[InventoryFieldName, SourceField] = Field(default_factory=dict)
    cancellation: Literal["active", "cancelled", "uncertain"] = "active"
    marked: bool | None = None
    highlighted: bool | None = None
    crossed_out: bool | None = None
    uncertain: bool = False
    notes: list[StrictStr] = Field(default_factory=list)


class SourcePage(BaseModel):
    """Page evidence and extracted candidates; does not certify completeness.

    rows keep visual order. Header values can supply context for multiple
    rows without pretending those values were written in each row.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: StrictStr = Field(min_length=1)
    page_number: int = Field(gt=0, strict=True)
    header_fields: dict[InventoryFieldName, SourceField] = Field(default_factory=dict)
    rows: list[SourceRow] = Field(default_factory=list)
    layout_notes: list[StrictStr] = Field(default_factory=list)
    notes: list[StrictStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_row_identity_and_order(self) -> "SourcePage":
        ids = [row.row_id for row in self.rows]
        numbers = [row.row_number for row in self.rows]
        if len(ids) != len(set(ids)):
            raise ValueError("Source row IDs must be unique within a page")
        if numbers != sorted(set(numbers)):
            raise ValueError("Source row numbers must be unique and in visual order")
        return self


class ProcessingRow(InventoryRow):
    """Internal entity with acceptance level, separate from human approval.

    None means unassigned, not a fourth category. No rules exist yet.
    model_dump() retains acceptance and provenance for storage; use the output
    projection methods at the eventual export boundary.
    """

    acceptance_level: AcceptanceLevel | None = None
    source_row_id: StrictStr | None = Field(default=None, min_length=1)
    inherited_fields: dict[InventoryFieldName, SourceReference] = Field(default_factory=dict)

    def to_output_row(self) -> InventoryRow:
        """Remove processing fields without duplicating the business schema."""
        return InventoryRow.model_validate(self.to_output_dict())


class ResolvedRow(BaseModel):
    """Intermediary text values before numeric/date normalization or approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_row_id: StrictStr
    row_number: int
    values: dict[InventoryFieldName, StrictStr | None]
    inherited_fields: dict[InventoryFieldName, SourceReference] = Field(default_factory=dict)
    inheritance_reasons: dict[InventoryFieldName, StrictStr] = Field(default_factory=dict)
    unresolved_fields: dict[InventoryFieldName, StrictStr] = Field(default_factory=dict)


class ResolvedPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: StrictStr
    page_number: int
    resolver_version: StrictStr
    rows: list[ResolvedRow]


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ValidatedRow(ResolvedRow):
    """Unreviewed resolved values with deterministic risk, not acceptance."""

    risk: RiskLevel
    risk_reason: StrictStr


class ValidatedPage(ResolvedPage):
    validator_version: StrictStr
    rows: list[ValidatedRow]


class RunConfig(BaseModel):
    """Effective non-secret configuration for one extraction request/attempt.

    Record all explicitly sent model options (including image detail) and all
    rendering/cropping settings. Do not include credentials or environment dumps.
    code_version identifies a commit/build when available; None means unknown.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    provider: StrictStr = Field(min_length=1)
    model: StrictStr = Field(min_length=1)
    prompt_version: StrictStr = Field(min_length=1)
    rules_version: StrictStr = Field(min_length=1)
    schema_version: StrictStr = Field(min_length=1)
    model_settings: dict[str, JsonValue] = Field(default_factory=dict)
    preprocessing: dict[str, JsonValue] = Field(default_factory=dict)
    code_version: StrictStr | None = None


class RunArtifact(BaseModel):
    """A saved file, addressed relative to its run directory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: StrictStr
    sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    original_name: StrictStr | None = None


class ResolutionArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resolved_at: AwareDatetime
    source_page_sha256: StrictStr
    rules: RunArtifact
    rows: RunArtifact
    csv: RunArtifact


class ValidationArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    validated_at: AwareDatetime
    source_page_sha256: StrictStr
    resolution_rows_sha256: StrictStr
    rules: RunArtifact
    rows: RunArtifact
    csv: RunArtifact


class ExtractionRun(BaseModel):
    """Application-owned audit record; never requested from the LLM."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: StrictStr
    document_id: StrictStr = Field(min_length=1)
    page_number: int = Field(gt=0, strict=True)
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    status: Literal["running", "succeeded", "failed"] = "running"
    config: RunConfig
    inputs: list[RunArtifact] = Field(min_length=1)
    prompt: RunArtifact
    rules: RunArtifact
    response_schema: RunArtifact
    raw_response: RunArtifact | None = None
    extracted_page: RunArtifact | None = None
    preview_csv: RunArtifact | None = None
    resolution: ResolutionArtifacts | None = None
    validation: ValidationArtifacts | None = None
    returned_model: StrictStr | None = None
    provider_request_id: StrictStr | None = None
    usage: dict[str, JsonValue] = Field(default_factory=dict)
    error: StrictStr | None = None

    @model_validator(mode="after")
    def check_outcome(self) -> "ExtractionRun":
        if self.status == "running":
            if self.finished_at is not None or self.error is not None:
                raise ValueError("A running extraction cannot have a final outcome")
        else:
            if self.finished_at is None or self.finished_at < self.started_at:
                raise ValueError("Finished runs need a valid completion timestamp")
            if self.status == "succeeded" and (
                self.error is not None or self.raw_response is None or self.extracted_page is None
            ):
                raise ValueError("Success requires raw and validated results without an error")
            if self.status == "failed" and not self.error:
                raise ValueError("Failed runs need an error explanation")
        return self
