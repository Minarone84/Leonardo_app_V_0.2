# Contract Kernel

The Leonardo V2 contract kernel defines the importable value models used to
describe contracts, payload validation results, and compatibility reports.

The kernel is intentionally small in this phase. It provides:

- contract lifecycle status values;
- owner and schema-kind categories;
- immutable contract descriptors;
- structured validation issues and reports;
- structured compatibility reports.

Every `ContractDescriptor` includes:

- `contract_id`;
- `version`;
- `owner`;
- `status`;
- `schema_kind`;
- explicit `required_fields`;
- explicit `optional_fields`.

Validation results are represented by `ContractValidationReport`. The report
contains structured `ContractValidationIssue` entries and exposes a computed
`valid` property. Missing required fields are blocking validation errors.
Warnings, such as unknown declared-field warnings, remain structured without
making the report invalid.

Compatibility results are represented by `ContractCompatibilityReport`.
Compatibility compares a candidate descriptor against a registered base
descriptor. The first phase uses conservative field-surface compatibility:
required fields and existing optional fields must remain stable, while adding
optional fields is backward compatible.

The kernel does not provide runtime startup, persistence, GUI behavior, dynamic
loading, plugin discovery, Data Manager behavior, financial-tool behavior, or
old-code reuse.
