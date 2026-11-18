# Required column names

`src/rddc_omop_screen/qc_columns.json` lists columns marked `NOT NULL` in the
OMOP CDM 5.4 DDL. Structural QC requires these column names to be present; it does
not yet validate their values, types or relationships. Tables without a configured
column list receive the generic header and readability checks.

The list was extracted from `rddc-fhir-to-omop/qa/dqd/cdm54_ddl_duckdb.sql`, generated
by that repository from CommonDataModel 1.1.0. No neighboring repository is needed
at runtime. Source file SHA-256: `f3afadee6e18981aa23b348428fd4fef6a3b748ff26e3b3e77fb183cd34cad42`.
