# UI FIXTURE CONTRACT

**Every input to the UI is a serialized Alertissimo Portfolio.** A Portfolio may
contain one `SemanticRecord` or thousands. A bare `SemanticRecord` and raw broker
data are never top-level UI inputs; generated Portfolio JSON is the only fixture
form the UI needs to understand.

## Presentation model

- Summary records become thin object-search rows or cards.
- One selected record becomes an individual/detail page.
- Same-family records in one Portfolio become a group/hybrid page.
- The whole Portfolio becomes a complete object/event page.
- Several Portfolio JSON files enable many-object/search-result development.

No separate Portfolio-search row schema is defined.

## Offline data flow

```text
git pull
            ↓
python scripts/build_ui_fixtures.py
            ↓
.ui-fixtures/portfolios/*.json
            ↓
       UI development
```

`tests/fixtures/**` is frozen/raw evidence. UI code must never consume it
directly. `scripts/build_ui_fixtures.py` deterministically normalizes that
evidence through the production mappings and RecordBuilder.

`.ui-fixtures/portfolios/**` is generated normalized development data. Every
file there is a serialized Portfolio.

The trust categories are **REAL / FROZEN** (authoritative existing captures),
**REAL / UI CAPTURE** (the frozen Fink LSST/ZTF pair), **COMPOSED / REAL
RECORDS** (real normalized histories intentionally colocated), **DERIVED /
REAL** (one complete real record), and **SYNTHETIC / UI ONLY** (ontology-valid
representation coverage). The known LSST/ZTF composition is a fixture
association, not automated entity resolution, and deliberately adds no edge.

## Useful fixtures

- **ONE THIN OBJECT:** `minimal_summary_real.json`
- **ONE DETECTION:** `minimal_detection_real.json`
- **NORMAL LSST:** `lsst_fink_170587117485817955.json`
- **RICH LSST:** `lsst_lasair_313761042336317573.json`
- **RICH / STRESS ZTF:** `ztf_alerce_ZTF18abbuksn.json`
- **CROSSMATCH-RICH ZTF:** `ztf_antares_ZTF20aafqubg.json`
- **ONE OBJECT / MULTIPLE BROKERS:** `multibroker_lsst_170587117485817955.json`
- **ONE OBJECT / MULTIPLE SURVEYS:** `multisurvey_fink_313936986529333309__ZTF18acurdih.json`
- **ALL FIRST-LEVEL SEMANTIC FAMILIES:** `semantic_gallery_synthetic.json` plus the real corpus
- **MANY OBJECTS:** load several generated Portfolio JSON files at once

## First commands

```bash
python scripts/build_ui_fixtures.py
python scripts/list_ui_fixtures.py
python -m streamlit run alertissimo/ui/app.py
```
