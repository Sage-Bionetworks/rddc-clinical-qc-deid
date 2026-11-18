import csv
import json
import os
from pathlib import Path

import pytest

from rddc_omop_screen.cli import main
from rddc_omop_screen.screen import Screen, load_rules, properties

FIXTURES = Path(os.environ.get("RDDC_FIXTURES", Path(__file__).resolve().parents[3] / "tests" / "screen_omop"))


def table(tmp_path, name, rows):
    p = tmp_path / f"{name}.csv"
    with open(p, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return str(p)


def screen(tmp_path, name, rows, **kw):
    _, found, _ = Screen(load_rules(), **kw).file(table(tmp_path, name, rows), name)
    return found


def hits(found, action):
    return {(k.column, k.rule, k.detector) for k in found if k.action == action}


def test_location_address_stops_zip_inventoried(tmp_path):
    found = screen(tmp_path, "location", [{"location_id": "1", "address_1": "1 Main St", "city": "Boston",
                                           "state": "MA", "zip": "02139"}])
    assert ("address_1", "column:stop", "") in hits(found, "stop")
    assert ("city", "column:stop", "") in hits(found, "stop")
    assert properties(found) == ["direct_identifiers", "zip_codes"]


def test_empty_identifier_columns_pass(tmp_path):
    found = screen(tmp_path, "location", [{"location_id": "1", "address_1": "", "city": "", "state": "MA", "zip": ""}])
    assert properties(found) == []


def test_provider_policy(tmp_path):
    rows = [{"provider_id": "1", "provider_name": "Dr. Who", "npi": "9999942094"}]
    assert ("npi", "column:provider", "") in hits(screen(tmp_path, "provider", rows), "stop")
    found = screen(tmp_path, "provider", rows, provider_policy="review")
    assert ("npi", "column:provider", "") in hits(found, "review")
    assert properties(found) == []


def test_udi_device_identifier_only(tmp_path):
    ok = screen(tmp_path, "device_exposure", [{"unique_device_id": "(01)00844588003288"}])
    assert properties(ok) == []
    bad = screen(tmp_path, "device_exposure", [{"unique_device_id": "(01)00844588003288(17)141120(10)7654321D(21)10987654d321"}])
    assert ("unique_device_id", "udi", "") in hits(bad, "stop")
    assert ("production_id", "column:stop", "") in hits(screen(tmp_path, "device_exposure", [{"production_id": "X1"}]), "stop")


def test_person_source_value(tmp_path):
    rows = [{"person_id": "1", "person_source_value": "592ad309-7d98-4a5d", "year_of_birth": "1980",
             "month_of_birth": "1", "day_of_birth": "2"}]
    found = screen(tmp_path, "person", rows)
    assert ("person_source_value", "source_key", "unchecked") in hits(found, "review")
    assert "dates" in properties(found)  # day_of_birth: a full birth date
    found = screen(tmp_path, "person", rows, research_id_pattern=r"RID-\d{4}")
    assert ("person_source_value", "source_key", "not_research_id") in hits(found, "stop")
    rows[0]["person_source_value"] = "RID-0001"
    assert "direct_identifiers" not in properties(screen(tmp_path, "person", rows, research_id_pattern=r"RID-\d{4}"))


def test_patterns_and_long_strings(tmp_path):
    found = screen(tmp_path, "observation", [{"observation_id": "1", "observation_date": "2020-01-02",
                                              "value_as_string": "call 555-123-4567",
                                              "observation_source_value": "x" * 100}])
    assert ("value_as_string", "pattern", "phone") in hits(found, "stop")
    assert ("observation_source_value", "long_string", "") in hits(found, "free_text")
    assert ("observation_date", "dates", "") in hits(found, "dates")


def test_note_text_is_free_text_not_screened(tmp_path):
    found = screen(tmp_path, "note", [{"note_id": "1", "note_text": "SSN 123-45-6789"}])
    assert properties(found) == ["free_text"]


def test_allow_list(tmp_path):
    rows = [{"person_id": "1", "gender_source_value": "female"}, {"person_id": "2", "gender_source_value": "F (other)"}]
    found = screen(tmp_path, "person", rows, allow_list={("person", "gender_source_value"): {"female"}})
    assert ("gender_source_value", "allow_list", "") in hits(found, "review")
    assert sum(n for k, n in found.items() if k.rule == "allow_list") == 1
    # Columns with a rule of their own are not allow-list checked.
    found = screen(tmp_path, "person", [{"person_source_value": "RID-0001"}], research_id_pattern=r"RID-\d{4}",
                   allow_list={})
    assert not [k for k in found if k.rule == "allow_list"]


def test_person_links_and_unknown_table(tmp_path):
    found = screen(tmp_path, "fact_relationship", [{"domain_concept_id_1": "56", "fact_id_1": "1",
                                                    "domain_concept_id_2": "56", "fact_id_2": "2",
                                                    "relationship_concept_id": "4326600"}])
    assert ("", "person_link", "") in hits(found, "review")
    assert ("", "unknown_table", "") in hits(screen(tmp_path, "my_extra", [{"a": "1"}]), "review")


def run_batch(kind, tmp_path):
    doc = json.loads((FIXTURES / kind / "_sidecar.json").read_text())
    results, findings = [], []
    for i, item in enumerate(x for x in doc["distribution"] if x.get("cdmTable")):
        r, f = tmp_path / f"{kind}{i}.json", tmp_path / f"{kind}{i}.tsv"
        main(["file", str(FIXTURES / kind / item["contentUrl"]), "--file-id", item["@id"], "--name", item["name"],
              "--table", item["cdmTable"], "--encoding-format", item["encodingFormat"],
              "--findings", str(f), "--result", str(r)])
        results.append(str(r))
        findings.append(str(f))
    main(["report", *results, "--findings", *findings, "--out-dir", str(tmp_path)])
    return {x["file"]: x["properties"] for x in json.loads((tmp_path / "results.json").read_text())}, doc


@pytest.mark.skipif(not (FIXTURES / "dirty").exists(), reason="fixtures not mounted")
def test_dirty_batch_quarantines(tmp_path):
    props, doc = run_batch("dirty", tmp_path)
    names = {x["@id"]: x["name"] for x in doc["distribution"]}
    held = sorted(names[f] for f, p in props.items() if "direct_identifiers" in p)
    assert held == ["omop/care_site.csv", "omop/device_exposure.csv", "omop/location.csv", "omop/provider.csv"]
    rows = (tmp_path / "findings.tsv").read_text()
    assert "Boston" not in rows and "9999942094" not in rows  # no values in findings


@pytest.mark.skipif(not (FIXTURES / "clean").exists(), reason="fixtures not mounted")
def test_clean_batch_passes(tmp_path):
    props, _ = run_batch("clean", tmp_path)
    assert props and not [f for f, p in props.items() if "direct_identifiers" in p]
    assert any("dates" in p for p in props.values())
