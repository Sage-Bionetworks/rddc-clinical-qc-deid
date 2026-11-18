"""Screen FHIR R4 files for identifiers.

Reads NDJSON (optionally gzipped), a Bundle or a single resource, walks every resource
(Bundle entries and contained resources too) and reports findings by rule. Findings
never include the values found: only the resource type, the element path, the rule or
detector, and how many values matched.
"""

import gzip
import json
from collections import Counter
from dataclasses import dataclass
from importlib import resources as pkg

import yaml

from rddc_screen_common import detectors

PROPERTY = {"stop": "direct_identifiers", "dates": "dates", "zip_codes": "zip_codes", "free_text": "free_text"}
# The properties this screen is authoritative for. The orchestrator replaces a file's
# predicted values of these with the screen's report.
CHECKED = sorted(PROPERTY.values())


def load_rules(path=None):
    text = open(path).read() if path else pkg.files(__package__).joinpath("rules.yaml").read_text()
    return yaml.safe_load(text)


@dataclass(frozen=True)
class Key:
    resource_type: str
    path: str
    rule: str
    detector: str
    action: str


def resources_in(path):
    """(record number, resource) for every top-level resource in the file."""
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        head = fh.read(1)
        while head and head.isspace():
            head = fh.read(1)
        rest = fh.read()
    text = head + rest
    if not text.strip():
        return
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        doc = None
    if isinstance(doc, dict):
        if doc.get("resourceType") == "Bundle":
            for i, e in enumerate(doc.get("entry") or [], 1):
                if isinstance(e.get("resource"), dict):
                    yield i, e["resource"]
        else:
            yield 1, doc
        return
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip():
            yield i, json.loads(line)


def leaves(node, path=()):
    """(path of keys, parent dict, key, value) for every scalar; arrays are walked through."""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                yield from leaves(v, path + (k,))
            else:
                yield path + (k,), node, k, v
    elif isinstance(node, list):
        for v in node:
            yield from leaves(v, path)


def dicts(node, path=()):
    """(path, dict) for every object in the tree, the root included."""
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from dicts(v, path + (k,))
    elif isinstance(node, list):
        for v in node:
            yield from dicts(v, path)


def reference_type(ref):
    """The resource type a reference points to: Patient/1, Practitioner?identifier=..., or
    an absolute URL ending in Type/id."""
    if not isinstance(ref, str) or ref.startswith(("#", "urn:")):
        return None
    head = ref.split("?", 1)[0]
    parts = [p for p in head.split("/") if p]
    if "?" in ref:
        return parts[-1] if parts else None
    return parts[-2] if len(parts) >= 2 else None


class Screen:
    def __init__(self, rules, provider_policy="stop"):
        if provider_policy not in ("stop", "review"):
            raise ValueError("provider_policy must be stop or review")
        self.rules = rules
        self.provider_policy = provider_policy
        self.elements = [(r, tuple(tuple(p.split(".")) for p in r["paths"])) for r in rules.get("elements", [])]
        pat = rules.get("patterns", {})
        self.skip_keys = set(pat.get("skip_keys", []))
        self.url_hosts = tuple(pat.get("url_hosts", []))
        self.pattern_action = pat.get("action", "stop")
        self.date_skip = set(rules.get("dates", {}).get("skip_under", []))

    def action(self, a):
        return self.provider_policy if a == "provider" else a

    def resource(self, res, found, first, n):
        rt = res.get("resourceType", "?")
        res = {k: v for k, v in res.items() if k != "contained"}  # screened as resources of their own

        seen = set()

        def add(path, rule, detector, action, once=False):
            """Count a finding; once: at most once per resource (a matched element)."""
            k = Key(rt, ".".join(path), rule, detector, self.action(action))
            if once:
                if k in seen:
                    return
                seen.add(k)
            found[k] += 1
            first.setdefault(k, n)

        for path, parent, key, value in leaves(res):
            if value is None or value == "" or key == "resourceType":
                continue
            for rule, paths in self.elements:
                if rule["resources"] == ["*"] or rt in rule["resources"]:
                    for p in paths:
                        if path[:len(p)] == p:
                            add(p, rule["id"], "", rule["action"], once=True)
            if key in self.rules.get("keys", {}):
                add(path, f"key:{key}", "", self.rules["keys"][key])
            if not isinstance(value, str):
                continue
            if detectors.is_full_date(value) and not (set(path) & self.date_skip):
                add(path, "dates", "", self.rules.get("dates", {}).get("action", "dates"))
            if key not in self.skip_keys and not (key == "display" and "reference" in parent):
                for d in detectors.scan(value, self.url_hosts):
                    add(path, "pattern", d, self.pattern_action)
        rd = self.rules.get("reference_display", {})
        exts = self.rules.get("extensions", {})
        for path, d in dicts(res):
            if "reference" in d:
                target = reference_type(d["reference"])
                if d.get("display"):
                    action = ("stop" if target in rd.get("stop", []) else "provider" if target in rd.get("provider", [])
                              else rd.get("other", "free_text"))
                    add(path + ("display",), "reference_display", target or "", action)
                if target in rd.get("provider", []) and "?" in str(d["reference"]):
                    add(path + ("reference",), "reference_identifier", target, self.rules.get("reference_provider_identifier", "provider"))
            if "url" in d and path and path[-1] in ("extension", "modifierExtension"):
                verdict = exts.get(d["url"])
                valued = [k for k in d if k.startswith("value")]
                if verdict in ("stop", "review", "free_text"):
                    add(path, f"extension:{d['url']}", "", verdict)
                elif verdict is None and any(k in ("valueString", "valueHumanName", "valueAddress", "valueContactPoint",
                                                     "valueIdentifier") for k in valued):
                    add(path, "extension:unknown", d["url"], "review")

    def file(self, path):
        found, first = Counter(), {}
        records = 0
        for n, res in resources_in(path):
            records += 1
            self.resource(res, found, first, n)
            for c in res.get("contained") or []:
                if isinstance(c, dict):
                    self.resource(c, found, first, n)
        return records, found, first


def properties(found):
    return sorted({PROPERTY[k.action] for k in found if k.action in PROPERTY})
