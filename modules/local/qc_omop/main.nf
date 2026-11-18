// Check file structure. Failures are reported; the workflow gates the whole batch.
process QC_OMOP {
    tag "${meta.name}"
    label 'process_single'
    container 'ghcr.io/sage-bionetworks/rddc-omop-screen:0.1.0'

    input:
    tuple val(meta), path(data)

    output:
    tuple val(meta), path(data), emit: checked
    path "${meta.id}.qc.json", emit: result

    script:
    def fmt = meta.encodingFormat ? "--encoding-format '${meta.encodingFormat}'" : ''
    """
    rddc-omop-screen qc '${data}' --file-id '${meta.urn}' --table '${meta.cdmTable}' ${fmt} --result ${meta.id}.qc.json
    """

    stub:
    """
    printf '{"file":"%s","status":"pass","records":0,"error":"","record":0}\\n' '${meta.urn}' > ${meta.id}.qc.json
    """
}
