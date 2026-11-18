// Merge the per-table results: results.json (what the dispatcher records on the step),
// findings.tsv and summary.tsv.
process SCREEN_OMOP_REPORT {
    label 'process_single'
    container 'ghcr.io/sage-bionetworks/rddc-omop-screen:0.1.0'
    publishDir "${params.outdir}", mode: 'copy'

    input:
    path results,  stageAs: 'results/*'
    path findings, stageAs: 'findings/*'

    output:
    path 'results.json', emit: results
    path 'findings.tsv', emit: findings
    path 'summary.tsv',  emit: summary

    script:
    """
    rddc-omop-screen report results/* --findings findings/* --out-dir .
    """

    stub:
    """
    printf '[]\\n' > results.json
    : > findings.tsv
    : > summary.tsv
    """
}
