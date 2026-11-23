# screen_fhir changelog

Release tags use `screen_fhir/v<version>`.

## 0.1.0 (unreleased)

- Add structural QC before screening. If any selected file fails, no files are screened.
  Write the QC report to `qc/qc.tsv` without source values.
- Use the shared detector package and an independent checksum container.

- Add the first identifier screen for every FHIR file in a batch. Checks cover resource
  fields, reference display text, extensions, full dates, ZIP codes and identifier
  patterns (SSN, phone, email, URL, IPv4 and labelled MRN).
- Define checks in the [FHIR rules](../../containers/rddc-fhir-screen/src/rddc_fhir_screen/rules.yaml),
  based on inventory section 4.2.
- Write `results.json` as a list of `{file, properties}` objects, plus `findings.tsv`,
  `summary.tsv` and `intake/intake.tsv`. Findings omit matched values.
- Fail the run if a FHIR file cannot pass intake.
- Write element rules as FHIRPath (R4) expressions. Rules are checked against the R4
  model in tests and parsed strictly at load, so a misspelt rule fails instead of matching
  nothing. Attachments in Media, Communication, QuestionnaireResponse answers and
  extensions are now reported for review.
