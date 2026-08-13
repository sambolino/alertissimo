#!/usr/bin/env python3
from copy import deepcopy
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / 'alertissimo/data_layer/providers/lasair/lsst'
MP = P / 'mappings.yaml'
EP = P / 'endpoints.yaml'
CAP = ROOT / 'tests/fixtures/lasair/lsst/capture_20260813T140948Z'
ALE = yaml.safe_load((ROOT / 'alertissimo/data_layer/providers/alerce/lsst/mappings.yaml').read_text())
FINK = yaml.safe_load((ROOT / 'alertissimo/data_layer/providers/fink/lsst/mappings.yaml').read_text())
obj = json.loads((CAP / 'object_with_context.json').read_text())
source_rows = obj.get('diaSourcesList', [])
forced_rows = obj.get('diaForcedSourcesList', [])
source_keys = {k for row in source_rows for k in row}
forced_keys = {k for row in forced_rows for k in row}
dia_object = obj.get('diaObject', {})
lasair_data = obj.get('lasairData', {})

m = {
 'broker':'lasair','origin':'lsst',
 'description':'Authoritative semantic mappings for fields returned by the Lasair LSST REST API.',
 'payloads':{
  'object':{'endpoint':'object','path':'.'},
  'query':{'endpoint':'query','path':'[]'},
  'cone_objects':{'endpoint':'cone','path':'objects[]'},
  'diaSourcesList':{'endpoint':'object','path':'diaSourcesList[]'},
  'diaForcedSourcesList':{'endpoint':'object','path':'diaForcedSourcesList[]'},
  'sherlock_object_classifications':{'endpoint':'sherlock_object','path':'classifications{}'},
  'sherlock_position_classifications':{'endpoint':'sherlock_position','path':'classifications{}'},
  'sherlock_object_crossmatches':{'endpoint':'sherlock_object','path':'crossmatches[]'},
  'sherlock_position_crossmatches':{'endpoint':'sherlock_position','path':'crossmatches[]'},
 },
 'mappings':{},'transforms':{}
}

def add(path,*refs):
 out=m['mappings'].setdefault(path,[])
 for ref in refs:
  if ref not in out: out.append(ref)

def tr(path,ref,spec): m['transforms'].setdefault(path,{})[ref]=deepcopy(spec)

add('summary@lsst:lasair.identity.object_id','object#diaObjectId','object#diaObject.diaObjectId','object#lasairData.diaObjectId','query#diaObjectId','cone_objects#object')
add('summary@lsst:lasair.detection_count','object#diaObject.nDiaSources','object#lasairData.nDiaSources')
add('summary@lsst:lasair.time.first_mjd','object#diaObject.firstDiaSourceMjdTai','object#lasairData.firstDiaSourceMjdTai','object#lasairData.discMjd')
add('summary@lsst:lasair.time.last_mjd','object#diaObject.lastDiaSourceMjdTai','object#lasairData.lastDiaSourceMjdTai','object#lasairData.latestMjd')
add('summary@lsst:lasair.time.first_detection','object#lasairData.discUtc')
add('summary@lsst:lasair.time.last_detection','object#lasairData.latestUtc')
add('summary@lsst:lasair.position.ra','object#diaObject.ra')
add('summary@lsst:lasair.position.dec','object#diaObject.decl')
add('summary@lsst:lasair.position.ra_error','object#diaObject.raErr','object#lasairData.raErr')
add('summary@lsst:lasair.position.dec_error','object#diaObject.decErr','object#lasairData.decErr')
add('summary@lsst:lasair.position.ra_dec_covariance','object#diaObject.ra_dec_Cov','object#lasairData.ra_dec_Cov')

# Native DiaObject aggregates: inherit the already-authoritative Fink/Rubin semantics.
for sem,refs in FINK.get('mappings',{}).items():
 if not sem.startswith('summary@lsst:fink.'): continue
 target=sem.replace('summary@lsst:fink.','summary@lsst:lasair.',1)
 for ref in refs:
  if not ref.startswith('objects#r:'): continue
  raw=ref.split('#r:',1)[1]
  if raw in dia_object: add(target,f'object#diaObject.{raw}')
  if raw in lasair_data: add(target,f'object#lasairData.{raw}')

# Native DiaSource rows: inherit the authoritative ALeRCE/Rubin semantics by raw name.
for sem,refs in ALE.get('mappings',{}).items():
 if not sem.startswith('detection@lsst:alerce.'): continue
 target=sem.replace('detection@lsst:alerce.','detection@lsst:lasair.',1)
 for ref in refs:
  if not ref.startswith('query_detections#'): continue
  raw=ref.split('#',1)[1]
  if raw in source_keys: add(target,f'diaSourcesList#{raw}')
add('detection@lsst:lasair.identity.object_id','diaSourcesList#diaObjectId')
add('detection@lsst:lasair.identity.source_id','diaSourcesList#diaSourceId')
add('detection@lsst:lasair.time.mjd','diaSourcesList#midpointMjdTai')
add('detection@lsst:lasair.position.dec','diaSourcesList#decl')
add('detection@lsst:lasair.photometry.{filter}','diaSourcesList#band')
add('detection@lsst:lasair.forced_photometry.{filter}','diaSourcesList#band')
for sem,rawtrs in ALE.get('transforms',{}).items():
 if not sem.startswith('detection@lsst:alerce.'): continue
 target=sem.replace('detection@lsst:alerce.','detection@lsst:lasair.',1)
 for ref,spec in rawtrs.items():
  if not ref.startswith('query_detections#'): continue
  raw=ref.split('#',1)[1]; new=f'diaSourcesList#{raw}'
  if new in m['mappings'].get(target,[]): tr(target,new,spec)

forced={
 'detection@lsst:lasair.identity.object_id':'diaObjectId',
 'detection@lsst:lasair.identity.source_id':'diaForcedSourceId',
 'detection@lsst:lasair.identity.visit_id':'visit',
 'detection@lsst:lasair.identity.detector_id':'detector',
 'detection@lsst:lasair.time.mjd':'midpointMjdTai',
 'detection@lsst:lasair.time.processed_mjd':'timeProcessedMjdTai',
 'detection@lsst:lasair.time.invalidated_mjd':'timeWithdrawnMjdTai',
 'detection@lsst:lasair.position.ra':'ra','detection@lsst:lasair.position.dec':'decl',
 'detection@lsst:lasair.forced_photometry.{filter}':'band',
 'detection@lsst:lasair.forced_photometry.{filter}.psf.flux':'psfFlux',
 'detection@lsst:lasair.forced_photometry.{filter}.psf.flux.error':'psfFluxErr',
}
for sem,raw in forced.items():
 if raw in forced_keys: add(sem,f'diaForcedSourcesList#{raw}')

# Existing TNS singleton semantics remain valid; this particular object has an empty TNS block.
add('crossmatch@tns:lasair.identity.object_id','object#lasairData.TNS.name')
add('crossmatch@tns:lasair.position.ra','object#lasairData.TNS.ra')
add('crossmatch@tns:lasair.position.dec','object#lasairData.TNS.decl')

MP.write_text(yaml.safe_dump(m,sort_keys=False,width=120))
e=yaml.safe_load(EP.read_text())
e['endpoints']['cone']['output']['type']='object'
e['endpoints']['cone']['description']='Search LSST diaObjects around a sky position. The live service returns an object wrapper whose keys depend on requestType (objects, nearest, and/or count).'
EP.write_text(yaml.safe_dump(e,sort_keys=False,width=120))
print('core generated',len(source_rows),len(forced_rows),len(m['mappings']))
