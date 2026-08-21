# Alertissimo UI product plan

## Current scope

The initial UI work is deliberately limited to these two Streamlit pages:

- `alertissimo/app_plot.py`: one object and one local light-curve JSON file.
- `alertissimo/app_plot_n.py`: multiple objects from one local light-curve JSON file.

They may use fake or hardcoded data while the interaction design is developed.
They are prototypes for the scientific workflow, not yet broker clients or
production Portfolio viewers.

The first entry page is `alertissimo/app_search.py`. It offers only known
Object-ID lookup and coordinate cone search, backed by local demo candidates.
Loading a saved Portfolio is intentionally deferred.

A cone search first opens a dedicated multi-object results page. Each result
is shown as a compact scientific card; selecting a card opens the separate
single-object portfolio view. Cone-search results are not represented by a
dropdown selector.

## Product direction

Alertissimo helps astronomers collect, inspect, and combine alert information
from Fink, Lasair, Antares, and ALeRCE for LSST and ZTF sources. The essential
question during triage is: is this candidate real, interesting, new, and worth
further observation?

Do not solve this by putting every available field on the first page. Show a
short scientific summary first, then allow progressive disclosure of detailed
photometry, classification, context, images, and provenance.

## Scientist scenario

1. Search for or load a candidate (eventually by object ID, cone search, or
   saved Portfolio).
2. Triage candidates using recency, detections, brightness evolution,
   classification, and data availability.
3. Open one candidate and inspect its light curve, classifications, contextual
   matches, and image cutouts.
4. Request missing data from an appropriate broker and add the result to the
   candidate Portfolio with its provenance intact.
5. Compare selected candidates, export a scientific summary, or prepare a
   follow-up/monitoring workflow.

## UI roles

### Object portfolio: evolution of `app_plot.py`

This is the single-candidate scientific view. Its eventual layout is:

- scientific header: identity, coordinates, survey, first/last detection,
  contributing brokers, compact classification and coverage summary;
- **Overview**: decision-relevant metrics and a compact candidate summary;
- **Photometry**: detections, non-detections, forced photometry, uncertainties,
  filters, brokers, and a UTC/MJD control;
- **Classification**: classifications and probabilities by broker/model, with
  explicit disagreement rather than forced agreement;
- **Context**: host, crossmatches, redshift, and contextual classifications;
- **Images**: science, template, and difference cutouts;
- **Provenance**: endpoint, parameters, time, status, mapping/registry version,
  and source semantic record;
- **Add data**: supported requests for enriching the existing Portfolio.

The first implementation should focus only on Overview, Photometry, and
Provenance using fake data.

### Candidate workspace: evolution of `app_plot_n.py`

This is a multi-candidate triage view, not a long stack of identical charts.
Its eventual layout is:

- query/upload controls;
- filters for survey, broker, time range, band, detection count,
  classification/probability, anomaly score, and available data products;
- a sortable candidate table with concise scientific columns;
- selection of candidates for side-by-side comparison;
- drill-down into the object portfolio.

The first implementation should use hardcoded multi-object data and deliver a
filterable, sortable candidate list plus a selected-object detail view.

## Scientific plotting conventions

- Keep astronomical magnitude axes inverted.
- Use stable colors for filters (`g`, `r`, `i`, `z`) and a visually distinct
  encoding for provider/broker.
- Draw uncertainty bars and distinguish detections, upper limits, and forced
  photometry with both marker shape and legend text.
- Offer a visible filter/date control and explain empty states.
- Never silently merge conflicting classifications or measurements.

## Architecture boundary for later work

The Streamlit UI should consume presentation projections of normalized
Portfolios. It must not call brokers directly or hold credentials.

```
Streamlit UI -> user intent / WorkflowIR -> planner and executor
             -> normalized Portfolio -> presentation projections -> UI
```

The capability graph should determine which enrichment controls are available
for a chosen broker and origin. New execution results append records, edges,
and execution provenance; they do not overwrite earlier evidence.

## Portfolio and SemanticRecord navigation

A Portfolio is a container of `SemanticRecord` instances, using the families
declared by `<portfolio>` in `ontology.yaml`: `summary`, `detection`,
`crossmatch`, `lightcurve`, `spectrum`, `data_product`, `classification`, and
`survey`. A Portfolio is not itself a search result type.

Every SemanticRecord family needs three compatible views:

- **Grouped search:** results across Portfolios, for example detection rows or
  classification assertions. A summary result is a thin object-oriented row
  that opens its Portfolio.
- **Individual record:** one concrete SemanticRecord and its provenance, with
  a route back to its Portfolio.
- **Portfolio hybrid:** grouped records restricted to one Portfolio. For
  example, the Portfolio light-curve view is a combined lightcurve with its
  detection records; users can then open an individual provider/telescope
  record.

The local `app_plot.py` prototype exposes this hierarchy through family tabs
and a Semantic Records index. Its fixture adapter is temporary; production
views must consume normalized `Portfolio.records` directly.

## Delivery sequence

1. Treat the two current JSON apps as visual prototypes and improve their
   information hierarchy and interaction design with fake data.
2. Add a common, tested view-model layer so both pages share chart, filtering,
   metric, and provenance formatting.
3. Build the Object portfolio MVP: Overview, Photometry, Provenance.
4. Build the Candidate workspace MVP: filterable/sortable table, selection,
   comparison, and drill-down.
5. Replace prototype-specific JSON inputs with normalized serialized
   `Portfolio` inputs and data-layer presentation projections.
6. Add capability-aware Portfolio enrichment through orchestration.
7. Add context, cutouts, export, monitoring, and follow-up workflows.

## Acceptance examples

- A scientist can identify the object, source survey, time span, and available
  broker evidence without reading raw JSON.
- A scientist can filter a demo candidate list to a band/time/class criterion
  and compare a small selection.
- A scientist can distinguish a non-detection from a photometric detection on
  the chart.
- A scientist can trace any displayed scientific value to its source in the
  portfolio once Portfolio data is introduced.
