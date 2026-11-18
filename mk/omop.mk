SCREENS += omop
INTAKE_FAILS_omop := omop/person.csv
.PHONY: fixtures-omop

fixtures-omop: venv   ## both OMOP batches and sidecars, from rddc-fhir-to-omop's output (FHIR_TO_OMOP_OUT)
	.venv/bin/python -I tests/screen_omop/make_batches.py $(FHIR_TO_OMOP_OUT)
	$(RDDC_SIDECAR) generate tests/screen_omop/dirty --contributor-id test-site --source-id src-synthea-01 \
	    --bucket rddc-deposit-test --prefix '{sourceId}/{batchId}/' --attest-direct-identifiers-removed \
	    --synthetic --batch-id 2026-11-synthea-omop-dirty \
	    --sidecar-id urn:uuid:5e1d0c2a-0000-4000-8000-0000000000c2 --created-at 2026-11-17T00:00:00Z --force
	$(RDDC_SIDECAR) generate tests/screen_omop/clean --contributor-id test-site --source-id src-synthea-01 \
	    --bucket rddc-deposit-test --prefix '{sourceId}/{batchId}/' --attest-direct-identifiers-removed \
	    --synthetic --batch-id 2026-11-synthea-omop-clean \
	    --sidecar-id urn:uuid:5e1d0c2a-0000-4000-8000-0000000000c3 --created-at 2026-11-17T00:00:00Z --force
	python3 -I tests/screen_omop/make_batches.py --errors
