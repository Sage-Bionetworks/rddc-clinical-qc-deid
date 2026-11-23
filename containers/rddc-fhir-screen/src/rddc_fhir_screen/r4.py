"""Element types from the FHIR R4 model bundled with fhirpathpy.

The screen uses them to treat values by type (a canonical URL is not an identifier); the
tests use them to check that rule expressions name real elements.
"""

from functools import lru_cache

from fhirpathpy.models import models

MODEL = models["r4"]
_TYPES = MODEL["path2Type"]
_CHOICES = MODEL["choiceTypePaths"]
_ELSEWHERE = MODEL["pathsDefinedElsewhere"]
_PARENT = MODEL["type2Parent"]
# Paths of backbone elements (Patient.link): they have no type of their own, only children.
_BACKBONES = {key.rsplit(".", n)[0] for key in _TYPES for n in range(1, key.count("."))}
RESOURCES = frozenset(t for t, parent in _PARENT.items() if parent in ("DomainResource", "Resource"))
# Concrete names of choice elements (Observation.valueString). FHIRPath writes them as
# value.ofType(string); JSON uses the concrete name. The model lists both.
CHOICE_NAMES = frozenset(f"{path}{t[0].upper()}{t[1:]}" for path, types in _CHOICES.items() for t in types)


def child(owner, name):
    """What `name` under `owner` (a type name, or the path of a backbone element) is:
    ("type", T), ("backbone", path), ("choice", [types]) or None if R4 has no such element.
    Elements inherited from a parent type (Patient.text, from DomainResource) are found."""
    while owner:
        key = _ELSEWHERE.get(f"{owner}.{name}", f"{owner}.{name}")
        if key in _TYPES:
            return "type", _TYPES[key]
        if key in _CHOICES:
            return "choice", _CHOICES[key]
        if key in _BACKBONES:
            return "backbone", key
        owner = _PARENT.get(owner)
    return None


@lru_cache(maxsize=65536)
def element_type(resource_type, path):
    """The R4 type of the element at a JSON key path (a tuple, arrays walked through) of a
    resource, such as "canonical" for ("differential", "element", "type", "targetProfile")
    of a StructureDefinition. None if the path is not an R4 element."""
    owner, kind = resource_type, None
    for name in path:
        found = child(owner, name)
        if found is None or found[0] == "choice":
            return None
        kind, owner = found
    return owner if kind == "type" else None
