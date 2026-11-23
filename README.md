# rddc-clinical-qc-deid

Quality checks and identifier screening for clinical data in the Rare Disease Data
Commons (RDDC). Checks report findings and leave the source data unchanged.

[FHIR R4 QC and screening](workflows/screen_fhir/README.md) is available as a prototype.
OMOP CDM 5.4 support is planned. Full profile, terminology and relational QC are also
planned; the current QC checks file structure.

## How it works

The RDDC orchestrator starts workflows on Cirro in the processing project.
Each workflow has its own entry point, container and release tag.

The order is intake, structural QC, then identifier screening. Every selected file must
pass QC before screening starts. A QC failure stops the run and produces `qc/qc.tsv`.
A direct identifier tells the orchestrator to quarantine the whole batch for data manager review (and potential removal).
A screen verdict of `pass` means no direct identifiers were found under its rules;
dates, ZIP codes, free text and review findings need further processing (to be developed) and attention.

## Development

Use Python 3.11 or later and Java 21. Run commands from the repository root. The
Makefile downloads its pinned Nextflow version into `.tools/` when needed.

```sh
make venv           # Install the shared package, screens and pytest into .venv/.
make py-test        # Test the shared package, screens and synthetic fixtures.
make lint           # Check Nextflow syntax and style.
make stub           # Check workflow connections using placeholder tasks.
make nf-test-local  # Run workflows locally, including intake and QC failures.
make nf-test        # Build images and run the same workflow tests in Docker.
make image-test     # Run Python tests in containers.
```

Docker is needed for image builds and container tests. `make help` lists all targets.
Workflows are registered through separate `mk/*.mk` files and have separate CI files.
This lets another standard be added without changing the common build commands.

The committed fixtures contain eight synthetic Synthea patients. The `dirty` batch
keeps identifiers; the `clean` batch removes identifier fields. Tests use these files
directly. Rebuilding them with `make fixtures` needs the `rddc-sidecar` binary; its
default path is `../rddc-sidecar/target/release/rddc-sidecar`, overridden by `RDDC_SIDECAR`.

## Layout

| Path | Purpose |
| --- | --- |
| `workflows/screen_fhir/` | Workflow entry point, documentation and changelog. |
| `.cirro/screen_fhir/` | Cirro form, input mapping and preprocessing. |
| `containers/` | Screen packages and container definitions. |
| `shared/` | Common detectors and QC reporting, installed in each screen image. |
| `modules/local/` | Nextflow processes for intake, QC, screening and reports. |
| `subworkflows/local/sidecar_intake/` | Intake code copied from `rddc-genomics-workflows`; keep it in sync. |
| `tests/` | Synthetic batches and workflow assertions. |
| `mk/` | Development settings and fixture recipes for each standard. |
| `conf/` | Shared resource settings. |

Build containers from the repository root so they can include `shared/`. The checksum
step uses `rddc-intake`, independently of the screen images. Run `make check-image-tags`
to check screen image tags against their Python package versions.

## Releases

Release each workflow separately with a tag such as `screen_fhir/v0.1.0`:

1. Update its changelog, package version and module image tags. If the shared package
   changes version, update each screen's dependency too. If the intake image changes,
   update `INTAKE_IMAGE` in the Makefile and its module tag.
2. Run the tests and merge. Tag the merge commit: `intake/vX.Y.Z` first when the intake
   image changed, then `screen_<std>/vX.Y.Z`. The `image` workflow checks the versions,
   runs the tests and publishes the image for each tag. It never overwrites a published
   tag, and a screen release fails if the intake image its modules pin is not published.
3. Update the Cirro configuration to use the release tag.

The Cirro configuration uses repository ID `clinical_qc_deid` and points to
`workflows/<name>/main.nf`, `.cirro/<name>/` and the release tag.
