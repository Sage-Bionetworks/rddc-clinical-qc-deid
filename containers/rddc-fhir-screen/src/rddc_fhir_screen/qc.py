"""Check readable JSON and resource structure, without full FHIR profile validation."""

import gzip
import json
import re
import zlib

from rddc_screen_common.qc import QCError


def resource(value, record):
    if not isinstance(value, dict):
        raise QCError("resource_not_object", record)
    kind = value.get("resourceType")
    if not isinstance(kind, str) or not re.fullmatch(r"[A-Z][A-Za-z0-9]*", kind):
        raise QCError("invalid_resource_type", record)
    if "contained" in value:
        if not isinstance(value["contained"], list):
            raise QCError("contained_not_array", record)
        for child in value["contained"]:
            resource(child, record)
    if kind == "Bundle":
        entries = value.get("entry", [])
        if not isinstance(entries, list):
            raise QCError("bundle_entry_not_array", record)
        for index, entry in enumerate(entries, 1):
            if not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict):
                raise QCError("bundle_entry_resource_required", index)
            resource(entry["resource"], index)
        return len(entries)
    return 1


def reject_constant(_value):
    raise ValueError("non_json_constant")


def validate(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8") as fh:
            text = fh.read()
    except zlib.error:
        raise QCError("unreadable_file") from None
    if not text.strip():
        raise QCError("empty_file")
    try:
        doc = json.loads(text, parse_constant=reject_constant)
    except ValueError:
        records = 0
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                doc = json.loads(line, parse_constant=reject_constant)
            except ValueError:
                raise QCError("invalid_json", number) from None
            records += resource(doc, number)
        return records
    return resource(doc, 1)
