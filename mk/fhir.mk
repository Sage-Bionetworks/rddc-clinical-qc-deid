SCREENS += fhir
INTAKE_FAILS_fhir := fhir/Observation.ndjson.gz
.PHONY: fixtures-fhir

fixtures-fhir:   ## the clean FHIR batch and its sidecar, from the dirty one
	python3 -I tests/screen_fhir/make_clean_batch.py
	$(RDDC_SIDECAR) generate tests/screen_fhir/clean --contributor-id test-site --source-id src-synthea-01 \
	    --bucket rddc-deposit-test --prefix '{sourceId}/{batchId}/' --attest-direct-identifiers-removed \
	    --synthetic --fhir-subject id --batch-id 2026-11-synthea-clean --export-time 2026-11-11T00:00:00Z \
	    --sidecar-id urn:uuid:5e1d0c2a-0000-4000-8000-0000000000c1 --created-at 2026-11-17T00:00:00Z --force
