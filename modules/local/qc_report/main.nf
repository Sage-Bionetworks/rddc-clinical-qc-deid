// Publish structural QC results before the workflow opens the screening gate.
process QC_REPORT {
    label 'process_single'
    // The selected standard's image also contains the shared QC reporter.
    container "${qc_container}"
    publishDir "${params.outdir}/qc", mode: 'copy'

    input:
    path reports, stageAs: 'reports/*'
    val qc_container

    output:
    path 'qc.tsv', emit: report
    stdout emit: verdict


    script:
    """
    rddc-screen-qc reports/* --output qc.tsv
    """

    stub:
    """
    printf 'file\\tstatus\\trecords\\terror\\trecord\\n' > qc.tsv
    printf pass
    """
}
