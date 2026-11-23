# FHIR QC and identifier screening

`screen_fhir` checks incoming FHIR R4 files for identifiers before de-identification or
conversion to OMOP. It checks file structure before screening, reports findings and leaves the data unchanged.

## Inputs

| Parameter | Description |
| --- | --- |
| `--sidecar` | Required. The batch's `_sidecar.json`, which lists its files. The workflow screens every FHIR file listed, including NDJSON (plain or gzipped), Bundles and single resources. On Cirro, the preprocessing script finds the sidecar in the input dataset. |
| `--provider_policy` | How to handle clinician and site identity. `stop` (default) treats names and identifiers in Practitioner, PractitionerRole, Organization, Location and references to them as direct identifiers. `review` reports those findings for a curator. Choose the policy for each source. |
| `--source_config` | Optional. A directory with the source's `fhir_screen.yaml`. By default the workflow uses `assets/sources/<sourceId>/` for the sidecar's `sourceId`, if it exists. |
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
come from section 4.2 of RDDC's QC and de-identification inventory, an internal planning document.
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
| Resource ids of Patient, RelatedPerson and Person | `stop` |
| Identifiers on all other resources, such as visit, accession, order and claim numbers; Medication and Substance product codes are not checked | `stop` |
| Resource ids of Practitioner and PractitionerRole | Provider policy |
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

Resource ids and the identifiers on other resources pass when they are opaque (a UUID,
set by `opaque_ids` in the rules) or a pseudonym the source confirmed. Opaque values appear
in `findings.tsv` with action `opaque`. A source that uses MRNs as resource ids, or real
visit numbers, is stopped.

Pattern checks skip fields listed in `patterns.skip_keys`, such as codes, systems and
reference URLs, and elements whose R4 type is `canonical`, such as `meta.profile` and
`QuestionnaireResponse.questionnaire`. A canonical names a definition, not a person.
Reference display text is handled by the reference checks above.

Definition resources are not screened: conformance and terminology resources, such as
StructureDefinition, ImplementationGuide, CodeSystem and ValueSet, and Questionnaire. They
describe data rather than hold it. `findings.tsv` counts them under rule
`definition_resource` with action `skipped`, and they do not affect the verdict. The full
list is `skip_resources` in the rules.

## Source configs

A source can confirm the pseudonyms it uses in place of identifiers and names, such as a
study ID in `Patient.identifier`, a placeholder name, a non-UUID resource id, or its own
visit and order numbers. It can also list its own extensions. These are recorded in
[`assets/sources/<sourceId>/fhir_screen.yaml`](../../assets/sources/README.md), and each
source confirms them before its first deposit. A value passes only if it matches a
confirmed pattern exactly: an identifier needs a confirmed system and a matching value, a
name needs every part to match, and a resource id must match the confirmed id pattern. Identifiers and names that do not match are
handled as usual. A value that passes appears in `findings.tsv` with action `pseudonym`
and the source ID as detector. It adds no property and does not quarantine the batch.

The source config's `source_id` must match the sidecar's `sourceId`. A source can add
extension URLs but cannot change the actions set by the shared rules.

## Testing

The automated tests use the committed Synthea fixtures: the `dirty` batch is quarantined,
the `clean` batch passes, and intake and QC failures stop the run. The screen has also
been run on two other sources, outside CI:

| Data | Kind | Result |
| --- | --- | --- |
| [MIMIC-IV Clinical Database Demo on FHIR](https://physionet.org/content/mimic-iv-fhir-demo/2.1.0/) 2.1.0 | De-identified real data: 100 patients, 30 files | With the `src-mimic-demo` source config and `--provider_policy review`, every file passes. Dates and free text are reported. With the default `stop` policy, the hospital's Organization and Location names quarantine their files. |
| FDNA mock package (ARPA-H RAPID) | Synthetic: 30 cases, FHIR R4 with profiles and images | The FHIR part passes with the `src-fdna-mock` source config. Its definition resources are skipped and its 90 Media attachments are reported for review. The images were deposited as a separate batch and are not screened by this workflow. |

## Limits

Structural QC is not full FHIR R4 or US Core profile validation. Reference and terminology checks remain planned.

Pattern detectors recognize fixed formats such as phone numbers. They do not recognize
names, places or dates written in prose. Free text is flagged for `deid_fhir` and
`confirm_deid_text`. Attachments need separate extraction and handling by content type.
UK-specific identifiers, including NHS numbers and postcodes, are not covered yet.

## Further development

In priority order, highest value first:

1. **Missing Safe Harbor coverage.** Add `Organization.contact`,
   `Practitioner.qualification.identifier` (licence numbers), `Coverage.subscriberId`
   (health plan numbers held as a string) and SSNs without dashes.
2. **Routing by sidecar class.** A FHIR file whose `additionalType` is not a FHIR class
   is skipped without being screened. Intake could detect FHIR content and refuse to
   skip it.
3. **Workflow test with a source config.** CI runs only the Synthea fixtures. A small
   MIMIC-IV demo excerpt (ODbL) would test pseudonyms and source extensions end to end.
4. **URL allow-list.** Hosts match by prefix, so `hl7.org.example.com` passes, and
   `github.com/synthetichealth` is there only for the test fixtures. Match whole hosts,
   and move fixture hosts into a test source config.
5. **Shared rules with `deid_fhir`.** Export the element rules as an anonymizer
   configuration (Microsoft Tools for Health Data Anonymization), and decide the
   date-shift scope (per patient or per batch) before implementing it.
6. **Profile, terminology and reference QC**, beyond file structure.
7. **UK identifiers**, including NHS numbers and postcodes.
