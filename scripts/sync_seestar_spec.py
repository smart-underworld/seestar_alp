#!/usr/bin/env python3
"""Flatten the seestar-spec request catalog into tests/seestar_spec/catalog.json.

seestar-spec (https://github.com/zmerlynn/seestar-spec, CC0) describes every
JSON method the Seestar firmware registers, with a JSON Schema per request.
The test suite validates the requests seestar_alp sends against it, so it
needs the schemas without the spec repo checked out. This script resolves
the catalog's $refs and keeps only what request validation uses: method
names, side-effect tiers and the params shapes (types, documented keys,
required keys, enums and numeric ranges).

Usage:
    python scripts/sync_seestar_spec.py /path/to/seestar-spec
"""

import argparse
import glob
import json
import os
import subprocess
import sys

import yaml

OUT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "tests",
    "seestar_spec",
    "catalog.json",
)
MAX_DEPTH = 6

_files = {}


def _load(path):
    path = os.path.normpath(path)
    if path not in _files:
        with open(path) as f:
            _files[path] = yaml.safe_load(f)
    return _files[path]


def _resolve(node, base, doc):
    """Follow $ref chains. Returns (node, base_dir, doc_root)."""
    while isinstance(node, dict) and "$ref" in node:
        ref, _, pointer = node["$ref"].partition("#")
        if ref:
            path = os.path.normpath(os.path.join(base, ref))
            base, doc = os.path.dirname(path), _load(path)
        target = doc
        for part in [p for p in pointer.split("/") if p]:
            target = target[part]
        node = target
    return node, base, doc


def _shape(node, base, doc, depth=0):
    """Reduce a JSON Schema node to the subset the validator understands."""
    node, base, doc = _resolve(node, base, doc)
    if not isinstance(node, dict) or depth > MAX_DEPTH:
        return {}
    out = {}
    alternatives = []
    for key in ("anyOf", "oneOf"):
        for alt in node.get(key, []):
            alternatives.append(_shape(alt, base, doc, depth + 1))
    if alternatives:
        out["anyOf"] = alternatives
    for alt in node.get("allOf", []):
        merged = _shape(alt, base, doc, depth + 1)
        for k, v in merged.items():
            if k == "properties":
                out.setdefault("properties", {}).update(v)
            elif k == "required":
                out["required"] = sorted(set(out.get("required", [])) | set(v))
            else:
                out.setdefault(k, v)

    t = node.get("type")
    if t:
        out["types"] = t if isinstance(t, list) else [t]
    if "const" in node:
        out["enum"] = [node["const"]]
    if "enum" in node:
        out["enum"] = node["enum"]
    if node.get("x-case-insensitive"):
        out["case_insensitive"] = True
    for k in ("minimum", "maximum", "minItems", "maxItems"):
        if k in node:
            out[k] = node[k]
    if "properties" in node:
        props = out.setdefault("properties", {})
        for name, sub in node["properties"].items():
            props[name] = _shape(sub, base, doc, depth + 1)
    if "required" in node:
        out["required"] = sorted(set(out.get("required", [])) | set(node["required"]))
    # Keys that are data (patternProperties, or a schema for
    # additionalProperties) cannot be checked against a fixed list.
    addl = node.get("additionalProperties")
    if "patternProperties" in node or isinstance(addl, dict):
        out["open"] = True
    if "items" in node and isinstance(node["items"], dict):
        out["items"] = _shape(node["items"], base, doc, depth + 1)
    if "prefixItems" in node:
        out["prefixItems"] = [
            _shape(p, base, doc, depth + 1) for p in node["prefixItems"]
        ]
    return out


def build(spec_root):
    catalog = os.path.join(spec_root, "catalog")
    methods = {}
    for path in sorted(glob.glob(os.path.join(catalog, "*", "methods", "*.yaml"))):
        entry = _load(path)
        if entry.get("x-retired"):
            continue
        base, doc = os.path.dirname(path), entry
        request, base, doc = _resolve(entry.get("request") or {}, base, doc)
        params = (request.get("properties") or {}).get("params")
        methods[entry["name"]] = {
            "service": path.split(os.sep)[-3],
            "tier": entry.get("side_effect_tier"),
            "params_required": "params" in (request.get("required") or []),
            "params": None if params is None else _shape(params, base, doc),
        }
    try:
        rev = subprocess.check_output(
            ["git", "-C", spec_root, "rev-parse", "HEAD"], text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        rev = "unknown"
    return {
        "source": "https://github.com/zmerlynn/seestar-spec",
        "license": "CC0-1.0",
        "revision": rev,
        "methods": methods,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec_root", help="path to a seestar-spec checkout")
    parser.add_argument("-o", "--output", default=OUT)
    args = parser.parse_args(argv)
    data = build(args.spec_root)
    with open(args.output, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")
    print(f"wrote {len(data['methods'])} methods to {os.path.normpath(args.output)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
