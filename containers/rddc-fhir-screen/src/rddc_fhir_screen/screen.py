"""Screen FHIR R4 files for identifiers.

Reads NDJSON (optionally gzipped), a Bundle or a single resource, walks every resource
(Bundle entries and contained resources too) and reports findings by rule. Findings
never include the values found: only the resource type, the element path, the rule or
detector, and how many values matched.

Element rules are FHIRPath expressions, evaluated with the R4 model. The checks that apply
to every value (patterns, dates, keys, reference display text and extensions) walk the JSON
tree instead: they are about ten times faster that way than with descendants().
"""

import gzip
import json
import re
from collections import Counter
from dataclasses import dataclass
from importlib import resources as pkg

import fhirpathpy
import yaml
from antlr4 import CommonTokenStream, InputStream, Token
from antlr4.error.ErrorListener import ErrorListener
from fhirpathpy.models import models as fhir_models
from fhirpathpy.parser.generated.FHIRPathLexer import FHIRPathLexer
from fhirpathpy.parser.generated.FHIRPathParser import FHIRPathParser

from rddc_screen_common import detectors

from .r4 import element_type

PROPERTY = {"stop": "direct_identifiers", "dates": "dates", "zip_codes": "zip_codes", "free_text": "free_text"}
# The properties this screen is authoritative for. The orchestrator replaces a file's
# predicted values of these with the screen's report.
CHECKED = sorted(PROPERTY.values())
R4 = fhir_models["r4"]
# Extension values that can carry identity, or a whole document.
IDENTIFYING_VALUES = ("valueString", "valueHumanName", "valueAddress", "valueContactPoint", "valueIdentifier",
                      "valueAttachment")


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


def leaves(node, path=(), parent=None, key=None):
    """(path of keys, parent dict, key, value) for every scalar; arrays are walked through.

    A scalar inside an array (Address.line, HumanName.given) is reported with the key and
    dict that hold the array."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from leaves(v, path + (k,), node, k)
    elif isinstance(node, list):
        for v in node:
            yield from leaves(v, path, parent, key)
    elif path:
        yield path, parent, key, node


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


def root_type(expr):
    """The resource type an expression starts with (Patient.name), or None for an expression
    that applies to every resource (note.text)."""
    m = re.match(r"([A-Z][A-Za-z0-9]*)(?:\.|$)", expr)
    return m.group(1) if m else None


def report_path(expr):
    """The expression as written in findings: without its resource type or backticks."""
    rt = root_type(expr)
    return (expr[len(rt) + 1:] if rt else expr).replace("`", "")


class _RaiseOnError(ErrorListener):
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        raise ValueError(f"column {column}: {msg}")


def check_syntax(expr):
    """Parse strictly. fhirpathpy's own parser recovers from syntax errors silently, so
    `Patient..name` or `Patient.name)` would compile and match something else, or nothing."""
    lexer = FHIRPathLexer(InputStream(expr))
    lexer.removeErrorListeners()
    lexer.addErrorListener(_RaiseOnError())
    tokens = CommonTokenStream(lexer)
    parser = FHIRPathParser(tokens)
    parser.removeErrorListeners()
    parser.addErrorListener(_RaiseOnError())
    parser.expression()
    if tokens.LA(1) != Token.EOF:
        raise ValueError("unexpected text after the expression")


def present(value):
    return not (value is None or (isinstance(value, (str, list, dict)) and not value))


class Element:
    """One FHIRPath expression of an element rule."""

    def __init__(self, rule, expr):
        self.rule, self.expr = rule, expr
        self.resource_type = root_type(expr)
        self.path = report_path(expr)
        try:
            check_syntax(expr)
            self.fn = fhirpathpy.compile(expr, model=R4)
            # Unknown functions and wrong arities only fail on evaluation.
            self.fn({"resourceType": self.resource_type or "Basic"})
        except Exception as exc:  # fhirpathpy raises bare Exceptions
            raise ValueError(f"rule {rule['id']}: invalid FHIRPath {expr!r}: {exc}") from exc

    def matches(self, res):
        return any(present(v) for v in self.fn(res))


class Screen:
    def __init__(self, rules, provider_policy="stop"):
        if provider_policy not in ("stop", "review"):
            raise ValueError("provider_policy must be stop or review")
        self.rules = rules
        self.provider_policy = provider_policy
        self.elements = [Element(r, expr) for r in rules.get("elements", []) for expr in r["paths"]]
        pat = rules.get("patterns", {})
        self.skip_keys = set(pat.get("skip_keys", []))
        self.skip_types = set(pat.get("skip_types", []))
        self.skip_resources = set(rules.get("skip_resources", []))
        self.url_hosts = tuple(pat.get("url_hosts", []))
        self.pattern_action = pat.get("action", "stop")
        self.date_skip = set(rules.get("dates", {}).get("skip_under", []))

    def action(self, a):
        return self.provider_policy if a == "provider" else a

    def resource(self, res, found, first, n):
        rt = res.get("resourceType", "?")
        res = {k: v for k, v in res.items() if k != "contained"}  # screened as resources of their own

        def add(path, rule, detector, action):
            """Count a finding. An element rule counts once per resource it matches."""
            k = Key(rt, ".".join(path), rule, detector, self.action(action))
            found[k] += 1
            first.setdefault(k, n)

        if rt in self.skip_resources:
            # Definitions (profiles, code systems, forms) describe data and hold none.
            add((), "definition_resource", "", "skipped")
            return

        for el in self.elements:
            if el.resource_type in (None, rt) and el.matches(res):
                add((el.path,), el.rule["id"], "", el.rule["action"])

        for path, parent, key, value in leaves(res):
            if value is None or value == "" or key == "resourceType":
                continue
            if key in self.rules.get("keys", {}):
                add(path, f"key:{key}", "", self.rules["keys"][key])
            if not isinstance(value, str):
                continue
            if detectors.is_full_date(value) and not (set(path) & self.date_skip):
                add(path, "dates", "", self.rules.get("dates", {}).get("action", "dates"))
            if (key not in self.skip_keys and not (key == "display" and "reference" in parent)
                    and element_type(rt, path) not in self.skip_types):
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
                elif verdict is None and any(k in IDENTIFYING_VALUES for k in valued):
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
