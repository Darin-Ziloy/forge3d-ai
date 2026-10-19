"""Texture authoring contract and real portable textured/baked output checks."""
import copy
import json
import os
from pathlib import Path
import struct
import time
import zipfile
import zlib

import pytest
from pydantic import ValidationError

from forge3d.engine import Engine
from forge3d.schema import SceneSpec
from forge3d.server import archive
from forge3d.storage import import_asset, open_archive
from scripts.create_textured_example import atlas_box_scene


def png(path):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind+data))
    raw = b''.join(b'\0'+b''.join(bytes((220 if x<16 else 20, y*7, 80)) for x in range(32)) for y in range(32))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',32,32,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))


def box(asset):
    return atlas_box_scene(asset,{"size":[32,32],"faces":{k:[(i%3)*10,(i//3)*16,(i%3)*10+10,(i//3)*16+16] for i,k in enumerate(['front','back','left','right','top','bottom'])}})


def wait(engine, job):
    deadline = time.monotonic()+180
    while time.monotonic()<deadline:
        result=engine.job(job['id'])
        if result['status'] not in {'queued','running'}:
            return result
        time.sleep(.1)
    raise TimeoutError(engine.job(job['id']))


def glb(path):
    data=path.read_bytes()
    return json.loads(data[20:20+struct.unpack_from('<I',data,12)[0]])


def test_uv_validation_and_bake_references():
    scene=box('image.png')
    SceneSpec.model_validate(scene)
    for coordinates in [[], [[[0,0]]]*6, [[[float('nan'),0]]*4]*6]:
        bad=copy.deepcopy(scene)
        bad['objects'][0]['uv']['coordinates']=coordinates
        with pytest.raises(ValidationError): SceneSpec.model_validate(bad)
    with pytest.raises(ValidationError):
        SceneSpec.model_validate({'objects':[{'id':'low'}],'bakes':[{'low':'low','high':['missing']}]})
    with pytest.raises(ValidationError):
        SceneSpec.model_validate({'objects':[{'id':'low'}],'bakes':[{'low':'low','high':['low']}]})


def test_texture_copy_missing_and_path_escape(tmp_path):
    source=tmp_path/'atlas.png'; png(source)
    project=tmp_path/'project'
    asset=import_asset(project,str(source))
    assert (project/'assets'/asset['asset']).read_bytes()==source.read_bytes()
    engine=Engine(tmp_path/'engine')
    try:
        pid=engine.create_project('Images')['id']
        for name in ['../../atlas.png','C:/atlas.png','missing.png']:
            with pytest.raises(ValueError): engine.build(pid,{'scene':box(name)})
        assert not engine.jobs()
    finally: engine.close()


@pytest.mark.skipif(os.environ.get('FORGE3D_INTEGRATION')!='1',reason='Real Blender opt-in')
def test_textured_package_portability_and_baking(tmp_path):
    source=tmp_path/'atlas.png'; png(source)
    engine=Engine(tmp_path/'engine',timeout=180)
    try:
        pid=engine.create_project('Texture pipeline')['id']
        texture=engine.assets(pid,str(source))['asset']
        scene=box(texture)
        job=wait(engine,engine.build(pid,{'scene':scene,'render':{'enabled':True,'width':128,'height':128,'samples':1}}))
        assert job['status']=='succeeded',job
        report=job['manifest']['asset_report']
        assert (report['triangles'],report['mesh_count'],report['material_count'])==(12,1,1)
        assert report['objects'][0]['uv_maps']==['UV_Main']
        assert report['objects'][0]['degenerate_uv_faces']==0
        base=engine.job_dir(job['id'])
        data=glb(base/'preview.glb')
        assert 'TEXCOORD_0' in data['meshes'][0]['primitives'][0]['attributes']
        assert data['materials'][0]['pbrMetallicRoughness']['baseColorTexture']
        assert data['images'][0]['bufferView']>=0 and 'uri' not in data['images'][0]
        assert (base/'scene.fbx').stat().st_size>1000
        with zipfile.ZipFile(base/'asset_bundle.zip') as bundle:
            assert report['textures'][0]['path'] in bundle.namelist()
            assert 'render_00001.png' in bundle.namelist()
        # FBX must reimport with a texture; GLB must retain its embedded image.
        for name in ['scene.fbx','preview.glb']:
            imported_pid=engine.create_project('Reimport '+name)['id']
            asset=engine.assets(imported_pid,str(base/name))['asset']
            imported=wait(engine,engine.build(imported_pid,{'scene':{'objects':[{'id':'model','type':'import','asset':asset}]}}))
            assert imported['status']=='succeeded',imported
            assert imported['manifest']['textures'], imported
        # Archive/rebuild must remain independent of the original source/project.
        saved=archive(engine,pid)
        reopened=open_archive(engine.data,saved['path'])
        source.unlink()
        (engine.project_dir(pid)/'assets'/texture).unlink()
        restored=wait(engine,engine.restore(reopened['id'],job['id'],job['id']))
        assert restored['status']=='succeeded',restored
        rebuilt=wait(engine,engine.build(reopened['id'],{'scene':engine.project(reopened['id'])['scene'],'expected_revision':restored['id']}))
        assert rebuilt['status']=='succeeded',rebuilt
        assert rebuilt['manifest']['textures']
        # Atomic rejection of a textured mesh with collapsed UVs and of over-budget assets.
        bad=copy.deepcopy(scene); bad['materials'][0]['base_color_texture']['asset']=texture
        bad['objects'][0]['uv']['coordinates']=[[[0,0]]*4]*6
        failed=wait(engine,engine.build(reopened['id'],{'scene':bad,'expected_revision':rebuilt['id']}))
        assert failed['status']=='failed'
        assert engine.project(reopened['id'])['revision']==rebuilt['id']
        over_budget=copy.deepcopy(scene); over_budget['asset_checks']['max_tris']=10
        failed=wait(engine,engine.build(reopened['id'],{'scene':over_budget,'expected_revision':rebuilt['id']}))
        assert failed['status']=='failed'
        assert engine.project(reopened['id'])['revision']==rebuilt['id']
        pbr=copy.deepcopy(scene)
        for slot in ['normal_texture','roughness_texture','metallic_texture']:
            pbr['materials'][0][slot]={'asset':texture,'uv_map':'UV_Main'}
        maps=wait(engine,engine.build(reopened['id'],{'scene':pbr,'expected_revision':rebuilt['id']}))
        assert maps['status']=='succeeded',maps
        data=glb(engine.job_dir(maps['id'])/'preview.glb')
        assert data['materials'][0]['normalTexture']
        assert data['materials'][0]['pbrMetallicRoughness']['metallicRoughnessTexture']
        assert len(maps['manifest']['textures'])==4
        bake_pid=engine.create_project('Baked relief')['id']
        bake_scene={'export_fbx':True,'materials':[{'id':'paint','color':[.1,.6,.2,1]}],
            'objects':[{'id':'low','smooth':False,'uv':{'mode':'smart'}},
                       {'id':'high','smooth':False,'material':'paint','modifiers':[{'type':'bevel','amount':.08}]}],
            'bakes':[{'low':'low','high':['high'],'mode':'both','size':128,'cage_extrusion':.2}]}
        baked=wait(engine,engine.build(bake_pid,{'scene':bake_scene,'render':{'enabled':True,'width':128,'height':128,'samples':1}}))
        assert baked['status']=='succeeded',baked
        report=baked['manifest']['asset_report']
        assert report['mesh_count']==1 and len(report['textures'])==2
        assert {t['color_space'] for t in report['textures']}=={'sRGB','Non-Color'}
        assert all(o['name']!='high' for o in baked['manifest']['objects'])
        data=glb(engine.job_dir(baked['id'])/'preview.glb')
        assert data['materials'][0]['normalTexture']
        assert data['materials'][0]['pbrMetallicRoughness']['baseColorTexture']
    finally: engine.close()
