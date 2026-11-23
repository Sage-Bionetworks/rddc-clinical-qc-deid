# FHIR QC and identifier screening

`screen_fhir` checks incoming FHIR R4 files for identifiers before de-identification or
conversion to OMOP. It checks file structure before screening, reports findings and leaves the data unchanged.

## Inputs

| Parameter | Description |
| --- | --- |
| `--sidecar` | Required. The batch's `_sidecar.json`, which lists its files. The workflow screens every FHIR file listed, including NDJSON (plain or gzipped), Bundles and single resources. On Cirro, the preprocessing script finds the sidecar in the input dataset. |
| `--provider_policy` | How to handle clinician and site identity. `stop` (default) treats names and identifiers in Practitioner, PractitionerRole, Organization, Location and references to them as direct identifiers. `review` reports those findings for a curator. Choose the policy for each source. |
| `--outdir` | Required. Directory for the reports. Cirro supplies this path. |

## Structural QC

After intake, every selected file must pass these checks before any file is screened:

- Readable JSON in NDJSON, gzip, Bundle or single-resource files.
- Resource objects with a non-empty, correctly shaped `resourceType` string.
- Array structure for `contained` resources and Bundle entries. Each Bundle entry
  must contain a resource; transaction-only entries are not supported.
- Empty files and malformed records fail QC. Empty Bundles are allowed.

A failure stops the workflow and leaves `qc/qc.tsv` for review. It does not produce a
passing screening result. The QC report includes file IDs, status, record counts and
fixed error codes; it omits source values and exception text. A failed file's count is
zero because its total is unknown.

## Outputs

| File | Content |
| --- | --- |
| `qc/qc.tsv` | One row per selected file: `file`, `status`, `records`, `error` and `record`. Screening starts only if every status is `pass`. |
| `results.json` | A list of `{file, properties}` objects. `file` is the sidecar `@id`; `properties` lists any of `direct_identifiers`, `dates`, `zip_codes` and `free_text` found in that file. The dispatcher records these properties on the workflow step. |
| `findings.tsv` | File, resource type, element path, rule, detector, action, match count and first record number. Matched values are omitted. |
| `summary.tsv` | One row per file with its record count, verdict (`quarantine` or `pass`) and property flags. |
| `intake/intake.tsv` | Each sidecar entry and its intake outcome: screened, skipped because it is not FHIR, or rejected with a reason. |

A `direct_identifiers` result tells the orchestrator to quarantine the whole batch.
A `pass` verdict means no direct identifiers were found under the screen's rules;
other findings may still need attention. Findings marked `review` appear in
`findings.tsv` but do not add a property or trigger quarantine on their own.

Finding an identifier does not fail the run: the finding is recorded in the reports.
A FHIR file that fails intake, such as a file with a checksum mismatch or a path outside
the batch, does fail the run because it could not be screened.

## Checks

The [FHIR rules](../../containers/rddc-fhir-screen/src/rddc_fhir_screen/rules.yaml)
come from section 4.2 of `rddc-source-map/qc_deid_inventory.md`.
Element rules, which name fields of particular resources, are FHIRPath (R4) expressions,
so the same paths can drive de-identification. Checks that apply to every value, such as
patterns, dates, reference display text and extensions, walk each resource directly.

In the table below, `stop` flags a direct identifier. “Provider policy” uses
`--provider_policy`. The other actions flag data for later work.

| Data checked | Action |
| --- | --- |
| Patient names, contact details, address lines/city/district/text/extensions, identifiers, photos, contacts and links | `stop` |
| RelatedPerson and FamilyMemberHistory names, contact details, address lines/city/district/text, identifiers and photos | `stop` |
| Device `udiCarrier`, `serialNumber` and `distinctIdentifier` | `stop` |
| Practitioner, PractitionerRole, Organization and Location names, aliases, identifiers, contact details, addresses, positions and photos | Provider policy |
| `Reference.display` pointing to Patient, RelatedPerson or Person | `stop` |
| `Reference.display` pointing to a clinician or site; conditional references such as `Practitioner?identifier=…` | Provider policy |
| Other `Reference.display` values | `free_text` |
| Mother's maiden name, birthplace and geolocation extensions | `stop` |
| Unknown extensions containing a string, name, address, contact or identifier value | `review` |
| String patterns: SSN, phone, email, URL outside the allowed hosts, IPv4 address or labelled medical record number (MRN) | `stop` |
| Narrative (`text.div`), notes, `valueString`, `code.text` and other configured prose fields | `free_text` |
| Full dates outside `meta` | `dates` |
| `postalCode` | `zip_codes` |
| Attachments: DocumentReference content, `DiagnosticReport.presentedForm`, `Media.content`, `Binary.data`, Communication payloads, QuestionnaireResponse answers and extensions | `review` |

Pattern checks skip fields listed in `patterns.skip_keys`, such as codes, systems and
reference URLs. Reference display text is handled by the reference checks above.

## Limits

Structural QC is not full FHIR R4 or US Core profile validation. Reference and terminology checks remain planned.

Pattern detectors recognize fixed formats such as phone numbers. They do not recognize
names, places or dates written in prose. Free text is flagged for `deid_fhir` and
`confirm_deid_text`. Attachments need separate extraction and handling by content type.
UK-specific identifiers, including NHS numbers and postcodes, are not covered yet.
