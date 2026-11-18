# Shared QC and screening tools

Both standards use this package for pattern detectors and QC reports. Install it with
`pip install -e './shared[test]'`. Each screen image includes its own installed copy;
neither image depends on the other screen.

Structural QC runs after intake and before identifier screening. Each file produces
JSON with `file` (sidecar ID), `status` (`pass` or `fail`), `records`, `error` (a fixed
code) and `record` (the first failing record, or zero when unavailable). A failed file
reports zero for `records`; it is not a complete count. Reports omit source values
and exception messages. Unexpected implementation errors fail the task.

`QC_REPORT` combines these results into `qc/qc.tsv`. Screening starts only after every
selected file passes. A QC failure fails the workflow; it never becomes an empty or
passing screen result. Screening results retain the `{file, properties}` format.

Keep shared changes in separate commits so both feature branches can incorporate them.
