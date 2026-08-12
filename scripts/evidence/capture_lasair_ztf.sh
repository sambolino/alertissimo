#!/usr/bin/env bash
# Capture raw Lasair/ZTF authenticated REST evidence. Credentials are never persisted.
set -euo pipefail
if [[ "${1:-}" == --help ]]; then echo "Usage: $0 [OUTPUT_DIR]"; echo "Requires LASAIR_TOKEN."; exit 0; fi
for cmd in curl jq sha256sum; do command -v "$cmd" >/dev/null || { echo "ERROR: required command not found: $cmd" >&2; exit 1; }; done
: "${LASAIR_TOKEN:?ERROR: LASAIR_TOKEN is required (raw token; it will not be persisted)}"
OID="${LASAIR_ZTF_OID:-ZTF20acpwljl}"
BASE='https://lasair-ztf.lsst.ac.uk'; STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"; OUT="${1:-/tmp/lasair-ztf-capture-${STAMP}}"
if [[ -d "$OUT" ]] && [[ -n "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then echo "ERROR: destination exists and is non-empty: $OUT" >&2; exit 1; fi
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"; CAPTURED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"; printf '%s\n' "$CAPTURED_AT" > "$OUT/capture_date.txt"
GIT_COMMIT="$(git rev-parse HEAD 2>/dev/null || printf unavailable)"; GIT_BRANCH="$(git branch --show-current 2>/dev/null || printf unavailable)"; GIT_BRANCH="${GIT_BRANCH:-unavailable}"
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
sha256sum "$0" | awk '{print $1 "  " $2}' > "$OUT/capture_script.sha256"
post() { local label="$1" path="$2"; shift 2; jq -n "$@" > "$OUT/${label}.request.json"; local form=(); while IFS=$'\t' read -r key value; do form+=(--data-urlencode "$key=$value"); done < <(jq -r 'to_entries[] | [.key, (.value|tostring)] | @tsv' "$OUT/${label}.request.json"); echo "POST $path"; curl --fail-with-body --compressed -sS -D "$OUT/${label}.headers" -H "Authorization: Token $LASAIR_TOKEN" "${form[@]}" "$BASE$path" -o "$OUT/${label}.json"; jq -e . "$OUT/${label}.json" >/dev/null; }
post object /api/object/ --arg oid "$OID" '{objectId:$oid,lasair_added:true}'
RA="$(jq -r '.ramean // .ra // .meanra' "$OUT/object.json")"; DEC="$(jq -r '.decmean // .dec // .meandec' "$OUT/object.json")"; if [[ "$RA" == null || "$DEC" == null || -z "$RA" || -z "$DEC" ]]; then echo "ERROR: primary object response has no usable RA/Dec" >&2; exit 1; fi
post lightcurves /api/lightcurves/ --arg oid "$OID" '{objectIds:$oid}'
post cone /api/cone/ --argjson ra "$RA" --argjson dec "$DEC" '{ra:$ra,dec:$dec,radius:5,requestType:"all"}'
post sherlock_objects /api/sherlock/objects/ --arg oid "$OID" '{objectIds:$oid,lite:true}'
post sherlock_position /api/sherlock/position/ --argjson ra "$RA" --argjson dec "$DEC" '{ra:$ra,dec:$dec,lite:true}'
FILES=(object lightcurves cone sherlock_objects sherlock_position)
{ for f in "${FILES[@]}"; do jq -r --arg f "$f" '"\($f): json_type=\(type) rows=\(if type=="array" then length else 1 end) union_field_count=\(if type=="array" and length>0 then ([.[]|keys[]]|unique|length) elif type=="object" then (keys|length) else 0 end)"' "$OUT/$f.json"; done; } > "$OUT/inventory.txt"
{ echo "object_id=$OID"; echo "ra=$RA"; echo "dec=$DEC"; for f in "${FILES[@]}"; do echo "$f=$(jq -r 'if type=="array" then length elif type=="object" then (keys|length) else 1 end' "$OUT/$f.json")"; done; } > "$OUT/summary.txt"
( cd "$OUT"; printf '%s\0' "${FILES[@]/%/.json}" | xargs -0 sha256sum > SHA256SUMS.txt )
echo "Verify response hashes with:"; echo "  (cd \"$OUT\" && sha256sum -c SHA256SUMS.txt)"; echo "Capture complete: $OUT"
