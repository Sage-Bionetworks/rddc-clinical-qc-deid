# screen_omop changelog

Release tags use `screen_omop/v<version>`.

## 0.1.0 (unreleased)

- Add structural QC before screening. If any selected file fails, no files are screened.
  Write the QC report to `qc/qc.tsv` without source values.
- Use the shared detector package and an independent checksum container.

- Add the first identifier screen for deposited OMOP tables in CSV, TSV (plain or
  gzipped) and Parquet. Each file's `cdmTable` selects the table checks.
- Check identifier columns in `location`, `provider`, `care_site`, `device_exposure`,
  `specimen` and `payer_plan_period`. Flag device IDs that include production identifiers.
- Support an optional research ID pattern for `person_source_value` and a source-specific
  allow list for eligible `*_source_value` columns.
- Flag person-to-person `fact_relationship` rows, dates, ZIP codes and long strings.
  Reuse the FHIR pattern detectors. Report note text as `free_text` for `deid_omop_notes`.
- Define checks in the [OMOP rules](../../containers/rddc-omop-screen/src/rddc_omop_screen/rules.yaml),
  based on inventory section 4.1.
- Write `results.json` as a list of `{file, properties}` objects, plus `findings.tsv`,
  `summary.tsv` and `intake/intake.tsv`. Findings omit matched values.
- Fail the run if an OMOP table cannot pass intake or has no `cdmTable`.
