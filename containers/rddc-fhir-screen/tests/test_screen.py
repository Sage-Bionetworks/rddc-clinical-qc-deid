import gzip
import json
import os
import re
from pathlib import Path

import pytest
from rddc_fhir_screen import r4
from rddc_fhir_screen.screen import Screen, load_rules, properties, reference_type, root_type
from rddc_fhir_screen.source import SourceConfigError, load_source

FIXTURES = Path(os.environ.get("RDDC_FIXTURES", Path(__file__).resolve().parents[3] / "tests" / "screen_fhir"))
SOURCES = Path(os.environ.get("RDDC_SOURCES", Path(__file__).resolve().parents[3] / "assets" / "sources"))


def screen(resources, tmp_path, policy="stop", source=None):
    p = tmp_path / "x.ndjson"
    p.write_text("".join(json.dumps(r) + "\n" for r in resources))
    _, found, _ = Screen(load_rules(), policy, source).file(str(p))
    return found


def source_config(tmp_path, text, source_id=None):
    p = tmp_path / "fhir_screen.yaml"
    p.write_text(text)
    return load_source(str(p), load_rules(), source_id)


PSEUDONYMS = """
source_id: src-test
pseudonyms:
- resources: [Patient]
  identifier_system: https://example.org/id/patient
  identifier_pattern: 'P[0-9]{6}'
  name_pattern: 'Patient_[0-9]{6}'
- resources: [Organization]
  name_pattern: 'Site [0-9]{2}'
extensions:
  https://example.org/StructureDefinition/priority: ok
"""


def rules_hit(found, action):
    return {(k.resource_type, k.path, k.rule) for k in found if k.action == action}


def r4_child(owner, name):
    """r4.child, but a concrete choice name (valueString) is not an element in FHIRPath."""
    found = r4.child(owner, name)
    if found and found[0] == "type" and f"{owner}.{name}" in r4.CHOICE_NAMES:
        return None
    return found


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
            roots = [root_type(expr)] if root_type(expr) else sorted(r4.RESOURCES)
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
    found = screen([{"resourceType": "Patient", "id": "0b8e3c1e-5f0a-4c47-9a39-7c2f0f6d1a11", "gender": "female", "birthDate": "1980"}], tmp_path)
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


def test_canonical_urls_are_not_identifiers(tmp_path):
    qr = {"resourceType": "QuestionnaireResponse", "id": "q1", "status": "completed",
          "questionnaire": "https://forms.example.org/Questionnaire/intake|1.0"}
    plan = {"resourceType": "CarePlan", "id": "c1", "instantiatesCanonical": ["https://example.org/PlanDefinition/x"]}
    found = screen([qr, plan], tmp_path)
    assert not [k for k in found if k.rule == "pattern"], found
    # URLs in other values are still checked, and attachment URLs are reported for review.
    doc = {"resourceType": "DocumentReference", "id": "d1",
           "content": [{"attachment": {"url": "https://ehr.example.org/docs/12345.pdf"}}]}
    obs = {"resourceType": "Observation", "id": "o1", "valueString": "see https://ehr.example.org/p/1"}
    found = screen([doc, obs], tmp_path)
    assert ("Observation", "valueString", "pattern") in rules_hit(found, "stop")
    assert ("DocumentReference", "content.attachment.url", "attachments") in rules_hit(found, "review")


def test_definition_resources_are_skipped(tmp_path):
    sd = {"resourceType": "StructureDefinition", "id": "s1", "url": "https://example.org/sd",
          "contact": [{"telecom": [{"system": "email", "value": "author@example.org"}]}],
          "date": "2026-01-01"}
    vs = {"resourceType": "ValueSet", "id": "v1", "copyright": "See https://example.org/terms"}
    found = screen([sd, vs, sd], tmp_path)
    assert properties(found) == []
    assert {(k.resource_type, k.rule, k.action, n) for k, n in found.items()} == {
        ("StructureDefinition", "definition_resource", "skipped", 2), ("ValueSet", "definition_resource", "skipped", 1)}
    # A contained definition is skipped; the resource that contains it is screened.
    qr = {"resourceType": "QuestionnaireResponse", "id": "q1", "status": "completed",
          "contained": [{"resourceType": "Questionnaire", "id": "q", "status": "active",
                         "contact": [{"telecom": [{"system": "email", "value": "author@example.org"}]}]}],
          "author": {"reference": "Patient/p1", "display": "Jane Doe"}}
    found = screen([qr], tmp_path)
    assert ("Questionnaire", "", "definition_resource") in rules_hit(found, "skipped")
    assert ("QuestionnaireResponse", "author.display", "reference_display") in rules_hit(found, "stop")


