"""Configurable deterministic row risk. Risk never grants human approval."""

import argparse
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas import InventoryFieldName, InventoryRow, ResolvedPage, RiskLevel, SourcePage, ValidatedPage, ValidatedRow


DEFAULT_RULES = Path(__file__).resolve().parent / "config/validator_v001.json"


class ValidatorRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    missing_fields_medium: list[InventoryFieldName]
    inherited_fields_medium: list[InventoryFieldName]
    max_inherited_fields: int = Field(ge=0, strict=True)
    high_risk_flags: list[Literal["marked", "crossed_out", "highlighted", "cancelled"]]


def validate_page(source: SourcePage, resolved: ResolvedPage,
                  rules: ValidatorRules | None = None) -> ValidatedPage:
    """Assess missing values after resolution and use source visual evidence."""
    rules = rules or ValidatorRules.model_validate_json(DEFAULT_RULES.read_bytes())
    if source.document_id != resolved.document_id or source.page_number != resolved.page_number:
        raise ValueError("Source and resolved pages must refer to the same document/page")
    if [(row.row_id, row.row_number) for row in source.rows] != [
        (row.source_row_id, row.row_number) for row in resolved.rows
    ]:
        raise ValueError("Source and resolved row identities/order do not match")
    labels = {name: field.alias or name for name, field in InventoryRow.model_fields.items()}
    high_labels = {
        "marked": "Row has visual review/correction marks",
        "crossed_out": "Row is drawn across or crossed out",
        "highlighted": "Row is highlighted",
        "cancelled": "Row is marked cancelled",
    }
    rows = []
    for original, row in zip(source.rows, resolved.rows):
        high = [high_labels[flag] for flag in rules.high_risk_flags
                if (original.cancellation == "cancelled" if flag == "cancelled"
                    else getattr(original, flag) is True)]
        medium = [f"Missing {labels[name]}" for name in rules.missing_fields_medium
                  if not (row.values.get(name) or "").strip()]
        medium.extend(f"{labels[name]} was inherited" for name in rules.inherited_fields_medium
                      if name in row.inherited_fields)
        if len(row.inherited_fields) > rules.max_inherited_fields:
            medium.append(f"{len(row.inherited_fields)} fields inherited (more than {rules.max_inherited_fields})")
        risk = RiskLevel.HIGH if high else RiskLevel.MEDIUM if medium else RiskLevel.LOW
        reason = "; ".join(high + medium) or "No configured risk rule matched"
        if any(getattr(original, flag) is None for flag in rules.high_risk_flags if flag != "cancelled"):
            reason += "; visual marking assessment is incomplete"
        rows.append(ValidatedRow(**row.model_dump(), risk=risk, risk_reason=reason))
    return ValidatedPage(**resolved.model_dump(exclude={"rows"}),
                         validator_version=rules.version, rows=rows)


def main() -> None:
    from runs import add_validation, load_run

    parser = argparse.ArgumentParser(description="Assign row risk to saved runs without model calls.")
    parser.add_argument("path", type=Path, help="One run directory or its parent runs directory")
    args = parser.parse_args()
    directories = ([args.path] if (args.path / "manifest.json").is_file()
                   else sorted(path.parent for path in args.path.glob("*/manifest.json")))
    if not directories:
        parser.error("No run manifests found")
    try:
        for directory in directories:
            if load_run(directory).status == "succeeded":
                print(add_validation(directory))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Validation failed: {exc}\n")


if __name__ == "__main__":
    main()
