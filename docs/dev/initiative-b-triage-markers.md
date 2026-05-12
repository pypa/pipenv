# Initiative B Triage: `pipenv/utils/markers.py`

`pipenv/utils/markers.py` is **owned project glue**, not inlined former vendor
code. Its import head (lines 1-14) pulls `parse_marker` from
`pipenv.patched.pip._vendor.distlib.util` and `InvalidMarker`, `Marker`,
`Specifier`, and `SpecifierSet` from `pipenv.patched.pip._vendor.packaging`;
the marker/specifier semantics themselves live in those vendored libraries
and are managed by the vendor tooling, while this module only composes them
into pipenv-specific helpers (cleanup, intersection, lookup tables such as
`MAX_VERSIONS` / `DEPRECATED_VERSIONS`, and the local `RequirementError`).
There is therefore no separate vendor lineage to triage under Initiative B,
and the module can be refactored freely under Initiative E (requirement-model
consolidation) if useful. Recorded here so the "is this vendored?" question
stays closed.