def test_skip_settings_name_r4_types():
    rules = load_rules()
    assert set(rules["skip_resources"]) <= r4.RESOURCES
    for rule in rules["elements"]:
        assert set(rule.get("except", [])) <= r4.RESOURCES, rule["id"]
    assert r4.element_type("StructureDefinition", ("differential", "element", "type", "targetProfile")) == "canonical"
    assert r4.element_type("Media", ("content", "url")) == "url"


def test_confirmed_pseudonyms_pass(tmp_path):
    src = source_config(tmp_path, PSEUDONYMS, "src-test")
    patient = {"resourceType": "Patient", "id": "0b8e3c1e-5f0a-4c47-9a39-7c2f0f6d1a11", "name": [{"family": "Patient_000123"}],
               "identifier": [{"system": "https://example.org/id/patient", "value": "P000123"}]}
    site = {"resourceType": "Organization", "id": "o1", "name": "Site 04"}
    found = screen([patient, site], tmp_path, source=src)
    assert properties(found) == []
    assert rules_hit(found, "pseudonym") == {("Patient", "name", "patient_direct"),
                                            ("Patient", "identifier", "patient_direct"),
                                            ("Organization", "name", "provider_identity")}
    assert {k.detector for k in found if k.action == "pseudonym"} == {"src-test"}
    # Without the source config the same data is stopped.
    assert "direct_identifiers" in properties(screen([patient, site], tmp_path))


@pytest.mark.parametrize("patient", [
    # An MRN beside the pseudonym, a value that does not match, the wrong system, a real given name.
    {"identifier": [{"system": "https://example.org/id/patient", "value": "P000123"},
                    {"system": "https://example.org/id/patient", "value": "MRN-55"}]},
    {"identifier": [{"system": "https://example.org/id/patient", "value": "P000123x"}]},
    {"identifier": [{"system": "https://hospital.example.org/mrn", "value": "P000123"}]},
    {"identifier": [{"value": "P000123"}]},
    {"name": [{"family": "Patient_000123", "given": ["Jane"]}]},
    {"name": [{"text": "Jane Doe"}]},
])
def test_other_identifiers_and_names_still_stop(tmp_path, patient):
    src = source_config(tmp_path, PSEUDONYMS, "src-test")
    found = screen([{"resourceType": "Patient", "id": "p1", **patient}], tmp_path, source=src)
    assert "direct_identifiers" in properties(found), found
    assert not rules_hit(found, "pseudonym")


def test_pseudonyms_apply_to_their_resource_types_only(tmp_path):
    src = source_config(tmp_path, PSEUDONYMS, "src-test")
    rp = {"resourceType": "RelatedPerson", "id": "r1",
          "identifier": [{"system": "https://example.org/id/patient", "value": "P000123"}]}
    assert "direct_identifiers" in properties(screen([rp], tmp_path, source=src))


def test_source_extensions(tmp_path):
    src = source_config(tmp_path, PSEUDONYMS, "src-test")
    obs = {"resourceType": "Observation", "id": "o1",
           "extension": [{"url": "https://example.org/StructureDefinition/priority", "valueString": "STAT"}]}
    assert rules_hit(screen([obs], tmp_path), "review")
    assert not rules_hit(screen([obs], tmp_path, source=src), "review")


