#!/usr/bin/env bash
set -euo pipefail

for cmd in curl jq sha256sum; do
    command -v "$cmd" >/dev/null || {
        echo "ERROR: required command not found: $cmd" >&2
        exit 1
    }
done

BASE='https://api.ztf.fink-portal.org'
OID="${FINK_ZTF_OID:-ZTF21abfmbix}"

STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
OUT="${1:-/tmp/fink-ztf-capture-${STAMP}}"

if [[ -d "$OUT" ]] && [[ -n "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "ERROR: destination exists and is non-empty: $OUT" >&2
    exit 1
fi
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

date -u '+%Y-%m-%dT%H:%M:%SZ' > "$OUT/capture_date.txt"

cat > "$OUT/capture_metadata.txt" <<META
broker=fink
survey=ztf
capture_utc=$(cat "$OUT/capture_date.txt")
transport=rest
base_url=$BASE
primary_object_id=$OID
capture_script=$0
META

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    {
        echo "git_commit=$(git rev-parse HEAD)"
        echo "git_branch=$(git branch --show-current)"
    } >> "$OUT/capture_metadata.txt"
else
    printf 'git_commit=unavailable\ngit_branch=unavailable\n' >> "$OUT/capture_metadata.txt"
fi

sha256sum "$0" > "$OUT/capture_script.sha256"


post_capture() {
    local name="$1"
    local path="$2"

    jq . > "$OUT/${name}.request.json"

    echo "=== POST ${path} -> ${name}.json"

    curl \
        --fail-with-body \
        --compressed \
        -sS \
        -D "$OUT/${name}.headers" \
        -H 'Content-Type: application/json' \
        -X POST \
        "${BASE}${path}" \
        --data-binary @"$OUT/${name}.request.json" \
        -o "$OUT/${name}.json"

    jq -e . "$OUT/${name}.json" >/dev/null
}


# ============================================================
# 1. Ordinary object history — full response
# ============================================================

cat <<JSON | post_capture objects_core /api/v1/objects
{
  "objectId": "$OID",
  "withupperlim": false,
  "withcutouts": false,
  "output-format": "json"
}
JSON


# ============================================================
# 2. Same object including upper limits and bad-quality rows
# ============================================================

cat <<JSON | post_capture objects_withupperlim /api/v1/objects
{
  "objectId": "$OID",
  "withupperlim": true,
  "withcutouts": false,
  "output-format": "json"
}
JSON


# ============================================================
# Choose the latest real valid detection as spatial anchor
# ============================================================

jq '
    map(select(.["i:jd"] != null))
    | max_by(.["i:jd"])
    | {
        objectId: .["i:objectId"],
        candid: .["i:candid"],
        jd: .["i:jd"],
        ra: .["i:ra"],
        dec: .["i:dec"],
        fid: .["i:fid"]
      }
' "$OUT/objects_core.json" > "$OUT/object_anchor.json"

RA="$(jq -r '.ra' "$OUT/object_anchor.json")"
DEC="$(jq -r '.dec' "$OUT/object_anchor.json")"

if [[ "$RA" == "null" || "$DEC" == "null" ]]; then
    echo "ERROR: failed to obtain RA/Dec from primary object" >&2
    exit 1
fi

echo "Primary object: $OID"
echo "Cone anchor: RA=$RA Dec=$DEC"


# ============================================================
# 3. Cone search — deliberately full response
# Fink ZTF cone n is an upstream scan cap before exact cone filtering; an
# unnecessarily small n may therefore return empty around a known object.
# ============================================================

cat <<JSON | post_capture conesearch /api/v1/conesearch
{
  "ra": $RA,
  "dec": $DEC,
  "radius": 5,
  "n": 1000,
  "output-format": "json"
}
JSON


# ============================================================
# 4. Reproducible class-search surface
#
# Historical window taken from Fink API test cases.
# ============================================================

cat <<'JSON' | post_capture latests /api/v1/latests
{
  "class": "Early SN Ia candidate",
  "n": 10,
  "startdate": "2021-11-01",
  "stopdate": "2021-12-01",
  "output-format": "json"
}
JSON


# ============================================================
# 5. Reproducible anomaly surface
# ============================================================

cat <<'JSON' | post_capture anomaly /api/v1/anomaly
{
  "n": 10,
  "start_date": "2023-01-25",
  "stop_date": "2023-01-25",
  "output-format": "json"
}
JSON


# ============================================================
# 6. Solar-System core surface
# ============================================================

cat <<'JSON' | post_capture sso_core /api/v1/sso
{
  "n_or_d": "8467",
  "withEphem": false,
  "withResiduals": false,
  "withcutouts": false,
  "columns": "*",
  "output-format": "json"
}
JSON


# ============================================================
# 7. TNS resolver shape
# ============================================================

cat <<'JSON' | post_capture resolver_tns /api/v1/resolver
{
  "resolver": "tns",
  "name": "ZTF23aaaahln",
  "reverse": true,
  "nmax": 10,
  "output-format": "json"
}
JSON


# ============================================================
# 8. SIMBAD resolver shape
# ============================================================

cat <<'JSON' | post_capture resolver_simbad /api/v1/resolver
{
  "resolver": "simbad",
  "name": "Markarian 2",
  "nmax": 10,
  "output-format": "json"
}
JSON


# ============================================================
# 9. SSODNet resolver shape
# ============================================================

cat <<'JSON' | post_capture resolver_ssodnet /api/v1/resolver
{
  "resolver": "ssodnet",
  "name": "624188",
  "nmax": 10,
  "output-format": "json"
}
JSON


# ============================================================
# 10. One reproducible statistics row
# ============================================================

cat <<'JSON' | post_capture statistics_day /api/v1/statistics
{
  "date": "20211103",
  "columns": "*",
  "output-format": "json"
}
JSON


# ============================================================
# GET support probes
#
# Alertissimo currently describes these endpoints as GET,
# while Fink's official tests primarily exercise POST JSON.
# These are evidence probes, not authoritative fixture payloads.
# ============================================================

{
    echo '===== objects GET ====='
    curl \
        --compressed \
        -sS \
        -D "$OUT/objects_get_probe.headers" \
        -o "$OUT/objects_get_probe.json" \
        -w 'HTTP %{http_code}\n' \
        -G "${BASE}/api/v1/objects" \
        --data-urlencode "objectId=$OID" \
        --data-urlencode 'output-format=json'

    echo
    echo '===== conesearch GET ====='
    curl \
        --compressed \
        -sS \
        -D "$OUT/conesearch_get_probe.headers" \
        -o "$OUT/conesearch_get_probe.json" \
        -w 'HTTP %{http_code}\n' \
        -G "${BASE}/api/v1/conesearch" \
        --data-urlencode "ra=$RA" \
        --data-urlencode "dec=$DEC" \
        --data-urlencode 'radius=5' \
        --data-urlencode 'n=1000' \
        --data-urlencode 'output-format=json'

} > "$OUT/method_probe.txt"


# ============================================================
# Response inventory
# ============================================================

FILES=(
    objects_core
    objects_withupperlim
    conesearch
    latests
    anomaly
    sso_core
    resolver_tns
    resolver_simbad
    resolver_ssodnet
    statistics_day
)

{
    echo '================ RESPONSE INVENTORY ================'

    for name in "${FILES[@]}"; do
        echo
        echo "===== $name ====="

        jq -r '
            "json_type=\(type)",
            "rows=\(
                if type == "array" then length
                else 1
                end
            )",
            "union_columns=\(
                if type == "array" and length > 0 then
                    ([.[] | keys[]] | unique | length)
                elif type == "object" then
                    (keys | length)
                else
                    0
                end
            )"
        ' "$OUT/${name}.json"
    done

} | tee "$OUT/inventory.txt"


