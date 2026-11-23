# Source configs

One directory per source, named by the `sourceId` in the batch's sidecar. A workflow
picks up `assets/sources/<sourceId>/` by itself; `--source_config DIR` names one directly.
A source with no directory is screened with the shared rules only.

## `fhir_screen.yaml`

What the source has confirmed about its FHIR data, for `screen_fhir`:

- `source_id`: the source's `sourceId`. The run fails if it is not the batch's.
- `pseudonyms`: the identifiers and names the source uses in place of real ones. Each
  entry lists `resources` and gives `identifier_system` with `identifier_pattern`, a
  `name_pattern`, or both. Patterns are regular expressions that must match the whole
  value. An identifier passes when its system is `identifier_system` and its value
  matches; a name passes when every part (text, family, given, prefix, suffix) matches.
  For a string name such as `Organization.name`, the whole string must match. A rule's
  values pass only if all of them are pseudonyms. `note` is free text for reviewers.
- `extensions`: extension URLs the source uses, with an action: `ok`, `review`,
  `free_text` or `stop`. A source can add URLs but not change those in the shared rules.

A value that passes as a pseudonym appears in `findings.tsv` with action `pseudonym` and
the source ID as detector. It adds no property and does not quarantine the batch.

Each source confirms its patterns before its first deposit, and changes to them are
reviewed like code. `src-mimic-demo` (MIMIC-IV FHIR demo) and `src-fdna-mock` (FDNA mock
package) are the worked examples.
