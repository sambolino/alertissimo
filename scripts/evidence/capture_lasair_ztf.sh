#!/usr/bin/env bash
#
# Capture authoritative Lasair/ZTF REST evidence.
#
# Credentials are NEVER persisted.
#
# Required:
#   LASAIR_TOKEN
#
# Optional:
#   LASAIR_ZTF_OID   default: ZTF20acpwljl
#   LASAIR_ZTF_BASE  default: https://lasair-ztf.lsst.ac.uk
#
# Usage:
#   scripts/evidence/capture_lasair_ztf.sh [OUTPUT_DIR]
#
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage:
  capture_lasair_ztf.sh [OUTPUT_DIR]

Required environment:
  LASAIR_TOKEN       Raw Lasair API token; do NOT include "Token ".

Optional environment:
  LASAIR_ZTF_OID     Object to capture (default: ZTF20acpwljl)
  LASAIR_ZTF_BASE    API base URL (default: https://lasair-ztf.lsst.ac.uk)

The capture includes:
  - /api/object/ default response
  - /api/object/ with lite=true
  - /api/object/ with lite=false
  - legacy/plural /api/objects/ probe
  - /api/lightcurves/ probe
  - cone all / nearest / count
  - fixed core /api/query/ projection
  - Sherlock object lite + full
  - Sherlock position lite + full
  - legacy/plural Sherlock probes

Core/current endpoints are required where appropriate.
Compatibility/version-dependent probes are recorded but do not abort the run.
Credentials are never written to disk.
EOF
    exit 0
fi

for cmd in curl jq sha256sum sort git; do
    command -v "$cmd" >/dev/null || {
        echo "ERROR: required command not found: $cmd" >&2
        exit 1
    }
done

: "${LASAIR_TOKEN:?ERROR: LASAIR_TOKEN is required (raw token; it will not be persisted)}"

if [[ "$LASAIR_TOKEN" == Token\ * ]]; then
    echo 'ERROR: LASAIR_TOKEN must contain only the raw token, not "Token <token>".' >&2
    exit 1
fi

if [[ "$LASAIR_TOKEN" != "${LASAIR_TOKEN#"${LASAIR_TOKEN%%[![:space:]]*}"}" ]] ||
   [[ "$LASAIR_TOKEN" != "${LASAIR_TOKEN%"${LASAIR_TOKEN##*[![:space:]]}"}" ]]; then
    echo "ERROR: LASAIR_TOKEN appears to contain leading/trailing whitespace." >&2
    exit 1
fi

OID="${LASAIR_ZTF_OID:-ZTF20acpwljl}"
BASE="${LASAIR_ZTF_BASE:-https://lasair-ztf.lsst.ac.uk}"

STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
OUT="${1:-/tmp/lasair-ztf-capture-${STAMP}}"

if [[ -d "$OUT" ]] &&
   [[ -n "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "ERROR: destination exists and is non-empty: $OUT" >&2
    exit 1
fi

mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

CAPTURED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
GIT_COMMIT="$(git rev-parse HEAD 2>/dev/null || printf unavailable)"
GIT_BRANCH="$(git branch --show-current 2>/dev/null || true)"
GIT_BRANCH="${GIT_BRANCH:-unavailable}"

printf '%s\n' "$CAPTURED_AT" > "$OUT/capture_date.txt"

cat > "$OUT/capture_metadata.txt" <<META
broker=lasair
survey=ztf
capture_utc=$CAPTURED_AT
script=$0
transport=authenticated-rest
base_url=$BASE
primary_object_identifier=$OID
git_commit=$GIT_COMMIT
git_branch=$GIT_BRANCH
META

sha256sum "$0" > "$OUT/capture_script.sha256"

printf 'label\tmode\thttp\tjson\tpath\n' > "$OUT/http_status.tsv"

declare -a SUCCESS_LABELS=()

post()
{
    local mode="$1"
    local label="$2"
    local path="$3"
    shift 3

    local request_file="$OUT/${label}.request.json"
    local body_file="$OUT/${label}.body"
    local headers_file="$OUT/${label}.headers"

    jq -n "$@" > "$request_file"

    local form=()
    while IFS=$'\t' read -r key value; do
        form+=(--data-urlencode "$key=$value")
    done < <(
        jq -r '
            to_entries[]
            | [.key, (.value | tostring)]
            | @tsv
        ' "$request_file"
    )

    echo "POST $path  [$label]"

    local http

    if ! http="$(
        curl \
            --compressed \
            -sS \
            -D "$headers_file" \
            -o "$body_file" \
            -w '%{http_code}' \
            -H "Authorization: Token $LASAIR_TOKEN" \
            "${form[@]}" \
            "$BASE$path"
    )"; then
        printf '%s\t%s\t%s\t%s\t%s\n' \
            "$label" "$mode" "NETWORK_ERROR" "unknown" "$path" \
            >> "$OUT/http_status.tsv"

        echo "WARNING: network/curl failure for $label" >&2

        if [[ "$mode" == required ]]; then
            return 1
        fi
        return 0
    fi

    local is_json=no
    local response_file="$OUT/${label}.raw"

    if jq -e . "$body_file" >/dev/null 2>&1; then
        is_json=yes
        response_file="$OUT/${label}.json"
        mv "$body_file" "$response_file"
    else
        mv "$body_file" "$response_file"
    fi

    printf '%s\t%s\t%s\t%s\t%s\n' \
        "$label" "$mode" "$http" "$is_json" "$path" \
        >> "$OUT/http_status.tsv"

    if [[ ! "$http" =~ ^2[0-9][0-9]$ ]]; then
        echo "WARNING: $label returned HTTP $http" >&2

        if [[ -f "$response_file" ]]; then
            echo "--- response excerpt ---" >&2
            head -n 20 "$response_file" >&2 || true
            echo "------------------------" >&2
        fi

        if [[ "$mode" == required ]]; then
            return 1
        fi
        return 0
    fi

    if [[ "$is_json" != yes ]]; then
        echo "WARNING: successful HTTP response for $label was not JSON" >&2

        if [[ "$mode" == required ]]; then
            return 1
        fi
        return 0
    fi

    SUCCESS_LABELS+=("$label")
}

##############################################################################
# OBJECT SURFACE
##############################################################################

# The current REST contract: named object + Lasair-added context.
post required object_default /api/object/ \
    --arg oid "$OID" \
    '{objectId:$oid, lasair_added:true}'

# Capture both explicit lite variants rather than assuming their semantics.
# These are compatibility/evidence probes: failure does not invalidate the
# otherwise authoritative capture.
post optional object_lite_true /api/object/ \
    --arg oid "$OID" \
    '{objectId:$oid, lasair_added:true, lite:true}'

post optional object_lite_false /api/object/ \
    --arg oid "$OID" \
    '{objectId:$oid, lasair_added:true, lite:false}'

##############################################################################
# RESOLVE POSITION FROM AUTHORITATIVE OBJECT RESPONSE
##############################################################################

RA="$(
    jq -r '
        (if type=="array" then .[0] else . end)
        | .objectData.ramean
          // .ramean
          // .ra
          // .meanra
          // empty
    ' "$OUT/object_default.json"
)"

DEC="$(
    jq -r '
        (if type=="array" then .[0] else . end)
        | .objectData.decmean
          // .decmean
          // .dec
          // .meandec
          // empty
    ' "$OUT/object_default.json"
)"

if [[ -z "$RA" || -z "$DEC" || "$RA" == null || "$DEC" == null ]]; then
    echo "ERROR: object response has no usable RA/Dec." >&2
    exit 1
fi

echo "Resolved position: RA=$RA Dec=$DEC"

##############################################################################
# CURRENT / LEGACY OBJECT COLLECTION SURFACES
##############################################################################

# These remain useful because older Lasair documentation and our registry
# contain the plural endpoints. Probe rather than assuming either availability
# or deprecation.
post optional objects_plural /api/objects/ \
    --arg oid "$OID" \
    '{objectIds:$oid}'

post optional lightcurves /api/lightcurves/ \
    --arg oid "$OID" \
    '{objectIds:$oid}'

##############################################################################
# CONE SEARCH
##############################################################################

post required cone_all /api/cone/ \
    --argjson ra "$RA" \
    --argjson dec "$DEC" \
    '{ra:$ra, dec:$dec, radius:5, requestType:"all"}'

post required cone_nearest /api/cone/ \
    --argjson ra "$RA" \
    --argjson dec "$DEC" \
    '{ra:$ra, dec:$dec, radius:5, requestType:"nearest"}'

# 'count' exists in some current/develop Lasair documentation but has had
# less stable documented serialized output. Capture it as an optional probe.
post optional cone_count /api/cone/ \
    --argjson ra "$RA" \
    --argjson dec "$DEC" \
    '{ra:$ra, dec:$dec, radius:5, requestType:"count"}'

##############################################################################
# FIXED QUERY PROJECTION
##############################################################################

QUERY_CONDITION="objects.objectId='${OID}'"

post optional query_core /api/query/ \
    --arg condition "$QUERY_CONDITION" \
    '{
        selected:"objects.objectId,objects.ramean,objects.decmean,objects.ncand,objects.jdmin,objects.jdmax",
        tables:"objects",
        conditions:$condition,
        limit:10,
        offset:0
    }'

##############################################################################
# SHERLOCK — CURRENT SINGULAR ENDPOINTS
##############################################################################

# For Sherlock the semantics are explicit:
#   lite=true  -> reduced/lite record
#   lite=false -> full record with broader crossmatches.

post required sherlock_object_lite /api/sherlock/object/ \
    --arg oid "$OID" \
    '{objectId:$oid, lite:true}'

post required sherlock_object_full /api/sherlock/object/ \
    --arg oid "$OID" \
    '{objectId:$oid, lite:false}'

post required sherlock_position_lite /api/sherlock/position/ \
    --argjson ra "$RA" \
    --argjson dec "$DEC" \
    '{ra:$ra, dec:$dec, lite:true}'

post required sherlock_position_full /api/sherlock/position/ \
    --argjson ra "$RA" \
    --argjson dec "$DEC" \
    '{ra:$ra, dec:$dec, lite:false}'

##############################################################################
# SHERLOCK — PLURAL/OLDER API PROBES
##############################################################################

post optional sherlock_objects_lite /api/sherlock/objects/ \
    --arg oid "$OID" \
    '{objectIds:$oid, lite:true}'

post optional sherlock_objects_full /api/sherlock/objects/ \
    --arg oid "$OID" \
    '{objectIds:$oid, lite:false}'

##############################################################################
# INVENTORY / FIELD SURFACE
##############################################################################

mkdir -p "$OUT/field_paths"

: > "$OUT/inventory.txt"

for label in "${SUCCESS_LABELS[@]}"; do
    file="$OUT/${label}.json"

    jq -r \
        --arg label "$label" '
        def row_count:
            if type=="array" then length
            else 1
            end;

        def field_count:
            if type=="array" then
                ([.[] | select(type=="object") | keys[]] | unique | length)
            elif type=="object" then
                (keys | length)
            else
                0
            end;

        "\($label): json_type=\(type) rows=\(row_count) top_or_union_field_count=\(field_count)"
    ' "$file" >> "$OUT/inventory.txt"

    jq -r '
        paths(scalars)
        | map(
            if type=="number"
            then "[]"
            else tostring
            end
        )
        | join(".")
    ' "$file" \
        | sort -u \
        > "$OUT/field_paths/${label}.txt"
done

##############################################################################
# SUMMARY
##############################################################################

{
    echo "object_id=$OID"
    echo "ra=$RA"
    echo "dec=$DEC"
    echo "successful_json_responses=${#SUCCESS_LABELS[@]}"
    echo
    echo "[HTTP status]"
    cat "$OUT/http_status.tsv"
    echo
    echo "[Inventory]"
    cat "$OUT/inventory.txt"
} > "$OUT/summary.txt"

##############################################################################
# RESPONSE HASHES
##############################################################################

(
    cd "$OUT"

    for label in "${SUCCESS_LABELS[@]}"; do
        sha256sum "${label}.json"
    done
) > "$OUT/SHA256SUMS.txt"

##############################################################################
# COMPLETE
##############################################################################

echo
echo "Capture complete:"
echo "  $OUT"
echo
echo "HTTP status:"
column -t -s $'\t' "$OUT/http_status.tsv" 2>/dev/null \
    || cat "$OUT/http_status.tsv"
echo
echo "Inventory:"
cat "$OUT/inventory.txt"
echo
echo "Verify successful response hashes with:"
echo "  (cd \"$OUT\" && sha256sum -c SHA256SUMS.txt)"
echo
echo "Archive for review with:"
echo "  tar -C \"$(dirname "$OUT")\" -czf \"${OUT}.tar.gz\" \"$(basename "$OUT")\""
