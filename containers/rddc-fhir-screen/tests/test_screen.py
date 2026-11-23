import gzip
import json
import os
import re
from pathlib import Path

import pytest
from fhirpathpy.models import models

from rddc_fhir_screen.screen import Screen, load_rules, properties, reference_type, root_type

FIXTURES = Path(os.environ.get("RDDC_FIXTURES", Path(__file__).resolve().parents[3] / "tests" / "screen_fhir"))


def screen(resources, tmp_path, policy="stop"):
    p = tmp_path / "x.ndjson"
    p.write_text("".join(json.dumps(r) + "\n" for r in resources))
    _, found, _ = Screen(load_rules(), policy).file(str(p))
    return found


def rules_hit(found, action):
    return {(k.resource_type, k.path, k.rule) for k in found if k.action == action}


R4 = models["r4"]
RESOURCES = {t for t, parent in R4["type2Parent"].items() if parent in ("DomainResource", "Resource")}
# Concrete names of choice elements (Observation.valueString), which FHIRPath writes as
# value.ofType(string). The model lists them as paths too.
CHOICE_NAMES = {f"{path}{t[0].upper()}{t[1:]}" for path, types in R4["choiceTypePaths"].items() for t in types}


def r4_child(owner, name):
    """What `name` under `owner` (a type, or the path of a backbone element) is in R4:
    ("type", T), ("backbone", path), ("choice", [types]) or None."""
    p2t, choice, elsewhere = R4["path2Type"], R4["choiceTypePaths"], R4["pathsDefinedElsewhere"]
    while owner:
        key = elsewhere.get(f"{owner}.{name}", f"{owner}.{name}")
        if key in CHOICE_NAMES:
            return None
        if key in p2t:
            return "type", p2t[key]
        if key in choice:
            return "choice", choice[key]
        if any(k.startswith(key + ".") for k in p2t):
            return "backbone", key
        owner = R4["type2Parent"].get(owner)  # inherited (Patient.text from DomainResource)
    return None


def r4_valid(expr, root):
    """Whether a rule expression names real R4 elements from `root`. Supports the subset the
    rules use: element names, `quoted` names, repeat(name) and ofType(Type) after a choice."""
    owner, pending = root, None
    segments = re.findall(r"[A-Za-z]+\([A-Za-z]+\)|`[^`]+`|[A-Za-z]+", expr)
    if root_type(expr):
        segments = segments[1:]
    for seg in segments:
        call = re.fullmatch(r"(repeat|ofType)\(([A-Za-z]+)\)", seg)
        if call and call[1] == "ofType":
            if not pending or call[2].lower() not in [t.lower() for t in pending]:
                return False
            owner, pending = call[2], None
            continue
        if pending or owner is None:
            return False
        child = r4_child(owner, call[2] if call else seg.strip("`"))
        if child is None:
            return False
        kind, value = child
        if kind == "choice":
            pending = value
        else:
            owner = value  # repeat(item) continues from item, which contains item
    return pending is None


def test_rule_expressions_exist_in_r4():
    bad = []
    for rule in load_rules()["elements"]:
        for expr in rule["paths"]:
            roots = [root_type(expr)] if root_type(expr) else sorted(RESOURCES)
            if not any(r4_valid(expr, r) for r in roots):
                bad.append(f"{rule['id']}: {expr}")
    assert not bad, bad


def test_r4_check_rejects_misspelt_paths():
    assert r4_valid("Patient.address.line", "Patient")
    assert not r4_valid("Patient.adress.line", "Patient")
    assert not r4_valid("Observation.valueString", "Observation")  # needs value.ofType(string)
    assert not r4_valid("Observation.value.ofType(Attachment)", "Observation")  # not allowed in R4


@pytest.mark.parametrize("expr", ["Patient.name.where(", "Patient..name", "Patient.name)",
                                  "Patient.name.nosuchfunction()", "Patient.name.where()"])
def test_invalid_fhirpath_fails_at_load(expr):
    rules = {"elements": [{"id": "broken", "action": "stop", "paths": [expr]}]}
    with pytest.raises(ValueError, match="broken"):
        Screen(rules)


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


def test_strings_in_arrays_are_screened(tmp_path):
    # Address.line and HumanName.given are arrays of strings, with no other field beside them.
    patient = {"resourceType": "Patient", "id": "p1", "address": [{"line": ["1 Main St"]}]}
    assert ("Patient", "address.line", "patient_direct") in rules_hit(screen([patient], tmp_path), "stop")
    patient = {"resourceType": "Patient", "id": "p1", "name": [{"given": ["Jane"]}]}
    assert ("Patient", "name", "patient_direct") in rules_hit(screen([patient], tmp_path), "stop")
    enc = {"resourceType": "Encounter", "id": "e1", "location": [{"x": {"line": ["call 555-123-4567"]}}]}
    found = screen([enc], tmp_path)
    assert ("Encounter", "location.x.line", "pattern") in rules_hit(found, "stop")
    assert {k.detector for k in found if k.rule == "pattern"} == {"phone"}


def test_fhirpath_element_rules(tmp_path):
    obs = {"resourceType": "Observation", "id": "o1", "text": {"div": "<div>x</div>"},
           "valueString": "prose", "component": [{"valueString": "more"}]}
    free = rules_hit(screen([obs], tmp_path), "free_text")
    assert {("Observation", "text.div", "narrative"),
            ("Observation", "value.ofType(string)", "free_text_elements"),
            ("Observation", "component.value.ofType(string)", "free_text_elements")} <= free
    # A rule for another resource type does not match.
    assert not [k for k in free if k[2] == "patient_direct"]


def test_attachments_reviewed(tmp_path):
    qr = {"resourceType": "QuestionnaireResponse", "id": "q1", "status": "completed",
          "item": [{"linkId": "1", "item": [{"linkId": "1.1", "answer": [{"valueAttachment": {"data": "QQ=="}}]}]}]}
    msg = {"resourceType": "Communication", "id": "c1", "status": "completed",
           "payload": [{"contentAttachment": {"url": "https://files.example.org/1"}}]}
    ext = {"resourceType": "Observation", "id": "o1",
           "extension": [{"url": "http://example.org/scan", "valueAttachment": {"data": "QQ=="}}]}
    review = rules_hit(screen([qr, msg, ext], tmp_path), "review")
    assert ("QuestionnaireResponse", "repeat(item).answer.value.ofType(Attachment)", "attachments") in review
    assert ("Communication", "payload.content.ofType(Attachment)", "attachments") in review
    assert ("Observation", "extension", "extension:unknown") in review


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
