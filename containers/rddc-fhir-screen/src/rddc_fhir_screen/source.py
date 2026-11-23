"""Source configs: what one source has confirmed about its FHIR data.

A source confirms the pseudonyms it uses in place of identifiers and names, and the
extensions it adds. The screen lets a value that matches a confirmed pseudonym pass, and
reports it as such. The file is assets/sources/<sourceId>/fhir_screen.yaml:

    source_id: src-mimic-demo
    pseudonyms:
    - resources: [Patient]
      identifier_system: http://mimic.mit.edu/fhir/mimic/identifier/patient
      identifier_pattern: '[0-9]{8}'
      name_pattern: 'Patient_[0-9]{8}'
    extensions:
      http://mimic.mit.edu/fhir/mimic/StructureDefinition/lab-priority: ok

Patterns are regular expressions that must match a whole value. An identifier is a
pseudonym when its system is identifier_system (one URI or a list) and its value matches
identifier_pattern. A name is a pseudonym when every part of it (text, family, given,
prefix, suffix) matches name_pattern; for Organization.name and other string names, the
whole string must match. A resource id is a pseudonym when it matches id_pattern.
"""

import re

import yaml

from . import r4

KEYS = {"source_id", "pseudonyms", "extensions"}
PSEUDONYM_KEYS = {"resources", "identifier_system", "identifier_pattern", "name_pattern", "id_pattern", "note"}
EXTENSION_ACTIONS = {"ok", "review", "free_text", "stop"}
NAME_PARTS = ("text", "family", "given", "prefix", "suffix")


class SourceConfigError(ValueError):
    pass


def _pattern(text, where):
    if not isinstance(text, str) or not text:
        raise SourceConfigError(f"{where}: a pattern must be a non-empty string")
    try:
        return re.compile(text)
    except re.error as exc:
        raise SourceConfigError(f"{where}: invalid pattern {text!r}: {exc}") from None


class Pseudonym:
    def __init__(self, entry, where):
        if not isinstance(entry, dict):
            raise SourceConfigError(f"{where}: expected a mapping")
        unknown = set(entry) - PSEUDONYM_KEYS
        if unknown:
            raise SourceConfigError(f"{where}: unknown keys {sorted(unknown)}")
        self.resources = entry.get("resources")
        if not isinstance(self.resources, list) or not self.resources:
            raise SourceConfigError(f"{where}: resources must list resource types")
        bad = [t for t in self.resources if t not in r4.RESOURCES]
        if bad:
            raise SourceConfigError(f"{where}: not R4 resource types: {bad}")
        systems = entry.get("identifier_system")
        self.systems = set(systems) if isinstance(systems, list) else {systems} if systems is not None else set()
        has_id = "identifier_system" in entry or "identifier_pattern" in entry
        if has_id and not (self.systems and all(isinstance(x, str) and x for x in self.systems)
                           and "identifier_pattern" in entry):
            raise SourceConfigError(f"{where}: identifier_system and identifier_pattern go together")
        self.identifier = _pattern(entry["identifier_pattern"], where) if has_id else None
        self.name = _pattern(entry["name_pattern"], where) if "name_pattern" in entry else None
        self.id = _pattern(entry["id_pattern"], where) if "id_pattern" in entry else None
        if not (self.identifier or self.name or self.id):
            raise SourceConfigError(f"{where}: give identifier_system and identifier_pattern, name_pattern "
                                    "or id_pattern")

    def identifier_matches(self, value):
        return (self.identifier is not None and isinstance(value, dict) and value.get("system") in self.systems
                and isinstance(value.get("value"), str) and bool(self.identifier.fullmatch(value["value"])))

    def id_matches(self, value):
        return self.id is not None and isinstance(value, str) and bool(self.id.fullmatch(value))

    def name_matches(self, value):
        if self.name is None:
            return False
        if isinstance(value, str):
            return bool(self.name.fullmatch(value))
        if not isinstance(value, dict):
            return False
        parts = []
        for key in NAME_PARTS:
            part = value.get(key)
            parts += part if isinstance(part, list) else [part] if part is not None else []
        return bool(parts) and all(isinstance(p, str) and self.name.fullmatch(p) for p in parts)


class Source:
    def __init__(self, source_id, pseudonyms=(), extensions=None):
        self.id = source_id
        self.pseudonyms = list(pseudonyms)
        self.extensions = dict(extensions or {})

    def is_pseudonym(self, resource_type, kind, value):
        """Whether a value of an identifier, name or resource id element is a confirmed
        pseudonym."""
        for p in self.pseudonyms:
            if resource_type in p.resources:
                if kind == "identifier" and p.identifier_matches(value):
                    return True
                if kind == "name" and p.name_matches(value):
                    return True
                if kind == "id" and p.id_matches(value):
                    return True
        return False


def load_source(path, rules, source_id=None):
    """Read and check a source config. rules: the base rules, whose extension verdicts a
    source cannot change. source_id: the batch's sourceId, which the file must name."""
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise SourceConfigError(f"{path}: expected a mapping")
    unknown = set(data) - KEYS
    if unknown:
        raise SourceConfigError(f"{path}: unknown keys {sorted(unknown)}")
    sid = data.get("source_id")
    if not isinstance(sid, str) or not sid:
        raise SourceConfigError(f"{path}: source_id is required")
    if source_id is not None and sid != source_id:
        raise SourceConfigError(f"{path} is for source {sid}, not {source_id}")
    entries = data.get("pseudonyms") or []
    if not isinstance(entries, list):
        raise SourceConfigError(f"{path}: pseudonyms must be a list")
    pseudonyms = [Pseudonym(e, f"{path}: pseudonyms[{i}]") for i, e in enumerate(entries)]
    extensions = data.get("extensions") or {}
    if not isinstance(extensions, dict):
        raise SourceConfigError(f"{path}: extensions must map URLs to actions")
    for url, action in extensions.items():
        if action not in EXTENSION_ACTIONS:
            raise SourceConfigError(f"{path}: extension {url}: action must be one of {sorted(EXTENSION_ACTIONS)}")
        if url in (rules.get("extensions") or {}):
            raise SourceConfigError(f"{path}: extension {url} is set by the shared rules; a source cannot change it")
    return Source(sid, pseudonyms, extensions)
