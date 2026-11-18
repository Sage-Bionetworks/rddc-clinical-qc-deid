import gzip
import json
import os
from pathlib import Path

import pytest

from rddc_fhir_screen.screen import Screen, load_rules, properties, reference_type

FIXTURES = Path(os.environ.get("RDDC_FIXTURES", Path(__file__).resolve().parents[3] / "tests" / "screen_fhir"))


def screen(resources, tmp_path, policy="stop"):
    p = tmp_path / "x.ndjson"
    p.write_text("".join(json.dumps(r) + "\n" for r in resources))
    _, found, _ = Screen(load_rules(), policy).file(str(p))
    return found


def rules_hit(found, action):
    return {(k.resource_type, k.path, k.rule) for k in found if k.action == action}


def test_reference_type():
    assert reference_type("Patient/123") == "Patient"
    assert reference_type("Practitioner?identifier=http://hl7.org/fhir/sid/us-npi|9999987297") == "Practitioner"
    assert reference_type("https://fhir.example.org/r4/Organization/9") == "Organization"
    assert reference_type("#contained-1") is None


def test_patient_direct_identifiers_stop(tmp_path):
    found = screen([{"resourceType": "Patient", "id": "p1", "name": [{"family": "Doe"}],
                     "birthDate": "1980-01-02", "address": [{"postalCode": "02139", "state": "MA"}]}], tmp_path)
    assert ("Patient", "name", "patient_direct") in rules_hit(found, "stop")
    assert properties(found) == ["dates", "direct_identifiers", "zip_codes"]


def test_clean_patient_passes(tmp_path):
    found = screen([{"resourceType": "Patient", "id": "p1", "gender": "female", "birthDate": "1980"}], tmp_path)
    assert properties(found) == []


def test_reference_display(tmp_path):
    enc = {"resourceType": "Encounter", "id": "e1",
           "subject": {"reference": "Patient/p1", "display": "Jane Doe"},
           "participant": [{"individual": {"reference": "Practitioner/d1", "display": "Dr. Who"}}]}
    stop = rules_hit(screen([enc], tmp_path), "stop")
    assert ("Encounter", "subject.display", "reference_display") in stop
    assert ("Encounter", "participant.individual.display", "reference_display") in stop
    review = rules_hit(screen([enc], tmp_path, policy="review"), "review")
    assert ("Encounter", "participant.individual.display", "reference_display") in review


def test_pattern_in_free_text(tmp_path):
    obs = {"resourceType": "Observation", "id": "o1", "valueString": "patient called from 555-123-4567"}
    found = screen([obs], tmp_path)
    assert ("Observation", "valueString", "pattern") in rules_hit(found, "stop")
    assert "free_text" in properties(found)


def test_unknown_extension_reviewed(tmp_path):
    p = {"resourceType": "Patient", "id": "p1",
         "extension": [{"url": "http://example.org/nickname", "valueString": "Jo"}]}
    assert ("Patient", "extension", "extension:unknown") in rules_hit(screen([p], tmp_path), "review")


def test_bundle_and_contained(tmp_path):
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": [
        {"resource": {"resourceType": "Observation", "id": "o1",
                      "contained": [{"resourceType": "Patient", "id": "c", "telecom": [{"value": "x"}]}]}}]}
    p = tmp_path / "b.json"
    p.write_text(json.dumps(bundle))
    records, found, _ = Screen(load_rules()).file(str(p))
    assert records == 1 and ("Patient", "telecom", "patient_direct") in rules_hit(found, "stop")


def screen_dir(d):
    out = {}
    for f in sorted((d / "fhir").glob("*.ndjson.gz")):
        _, found, _ = Screen(load_rules()).file(str(f))
        out[f.name.split(".")[0]] = properties(found)
    return out


@pytest.mark.skipif(not FIXTURES.exists(), reason="repo fixtures not mounted")
def test_synthea_dirty_batch_is_stopped():
    got = screen_dir(FIXTURES / "dirty")
    held = {k for k, v in got.items() if "direct_identifiers" in v}
    assert {"Patient", "Practitioner", "Organization", "Device", "Encounter"} <= held


@pytest.mark.skipif(not FIXTURES.exists(), reason="repo fixtures not mounted")
def test_synthea_clean_batch_passes():
    got = screen_dir(FIXTURES / "clean")
    assert not [k for k, v in got.items() if "direct_identifiers" in v], got
    assert "dates" in got["Patient"] and "zip_codes" in got["Patient"]
