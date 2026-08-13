#!/usr/bin/env bash
#
# Capture authoritative Lasair/LSST REST evidence.
# Credentials are NEVER persisted.
#
# Required:
#   LASAIR_TOKEN
#
# Optional:
#   LASAIR_LSST_OID   numeric diaObjectId; if unset, discover one
#   LASAIR_LSST_BASE  default: https://api.lasair.lsst.ac.uk
#
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage:
  capture_lasair_lsst.sh [OUTPUT_DIR]

Required:
  LASAIR_TOKEN       Raw Lasair API token; do NOT include "Token ".

Optional:
  LASAIR_LSST_OID    Numeric Rubin/LSST diaObjectId.
                     If unset, discover one with /api/query/.
  LASAIR_LSST_BASE   default: https://api.lasair.lsst.ac.uk

Captures:
  discovery query when needed
  object default / lasair_added=true / lasair_added=false
  plural objects probe
  lightcurves probe
  cone all / nearest / count
  fixed object query probes
  Sherlock object lite/full
  Sherlock position lite/full
  plural Sherlock lite/full probes

Compatibility probes may fail without aborting the authoritative core capture.
Credentials are never persisted.
EOF
    exit 0
fi

for cmd in curl jq sha256sum sort git; do
    command -v "$cmd" >/dev/null || {
        echo "ERROR: required command not found: $cmd" >&2
        exit 1
    }
done

: "${LASAIR_TOKEN:?ERROR: LASAIR_TOKEN is required}"

if [[ "$LASAIR_TOKEN" == Token\ * ]]; then
    echo 'ERROR: LASAIR_TOKEN must contain only the raw token.' >&2
    exit 1
fi

if [[ "$LASAIR_TOKEN" != "${LASAIR_TOKEN#"${LASAIR_TOKEN%%[![:space:]]*}"}" ]] ||
   [[ "$LASAIR_TOKEN" != "${LASAIR_TOKEN%"${LASAIR_TOKEN##*[![:space:]]}"}" ]]; then
    echo "ERROR: LASAIR_TOKEN has leading/trailing whitespace." >&2
    exit 1
fi

BASE="${LASAIR_LSST_BASE:-https://api.lasair.lsst.ac.uk}"
STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
OUT="${1:-/tmp/lasair-lsst-capture-${STAMP}}"

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
        jq -r 'to_entries[] | [.key, (.value | tostring)] | @tsv' \
            "$request_file"
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
            "$label" "$mode" NETWORK_ERROR unknown "$path" \
            >> "$OUT/http_status.tsv"

        echo "WARNING: curl/network failure for $label" >&2
        [[ "$mode" == required ]] && return 1
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
        [[ -f "$response_file" ]] && head -n 20 "$response_file" >&2 || true
        [[ "$mode" == required ]] && return 1
        return 0
    fi

    if [[ "$is_json" != yes ]]; then
        echo "WARNING: $label returned successful non-JSON response" >&2
        [[ "$mode" == required ]] && return 1
        return 0
    fi

    SUCCESS_LABELS+=("$label")
}

##############################################################################
# DISCOVER / RESOLVE A REAL DIAOBJECT
##############################################################################

OID="${LASAIR_LSST_OID:-}"

if [[ -z "$OID" ]]; then
    echo "LASAIR_LSST_OID not set; discovering a live diaObjectId."

    post optional discovery_query /api/query/ \
        '{
          selected:"diaObjectId",
          tables:"objects",
          conditions:"1=1",
          limit:10,
          offset:0
        }'

    if [[ -f "$OUT/discovery_query.json" ]]; then
        OID="$(
            jq -r '
              if type=="array" and length>0
              then (.[0].diaObjectId // empty)
              else empty
              end
            ' "$OUT/discovery_query.json"
        )"
    fi

    if [[ -z "$OID" ]]; then
        post optional discovery_query_qualified /api/query/ \
            '{
              selected:"objects.diaObjectId",
              tables:"objects",
              conditions:"1=1",
              limit:10,
              offset:0
            }'

        if [[ -f "$OUT/discovery_query_qualified.json" ]]; then
            OID="$(
                jq -r '
                  if type=="array" and length>0
                  then (.[0].diaObjectId // empty)
                  else empty
                  end
                ' "$OUT/discovery_query_qualified.json"
            )"
        fi
    fi

    if [[ -z "$OID" ]]; then
        echo "ERROR: could not discover a Lasair/LSST diaObjectId." >&2
        echo "Set LASAIR_LSST_OID explicitly and rerun with a NEW output directory." >&2
        exit 1
    fi
fi

if [[ ! "$OID" =~ ^[0-9]+$ ]]; then
    echo "ERROR: LSST diaObjectId must be numeric; got: $OID" >&2
    exit 1
fi

echo "Using LSST diaObjectId: $OID"

