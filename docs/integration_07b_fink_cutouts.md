# Fink ZTF cutouts through the existing JSON product path

Branch `feat/integration-07b-cutouts`, based on integration `da31fd7` / PR #322.
Target `integration/discovery-completion`; squash after focused local checks.

## Activated path

The existing public DSL can now request the verified Fink ZTF product:

```text
objects ZTF21abfmbix from ztf via fink
with data_product via fink
```

No noun or ontology family is added. The canonical IR `GetCutoutStep` and
`GetDataProductStep` both use the same provider recipe. The public ontology's
artifact noun remains `data_product`; this does not add `with cutout` as an alias.

Each candidate gets one singular request to the existing `/api/v1/cutouts` route,
with `kind=All` and `output-format=array`. Its normalized
`data_product@ztf:fink` record has a keyed inline payload:

```python
record.get("payload")["science"]
record.get("payload")["template"]
record.get("payload")["difference"]
```

The keys preserve the image roles. Previously the three references were ordinary
fallbacks and would keep only the first available stamp. Existing `object_key`
mapping composition now retains all three, including when normalizing a direct
legacy `cutouts` array response. Consumers of that previously unadmitted raw path
must now read the keyed payload rather than assume it is one matrix.

## Physical contract and execution

Provider-local `cutouts_array` names one fixed response mode of the same physical
route, not a new service. Its executor-owned fixed parameters constrain the
request to the verified JSON bundle, so it declares an object output with no
dynamic format selector. The original `cutouts` declaration remains available for
direct physical requests using PNG/FITS or explicit candidate IDs. Its notes now
correctly describe file bytes rather than image URLs.

The existing EndpointSpec carries an optional `required_matrices` tuple from
`output.required_matrices`. Opted-in object responses must contain each named
nonempty rectangular numeric matrix. Null pixels and numeric values are retained;
booleans and strings are not numeric pixels. There is no stretching, clipping,
resizing, plate-scale conversion or replacement of masked pixels. No fixed image
dimensions are invented. Other endpoints have no matrix requirement and retain
their existing execution behavior.

The check runs in the existing executor before success/provenance is returned.
The upstream empty-archive response can be empty PNG bytes even when array mode
was requested; that fails explicitly rather than becoming a successful empty
product. Missing/null stamps, ragged arrays, error objects and other binary
responses also fail the required retrieval. Raw successful executions retain the
complete response for replay; ordinary offline normalization uses the same
composition and candidate ownership.

This adds no architecture layer, transport, product domain model, IR Step,
selector language or binary exporter. It extends physical endpoint metadata and
the existing executor; planning uses the existing JSON product admission rules.

## Identity and scientific limits

Fink's default retrieval chooses its latest archived alert for the requested
object. It does not mean the alert that originally discovered the candidate, nor
does it implement global scientific `latest N`. The returned JSON does not echo
the chosen alert ID or observing time, so none is fabricated. A product belongs to
its singular request's object ID and execution provenance. Discovery/filter
continuations bind only surviving IDs, preserving earlier material snapshots.

PNG/FITS selection, an explicit size, product-type selectors and alert-specific
scientific retrieval remain deferred when their selectors cannot be honored by
the recipe. Fink Rubin cutouts use alert IDs and different response keys; their
existing identity-ownership deferral remains intact. No ZTF-to-Rubin copy is made.

## Evidence and local validation

Read-only primary source audit used official
[`astrolabsoftware/fink-object-api` at `a10923b`](https://github.com/astrolabsoftware/fink-object-api/tree/a10923b0626aa7b73ef41e684e198c96713f2dd3):

- `apps/routes/v1/ztf/cutouts/api.py`: GET/POST arguments and allowed kinds.
- `apps/routes/v1/ztf/cutouts/utils.py`: the three array-mode JSON keys, file
  responses, archive selection and empty-archive behavior.
- `apps/routes/v1/ztf/cutouts/test.py`: raw array versus PNG/FITS representations.
- Rubin's cutout utility: separate alert identity and different JSON keys.

New tests use explicitly synthetic 2×2 stamps with distinct roles, negative and
null pixels. These are shape/ownership regression fixtures, not a new live
capture. Existing authoritative fixtures are unchanged. No project imports,
tests, builds, applications or provider calls ran here; static Python/YAML,
whitespace and bundle checks accompany the branch.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_fink_cutouts.py \
  tests/test_orchestration_product_recipes.py \
  tests/test_dsl_retrieval_recipes.py \
  tests/test_endpoint_execution.py \
  tests/test_fink_registry_architecture.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  2>&1 | tee /tmp/alertissimo-integration-07b-tests.log
```

Coverage includes direct IR planning/fanout, public DSL execution and serialization,
survivor-only continuation, offline replay, all image roles, required-call failure
for unavailable/malformed data, fixed mode ownership, and retained unsupported
selectors. Generic JSON contract fixtures remain independent of production modes.

Next is the scheduled 07c ALeRCE reference-distance unit audit. After this material
sequence, run one manual Semantic registry checkpoint; final full CI and deployed
provider acceptance still precede main.
