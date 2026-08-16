# Synthetic orchestration smoke payloads

These deliberately tiny payloads reproduce the documented Fink `objects` row,
and Lasair `lightcurves` array shapes. They exist
because the frozen captures do not share enough target identifiers for deterministic
multi-provider and two-object execution. IDs match the bound scenario inputs;
repeated Fink rows prove object-safe grouping. They are not authoritative provider
captures and must not replace or modify the dated evidence under `tests/fixtures`.
