// Screen one OMOP table for identifiers (rddc-omop-screen file). Writes its findings (no
// values) and the data properties the screen reports for it.
process SCREEN_OMOP {
    tag "${meta.name}"
    label 'process_single'
    container 'ghcr.io/sage-bionetworks/rddc-omop-screen:0.1.0'

    input:
    tuple val(meta), path(data)
    val provider_policy
    val research_id_pattern
    path allow_list   // assets/NO_FILE when there is none

    output:
    path "${meta.id}.findings.tsv", emit: findings
    path "${meta.id}.result.json",  emit: result

    script:
    def rid   = research_id_pattern ? "--research-id-pattern '${research_id_pattern.replace("'", "'\\''")}'" : ''
    def allow = allow_list.name != 'NO_FILE' ? "--allow-list '${allow_list}'" : ''
    def fmt   = meta.encodingFormat ? "--encoding-format '${meta.encodingFormat}'" : ''
    """
    rddc-omop-screen file '${data}' --file-id '${meta.urn}' --name '${meta.name}' \\
        --table '${meta.cdmTable}' ${fmt} --provider-policy ${provider_policy} ${rid} ${allow} \\
        --findings ${meta.id}.findings.tsv --result ${meta.id}.result.json
    """

    stub:
    """
    : > ${meta.id}.findings.tsv
    printf '{"file": "%s", "name": "%s", "table": "%s", "records": 0, "properties": [], "checked": []}\\n' \\
        '${meta.urn}' '${meta.name}' '${meta.cdmTable}' > ${meta.id}.result.json
    """
}