cat > "$OUT/capture_metadata.txt" <<META
broker=lasair
survey=lsst
capture_utc=$CAPTURED_AT
script=$0
transport=authenticated-rest
base_url=$BASE
primary_object_identifier=$OID
git_commit=$GIT_COMMIT
git_branch=$GIT_BRANCH
META

##############################################################################
# OBJECT SURFACE
##############################################################################

post optional object_default /api/object/ \
    --arg oid "$OID" \
    '{objectId:$oid}'

post required object_with_context /api/object/ \
    --arg oid "$OID" \
    '{objectId:$oid, lasair_added:true}'

post optional object_raw /api/object/ \
    --arg oid "$OID" \
    '{objectId:$oid, lasair_added:false}'

##############################################################################
# POSITION
##############################################################################

RA="$(
    jq -r '
      (if type=="array" then .[0] else . end)
      | .diaObject.ra
        // .objectData.ramean
        // .ramean
        // .ra
        // .meanra
        // empty
    ' "$OUT/object_with_context.json"
)"

DEC="$(
    jq -r '
      (if type=="array" then .[0] else . end)
      | .diaObject.decl
        // .diaObject.dec
        // .objectData.decmean
        // .decmean
        // .decl
        // .dec
        // .meandec
        // empty
    ' "$OUT/object_with_context.json"
)"

if [[ -z "$RA" || -z "$DEC" || "$RA" == null || "$DEC" == null ]]; then
    echo "ERROR: object response has no usable RA/Dec." >&2
    exit 1
fi

echo "Resolved position: RA=$RA Dec=$DEC"

##############################################################################
# COLLECTION / COMPATIBILITY SURFACES
##############################################################################

post optional objects_plural /api/objects/ \
    --arg oid "$OID" \
    '{objectIds:$oid}'

post optional lightcurves /api/lightcurves/ \
    --arg oid "$OID" \
    '{objectIds:$oid}'

##############################################################################
# CONE SHAPES
##############################################################################

post required cone_all /api/cone/ \
    --argjson ra "$RA" \
    --argjson dec "$DEC" \
    '{ra:$ra, dec:$dec, radius:5, requestType:"all"}'

post optional cone_nearest /api/cone/ \
    --argjson ra "$RA" \
    --argjson dec "$DEC" \
    '{ra:$ra, dec:$dec, radius:5, requestType:"nearest"}'

post optional cone_count /api/cone/ \
    --argjson ra "$RA" \
    --argjson dec "$DEC" \
    '{ra:$ra, dec:$dec, radius:5, requestType:"count"}'

##############################################################################
# FIXED QUERY PROBES
##############################################################################

QUERY_CONDITION="diaObjectId=${OID}"

post optional query_object /api/query/ \
    --arg condition "$QUERY_CONDITION" \
    '{
      selected:"diaObjectId",
      tables:"objects",
      conditions:$condition,
      limit:10,
      offset:0
    }'

QUERY_CONDITION_QUALIFIED="objects.diaObjectId=${OID}"

post optional query_object_qualified /api/query/ \
    --arg condition "$QUERY_CONDITION_QUALIFIED" \
    '{
      selected:"objects.diaObjectId",
      tables:"objects",
      conditions:$condition,
      limit:10,
      offset:0
    }'

##############################################################################
# SHERLOCK: LITE + FULL
##############################################################################

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

post optional sherlock_objects_lite /api/sherlock/objects/ \
    --arg oid "$OID" \
    '{objectIds:$oid, lite:true}'

post optional sherlock_objects_full /api/sherlock/objects/ \
    --arg oid "$OID" \
    '{objectIds:$oid, lite:false}'

##############################################################################
# INVENTORY / FIELD PATHS
##############################################################################

mkdir -p "$OUT/field_paths"
: > "$OUT/inventory.txt"

for label in "${SUCCESS_LABELS[@]}"; do
    file="$OUT/${label}.json"

    jq -r --arg label "$label" '
      def row_count:
        if type=="array" then length else 1 end;

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
      | map(if type=="number" then "[]" else tostring end)
      | join(".")
    ' "$file" |
        sort -u > "$OUT/field_paths/${label}.txt"
done

##############################################################################
# SUMMARY / HASHES
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

(
    cd "$OUT"
    for label in "${SUCCESS_LABELS[@]}"; do
        sha256sum "${label}.json"
    done
) > "$OUT/SHA256SUMS.txt"

echo
echo "Capture complete:"
echo "  $OUT"
echo
echo "HTTP status:"
column -t -s $'\t' "$OUT/http_status.tsv" 2>/dev/null ||
    cat "$OUT/http_status.tsv"
echo
echo "Inventory:"
cat "$OUT/inventory.txt"
echo
echo "Verify hashes:"
echo "  (cd \"$OUT\" && sha256sum -c SHA256SUMS.txt)"
echo
echo "Archive:"
echo "  tar -C \"$(dirname "$OUT")\" -czf \"${OUT}.tar.gz\" \"$(basename "$OUT")\""