# ============================================================
# Detailed evidence summaries
# ============================================================

{
    echo '================ OBJECT TAG COUNTS ================='

    jq -r '
        group_by(.["d:tag"])
        | .[]
        | "\(.[0]["d:tag"] // "<missing>")\t\(length)"
    ' "$OUT/objects_withupperlim.json"

    echo
    echo '================ OBJECT PREFIX COUNTS =============='

    jq -r '[.[] | keys[]] | unique[]' \
        "$OUT/objects_withupperlim.json" |
    awk -F: '
        NF > 1 { count[$1]++ }
        NF == 1 { count["<root>"]++ }
        END {
            for (k in count)
                print k "\t" count[k]
        }
    ' |
    sort

    echo
    echo '================ FILTER VALUES ====================='

    jq -r '
        [.[] | .["i:fid"]]
        | unique
        | .[]
    ' "$OUT/objects_core.json"

    echo
    echo '================ isdiffpos VALUES =================='

    jq -r '
        [.[] | .["i:isdiffpos"]]
        | unique
        | .[]
    ' "$OUT/objects_core.json"

    echo
    echo '================ CANDID TYPES ======================'

    jq -r '
        [.[] | .["i:candid"] | type]
        | group_by(.)
        | .[]
        | "\(.[0])\t\(length)"
    ' "$OUT/objects_core.json"

    echo
    echo '================ METHOD PROBES ====================='

    cat "$OUT/method_probe.txt"

} | tee "$OUT/summary.txt"


# ============================================================
# Exact response hashes
# ============================================================

(
    cd "$OUT"

    sha256sum \
        objects_core.json \
        objects_withupperlim.json \
        conesearch.json \
        latests.json \
        anomaly.json \
        sso_core.json \
        resolver_tns.json \
        resolver_simbad.json \
        resolver_ssodnet.json \
        statistics_day.json \
        > SHA256SUMS.txt
)

echo
echo "Verify response hashes with:"
echo "  (cd \"$OUT\" && sha256sum -c SHA256SUMS.txt)"
echo
echo "====================================================="
echo "Capture complete:"
echo "$OUT"
echo
echo "Please send:"
echo "  $OUT/*.json"
echo "  $OUT/*.headers"
echo "  $OUT/*.request.json"
echo "  $OUT/capture_date.txt"
echo "  $OUT/capture_metadata.txt"
echo "  $OUT/object_anchor.json"
echo "  $OUT/method_probe.txt"
echo "  $OUT/inventory.txt"
echo "  $OUT/summary.txt"
echo "  $OUT/SHA256SUMS.txt"
echo "====================================================="
