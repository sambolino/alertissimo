# Classification evidence and declarative selection: design and PR plan

Agreed direction: 30 October 2026. Status: design, not implemented behavior.

This continues the [discovery integration plan](discovery_integration_plan.md)
after its end-topic consultation. Preserve that plan and the original saved
revision. The [integration audit](discovery_semantic_audit.md) identifies current
inconsistencies and the conditions blocking the main merge.

## Goal and implementation order

Map scientific fields accurately, retrieve available evidence reliably, make
assertions accessible for deliberate comparison, and implement classification
endpoint search last. Do not design a universal broker consensus classifier.

User intent specifies scientific material, qualifications and conditions.
Alertissimo chooses native filtering, safe discovery, required retrieval,
execution reuse and local evaluation. The scientist or future LLM should not
have to rewrite a query according to where a condition can execute.

No new architecture layers. Extend existing surface models/grammar, WorkflowIR,
GetClassificationStep, SearchStep/SearchSelection, FilterStep, ConfirmStep,
provider declarations, recipe compiler, planner, binder, staging, normalization,
Portfolio and existing presentation helpers. No parallel planner, evidence
service, consensus engine, universal label taxonomy or new container hierarchy.

## Public language contract

### Material and conditions

Target shape (the list form and complete request-wide scheduling are not yet
implemented):

```text
objects from ztf
with classification via alerce, fink
where ...
```

`objects <id> from ...` remains a legitimate existing explicit lookup. It is
not the required workaround for candidate discovery. The same scientific
condition must be preserved on either an explicit named population or a
discovered population.

Scoped shorthand remains useful:

```text
with classification from MODEL via BROKER where best.class = "SN" and best.probability >= 0.8
```

MODEL/BROKER are placeholders. The actual mapped fields might instead be named
`assessment` leaves. This sketch is not a promise that each producer supplies
best class, a probability, every class label or the stated literal threshold.

`with` requests material. Its `where` constrains candidates using that material.
Requested retrieval may return no assertion for a candidate; merely attaching
material must not fabricate a value or silently impose broker quorum. A positive
predicate requires actual evidence. A required provider-call failure remains an
execution failure rather than a silent abstention.

A top-level `where` is a scientific condition over the request's evidence. It
must not be permanently assigned to the first physical endpoint just because of
its spelling or clause position. Canonical lowering must preserve the original
predicate and dependency scope without deciding provider API parameters.

### Continuation and ordering

`filter` adds a later selection to the current candidate population, especially
in a continuation. It is not the exclusive syntax for local pruning.

An initial `with ... where` can be realized locally without requiring the user
to add `filter`. The existing FilterStep can represent a local realization where
appropriate. A continuation adds Steps without retroactively changing the
executed prefix, reference clock, request bindings or prior selection.

Initial predicates, including those requiring fetched classifications, must be
decided before initial global `latest N`. Later continuation filtering does not
refill an earlier latest result. Do not advertise equivalence by simply appending
an enrichment/filter after the current SearchStep has already applied latest.

### Confirmation

Keep `confirm` as the existing proposition/existence quorum mechanism. A bare
confirmation remains an existence question. Proposition confirmation must carry
the intended predicate explicitly in its existing canonical IR and remain stable
across equivalent requirement spellings and continuation.

The existing syntax `where P` immediately followed by `confirm by K via ...`
has a useful supported meaning. Preserve valid programs, but eliminate silent
changes to bare existence when layout/material clauses intervene. Define scope
in the existing surface compiler and reject genuinely ambiguous attachment.
Do not guess which of several unrelated conditions is the confirmation question.

Each broker contributes at most one vote for the same exact candidate identity,
using its own attributable evidence. Missing/invalid comparison evidence does
not establish a negative assertion. A quorum counts named sources satisfying a
proposition; it makes no claim that their measurements, models or training sets
are statistically independent.

## Assertion semantics

- Keep producer, broker/channel, version, class, probability/score/reliability,
  and source evidence wherever the upstream response establishes them.
- A class and the associated threshold must refer to one assertion, even inside
  a mixed summary/classification condition. Preserve that binding through
  lowering, pushdown/residual splitting, staging and replay.
- Preserve missing comparison evidence under negation. Explicit evidence absence
  is a separate question; it is not a non-SN classification.
