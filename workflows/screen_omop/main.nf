#!/usr/bin/env nextflow
/*
 * screen_omop: check deposited OMOP CDM 5.4 tables for identifiers.
 * See rddc-source-map/qc_deid_inventory.md, section 4.1.
 *
 * Input: the batch's sidecar (--sidecar, _sidecar.json). Every OmopTableFile in it is
 * screened (CSV, TSV, gzipped or not, or Parquet), by its cdmTable; other files are listed in
 * intake.tsv as skipped. OMOP made from FHIR by fhir_to_omop is not screened again (the
 * screen_fhir result carries over). The screen leaves the data unchanged and writes, to
 * --outdir:
 *   qc/qc.tsv     structural QC results; all files must pass before screening
 *   results.json   [{file, properties}]: the data properties found for each table
 *                  (direct_identifiers, dates, zip_codes, free_text). The dispatcher records
 *                  them on the step; direct_identifiers quarantines the batch.
 *   findings.tsv   what was found where, by table, column, rule and detector, with counts
 *                  and no values
 *   summary.tsv    one row per table: records, verdict, properties
 *   intake/intake.tsv  every sidecar entry and what happened to it
 *
 * An OMOP table that fails intake (checksum, location) or has no cdmTable cannot be
 * screened, so the run fails: an unscreened table must not pass as clean.
 */

// Parameter defaults for this pipeline (before the includes). Shared params (outdir) are in
// nextflow.config.
params.sidecar             = null     // _sidecar.json of the batch
params.provider_policy     = 'stop'   // clinician and site identity: stop (a direct identifier) or review
params.research_id_pattern = ''       // regex every person_source_value must match; empty: report for review
params.allow_list          = null     // TSV (table, column, value) of the source's reviewed *_source_value values

include { SIDECAR_INTAKE     } from '../../subworkflows/local/sidecar_intake/main.nf'
include { SCREEN_OMOP        } from '../../modules/local/screen_omop/main.nf'
include { SCREEN_OMOP_REPORT } from '../../modules/local/screen_omop_report/main.nf'

include { QC_OMOP } from '../../modules/local/qc_omop/main.nf'
include { QC_REPORT } from '../../modules/local/qc_report/main.nf'

def isOmop(Map meta) {
    return meta.additionalType == 'OmopTableFile'
}

def intakeRow(Map meta, String route, String reason) {
    return [meta.id, meta.name, meta.additionalType, route, reason].join('\t') + '\n'
}

// cdmTable of every file in the sidecar, by @id. SIDECAR_INTAKE (vendored from
// rddc-genomics-workflows) does not carry it in meta yet.
def cdmTables(sidecar) {
    def doc = new groovy.json.JsonSlurperClassic().parseText(sidecar.text)
    return (doc.distribution ?: []).findAll { item -> item.cdmTable }.collectEntries { item -> [(item['@id']): item.cdmTable] }
}

workflow {
    if (!params.sidecar) error "--sidecar (the batch's _sidecar.json) is required"
    if (!params.outdir)  error "--outdir is required"
    if (!(params.provider_policy in ['stop', 'review'])) error "--provider_policy must be stop or review"

    def sidecar = file(params.sidecar, checkIfExists: true)
    def tables  = cdmTables(sidecar)
    def allow   = params.allow_list ? file(params.allow_list, checkIfExists: true) : file("${projectDir}/../../assets/NO_FILE")

    SIDECAR_INTAKE(sidecar)

    omop  = SIDECAR_INTAKE.out.files
        .filter { meta, _f -> isOmop(meta) }
        .map { meta, f -> [meta + [cdmTable: tables[meta.urn]], f] }
    other = SIDECAR_INTAKE.out.files.filter { meta, _f -> !isOmop(meta) }

    omop.map { meta, _f -> intakeRow(meta, meta.cdmTable ? 'screened' : 'rejected', meta.cdmTable ? '' : 'no_cdm_table') }
        .mix(other.map { meta, _f -> intakeRow(meta, 'skipped', 'not_omop') })
        .mix(SIDECAR_INTAKE.out.rejected.map { meta, reason -> intakeRow(meta, 'rejected', reason) })
        .collectFile(name: 'intake.tsv', storeDir: "${params.outdir}/intake", sort: true,
                     seed: "file_id\tname\tclass\troute\treason\n")

    SIDECAR_INTAKE.out.rejected
        .filter { meta, _reason -> isOmop(meta) }
        .mix(omop.filter { meta, _f -> !meta.cdmTable }.map { meta, _f -> [meta, 'no_cdm_table'] })
        .toList()
        .subscribe { bad ->
            if (bad) error "OMOP tables failed intake and cannot be screened: " +
                bad.collect { meta, reason -> "${meta.name} (${reason})" }.join(', ')
        }

    selected = omop.filter { meta, _f -> meta.cdmTable }.toList().map { files ->
        if (!files) error "No OMOP files were selected for QC"
        files
    }.flatMap { files -> files }
    QC_OMOP(selected)
    QC_REPORT(QC_OMOP.out.result.collect(), 'ghcr.io/sage-bionetworks/rddc-omop-screen:0.1.0')
    gate = QC_REPORT.out.verdict.map { verdict ->
        if (verdict.trim() != 'pass') error "Structural QC failed; no files were screened (see qc/qc.tsv)"
        true
    }
    ready = QC_OMOP.out.checked.combine(gate).map { meta, data, _passed -> [meta, data] }
    SCREEN_OMOP(ready, params.provider_policy, params.research_id_pattern ?: '', allow)
    SCREEN_OMOP_REPORT(SCREEN_OMOP.out.result.collect(), SCREEN_OMOP.out.findings.collect())
}
