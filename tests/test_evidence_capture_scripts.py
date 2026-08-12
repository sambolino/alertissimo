"""Offline guardrails for the maintained evidence acquisition entrypoints."""
from __future__ import annotations
import py_compile
import re
import stat
import subprocess
from pathlib import Path
ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "scripts" / "evidence"
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
