# ALeRCE/ZTF selected headline evidence

`lc.json` and `stamp.json` retain the URL and REST payload captured during the
preceding classification review for `ZTF20aaelulu`. They are not new live calls or
captures from the Python client. The LC response selects `SNIbc` at `0.525456`;
the stamp response selects `SN` at `0.81320095`. Neither supplies a classifier
version. Tests must not infer one from the probability table.

`contract.json` records static inspection of the published ALeRCE 2.3.1 wheel on
12 November 2026. `Alerce.query_objects` forwards ZTF keywords to the legacy client,
which passes `oid` and `classifier` unchanged to the objects API. Unlike
`query_probabilities`, this public method accepts extra keywords. Inspection did
not import the package, run it or make new broker requests.

The public API tests replay these payloads through the registry's Python transport
using a substitute client. Cases with different object IDs, alternative probability
versions, empty outputs, unknown labels or conflicts are explicitly controlled
counterexamples, not claims about the captured object's current classification.
