// Screen one FHIR file for identifiers (rddc-fhir-screen file). Writes its findings (no
// values) and the data properties the screen reports for it.
process SCREEN_FHIR {
    tag "${meta.name}"
    label 'process_single'
    container 'ghcr.io/sage-bionetworks/rddc-fhir-screen:0.1.0'

    input:
    tuple val(meta), path(data)
    val provider_policy

    output:
    path "${meta.id}.findings.tsv", emit: findings
    path "${meta.id}.result.json",  emit: result

    script:
    """
    rddc-fhir-screen file '${data}' --file-id '${meta.urn}' --name '${meta.name}' \\
        --provider-policy ${provider_policy} \\
        --findings ${meta.id}.findings.tsv --result ${meta.id}.result.json
    """

    stub:
    """
    : > ${meta.id}.findings.tsv
    printf '{"file": "%s", "name": "%s", "records": 0, "properties": [], "checked": []}\\n' \\
        '${meta.urn}' '${meta.name}' > ${meta.id}.result.json
    """
}
