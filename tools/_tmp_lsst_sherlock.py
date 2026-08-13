#!/usr/bin/env python3
from copy import deepcopy
import json
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
MP=ROOT/'alertissimo/data_layer/providers/lasair/lsst/mappings.yaml'
ZP=ROOT/'alertissimo/data_layer/providers/lasair/ztf/mappings.yaml'
CAP=ROOT/'tests/fixtures/lasair/lsst/capture_20260813T140948Z'
m=yaml.safe_load(MP.read_text()); z=yaml.safe_load(ZP.read_text())
obj=json.loads((CAP/'object_with_context.json').read_text())
fo=json.loads((CAP/'sherlock_object_full.json').read_text())
fp=json.loads((CAP/'sherlock_position_full.json').read_text())
compact=(obj.get('lasairData',{}).get('sherlock') or {})
ko={k for row in fo.get('crossmatches',[]) for k in row}
kp={k for row in fp.get('crossmatches',[]) for k in row}

def add(path,ref):
 out=m['mappings'].setdefault(path,[])
 if ref not in out: out.append(ref)

def xref(ref):
 if ref.startswith('object#sherlock.'):
  raw=ref.split('object#sherlock.',1)[1]
  return f'object#lasairData.sherlock.{raw}' if raw in compact else None
 if ref.startswith('sherlock_objects_classifications#'):
  return ref.replace('sherlock_objects_classifications#','sherlock_object_classifications#',1)
 if ref.startswith('sherlock_objects_crossmatches#'):
  raw=ref.split('#',1)[1]
  return f'sherlock_object_crossmatches#{raw}' if raw in ko else None
 if ref.startswith('sherlock_position_classifications#'): return ref
 if ref.startswith('sherlock_position_crossmatches#'):
  raw=ref.split('#',1)[1]
  return ref if raw in kp else None
 return None

def semok(s): return s.startswith('classification@sherlock:lasair.') or s.startswith('crossmatch@{producer}:lasair.')

for sem,refs in z.get('mappings',{}).items():
 if semok(sem):
  for ref in refs:
   new=xref(ref)
   if new: add(sem,new)
for sem,trs in z.get('transforms',{}).items():
 if not semok(sem): continue
 for ref,spec in trs.items():
  new=xref(ref)
  if new and new in m['mappings'].get(sem,[]):
   m['transforms'].setdefault(sem,{})[new]=deepcopy(spec)
pp='crossmatch@{producer}:lasair.provenance.producer.id'
for ref in m['mappings'].get(pp,[]):
 spec=m['transforms'].setdefault(pp,{}).setdefault(ref,{'type':'value_map','map':{}})
 if spec.get('type')=='value_map':
  spec.setdefault('map',{})['DESI']='desi_legacy_survey'; spec.pop('default',None)
ip='crossmatch@{producer}:lasair.identity.object_id'
for ref in m['mappings'].get(ip,[]):
 m['transforms'].setdefault(ip,{}).setdefault(ref,{'type':'to_string_strip'})
for f in ('W1','W2','W3','W4'):
 for p,keys in (('sherlock_object_crossmatches',ko),('sherlock_position_crossmatches',kp)):
  if f in keys: add(f'crossmatch@{{producer}}:lasair.photometry.{f}.mag',f'{p}#{f}')
  if f+'Err' in keys: add(f'crossmatch@{{producer}}:lasair.photometry.{f}.mag.error',f'{p}#{f}Err')
for sem in list(m['mappings']):
 refs=m['mappings'][sem]
 if sem=='crossmatch@{producer}:lasair.redshift.value': refs[:]=[r for r in refs if 'photoZ' not in r]
 if sem=='crossmatch@{producer}:lasair.redshift.error': refs[:]=[r for r in refs if 'photoZErr' not in r]
 if sem=='crossmatch@{producer}:lasair.rank': refs[:]=[r for r in refs if not r.endswith('#merged_rank')]
 if not refs: m['mappings'].pop(sem); m['transforms'].pop(sem,None)
for sem,trs in list(m['transforms'].items()):
 allowed=set(m['mappings'].get(sem,[]))
 for ref in list(trs):
  if ref not in allowed: trs.pop(ref)
 if not trs: m['transforms'].pop(sem)
MP.write_text(yaml.safe_dump(m,sort_keys=False,width=120))
print('sherlock generated',len(ko),len(kp),len(m['mappings']))
