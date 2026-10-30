# Discovery integration and reference-workflow acceptance

This guide consolidates the current integration contracts. It accompanies step
09a, `feat/integration-09a-recorded-acceptance`, based on `6daa6b4` / PR #326 on
`integration/discovery-completion`. The [09b live runner and verification guide](discovery_live_acceptance.md)
adds explicit local scenarios; final live acceptance and the main merge remain pending.

The starting reports came from Bibin Thomas's
[nucleuswatch integration notes](https://github.com/bibinthomas123/nucleuswatch/blob/f0b4ee7fff4db6faf508d01e5b8b0311f0e3d52d/docs/alertissimo.md).
Nucleuswatch is an external reference application with its own nuclear-transient
cuts, consensus and publishing policies. It is not an Alertissimo dependency or
an endorsed classifier. This series fixes acquisition/orchestration boundaries;
it does not certify the reference application's scientific selections.

Use this guide alongside the [implementation plan](discovery_integration_plan.md),
[required-material inventory](reference_workflow_material.md), and
[per-candidate application guide](application_portfolio_access.md). Older milestone
documents describe their then-current scope; the matrix below includes subsequent
time and selection work rather than copying their earlier deferrals.

## The three reported failures

**ALeRCE classification endpoint ambiguity:** fresh retrieval now plans one
`query_probabilities` call. Validation includes offline planning, so deterministic
ambiguity cannot be advertised as runnable. Classifications retain their producer,
version, class, probability and rank instead of selecting an implicit winner.

```text
objects ZTF21abfmbix from ztf via alerce
with classification via alerce
```

**Unsupported ALeRCE classifier argument:** a named classifier is selected locally
from the returned normalized assertions. It is not passed as an unsupported
`classifier` keyword to `query_probabilities`. Matching versions and classes are
all retained; no match leaves the candidate's other material available.

```text
objects ZTF21abfmbix from ztf via alerce
with classification from lc_classifier via alerce
```

**Fink class/time discovery:** the reported seven-day request now has a declared
class-index recipe, exact local time/class rechecking, and a saturation guard.

```text
objects from ztf via fink
within 7d
where classification.best.class = "SN candidate"
with lightcurve via fink
with classification via fink
```

The public entry points are `validate_dsl(source, continue_from=None)` and
`execute_dsl(source, continue_from=None)`. Validation makes no provider calls.
Execution can still fail on credentials, availability, malformed responses or
incomplete evidence. Use the final `result.portfolios` for consumers and
`result.to_json()` to preserve the final candidates plus workflow/run metadata.
The [ALeRCE fix notes](integration_01_alerce_classification.md) and
[Fink discovery regressions](../tests/test_fink_semantic_search.py) retain the
detailed contract evidence.

## Eight-provider/survey support matrix

Here **admitted** means that the current registry can validate and plan the
specified request. Recorded regressions exercise selected response contracts;
this is not a report that eight deployed services were just tested. An admitted
request can fail explicitly when execution cannot establish the required evidence.

| Broker / survey | Semantic discovery | Existing unwindowed cone | `within`, `first within`, `last within` | Global `latest N` |
| --- | --- | --- | --- | --- |
| ALeRCE / ZTF | Admitted object discovery; mapped first/last MJD minima and existing classification conditions; residual rechecking | Admitted | All three admitted on semantic and cone routes; default requires full ordinary-detection history | Admitted with complete pagination and declared object recency, after residual/time selection |
| ALeRCE / LSST | Existing class/model/probability discovery and mapped explicit first/last MJD minima | Admitted | Deferred: UTC membership and complete-history evidence are not declared for this survey | Deferred: no admitted complete recency-selection contract |
| Fink / ZTF | Admitted class-index discovery for `SN candidate` and `Early SN Ia candidate`; eligible class condition required | Admitted as its separate native cone population | Default admitted for the eligible class/time route only; first/last and temporal cone remain deferred | Deferred: historical class-alert order is not current object recency; object-history caps/per-pixel cone limits lack the needed proof |
| Fink / LSST | Deferred: mandatory physical search inputs have no generic semantic recipe translation | Admitted | Deferred: ZTF class/index/time contracts are not inherited | Deferred |
| Lasair / ZTF | Admitted finite numeric conjunctions on object count and first/last time; no bare unconstrained scan | Admitted; compact summary supplement retained | All three admitted through declared SQL/summary/history evidence | Admitted for SQL discovery and unpredicated cones; cone summary coverage is required |
| Lasair / LSST | Unsupported by current semantic-discovery contract; raw query availability does not establish a semantic projection | Admitted | Deferred: Rubin schema/projection/time proof needs its own audit | Deferred |
| ANTARES / ZTF | Admitted numeric RA/Dec conditions scoped to mapped ZTF identities; coordinate condition required | Admitted as its existing shared-sky population | All three admitted on the scoped coordinate-search route; native temporal cone remains deferred | Admitted on scoped coordinate search with complete ordinary-detection histories; native cone latest remains deferred |
| ANTARES / LSST | Deferred: mandatory native query has no generic semantic recipe translation | Admitted | Deferred: no surveyed identity/history membership recipe | Deferred |

Geometry, semantic discovery and temporal selection are separate contracts. A
working cone is not evidence for a generic class scan, a complete historical
search, or globally correct latest selection. Existing lookup/lightcurve retrieval
routes across these broker/survey combinations remain available independently of
semantic-discovery expansion. Enrichment-family membership does not activate a
missing provider capability.

Important provider limits:

- ALeRCE's pushed `firstmjd`/`lastmjd` minima are explicit object-summary predicates.
  Other operators can remain local residuals. ZTF class conditions must be
  rechecked against actual returned producer/class material; absence is not a
  matching classification. Do not infer new join tables from a client parameter.
- Lasair ZTF SQL discovery supports numeric `=`, `<`, `<=`, `>`, `>=` conjunctions
  on `summary.detection_count`, `summary.time.first_mjd`, `summary.time.last_mjd`.
  `!=`, OR/NOT, classification joins, untranslated fields and arbitrary raw SQL
  lowering remain deferred. Initial predicates on thin-ID cone/latest discovery
  remain deferred; use the admitted SQL route for those summary conditions.
- Fink admits only the two audited ordinary class streams. Its finite default
  `n=100` counts alert rows, not unique objects. A response reaching that limit
  fails as incomplete even if its unique-object count is small. The physical
  request pads the seven-day window outward by three hours at each edge for the
  native index encoding; local selection uses the original closed interval.
- ANTARES semantic coordinates are numeric summary RA/Dec conditions, not arbitrary
  Elasticsearch input. Complete iteration and required histories underpin temporal
  and latest selection. Conflicting loci sharing one ZTF ID cannot silently be
  ranked from the native lookup's first matching locus.

Detailed evidence and remaining limitations are in
[ALeRCE time](time_02_alerce_ztf.md),
[Lasair SQL](discovery_05b_lasair.md),
[Lasair cone latest](selection_02b_lasair_cone.md),
[Fink latest deferral](selection_03_fink_ztf.md), and
[ANTARES latest/identity review](discovery_06e_antares_latest.md).

## Temporal meaning and completeness

`within 7d` means at least one valid ordinary detection in the last seven days,
ending at the execution occurrence's pinned reference time. It does not mean
first or last detection, summary-interval overlap, recent processing, or a count
of upper limits. `within ["start", "end"]` uses explicit closed bounds.
`first within` and `last within` test the corresponding detection extrema only
where the declared native summary or complete-history contract proves them.

`latest N` selects candidates globally after complete discovery, residual/time
membership and object consolidation, using declared object recency. ANTARES derives
that recency from complete ordinary-detection history; ALeRCE/Lasair use their
verified mapped object-summary evidence. Ties use survey/object identity. All
returned measurements of each survivor remain available, including dates outside
the selection interval. Candidate selection is not measurement restriction.

Observable saturation, required-call failure, invalid coverage or exhausted
pagination policy cannot become successful completeness or a successful empty
population. A genuine complete empty response can. Fink has an explicit row-limit
guard; paginated services exhaust their declared pages. This proves neither an
atomic snapshot across changing requests nor all physical observations ever made.
Lasair's upstream cone helper can hide a database error as an empty response;
the client cannot distinguish an error the service does not expose.

## Recorded acceptance cases and direct comparison

`tests/test_discovery_integration_acceptance.py` is offline. It uses real public
facade execution with fake transports/native clients, not provider requests.

| Named case | Evidence checked |
| --- | --- |
| `alerce-classification` | Both original examples validate and execute; strict native signature accepts no classifier argument; normalized model/version/label/probability/rank multiset equals direct parsing of selected recorded rows |
| `fink-class-time` | Exact seven-day SN request at a frozen reference clock; padded physical bounds; candidate identity; original history's source IDs, times, magnitudes/errors and pixel distances preserved |
| `discovery-filter-retrieve` | Recorded class alerts, mapped residual selection, survivor-only downstream IDs, and all returned survivor lightcurve points |
| `multi-object-consumer` | Two different unchanged captured objects have their own IDs, photometry and classifications after normalization/serialization |
| `empty-window` | Complete empty discovery remains empty and makes no downstream history request |
| `incomplete-window` | Synthetic saturation and controlled interruption raise; neither returns an empty/successful result |
| `provider-discovery-matrix` | Public offline validation covers all eight contracts, baseline cones, admitted ZTF temporal/latest variants and representative deferred requests |

The ALeRCE report's `ZTF21abfmbix` lookup is reproduced by explicitly rebinding
the captured summary's identity; probability rows are unchanged. The Fink SN
class-response fixture routes unchanged rows from `objects_core.json` through
the compatible class-response shape. This is not a newly captured class search.
The fixed-clock November class case uses unchanged `latests.json`; the two-object
case combines unchanged rows from the July object-history and November class
captures. These routes establish ownership/normalization behavior, not a historical
population spanning those captures. Saturation repeats rows deliberately to test
the native alert-row cap.

Direct comparisons use the **same rows** on both paths. They compare scientific
values, ownership, unit fields and class/version/rank tuples; internal generated
IDs, output ordering and payload list order are not scientific equality criteria.
The core Fink capture has 14 loaded ordinary measurements while the most recent
reported summary count is 17. Normalization keeps both facts and historical count
snapshots rather than making a count match by dropping or inventing observations.

The original nuclear recipe is a different selection policy. Its cuts all refer
to a single native alert row and then choose the brightest passing alert. A
Portfolio-level candidate filter may have different measurement or catalogue
witnesses. Correlate source rows explicitly for an exact application comparison;
do not weaken Alertissimo's candidate semantics to force equal populations.
Per-alert real/bogus, positive subtraction, pixel versus angular distances,
missing context and producer/version rules remain described in the
[material inventory](reference_workflow_material.md).

## Local handoff and remaining work

No tests, builds, project imports, applications or provider calls ran during
preparation. Static AST/YAML, relative documentation links, whitespace and bundle
checks accompany this step. Run:

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_discovery_integration_acceptance.py \
  tests/test_dsl_alerce_classification.py \
  tests/test_fink_semantic_search.py \
  tests/test_orchestration_discovery_eligibility.py \
  tests/test_application_portfolio_access.py \
  2>&1 | tee /tmp/alertissimo-integration-09a-tests.log
```

Squash into integration after focused local success; the branch's automatic-CI
exclusion remains. The DSL workflow includes this recorded suite for the final
shared check. The last paired shared checkpoints passed on `4d93b51` before the
consumer-only 08 step. The [09b guide](discovery_live_acceptance.md) supplies the
live script with explicit scenario selection, paired historical bounds,
credentials, serialized evidence and outcome classification. A passing offline
matrix is not a live acceptance result.

Keep the final offline sweep, package checks, live provider acceptance and the
integration-to-main CI gate. Do not silently mark unavailable providers as passed
or merge main from this intermediate handoff.

Classification joins and additional Rubin discovery remain for consultation
before implementation. Joins need actual classification tables, object keys,
projected producer/version/class evidence and explicit correlation. Rubin needs
its own columns, response projection and time/identity contracts; ZTF's object SQL
and JD conversion cannot simply be copied. These are separate extensions, not
hidden prerequisites for the existing supported examples above.
