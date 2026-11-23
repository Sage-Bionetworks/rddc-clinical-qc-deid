# Local development and CI helpers. Pipelines run on Cirro from their tags; nothing here is
# needed there. `make tools` fetches Nextflow into .tools/; `make venv` installs the screen
# into .venv/ for the tests and container-free runs. Docker is needed for image and nf-test.

SHELL            := /bin/bash
NXF_VERSION      ?= 26.10.5
export NXF_HOME  ?= $(CURDIR)/.tools/nxf-home
export NXF_VER   := $(NXF_VERSION)
NEXTFLOW         := $(CURDIR)/.tools/nextflow

# One package and image per screen: containers/rddc-<std>-screen, image
# ghcr.io/sage-bionetworks/rddc-<std>-screen:<version>, workflow workflows/screen_<std>.
SCREENS          :=
.DEFAULT_GOAL := help
include $(wildcard mk/*.mk)
RDDC_SIDECAR     ?= ../rddc-sidecar/target/release/rddc-sidecar
FHIR_TO_OMOP_OUT ?= ../rddc-fhir-to-omop/results/test-docker/omop
dir_of            = containers/rddc-$(1)-screen
version_of        = $(shell sed -n 's/^version = "\(.*\)"/\1/p' $(call dir_of,$(1))/pyproject.toml)
image_of          = ghcr.io/sage-bionetworks/rddc-$(1)-screen:$(call version_of,$(1))
run_of            = $(NEXTFLOW) run . -main-script workflows/screen_$(1)/main.nf
, := ,

.PHONY: image-intake help tools venv py-test image image-test lint stub nf-test-local nf-test fixtures check-image-tags check-shared

help:   ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | expand -t 18

tools: $(NEXTFLOW)   ## fetch Nextflow into .tools/
$(NEXTFLOW):
	mkdir -p $(dir $@)
	curl -fsSL https://get.nextflow.io -o $@ && chmod +x $@ && $@ -version >/dev/null

venv: .venv/bin/rddc-screen-qc $(foreach s,$(SCREENS),.venv/bin/rddc-$(s)-screen)   ## install the screens (editable) and pytest into .venv/
.venv/bin/rddc-screen-qc: shared/pyproject.toml
	[ -x .venv/bin/python ] || python3 -m venv .venv
	.venv/bin/pip install -q -e "./shared[test]"

.venv/bin/rddc-%-screen: containers/rddc-%-screen/pyproject.toml .venv/bin/rddc-screen-qc
	[ -x .venv/bin/python ] || python3 -m venv .venv
	.venv/bin/pip install -q -e "containers/rddc-$*-screen[test]"

py-test: venv check-shared   ## unit tests and the fixture batches, no Docker
	$(foreach s,$(SCREENS),.venv/bin/python -m pytest -q $(call dir_of,$(s))/tests &&) true

image: image-intake   ## build each screen image with the tag its modules pin
	$(foreach s,$(SCREENS),docker build --target runtime -t $(call image_of,$(s)) -f $(call dir_of,$(s))/Dockerfile . &&) true

image-test:   ## unit tests in the images (fixtures and source configs mounted read-only, no network)
	$(foreach s,$(SCREENS),docker build --target test -t rddc-$(s)-screen:test -f $(call dir_of,$(s))/Dockerfile . && \
	    docker run --rm --network none -v $(CURDIR)/tests/screen_$(s):/fixtures:ro -e RDDC_FIXTURES=/fixtures \
	        -v $(CURDIR)/assets/sources:/sources:ro -e RDDC_SOURCES=/sources rddc-$(s)-screen:test &&) true

image-intake:   ## build the shared checksum image
	docker build -t ghcr.io/sage-bionetworks/rddc-intake:0.1.0 -f containers/rddc-intake/Dockerfile .

lint: tools   ## nextflow lint
	$(NEXTFLOW) lint $(wildcard workflows) modules subworkflows

stub: tools   ## the wiring, with stub tasks and no container
	$(foreach s,$(SCREENS),$(call run_of,$(s)) -profile test$(,)local -stub-run --sidecar tests/screen_$(s)/dirty/_sidecar.json --outdir results/stub-$(s) &&) true

# For each screen, the two batches give opposite verdicts: dirty has direct identifiers,
# clean has none. And a file of the screen's kind that fails intake (here a wrong md5)
# cannot be screened: the run must fail.
define CHECK_SCREEN
	$(2) --sidecar tests/screen_$(1)/dirty/_sidecar.json --outdir results/$(1)-dirty
	python3 -I tests/check_results.py results/$(1)-dirty quarantine
	$(2) --sidecar tests/screen_$(1)/clean/_sidecar.json --outdir results/$(1)-clean
	python3 -I tests/check_results.py results/$(1)-clean pass
	! $(2) --sidecar tests/screen_$(1)/dirty/_sidecar.errors.json --outdir results/$(1)-errors > results/$(1)-errors.log 2>&1
	grep -q 'failed intake and cannot be screened: $(3)' results/$(1)-errors.log
	@echo "screen_$(1): intake failure stops the screen, as expected"

endef

nf-test-local: tools venv   ## both fixture batches of each screen through Nextflow, tools from .venv (no Docker)
	@mkdir -p results
	$(foreach s,$(SCREENS),$(call CHECK_SCREEN,$(s),PATH=$(CURDIR)/.venv/bin:$$PATH $(call run_of,$(s)) -profile test$(,)local,$(INTAKE_FAILS_$(s))))
	$(foreach s,$(SCREENS),python3 -I tests/check_qc_failure.py $(s) test,local &&) true

nf-test: tools image   ## both fixture batches of each screen through Nextflow in Docker
	@mkdir -p results
	$(foreach s,$(SCREENS),$(call CHECK_SCREEN,$(s),$(call run_of,$(s)) -profile test$(,)docker,$(INTAKE_FAILS_$(s))))
	$(foreach s,$(SCREENS),python3 -I tests/check_qc_failure.py $(s) test,docker &&) true

fixtures: $(addprefix fixtures-,$(SCREENS))   ## rebuild fixtures for the installed standards

check-image-tags:   ## every module pins the image version in its screen's pyproject.toml
	@for s in $(SCREENS); do \
	    v=$$(sed -n 's/^version = "\(.*\)"/\1/p' containers/rddc-$$s-screen/pyproject.toml); \
	    bad=$$(grep -rho "rddc-$$s-screen:[0-9A-Za-z.]*" modules | sort -u | grep -v ":$$v$$" || true); \
	    if [ -n "$$bad" ]; then echo "modules pin $$bad, pyproject says $$v"; exit 1; fi; \
	done

check-shared: venv   ## test the shared detector and QC package
	.venv/bin/python -m pytest -q shared/tests
