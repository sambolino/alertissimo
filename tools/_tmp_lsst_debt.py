#!/usr/bin/env python3
import json
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]
UP=ROOT/'alertissimo/data_layer/providers/lasair/lsst/unmapped_fields.yaml'
CAP=ROOT/'tests/fixtures/lasair/lsst/capture_20260813T140948Z'

d={'broker':'lasair','origin':'lsst','notes':'Authoritative semantic-debt registry for the authenticated 2026-08-13 Lasair/LSST capture. Existing ontology concepts are used where exact; remaining fields are explicit debt.','unmapped':[]}
seen=set()

def reason(ref):
 if 'scienceFluxMean' in ref:
  return 'structural_measurement_semantics','Rubin DiaObject scienceFlux aggregate is distinct from the existing forced-photometry aggregate; retain debt until aggregate image-plane structure is modeled without collision.'
 if ref.startswith('diaForcedSourcesList#scienceFlux'):
  return 'unresolved_measurement_semantics','DiaForcedSource contains distinct psfFlux and scienceFlux measurements; psfFlux is canonical today and scienceFlux needs a separate image-plane decision.'
 if 'photoZ' in ref:
  return 'structural_multi_redshift_semantics','Sherlock photoZ/photoZErr are a distinct redshift estimate and must not be collapsed into the native redshift slot.'
 if ref.endswith('#merged_rank'):
  return 'distinct_rank_semantics','Sherlock merged_rank is distinct from ordinal rank and is not a fallback for rank.'
 if ref.endswith('#rankScore'):
  return 'unsupported_semantic_concept','Sherlock rankScore is distinct from ordinal rank; no same-meaning canonical crossmatch path is available.'
 if ref.endswith('#_key'):
  return 'duplicate_execution_payload_context','Sherlock classification dictionary key identifies the queried transient; execution/portfolio context already carries that identity.'
 if any(x in ref for x in ('catalogue_table_id','catalogue_view_id','catalogue_view_name')):
  return 'provider_native_implementation_identifier','Sherlock catalogue table/view implementation metadata is not scientific crossmatch identity.'
 if 'catalogue_object_subtype' in ref:
  return 'unsupported_semantic_concept','Catalogue object subtype is more specific than the existing crossmatch catalogue classification slot.'
 if 'transient_object_id' in ref:
  return 'duplicate_execution_payload_context','Sherlock transient identifier identifies the queried transient rather than the matched catalogue object.'
 if 'original_search_radius_arcsec' in ref:
  return 'unsupported_semantic_concept','Sherlock search-radius configuration is query context rather than matched-source separation.'
 if 'sm_axis_arcsec' in ref or 'major_axis_arcsec' in ref:
  return 'unsupported_semantic_concept','Catalogue-source apparent morphology has no same-meaning canonical crossmatch morphology path.'
 if 'parentDiaSourceId' in ref:
  return 'relationship_requires_edge','Rubin parent DiaSource identity is a relationship and belongs on the edge plane rather than intrinsic detection identity.'
 if 'lasairData.annotations.' in ref:
  return 'provider_annotation_structure_deferred','Lasair annotation records require producer/topic-aware repeated-record treatment; preserve raw evidence without inventing a flat semantic slot.'
 if 'lasairData.imageUrls.' in ref:
  return 'role_qualified_data_product_deferred','Science/template/difference cutout URLs require role-qualified repeated data-product records linked to their DiaSource.'
 if ref=='cone_objects#separation':
  return 'ambiguous_meaning','Provider cone-result separation is preserved as debt until its unit/reference-position contract is encoded explicitly.'
 return 'authoritative_field_deferred','Observed authoritative Lasair/LSST field intentionally deferred because no exact existing semantic path was selected; no ontology extension is introduced here.'

def debt(ref):
 if ref in seen:return
 r,n=reason(ref);d['unmapped'].append({ref:{'reason':r,'candidate_meaning':n}});seen.add(ref)

for p in ('sherlock_object_crossmatches','sherlock_position_crossmatches'):
 for raw in ('photoZ','photoZErr','merged_rank','rankScore','catalogue_object_subtype','catalogue_table_id','catalogue_view_id','catalogue_view_name','original_search_radius_arcsec','sm_axis_arcsec','transient_object_id'):
  debt(f'{p}#{raw}')
for ref in ('object#lasairData.sherlock.photoZ','object#lasairData.sherlock.photoZErr','object#lasairData.sherlock.major_axis_arcsec','diaForcedSourcesList#scienceFlux','diaForcedSourcesList#scienceFluxErr','cone_objects#separation','sherlock_object_classifications#_key','sherlock_position_classifications#_key'):
 debt(ref)
for prefix in ('object#diaObject.','object#lasairData.'):
 for f in 'ugrizy':
  for s in ('scienceFluxMean','scienceFluxMeanErr'): debt(f'{prefix}{f}_{s}')
UP.write_text(yaml.safe_dump(d,sort_keys=False,width=120))

from tools.audit_payload_mapping_coverage import audit_payload

def fixture(name):return json.loads((CAP/f'{name}.json').read_text())
def unaccounted(report):
 lines=report.splitlines();start=lines.index('Unaccounted leaves:')+1;out=[]
 for line in lines[start:]:
  if not line.strip():break
  v=line.strip()
  if v!='(none)':out.append(v)
 return out

audits=[('object','object_default'),('object','object_with_context'),('object','object_raw'),('query','query_object'),('query','query_object_qualified'),('cone','cone_all'),('sherlock_object','sherlock_object_lite'),('sherlock_object','sherlock_object_full'),('sherlock_position','sherlock_position_lite'),('sherlock_position','sherlock_position_full')]
for endpoint,name in audits:
 report=audit_payload(fixture(name),broker='lasair',origin='lsst',endpoint=endpoint,payload_file=str(CAP/f'{name}.json'))
 for ref in unaccounted(report):debt(ref)
UP.write_text(yaml.safe_dump(d,sort_keys=False,width=120))
for endpoint,name in audits:
 report=audit_payload(fixture(name),broker='lasair',origin='lsst',endpoint=endpoint,payload_file=str(CAP/f'{name}.json'))
 if 'Unaccounted leaves: 0' not in report:raise RuntimeError(f'nonzero audit {endpoint}/{name}\n{report}')
print('debt refs',len(d['unmapped']))