@pytest.mark.parametrize("text, message", [
    (PSEUDONYMS, "not src-other"),
    ("source_id: src-test\nunknown: 1\n", "unknown keys"),
    ("pseudonyms: []\n", "source_id is required"),
    ("source_id: src-test\npseudonyms:\n- resources: [Patient]\n  identifier_pattern: '[0-9'\n"
     "  identifier_system: https://x\n", "invalid pattern"),
    ("source_id: src-test\npseudonyms:\n- resources: [Patient]\n  identifier_pattern: '[0-9]+'\n",
     "go together"),
    ("source_id: src-test\npseudonyms:\n- resources: [Patient]\n", "give identifier_system"),
    ("source_id: src-test\npseudonyms:\n- resources: [Patients]\n  name_pattern: x\n", "not R4"),
    ("source_id: src-test\nextensions:\n  http://hl7.org/fhir/StructureDefinition/patient-birthPlace: ok\n",
     "cannot change"),
    ("source_id: src-test\nextensions:\n  https://example.org/x: allow\n", "action must be"),
])
def test_invalid_source_configs(tmp_path, text, message):
    with pytest.raises(SourceConfigError, match=message):
        source_config(tmp_path, text, "src-other" if message == "not src-other" else "src-test")


@pytest.mark.skipif(not SOURCES.exists(), reason="source configs not mounted")
def test_repository_source_configs_load():
    configs = sorted(SOURCES.glob("*/fhir_screen.yaml"))
    assert configs
    for p in configs:
        assert load_source(str(p), load_rules(), p.parent.name).id == p.parent.name


UUID = "0b8e3c1e-5f0a-4c47-9a39-7c2f0f6d1a11"


@pytest.mark.parametrize("res, rule", [
    ({"resourceType": "Patient", "id": "MRN0012345"}, "person_resource_ids"),
    ({"resourceType": "RelatedPerson", "id": "12345678"}, "person_resource_ids"),
    ({"resourceType": "Encounter", "id": UUID, "identifier": [{"system": "https://ehr.example.org/visit", "value": "V123"}]},
     "other_identifiers"),
    ({"resourceType": "Coverage", "id": UUID, "identifier": [{"value": "PLAN-998877"}]}, "other_identifiers"),
])
def test_resource_ids_and_other_identifiers_stop(tmp_path, res, rule):
    found = screen([res], tmp_path)
    assert rule in {k.rule for k in found if k.action == "stop"}, found


def test_opaque_ids_pass(tmp_path):
    patient = {"resourceType": "Patient", "id": UUID}
    enc = {"resourceType": "Encounter", "id": UUID,
           "identifier": [{"system": "https://ehr.example.org/visit", "value": "urn:uuid:" + UUID}]}
    found = screen([patient, enc], tmp_path)
    assert properties(found) == []
    assert rules_hit(found, "opaque") == {("Patient", "id", "person_resource_ids"),
                                          ("Encounter", "identifier", "other_identifiers")}
    # A clinician's id follows the provider policy.
    doc = {"resourceType": "Practitioner", "id": "npi-1234567890"}
    assert ("Practitioner", "id", "provider_resource_ids") in rules_hit(screen([doc], tmp_path, "review"), "review")


def test_product_identifiers_are_not_checked(tmp_path):
    med = {"resourceType": "Medication", "id": UUID,
           "identifier": [{"system": "http://hl7.org/fhir/sid/ndc", "value": "00904629161"}]}
    assert not [k for k in screen([med], tmp_path) if k.rule == "other_identifiers"]


def test_confirmed_resource_ids_and_identifiers(tmp_path):
    src = source_config(tmp_path, """
source_id: src-test
pseudonyms:
- resources: [Patient]
  id_pattern: 'patient-[0-9]{4}'
- resources: [Encounter, Specimen]
  identifier_system: [https://example.org/id/visit, https://example.org/id/specimen]
  identifier_pattern: '[0-9]{8}'
""", "src-test")
    patient = {"resourceType": "Patient", "id": "patient-0001"}
    enc = {"resourceType": "Encounter", "id": "e1-not-checked",
           "identifier": [{"system": "https://example.org/id/visit", "value": "20001234"}]}
    spec = {"resourceType": "Specimen", "id": UUID,
            "identifier": [{"system": "https://example.org/id/specimen", "value": "30001234"}]}
    found = screen([patient, enc, spec], tmp_path, source=src)
    assert properties(found) == [], found
    assert rules_hit(found, "pseudonym") == {("Patient", "id", "person_resource_ids"),
                                             ("Encounter", "identifier", "other_identifiers"),
                                             ("Specimen", "identifier", "other_identifiers")}
    # A pseudonym and a real number together: the real number stops it.
    enc["identifier"].append({"system": "https://ehr.example.org/mrn", "value": "MRN-55"})
    assert "direct_identifiers" in properties(screen([enc], tmp_path, source=src))


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
