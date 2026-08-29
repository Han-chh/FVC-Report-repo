#!/usr/bin/env python3
"""Read-only official SAFE detector-footprint audit for frozen 47SNB scenes."""
from __future__ import annotations
import csv, json, os, tempfile
from pathlib import Path
import boto3, numpy as np, rasterio
from affine import Affine
from botocore.config import Config
from dotenv import load_dotenv
from rasterio.warp import reproject
from rasterio.enums import Resampling

PUBLICATION=Path(__file__).resolve().parents[2]; WORKSPACE=PUBLICATION.parents[1]
EXP=PUBLICATION/'new_experiments/15_three_sensor_parity'; OUT=EXP/'13_SENTINEL_SOURCE_SUPPORT_FORENSICS'
MANIFEST=EXP/'08_SENTINEL_STAGE0_REPAIR/04_CORRECTED_SENTINEL_MANIFEST.csv'
SCENES={'SR-01','SR-03','SR-05','SR-07','SR-08','SR-10'}
OLD_ROOT=WORKSPACE/'qh-fvc-data/storage/projects/prj_20260729085738_7fd76c__示例范围/data-center/imagery/series/series_20260729182250_38962d4d__sentinel-2-summer-l2a-series-多年度-series/years/2025/annual_20260729182250_bd19c5a4__2025-s2-l2a-harmonized-r1/raw/acquisition/tables/scene_manifest.json'
TARGET=Affine(10,0,527780,0,-10,4222650); SHAPE=(2389,3542)
def main():
 load_dotenv(WORKSPACE/'model/.env'); c=boto3.client('s3',endpoint_url='https://'+os.environ['EODATA_S3_ENDPOINT'],aws_access_key_id=os.environ['EODATA_S3_ACCESS_KEY'],aws_secret_access_key=os.environ['EODATA_S3_SECRET_KEY'],config=Config(signature_version='s3v4'))
 products={x['scene_id']:x['product_id'] for x in json.loads(OLD_ROOT.read_text())}; rows=[]
 for s in csv.DictReader(MANIFEST.open()):
  sid=s['Parity_Scene_ID']
  if sid not in SCENES: continue
  product=products[s['SR_system_index']]; date=product.split('_')[2][:8]; prefix=f'Sentinel-2/MSI/L2A/{date[:4]}/{date[4:6]}/{date[6:8]}/{product}.SAFE/GRANULE/'
  keys=[x['Key'] for x in c.list_objects_v2(Bucket='eodata',Prefix=prefix).get('Contents',[])]; selected={band:next(x for x in keys if x.endswith(f'MSK_DETFOO_{band}.jp2')) for band in ('B04','B08')}
  data={}
  for band,key in selected.items():
   p=Path(tempfile.mkstemp(suffix='.jp2')[1]); c.download_file('eodata',key,str(p))
   with rasterio.open(p) as d:
    z=np.zeros(SHAPE,dtype=np.uint8); reproject(d.read(1),z,src_transform=d.transform,src_crs=d.crs,dst_transform=TARGET,dst_crs='EPSG:32647',resampling=Resampling.nearest); data[band]=(z,d)
   p.unlink()
  b4,b8=data['B04'][0],data['B08'][0]; joint=(b4>0)&(b8>0); first=int(np.flatnonzero(joint.any(axis=1))[0]); last=int(np.flatnonzero(joint.any(axis=1))[-1])
  rows.append({'scene_id':sid,'SAFE_product_id':product,'MGRS_tile':s['SR_tile'],'acquisition_time':s['SR_acquisition_datetime'],'processing_baseline':s['SR_processing_baseline'],'B04_detector_mask_identity':selected['B04'],'B08_detector_mask_identity':selected['B08'],'B04_support_boundary_first_row':int(np.flatnonzero((b4>0).any(axis=1))[0]),'B08_support_boundary_first_row':int(np.flatnonzero((b8>0).any(axis=1))[0]),'joint_support_first_row':first,'joint_support_last_row':last,'support_boundaries_equal':bool(np.array_equal(b4>0,b8>0)),'source_grid':'EPSG:32647;10m;[10,0,499980,0,-10,4200000]'})
 OUT.mkdir(parents=True,exist_ok=True); fields=sorted(rows[0]);
 with (OUT/'03_DETECTOR_FOOTPRINT_AUDIT.csv').open('w',newline='') as h: w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(rows)
 print(len(rows))
if __name__=='__main__': main()
