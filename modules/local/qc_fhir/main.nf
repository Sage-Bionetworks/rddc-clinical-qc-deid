// Check file structure. Failures are reported; the workflow gates the whole batch.
process QC_FHIR {
    tag "${meta.name}"
    label 'process_single'
    container 'ghcr.io/sage-bionetworks/rddc-fhir-screen:0.1.0'

    input:
    tuple val(meta), path(data)

    output:
    tuple val(meta), path(data), emit: checked
    path "${meta.id}.qc.json", emit: result

    script:
    """
    rddc-fhir-screen qc '${data}' --file-id '${meta.urn}' --result ${meta.id}.qc.json
    """

    stub:
    """
    printf '{"file":"%s","status":"pass","records":0,"error":"","record":0}\\n' '${meta.urn}' > ${meta.id}.qc.json
    """
}
