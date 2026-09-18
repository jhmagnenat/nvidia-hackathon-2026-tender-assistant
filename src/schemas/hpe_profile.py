"""HPE provider profile — what we match tender requirements against.

Transparent and editable: see data/hpe_profile.json for the actual instance
used by the demo. Capabilities may be listed as generic/illustrative without
a citation (that's the point — they describe what HPE broadly offers as a
service provider). Certifications and references must NOT be fabricated:
leave the list empty (UNKNOWN) rather than invent one, unless a real
`citation` backs the entry.
"""

from datetime import date

from pydantic import BaseModel, Field

from src.schemas.common import Citation, Language


class Capability(BaseModel):
    name: str
    description: str | None = None
    citation: Citation | None = Field(default=None, description="Source backing this claim, if any")


class Certification(BaseModel):
    name: str
    issuer: str | None = None
    valid_until: date | None = None
    citation: Citation | None = Field(default=None, description="Required to assert this — never fabricate")


class Reference(BaseModel):
    client: str
    project_description: str
    year: int | None = None
    contract_value_chf: float | None = None
    location: str | None = None
    citation: Citation | None = Field(default=None, description="Required to assert this — never fabricate")


class HPEProfile(BaseModel):
    company_name: str = "Hewlett Packard Enterprise"
    capabilities: list[Capability] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    insurance_coverage_chf: float | None = None
    references: list[Reference] = Field(default_factory=list)
    annual_revenue_chf: float | None = None
    employee_count: int | None = None
    languages_supported: list[Language] = Field(default_factory=list)
    notes: str | None = None
