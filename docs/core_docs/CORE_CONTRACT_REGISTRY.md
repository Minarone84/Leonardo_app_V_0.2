# Core Contract Registry

The Core contract registry owns in-memory contract registration, lookup,
payload validation, listing, and compatibility reporting for Leonardo V2.

The registry exposes:

- `register_contract(...)`;
- `get_contract(...)`;
- `list_contracts(...)`;
- `validate_payload(...)`;
- `compatibility_report(...)`.

Registration is keyed by `contract_id` and `version`. Duplicate registration is
rejected with `ValueError`; replacement mode is not implemented in this phase.

Payload validation checks:

- whether the requested contract is registered;
- whether the payload is a mapping;
- whether required fields are present;
- whether payload field names are strings;
- whether payload fields are undeclared by the contract.

Unknown contracts produce a structured validation report with a blocking issue.
Missing required fields produce structured validation errors. Unknown payload
fields are reported as structured warnings.

The registry has no global instance and performs no import-time registration.
It does not load contracts from the filesystem, discover plugins, start runtime
services, import GUI code, import Data Manager code, import financial tools, or
copy old Leonardo source.
