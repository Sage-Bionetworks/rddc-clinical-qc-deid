# OMOP QC and identifier screening

`screen_omop` checks deposited OMOP Common Data Model (CDM) 5.4 tables for identifiers
before note de-identification or loading. It checks file structure before screening, reports findings and leaves the data
unchanged. Tables produced by `fhir_to_omop` are not screened again; they carry forward
the `screen_fhir` result.

## Inputs

| Parameter | Description |
| --- | --- |
| `--sidecar` | Required. The batch's `_sidecar.json`. Each `OmopTableFile` must have a `cdmTable` identifying its table. Supported formats are CSV, TSV (plain or gzipped) and Parquet. On Cirro, the preprocessing script finds the sidecar in the input dataset. |
| `--provider_policy` | How to handle clinician and site identity in `provider` and `care_site`. `stop` (default) treats it as a direct identifier; `review` reports it for a curator. Choose the policy for each source. |
| `--research_id_pattern` | A regular expression from the source register. Each non-empty `person_source_value` must match the entire pattern, or it is flagged as a direct identifier. If unset (the default), these values are reported for review. |
| `--allow_list` | Optional TSV with a header of `table`, `column`, `value`, containing values a curator has reviewed for the source. Eligible source values missing from the list are reported for review. This option is not available in the Cirro form yet. |
| `--outdir` | Required. Directory for the reports. Cirro supplies this path. |

The allow list applies to `*_source_value` columns, including person gender, race and
ethnicity source values. Columns with their own rules, such as `person_source_value`,
are checked separately. Without a list, eligible columns still receive the pattern
and long-text checks.

## Structural QC

After intake, every selected file must pass these checks before any file is screened:

- Readable CSV, TSV, gzip or Parquet data.
- Non-empty, unique column names, compared without case or surrounding whitespace.
- The same number of values as columns in every CSV or TSV row.
- Presence of columns marked `NOT NULL` in the configured CDM 5.4 list. See
  [column list provenance](../../containers/rddc-omop-screen/QC_COLUMNS.md).

This checks required column names, not their values or types. Header-only tables are
allowed. Unknown tables receive generic structural checks and are flagged by screening.

A failure stops the workflow and leaves `qc/qc.tsv` for review. It does not produce a
passing screening result. The QC report includes file IDs, status, record counts and
fixed error codes; it omits source values and exception text. A failed file's count is
zero because its total is unknown.

## Outputs

| File | Content |
| --- | --- |
| `qc/qc.tsv` | One row per selected file: `file`, `status`, `records`, `error` and `record`. Screening starts only if every status is `pass`. |
| `results.json` | A list of `{file, properties}` objects. `file` is the sidecar `@id`; `properties` lists any of `direct_identifiers`, `dates`, `zip_codes` and `free_text` found in that table. The dispatcher records these properties on the workflow step. |
| `findings.tsv` | File, table, column, rule, detector, action, match count and first row number. Matched values are omitted. |
| `summary.tsv` | One row per table with its record count, verdict (`quarantine` or `pass`) and property flags. |
| `intake/intake.tsv` | Each sidecar entry and its intake outcome: screened, skipped because it is not OMOP, or rejected with a reason. |

A `direct_identifiers` result tells the orchestrator to quarantine the whole batch.
A `pass` verdict means no direct identifiers were found under the screen's rules;
other findings may still need attention. Findings marked `review` appear in
`findings.tsv` but do not add a property or trigger quarantine on their own.

Finding an identifier does not fail the run: the finding is recorded in the reports.
A table with a missing `cdmTable`, a checksum mismatch or a path outside the batch does
fail the run because it could not be screened.

## Checks

The [OMOP rules](../../containers/rddc-omop-screen/src/rddc_omop_screen/rules.yaml)
come from section 4.1 of RDDC's QC and de-identification inventory, an internal planning document. Column checks apply to
non-empty values.

In the table below, `stop` flags a direct identifier. “Provider policy” uses
`--provider_policy`. The other actions flag data for later work.

| Data checked | Action |
| --- | --- |
| `location`: `address_1`, `address_2`, `city`, `county`, `latitude`, `longitude`, `location_source_value` | `stop` |
| `device_exposure.production_id` | `stop` |
| `device_exposure.unique_device_id` beyond a device identifier alone (8–14 digits, optionally prefixed with `(01)`) | `stop` |
| `specimen.specimen_source_id` (lab accession number); `payer_plan_period.family_source_value` | `stop` |
| `provider`: `provider_name`, `npi`, `dea`, `provider_source_value`, `year_of_birth`; `care_site`: `care_site_name`, `care_site_source_value` | Provider policy |
| `person.person_source_value` | `stop` if it fails `--research_id_pattern`; `review` if no pattern is set |
| String patterns: SSN, phone, email, URL outside the allowed hosts, IPv4 address or labelled medical record number (MRN) | `stop` |
| Strings longer than 80 characters | `free_text` |
| `note`: `note_text`, `note_title`, `note_source_value`; `note_nlp`: `snippet`, `lexical_variant`, `term_modifiers` | `free_text`; left to `deid_omop_notes` |
| `*_date`, `*_datetime` and `person.day_of_birth` | `dates` |
| `location.zip` | `zip_codes` |
| `fact_relationship` rows linking two persons | `review` |
| Eligible source values missing from `--allow_list` | `review` |
| A `cdmTable` outside the configured CDM 5.4 table list | `review` |

Pattern and long-text checks skip date columns and the note columns listed above.
Rows in `cdm_source`, `metadata` and vocabulary tables are counted but not screened.

## Limits

Structural QC is not full DDL validation. Value types, required values, keys and relationships remain unchecked.

- Observation concepts that may contain phone numbers or email addresses in
  `value_as_string` do not yet have a concept deny list.
- Date-shift validation, full table definitions, vocabulary and DQD checks remain planned (inventory section 4.1).
- UK-specific identifiers, including NHS numbers and postcodes, are not covered yet
  (inventory gap 11).
- Screening runs row by row in Python. It is suitable for test batches; full site
  extracts with hundreds of millions of measurement rows need a faster implementation,
  such as DuckDB.

## Test batches

The fixtures use the same eight synthetic Synthea patients as the FHIR tests.
`tests/screen_omop/dirty/` contains the converted OMOP data from `rddc-fhir-to-omop`.
Most tables are CSV; `measurement` is Parquet and `observation` is gzipped CSV.

The dirty batch keeps street addresses, clinician names, NPIs and device production
identifiers. The screen flags `location`, `provider`, `care_site` and `device_exposure`
for quarantine. The `clean` batch empties those columns and uses research IDs in
`person_source_value`.

Run `make fixtures-omop` to rebuild both batches and their sidecars. Set
`FHIR_TO_OMOP_OUT` to the conversion output directory if it differs from the default
in the [Makefile](../../Makefile).

## Development

Run these commands from the repository root with Python 3.11 or later and Java 21:

```sh
make venv
make py-test SCREENS=omop
make lint
make stub SCREENS=omop
make nf-test-local SCREENS=omop
make nf-test SCREENS=omop  # Requires Docker.
```

The tests use committed synthetic fixtures and do not need the FHIR conversion
repository. Container builds use the repository root as their context to include the
shared detector and QC package. OMOP has its own Makefile fragment and CI workflow.
