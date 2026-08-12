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
