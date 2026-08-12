#!/usr/bin/env python3
"""Capture representative ANTARES/LSST evidence with antares-client."""
from __future__ import annotations
import argparse, os
from pathlib import Path
from client_capture import describe, finish, git_value, package_version, prepare_output, write_json
SCRIPT=Path(__file__).resolve(); SURVEY="lsst"; DEFAULT_OID="170587117485817955"; DEFAULT_LOCUS="ANT2026rq61krn5dipt"; ENV_OID="ANTARES_LSST_OID"

def main():
 parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("output_dir",nargs="?",help="empty output directory (default: /tmp/antares-lsst-capture-TIMESTAMP)"); a=parser.parse_args()
 out,at=prepare_output(a.output_dir,"antares-lsst"); oid=os.environ.get(ENV_OID,DEFAULT_OID); locus_id=os.environ.get("ANTARES_LSST_LOCUS_ID",DEFAULT_LOCUS)
 try:
  from antares_client import search
  from astropy.coordinates import Angle, SkyCoord
  import astropy.units as u
 except ImportError as exc: raise SystemExit("ERROR: install repository-supported antares-client and astropy") from exc
 manifest={"broker":"antares","survey":SURVEY,"object_id":oid,"calls":{}}; payloads=[]; inventory={}
 def capture(label,method,args,call):
  entry={"client_method":method,"arguments":args,"survey":SURVEY,"object_id":oid,"endpoint_label":label}
  try: value=call()
  except Exception as exc:
   entry.update(status="error",error=f"{type(exc).__name__}: {exc}"); manifest["calls"][label]=entry; write_json(out/"capture_manifest.json",manifest); raise SystemExit(f"ERROR: {label} failed: {exc}") from exc
  if value is None: entry["status"]="empty"; manifest["calls"][label]=entry; return None
  if not isinstance(value,(dict,list,str,int,float,bool)) and hasattr(value,"__iter__") and label=="cone_search": value=list(value)
  clean=write_json(out/f"{label}.json",value); entry["status"]="empty" if clean in ([],{}) else "success"; manifest["calls"][label]=entry; payloads.append(f"{label}.json"); inventory[label]=describe(clean); return value
 locus=capture("get_by_lsst_dia_object_id","get_by_lsst_dia_object_id",{"object_id":oid},lambda:getattr(search,"get_by_lsst_dia_object_id")(oid))
 if locus is None: raise SystemExit(f"ERROR: primary object not found: {oid}")
 by_id=capture("get_by_id","get_by_id",{"locus_id":locus_id},lambda:search.get_by_id(locus_id))
 ra=float(getattr(locus,"ra")); dec=float(getattr(locus,"dec")); capture("cone_search","cone_search",{"ra_deg":ra,"dec_deg":dec,"radius_arcsec":1,"limit":5},lambda:list(search.cone_search(SkyCoord(ra=ra*u.deg,dec=dec*u.deg),Angle(1,u.arcsec)))[:5])
 # Preserve separate native lazy relationships rather than flattening them into the locus.
 for label in ("alerts","catalog_objects","lightcurve"):
  capture(label,f"Locus.{label}",{"locus_id":getattr(locus,'locus_id',locus_id)},lambda label=label:getattr(locus,label))
 write_json(out/"capture_manifest.json",manifest); (out/"capture_date.txt").write_text(at+"\n")
 (out/"capture_metadata.txt").write_text(f"broker=antares\nsurvey={SURVEY}\ncapture_utc={at}\nscript={SCRIPT}\ntransport=python-client\nclient_package=antares-client\nclient_version={package_version('antares-client')}\nprimary_object_identifier={oid}\nprimary_locus_identifier={locus_id}\ngit_commit={git_value('rev-parse','HEAD')}\ngit_branch={git_value('branch','--show-current')}\n")
 (out/"summary.txt").write_text(f"object_id={oid}\nlocus_id={getattr(locus,'locus_id',locus_id)}\nra={ra}\ndec={dec}\n"+"\n".join(f"{k}={v['status']}" for k,v in manifest['calls'].items())+"\n"); finish(out,SCRIPT,payloads,inventory)
if __name__=="__main__": main()
