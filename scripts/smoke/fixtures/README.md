# Synthetic orchestration smoke payloads

These deliberately tiny payloads reproduce the documented Fink `objects` row,
and Lasair `lightcurves` array shapes. They exist
because the frozen captures do not share enough ZTF target identifiers for deterministic
multi-provider and two-object execution. The single-target payloads use
`ZTF18abbuksn`, and all IDs match the bound scenario inputs;
repeated Fink rows prove object-safe grouping. They are not authoritative provider
captures and must not replace or modify the dated evidence under `tests/fixtures`.
