"""Layout-independent normalized inventory entities, separate from raw evidence."""

from datetime import date as CalendarDate
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class AcceptanceLevel(str, Enum):
    """Provisional categories; business names and assignment rules are pending."""

    LEVEL_1 = "level_1"
    LEVEL_2 = "level_2"
    LEVEL_3 = "level_3"


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


class ProcessingRow(InventoryRow):
    """Internal entity with acceptance level, separate from human approval.

    None means unassigned, not a fourth category. No rules exist yet.
    model_dump() retains acceptance_level for storage; use the output
    projection methods at the eventual export boundary.
    """

    acceptance_level: AcceptanceLevel | None = None

    def to_output_row(self) -> InventoryRow:
        """Remove processing fields without duplicating the business schema."""
        return InventoryRow.model_validate(self.to_output_dict())