- Preserve all returned model versions and conflicting assertions. Do not choose
  the greatest score across versions or infer recency from version strings.
- Observation time, classification issue time and retrieval time differ. Do not
  invent historical classifier outputs when only today's result exists.
- Retain raw labels and score meanings. A catalogue AGN association, a Sherlock
  host-context label, a stamp classifier and a lightcurve physical-class output
  may address different questions. They need not be contradictory.
- A probability, binary assessment score and contextual reliability are not one
  interchangeable confidence scale. No automatic averaging or label equivalence.
- Source/candidate selection retains all measurements for survivors. No implicit
  measurement restriction or display-filter operation is introduced.

Use existing provenance for assertion attribution. Where a model lacks method,
version or issue-time information, record the gap; do not fill it with a pipeline
version or an invented method inferred from a class label.

## Provider/survey baseline to extend

This is the inspected integration baseline, not fresh live coverage of all cells.

| Pair | Mapped classification evidence | Retrieval work before new class discovery |
| --- | --- | --- |
| ALeRCE ZTF | Named models, versions, class probabilities/ranks; selected summary class where supplied | Preserve accurate probabilities signature, local model selection and complete returned assertions |
| ALeRCE LSST | Same semantic families with Rubin-specific model names/response schema | Preserve current retrieval; do not infer ZTF labels, time scales or temporal/latest support |
| Fink ZTF | Alert-associated Fink label and named science assessments | Preserve source row/time attribution; do not declare one historical label current by list order |
| Fink LSST | Object main label and source CATS/other assessments | Resolve real competing retrieval recipes without dropping either requested evidence level; current resolver permits one-call classification recipes only |
| Lasair ZTF | Sherlock class/reliability/description and TNS type where supplied | Make named-producer/generic retrieval contracts predictable across singular/plural targets |
| Lasair LSST | Sherlock context through object/Sherlock responses | Verify exact routes/provenance and missing material; retain Rubin-specific schema |
| ANTARES ZTF | No normalized classification records/recipe currently | Audit returned properties/catalogue evidence; map under the appropriate existing semantic concept, with a classification recipe only when justified |
| ANTARES LSST | No normalized classification records/recipe currently | Separate Rubin audit; absence of a mapping is not proof the service has no useful evidence |

None of the four current LSST routes admits generic within/first/last or global
latest. Explicit ALeRCE numeric object-summary MJD predicates are a separate
existing capability. Broader Rubin temporal discovery is not activated merely
by fixing classification retrieval.

## Planner obligations

1. Establish the requested candidate population from a valid declared source
   contract, without silently requiring the user to select an endpoint.
2. Identify material needed by predicates and requirements. Reuse compatible
   evidence or plan the existing target-bound retrievals.
3. Push only scientifically equivalent predicates or proven safe prefilters.
   Preserve remaining conditions for evaluation after their evidence exists.
4. Decide initial predicates on the correct accumulated candidate evidence before
   selection is consumed downstream. Keep class/score assertion ownership intact.
5. Complete declared pagination/coverage and identity consolidation, then apply
   initial latest globally. A later filter remains a later selection.
6. Preserve exact continuation prefixes and provenance. No rejected candidate may
   reappear merely because an earlier broader execution is reused.

Physical flexibility does not create missing archive coverage. For OR conditions,
one class stream alone may exclude candidates satisfying only another branch;
for AND conditions, a proven superset is needed. Unconstrained discovery,
unsupported population unions, mixed time scales or capped histories must remain
explicit limitations until their contracts are established. Material providers
and the candidate discovery population are related but distinct constraints.

Extend the existing planner/recipe paths rather than copying every class and
broker combination into a separate recipe. Any physical composition must keep
the authored scientific predicate, coverage evidence and final selection order
reviewable. Do not add a hidden second workflow or silently broaden the universe.

## Small PR sequence

Continue local focused checks and bundle handoffs. Current authorization permits
remote CI/review work, but main stays blocked by the audit. Use integration while
repairing its release blockers; subsequent feature branches can start from the
verified merged baseline. Do not create all future branches in advance.

