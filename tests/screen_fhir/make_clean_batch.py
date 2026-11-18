"""Build tests/screen_fhir/clean/fhir from tests/screen_fhir/dirty/fhir.

dirty/ is rddc-fhir-to-omop's 8-patient Synthea test batch (synthetic data, with the names,
addresses, SSNs, NPIs and device identifiers Synthea writes). clean/ is the same batch
with what screen_fhir stops on removed, as a contributor would before deposit:

- Patient: name, telecom, address (all but state, postalCode and country), identifier,
  photo, contact, link, and the mother's maiden name and birthplace extensions;
- Practitioner, PractitionerRole, Organization, Location: name, alias, identifier,
  telecom, address, position, photo;
- Device: udiCarrier, serialNumber, distinctIdentifier;
- every Reference.display; a conditional reference (Practitioner?identifier=...|NPI) is
  replaced by a literal reference to the resource's id, so references still resolve.

Dates, ZIP codes and free text stay: the screen reports them, and they do not stop a
batch. Run, then regenerate the sidecar (make fixtures):
    python3 -I tests/screen_fhir/make_clean_batch.py
"""

import gzip
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC, DST = HERE / "dirty" / "fhir", HERE / "clean" / "fhir"
SITE_TYPES = ("Practitioner", "PractitionerRole", "Organization", "Location")
PATIENT_DROP = ("name", "telecom", "identifier", "photo", "contact", "link")
SITE_DROP = ("name", "alias", "identifier", "telecom", "address", "position", "photo")
DEVICE_DROP = ("udiCarrier", "serialNumber", "distinctIdentifier")
EXT_DROP = ("http://hl7.org/fhir/StructureDefinition/patient-mothersMaidenName",
            "http://hl7.org/fhir/StructureDefinition/patient-birthPlace")


def read(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write(path, resources):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
        for r in resources:
            gz.write((json.dumps(r, separators=(",", ":")) + "\n").encode())


def identifier_index():
    """'Type?identifier=system|value' -> 'Type/id' for every clinician and site."""
    out = {}
    for t in SITE_TYPES:
        p = SRC / f"{t}.ndjson.gz"
        if not p.exists():
            continue
        for r in read(p):
            for i in r.get("identifier", []):
                out[f"{t}?identifier={i.get('system')}|{i.get('value')}"] = f"{t}/{r['id']}"
    return out


def scrub_refs(node, index):
    if isinstance(node, dict):
        if "reference" in node:
            node.pop("display", None)
            ref = node["reference"]
            if isinstance(ref, str) and "?identifier=" in ref:
                node["reference"] = index.get(ref, ref.split("?", 1)[0])
        for v in node.values():
            scrub_refs(v, index)
    elif isinstance(node, list):
        for v in node:
            scrub_refs(v, index)


def clean(r, index):
    t = r.get("resourceType")
    if t == "Patient":
        for k in PATIENT_DROP:
            r.pop(k, None)
        r["extension"] = [e for e in r.get("extension", []) if e.get("url") not in EXT_DROP]
        r["address"] = [{k: a[k] for k in ("state", "postalCode", "country") if k in a} for a in r.get("address", [])]
    elif t in SITE_TYPES:
        for k in SITE_DROP:
            r.pop(k, None)
    elif t == "Device":
        for k in DEVICE_DROP:
            r.pop(k, None)
    scrub_refs(r, index)
    return r


def main():
    index = identifier_index()
    for p in sorted(SRC.glob("*.ndjson.gz")):
        write(DST / p.name, [clean(r, index) for r in read(p)])
    print(f"wrote {DST}")


if __name__ == "__main__":
    main()
