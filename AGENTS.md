# AGENTS.md

## Project goal
Build a canonical feature registry for astronomical brokers (Fink, Lasair, ALeRCE, Antares).

## Rules
- Never delete existing feature_ids
- Prefer adding mappings over renaming
- Preserve original docs
- Keep L0–L3 separation strict

## Structure
registry/
  brokers.yaml
  features/
    L0_alert/
    L1_object/
    L2_timeseries/
    L3_derived/
