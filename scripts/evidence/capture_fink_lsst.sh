#!/usr/bin/env bash
# Capture the four independently supported Fink/Rubin REST surfaces without merging them.
set -euo pipefail
if [[ "${1:-}" == --help ]]; then echo "Usage: $0 [OUTPUT_DIR]"; exit 0; fi
for cmd in curl jq sha256sum; do command -v "$cmd" >/dev/null || { echo "ERROR: required command not found: $cmd" >&2; exit 1; }; done
BASE='https://api.lsst.fink-portal.org'; OID="${FINK_LSST_OID:-170587117485817955}"; STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"; OUT="${1:-/tmp/fink-lsst-capture-${STAMP}}"
if [[ -d "$OUT" ]] && [[ -n "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then echo "ERROR: destination exists and is non-empty: $OUT" >&2; exit 1; fi
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"; AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"; printf '%s\n' "$AT" > "$OUT/capture_date.txt"
COMMIT="$(git rev-parse HEAD 2>/dev/null || printf unavailable)"; BRANCH="$(git branch --show-current 2>/dev/null || printf unavailable)"; BRANCH="${BRANCH:-unavailable}"
printf 'broker=fink\nsurvey=lsst\ncapture_utc=%s\nscript=%s\ntransport=rest\nbase_url=%s\nprimary_object_identifier=%s\ngit_commit=%s\ngit_branch=%s\n' "$AT" "$0" "$BASE" "$OID" "$COMMIT" "$BRANCH" > "$OUT/capture_metadata.txt"
sha256sum "$0" > "$OUT/capture_script.sha256"
get_capture() { local name="$1" path="$2"; shift 2; jq -n "$@" > "$OUT/$name.request.json"; local query=(); while IFS=$'\t' read -r k v; do query+=(--data-urlencode "$k=$v"); done < <(jq -r 'to_entries[]|[.key,(.value|tostring)]|@tsv' "$OUT/$name.request.json"); curl --fail-with-body --compressed -sS -D "$OUT/$name.headers" -G "$BASE$path" "${query[@]}" -o "$OUT/$name.json"; jq -e . "$OUT/$name.json" >/dev/null; }
for endpoint in objects sources fp; do get_capture "$endpoint" "/api/v1/$endpoint" --arg oid "$OID" '{diaObjectId:$oid,"output-format":"json"}'; done
RA="$(jq -r '.[0]["r:ra"] // .[0].ra' "$OUT/objects.json")"; DEC="$(jq -r '.[0]["r:dec"] // .[0].dec' "$OUT/objects.json")"; [[ "$RA" != null && "$DEC" != null ]] || { echo 'ERROR: objects response has no RA/Dec' >&2; exit 1; }
get_capture conesearch /api/v1/conesearch --argjson ra "$RA" --argjson dec "$DEC" '{ra:$ra,dec:$dec,radius:1,n:100,columns:"r:diaSourceId,r:diaObjectId,r:midpointMjdTai,r:ra,r:dec,r:band,r:psfFlux,r:psfFluxErr,r:isNegative","output-format":"json"}'
FILES=(objects sources fp conesearch)
{ for f in "${FILES[@]}"; do jq -r --arg f "$f" '"\($f): json_type=\(type) rows=\(if type==\"array\" then length else 1 end) union_field_count=\(if type==\"array\" and length>0 then ([.[]|keys[]]|unique|length) elif type==\"object\" then (keys|length) else 0 end)"' "$OUT/$f.json"; done; } > "$OUT/inventory.txt"
{ echo "diaObjectId=$OID"; echo "ra=$RA"; echo "dec=$DEC"; for f in "${FILES[@]}"; do echo "$f.rows=$(jq 'if type==\"array\" then length else 1 end' "$OUT/$f.json")"; done; } > "$OUT/summary.txt"
( cd "$OUT"; sha256sum objects.json sources.json fp.json conesearch.json > SHA256SUMS.txt )
echo 'Verify response hashes with:'; echo "  (cd \"$OUT\" && sha256sum -c SHA256SUMS.txt)"; echo "Capture complete: $OUT"
