"""Offline guardrails for the maintained evidence acquisition entrypoints."""
from __future__ import annotations
import py_compile
import re
import stat
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "scripts" / "evidence"
sys.path.insert(0, str(EVIDENCE))
from client_capture import jsonable
SCRIPTS = [
 "capture_alerce_ztf.py", "capture_alerce_lsst.py",
 "capture_antares_ztf.py", "capture_antares_lsst.py",
 "capture_fink_ztf.sh", "capture_fink_lsst.sh",
 "capture_lasair_ztf.sh", "capture_lasair_lsst.sh",
]
def test_matrix_exists_and_is_offline_syntax_valid(tmp_path):
 for name in SCRIPTS:
  path=EVIDENCE/name
  assert path.is_file()
  text=path.read_text()
  assert "/tmp/" in text
  assert not re.search(r"(?i)(bearer|token)\s+[A-Za-z0-9_-]{20,}",text)
  if path.suffix==".sh":
   subprocess.run(["bash","-n",str(path)],check=True)
   assert path.stat().st_mode & stat.S_IXUSR
  else:
   py_compile.compile(str(path),cfile=str(tmp_path/(name+"c")),doraise=True)
def test_lasair_uses_environment_credential():
 for survey in ("ztf","lsst"):
  text=(EVIDENCE/f"capture_lasair_{survey}.sh").read_text()
  assert "LASAIR_TOKEN" in text
  assert "Authorization: Token $LASAIR_TOKEN" in text

def test_lasair_two_id_capture_contracts_are_offline_and_credential_safe():
 ztf=(EVIDENCE/'capture_lasair_ztf.sh').read_text()
 lsst=(EVIDENCE/'capture_lasair_lsst.sh').read_text()
 for text,variable in ((ztf,'LASAIR_ZTF_OID_2'),(lsst,'LASAIR_LSST_OID_2')):
  assert variable in text
  assert f'[[ -n "${{{variable}+x}}" ]]' in text
  assert 'must be non-empty when supplied' in text
  assert 'must differ from' in text
  metadata=text.split('cat > "$OUT/capture_metadata.txt" <<META',1)[1].split('\nMETA',1)[0]
  assert 'secondary_object_identifier=$OID_2' in metadata
  assert 'LASAIR_TOKEN' not in metadata
  assert 'Authorization' not in metadata
 assert '[[ "$OID_2" =~ ^ZTF[0-9]{2}[a-z]+$ ]]' in ztf
 assert '[[ "$OID_2" =~ ^[0-9]+$ ]]' in lsst
 assert 'sherlock_objects_batch_lite /api/sherlock/objects/' in ztf
 assert 'sherlock_objects_batch_full /api/sherlock/objects/' in ztf
 assert "'{objectIds:$ids, lite:true}'" in ztf
 assert 'sherlock_object_batch_lite /api/sherlock/object/' in lsst
 assert 'sherlock_object_batch_full /api/sherlock/object/' in lsst
 assert "'{objectId:$ids, lite:true}'" in lsst
 assert 'sherlock_object_lite /api/sherlock/object/' in ztf
 assert 'sherlock_object_lite /api/sherlock/object/' in lsst
 # Empty OID_2 preserves the original scalar path because batch calls are guarded.
 assert 'if [[ -n "$OID_2" ]]; then' in ztf
 assert 'if [[ -n "$OID_2" ]]; then' in lsst

def test_readme_indexes_all_pairs():
 text=(EVIDENCE/"README.md").read_text()
 for name in SCRIPTS: assert name in text

def test_antares_locus_id_comes_only_from_primary_lookup():
 for survey in ("ztf", "lsst"):
  text=(EVIDENCE/f"capture_antares_{survey}.py").read_text()
  assert "ANTARES_" + survey.upper() + "_LOCUS_ID" not in text
  assert "DEFAULT_LOCUS" not in text
  assert "locus_id=locus.locus_id" in text
  assert '{"locus_id":locus_id}' in text

def test_alerce_lsst_oid_is_parsed_once_as_integer():
 text=(EVIDENCE/"capture_alerce_lsst.py").read_text()
 assert "raw_oid = os.environ.get(ENV_OID, DEFAULT_OID)" in text
 assert "oid = int(raw_oid)" in text
 assert '"arguments": {"oid": oid' in text

def test_jsonable_preserves_non_finite_floats_distinctly_from_null():
 assert jsonable(None) is None
 assert jsonable(1.25) == 1.25
 values = [jsonable(float(value)) for value in ("nan", "inf", "-inf")]
 assert values == [
  {"__capture_float__": "nan"},
  {"__capture_float__": "+inf"},
  {"__capture_float__": "-inf"},
 ]
 assert all(value is not None for value in values)
 assert len({value["__capture_float__"] for value in values}) == 3
