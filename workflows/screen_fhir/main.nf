#!/usr/bin/env nextflow
/*
 * screen_fhir: check incoming FHIR R4 files for identifiers.
 * See rddc-source-map/qc_deid_inventory.md, section 4.2.
 *
 * Input: the batch's sidecar (--sidecar, _sidecar.json). Every FhirFile in it is screened;
 * other files are listed in intake.tsv as skipped. The screen leaves the data unchanged and
 * writes, to --outdir:
 *   qc/qc.tsv     structural QC results; all files must pass before screening
 *   results.json   [{file, properties}]: the data properties found for each file
 *                  (direct_identifiers, dates, zip_codes, free_text). The dispatcher records
 *                  them on the step; direct_identifiers quarantines the batch.
 *   findings.tsv   what was found where, by rule and detector, with counts and no values
 *   summary.tsv    one row per file: records, verdict, properties
 *   intake/intake.tsv  every sidecar entry and what happened to it
 *
 * A FHIR file that fails intake (checksum, location) cannot be screened, so the run fails:
 * an unscreened file must not pass as clean.
 */

// Parameter defaults for this pipeline (before the includes). Shared params (outdir) are in
// nextflow.config.
params.sidecar         = null     // _sidecar.json of the batch
params.provider_policy = 'stop'   // clinician and site identity: stop (a direct identifier) or review
params.source_config   = null     // directory with the source's fhir_screen.yaml; default assets/sources/<sourceId>

include { SIDECAR_INTAKE } from '../../subworkflows/local/sidecar_intake/main.nf'
include { SCREEN_FHIR    } from '../../modules/local/screen_fhir/main.nf'
include { SCREEN_REPORT  } from '../../modules/local/screen_report/main.nf'

include { QC_FHIR } from '../../modules/local/qc_fhir/main.nf'
include { QC_REPORT } from '../../modules/local/qc_report/main.nf'

def isFhir(Map meta) {
    return meta.additionalType in ['FhirFile', 'FhirBundleFile', 'FhirSingleTypeFile', 'FhirResourceFile', 'FhirNdjsonFile']
}

def intakeRow(Map meta, String route, String reason) {
    return [meta.id, meta.name, meta.additionalType, route, reason].join('\t') + '\n'
}

workflow {
    if (!params.sidecar) error "--sidecar (the batch's _sidecar.json) is required"
    if (!params.outdir)  error "--outdir is required"
    if (!(params.provider_policy in ['stop', 'review'])) error "--provider_policy must be stop or review"

    SIDECAR_INTAKE(file(params.sidecar, checkIfExists: true))

    fhir  = SIDECAR_INTAKE.out.files.filter { meta, _f -> isFhir(meta) }
    other = SIDECAR_INTAKE.out.files.filter { meta, _f -> !isFhir(meta) }

    fhir.map { meta, _f -> intakeRow(meta, 'screened', '') }
        .mix(other.map { meta, _f -> intakeRow(meta, 'skipped', 'not_fhir') })
        .mix(SIDECAR_INTAKE.out.rejected.map { meta, reason -> intakeRow(meta, 'rejected', reason) })
        .collectFile(name: 'intake.tsv', storeDir: "${params.outdir}/intake", sort: true,
                     seed: "file_id\tname\tclass\troute\treason\n")

    SIDECAR_INTAKE.out.rejected
        .filter { meta, _reason -> isFhir(meta) }
        .toList()
        .subscribe { bad ->
            if (bad) error "FHIR files failed intake and cannot be screened: " +
                bad.collect { meta, reason -> "${meta.name} (${reason})" }.join(', ')
        }

    selected = fhir.toList().map { files ->
        if (!files) error "No FHIR files were selected for QC"
        files
    }.flatMap { files -> files }
    QC_FHIR(selected)
    QC_REPORT(QC_FHIR.out.result.collect(), 'ghcr.io/sage-bionetworks/rddc-fhir-screen:0.1.0')
    gate = QC_REPORT.out.verdict.map { verdict ->
        if (verdict.trim() != 'pass') error "Structural QC failed; no files were screened (see qc/qc.tsv)"
        true
    }
    ready = QC_FHIR.out.checked.combine(gate).map { meta, data, _passed -> [meta, data] }

    // The source's confirmed pseudonyms and extensions (assets/sources/README.md). A source
    // without a config is screened with the shared rules only.
    assets = "${projectDir}/../../assets"
    source_rules = SIDECAR_INTAKE.out.batch.map { batch ->
        def dir = params.source_config ? file(params.source_config) : file("${assets}/sources/${batch.sourceId}")
        def config = dir.resolve('fhir_screen.yaml')
        if (params.source_config && !config.exists()) {
            error "--source_config ${params.source_config} has no fhir_screen.yaml"
        }
        config.exists() ? config : file("${assets}/NO_FILE")
    }.first()
    SCREEN_FHIR(ready, params.provider_policy, source_rules)
    SCREEN_REPORT(SCREEN_FHIR.out.result.collect(), SCREEN_FHIR.out.findings.collect())
}