| Order | Proposed branch | Concrete scope and acceptance |
| --- | --- | --- |
| R1 | `fix/dsl-predicate-preservation` | Preserve lookup/scoped conditions and reject or represent every admitted late clause. Prevent apparently successful empty results from evaluating a condition before its requested evidence exists; fail admission until a safe realization is available. Compare fresh and continuation outcomes through public execution. Audit A1/A2 and the unsafe A5 case. |
| R2 | `fix/predicate-assertion-evidence` | Same-assertion correlation under mixed Boolean conditions; missing/invalid evidence under NOT; confirmation negative evidence. Audit A3/A4. |
| C1 | `feat/classification-multi-broker-requirements` | Broker lists through the existing grammar/surface/IR/checks; one-broker compatibility, source attribution, deduplication and continuation. No new endpoint class search. |
| C2 | `fix/classification-retrieval-contracts` | Small provider/survey reviews for Fink LSST and Lasair route ambiguity; preserve requested object/source/model evidence. Extend the existing resolver if multiple required calls are necessary. |
| C3 | `feat/classification-evidence-mappings` | Audit/map missing evidence, particularly ANTARES, one pair at a time. Separate context from physical classification and document unsupported cases honestly. |
| C4 | `fix/dsl-declarative-evidence-planning` | Make initial with/where independent of native filtering support through existing dependency/planning/staging paths. Retrieve required material before local predicate evaluation and initial latest. |
| C5 | `fix/dsl-confirm-proposition-scope` | Stable explicit proposition attachment, including scoped requirements and continuation; preserve execution-local distinct-broker quorum and bare existence. |
| C6 | `feat/classification-comparison-view` | Present existing assertion records side by side with qualified identities, score meaning, versions and available timing/provenance. No universal winner, probability averaging or automatic taxonomy. |
| C7 | `feat/classification-discovery-bindings` | Last: audited endpoint filtering, including selected Lasair joins or other native routes. Prove equivalent local/native outcomes, identity multiplicity, coverage and missing assertions. Split by provider/survey. |

R1/R2 are release correctness repairs, not optional future enhancements. C1-C6
must not be described as already implemented by the old integration. Review C4
and C5 together where proposition dependencies overlap; keep PRs independently
reviewable without exposing incorrect intermediate behavior as supported.

## Verification that matters

R1 is prepared on `fix/dsl-predicate-preservation`; see its
[scope, local checks and draft-PR CI policy](dsl_predicate_preservation.md).
This is a local handoff, not a reported passing test result or merged status.
The public replay regressions cover A1/A2 and the unsafe A5 case. R2 remains next.
The first local R1 run exposed missed surface/preflight guards; the follow-up
aligns lookup `where` admission with lowering and corrects the audit's A2 public
impact claim. Invalid late clauses remain rejected at their earliest entry point.

- A condition survives parsing, lowering, planning, execution and serialization;
  a real non-match is rejected in both fresh and continuation cases.
- Native and local realizations use the same frozen candidate/evidence population
  and produce the same candidate IDs, including missing/partial assertions.
- SN/low-probability and AGN/high-probability assertions cannot satisfy an SN/high
  condition by mixing records; adding an unrelated summary condition changes
  nothing. Cover versions, Boolean grouping and residual splitting.
- Initial late-material predicates precede latest. A rejected most-recent object
  permits the next qualifying object to enter initial latest; an explicit later
  filter does not refill an already selected population.
- Confirm uses only each broker's own evidence, counts no duplicates, and treats
  unavailable comparisons as no established vote. Equivalent forms bind the
  same proposition; ambiguous syntax fails clearly.
- Surviving Portfolios retain full measurements and source evidence; continuation
  neither repeats reusable calls nor resurrects rejected candidates.
- Deterministic fixtures establish acquisition/selection correctness. User-run
  live scenarios establish actual deployment interoperability. Neither validates
  a universal scientific consensus or historical classifier accuracy.

The scientific consumer owns label grouping, version/time selection, thresholds,
ranking and follow-up policy. Nucleuswatch is a useful consumer and source of
requirements, not a taxonomy or voting policy to embed in Alertissimo. Any
accuracy claim needs independent reference classifications and time-respecting
held-out/prospective validation outside this acquisition series.

## Out of scope

No LLM training, universal consensus/confidence keyword, general SQL join language,
automatic cross-survey identity equivalence, classifier retraining, measurement
restriction, notifications or large UI overhaul. Counts/per-band quantifiers,
changes in class over time and cross-model disagreement searches can follow once
assertion binding and temporal evidence are explicit; do not advertise them as
implemented by these examples.
