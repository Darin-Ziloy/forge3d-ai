import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const $ = id => document.getElementById(id);
const viewport = $('viewport');
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 10000);
camera.position.set(8, 5, 8);
let renderer;
try {
  renderer = new THREE.WebGLRenderer({antialias:true, alpha:true});
} catch (error) {
  $('empty').textContent = 'WebGL 2 is required. Open this viewer in Chrome or Edge with hardware acceleration enabled.';
  throw error;
}
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setClearColor(0x000000, 0);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.9;
viewport.prepend(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.target.set(0, 1, 0);
const pmrem = new THREE.PMREMGenerator(renderer);
const room = new RoomEnvironment();
const environment = pmrem.fromScene(room, 0.04);
scene.environment = environment.texture;
room.dispose(); pmrem.dispose();
scene.add(new THREE.HemisphereLight(0xdbead4, 0x455645, 0.8));
const light = new THREE.DirectionalLight(0xffead6, 1.5);
light.position.set(5, 8, 6); scene.add(light);
const fill = new THREE.DirectionalLight(0xc6e6ed, 0.8);
fill.position.set(-4, 3, -3); scene.add(fill);
const grid = new THREE.GridHelper(30, 30, 0x4e6353, 0x35443a);
grid.material.transparent = true; grid.material.opacity = 0.24; grid.position.y = -0.012;
scene.add(grid);
const loader = new GLTFLoader();
let model, mixer, clips = [], duration = 0, currentTime = 0, fps = 24, totalFrames = 0, playing = false;
let projectId = new URLSearchParams(location.search).get('project');
let project, loadedURL = '', desiredURL = '', generation = 0, wireframe = false;
let selected = null, projectSignature = '', outlinerSignature = '', lastError = '';
const stageNames = {starting:'Starting Blender', modeling:'Creating objects', saving:'Saving project', exporting_preview:'Exporting 3D preview', preview_ready:'Preview ready', rendering:'Rendering frame', complete:'All files saved', failed:'Engine error'};
const stateNames = {queued:'Queued', running:'Building scene', succeeded:'Ready to view', failed:'Job failed', cancelled:'Job cancelled', interrupted:'Job interrupted'};

async function api(path) {
  const response = await fetch('/api' + path, {cache:'no-store'});
  if (!response.ok) throw new Error((await response.json()).error || response.statusText);
  return response.json();
}
function notice(message) {
  $('notice').textContent = message; $('notice').hidden = false;
  clearTimeout(notice.timer); notice.timer = setTimeout(() => $('notice').hidden = true, 8000);
}
function dispose(root) {
  const textures = new Set(), materials = new Set(), geometries = new Set();
  root.traverse(node => {
    if (node.geometry) geometries.add(node.geometry);
    const list = Array.isArray(node.material) ? node.material : [node.material];
    for (const mat of list.filter(Boolean)) {
      materials.add(mat);
      for (const value of Object.values(mat)) if (value?.isTexture) textures.add(value);
    }
  });
  textures.forEach(texture => { texture.dispose(); texture.source?.data?.close?.(); });
  materials.forEach(material => material.dispose());
  geometries.forEach(geometry => geometry.dispose());
}
function resetModel() {
  generation++; desiredURL = ''; loadedURL = '';
  if (model) {
    mixer?.stopAllAction(); mixer?.uncacheRoot(model);
    scene.remove(model); dispose(model); model = null;
  }
  mixer = null; clips = []; duration = 0; playing = false;
  $('play').disabled = $('rewind').disabled = $('scrubber').disabled = true;
  $('empty').hidden = false; $('loading').hidden = true;
  select(null);
}
function fit() {
  if (!model) return;
  const box = new THREE.Box3();
  model.updateMatrixWorld(true);
  model.traverse(node => {
    if (node.isMesh && !node.userData.forge_preview_hidden) box.expandByObject(node);
  });
  if (box.isEmpty()) box.setFromObject(model);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const radius = Math.max(size.length() * 0.5, 0.2);
  const vfov = THREE.MathUtils.degToRad(camera.fov);
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect);
  const distance = radius / Math.sin(Math.min(vfov, hfov) / 2) * 1.25;
  camera.position.copy(center).add(new THREE.Vector3(0.9, 0.5, 1.4).normalize().multiplyScalar(distance));
  camera.near = Math.max(0.001, radius / 1000); camera.far = Math.max(1000, distance * 100);
  camera.updateProjectionMatrix(); controls.target.copy(center);
  controls.minDistance = radius / 20; controls.maxDistance = distance * 20; controls.update();
}
function setWireframe() {
  model?.traverse(node => {
    for (const material of (Array.isArray(node.material) ? node.material : [node.material]).filter(Boolean)) material.wireframe = wireframe;
  });
}
async function loadModel(url, autoFit = false) {
  if (url === desiredURL) return;
  desiredURL = url;
  const requestGeneration = ++generation;
  $('loading').hidden = false;
  try {
    const gltf = await loader.loadAsync(url);
    if (requestGeneration !== generation) { dispose(gltf.scene); return; }
    const hadModel = !!model;
    if (model) {
      mixer?.stopAllAction(); mixer?.uncacheRoot(model);
      scene.remove(model); dispose(model);
    }
    model = gltf.scene; scene.add(model); loadedURL = url;
    // Explicit scene flag; exported geometry and final Blender render retain the object.
    model.traverse(node => { if (node.userData.forge_preview_hidden) node.visible = false; });
    mixer = new THREE.AnimationMixer(model); clips = gltf.animations;
    duration = Math.max(0, ...clips.map(c => c.duration));
    clips.forEach(clip => mixer.clipAction(clip).play());
    currentTime = 0; mixer.setTime(0); playing = duration > 0;
    $('play').disabled = $('rewind').disabled = $('scrubber').disabled = !duration;
    $('scrubber').max = duration || 1;
    $('empty').hidden = true; $('loading').hidden = true;
    $('view-mode').textContent = '3D preview · glTF';
    setWireframe();
    if (!hadModel || autoFit) fit();
    select(null);
  } catch (error) {
    if (requestGeneration !== generation) return;
    desiredURL = ''; $('loading').hidden = true;
    notice('Could not load the 3D preview: ' + error.message);
  }
}
function select(node) {
  selected = node;
  $('selection').textContent = node?.name || 'Nothing selected';
  $('selection-detail').textContent = node?.geometry ? `${node.geometry.attributes.position?.count || 0} vertices · ${node.type}` : node ? node.type : 'Click a model in the viewport';
  $('outliner').querySelectorAll('button').forEach(button => button.classList.toggle('selected', button.dataset.name === node?.name));
}
const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
let pointerStart;
renderer.domElement.addEventListener('pointerdown', event => pointerStart = [event.clientX, event.clientY]);
renderer.domElement.addEventListener('pointerup', event => {
  if (!model || !pointerStart || Math.hypot(event.clientX-pointerStart[0], event.clientY-pointerStart[1]) > 4) return;
  const rect = renderer.domElement.getBoundingClientRect();
  mouse.set((event.clientX-rect.left)/rect.width*2-1, -(event.clientY-rect.top)/rect.height*2+1);
  ray.setFromCamera(mouse, camera); select(ray.intersectObject(model, true)[0]?.object || null);
});
new ResizeObserver(() => {
  const width = viewport.clientWidth, height = viewport.clientHeight;
  renderer.setSize(width, height); camera.aspect = width / Math.max(1, height); camera.updateProjectionMatrix();
}).observe(viewport);
$('fit').onclick = fit;
window.addEventListener('keydown', event => { if (event.key.toLowerCase() === 'f' && !['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName)) fit(); });
$('wireframe').onclick = () => { wireframe = !wireframe; $('wireframe').setAttribute('aria-pressed', wireframe); setWireframe(); };
$('rotate').onclick = () => { controls.autoRotate = !controls.autoRotate; $('rotate').setAttribute('aria-pressed', controls.autoRotate); };
$('fullscreen').onclick = async () => { try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); } catch(error) { notice(error.message); } };
$('play').onclick = () => playing = !playing;
$('rewind').onclick = () => { currentTime = 0; mixer?.setTime(0); };
$('scrubber').oninput = event => { playing = false; currentTime = Number(event.target.value); mixer?.setTime(currentTime); };
$('render-button').onclick = () => $('render-dialog').showModal();
$('close-render').onclick = () => $('render-dialog').close();
$('render-dialog').onclick = event => { if(event.target === $('render-dialog')) $('render-dialog').close(); };
$('projects').onchange = () => {
  projectId = $('projects').value; project = null; outlinerSignature = ''; resetModel();
  history.replaceState(null, '', '/?project=' + projectId);
  $('revisions').replaceChildren(new Option('Current · live', 'live'));
  $('render-image').hidden = true; $('render-empty').hidden = false; $('render-button').disabled = true; $('render-download').hidden = true;
  for (const id of ['download-glb','download-blend']) { $(id).removeAttribute('href'); $(id).classList.add('disabled'); }
};
$('revisions').onchange = () => { desiredURL = ''; };

function showProject(data) {
  project = data;
  $('scene-title').textContent = data.scene?.name || data.name;
  $('scene-subtitle').textContent = `${data.history.length} versions · autosaved`;
  const revs = $('revisions');
  const signature = data.history.join(',');
  if (revs.dataset.signature !== signature) {
    const previous = revs.value;
    revs.replaceChildren(new Option('Current · live', 'live'));
    [...data.history].reverse().forEach((id, i) => revs.add(new Option(`Version ${data.history.length-i} · ${id.slice(0,8)}`, id)));
    if ([...revs.options].some(option => option.value === previous)) revs.value = previous;
    revs.dataset.signature = signature;
  }
}
function showInventory(manifest, signature) {
  if (outlinerSignature === signature) return;
  outlinerSignature = signature;
  const objects = (manifest?.objects || []).filter(o => !['CAMERA','LIGHT'].includes(o.type));
  $('object-count').textContent = objects.length;
  $('outliner').replaceChildren();
  objects.forEach(obj => {
    const button = document.createElement('button'); button.className = 'object-row';
    button.textContent = obj.name; button.dataset.name = obj.name;
    button.onclick = () => select(model?.getObjectByName(obj.name));
    $('outliner').append(button);
  });
  fps = manifest?.fps || 24; $('fps').textContent = fps + ' FPS';
  totalFrames = manifest ? manifest.frame_end - manifest.frame_start + 1 : 0;
  if(manifest?.blender_version) $('engine-label').textContent = manifest.blender_version + ' · background';
}
function showJob(job) {
  if (!job) {
    $('job-status').textContent = 'Waiting for a job'; $('job-stage').textContent = 'AI can work in the background';
    $('percent').textContent = '—'; $('progress').style.width = '0%'; $('job-list').replaceChildren();
    $('log').textContent = 'No log entries'; return;
  }
  const progress = job.progress || {};
  const done = job.status === 'succeeded';
  $('job-status').textContent = stateNames[job.status] || job.status;
  $('status-icon').textContent = done ? '✓' : job.status === 'failed' ? '!' : '◎';
  $('job-stage').textContent = job.error || stageNames[progress.stage] || 'Waiting to start';
  const percent = done ? 100 : Math.round((progress.fraction || 0)*100);
  $('percent').textContent = percent + '%'; $('progress').style.width = percent + '%';
  $('job-kind').textContent = job.kind.toUpperCase() + ' / ' + job.id.slice(0,8);
  $('log').textContent = job.log_tail || 'Starting…';
}
async function poll() {
  try {
    const [health, projects, jobs] = await Promise.all([api('/health'), api('/projects'), api('/jobs')]);
    $('connection').textContent = health.blender ? 'LOCAL ENGINE ONLINE' : 'BLENDER NOT FOUND';
    $('engine-label').textContent = project?.manifest?.blender_version ? project.manifest.blender_version + ' · background' : health.blender ? 'Ready' : 'Set BLENDER_PATH';
    const signature = projects.map(p => p.id+p.name).join();
    if (projectSignature !== signature) {
      projectSignature = signature;
      $('projects').replaceChildren(...projects.map(p => new Option(p.name, p.id)));
      if (!projects.length) $('projects').add(new Option('No projects', ''));
    }
    if (!projects.some(p => p.id === projectId)) projectId = projects[0]?.id;
    if (projectId) {
      $('projects').value = projectId;
      const selectedProject = projectId;
      const data = await api('/projects/' + selectedProject);
      if (projectId !== selectedProject) return;
      showProject(data);
      const filtered = jobs.filter(job => job.project === selectedProject);
      const latest = filtered[0] ? await api('/jobs/' + filtered[0].id) : null;
      if (projectId !== selectedProject) return;
      showJob(latest);
      $('job-list').replaceChildren(...filtered.slice(0,4).map(job => {
        const row = document.createElement('div'); row.className = 'job-row';
        const label = document.createElement('span'); label.textContent = job.kind + ' · ' + job.id.slice(0,6);
        const state = document.createElement('span'); state.className = job.status; state.textContent = job.status === 'succeeded' ? '✓ saved' : job.status;
        row.append(label, state); return row;
      }));
      const revision = $('revisions').value === 'live' ? data.revision : $('revisions').value;
      let base = revision ? `/artifacts/projects/${selectedProject}/${revision}/` : '';
      let selectedManifest = null;
      // A completed GLB can be inspected while its render is still running.
      if ($('revisions').value === 'live' && latest?.status === 'running' && latest.progress?.preview) base = `/artifacts/jobs/${latest.id}/`;
      if (base) {
        loadModel(base + 'preview.glb');
        if(revision) {
          const saved = `/artifacts/projects/${selectedProject}/${revision}/`;
          for (const [id,name] of [['download-glb','preview.glb'],['download-blend','scene.blend']]) {
            $(id).href = saved + name; $(id).classList.remove('disabled');
          }
          selectedManifest = revision === data.revision ? data.manifest : await (await fetch(saved+'manifest.json')).json();
          if (projectId === selectedProject) showInventory(selectedManifest, selectedProject + revision);
        }
      } else if (model) {
        resetModel();
      }
      const renderJob = filtered.find(job => job.status === 'succeeded' && job.manifest?.renders?.length && (job.id === revision || (job.kind === 'render' && job.base_revision === revision)));
      const renderURL = renderJob ? `/artifacts/jobs/${renderJob.id}/${renderJob.manifest.renders[0]}` : selectedManifest?.renders?.length ? `/artifacts/projects/${selectedProject}/${revision}/${selectedManifest.renders[0]}` : '';
      if(renderURL) {
        const url = renderURL;
        if ($('render-image').getAttribute('src') !== url) {
          $('render-image').src = $('large-render').src = url; $('render-download').href = url;
        }
        $('render-image').hidden = false; $('render-empty').hidden = true; $('render-button').disabled = false; $('render-download').hidden = false;
      } else {
        $('render-image').hidden = true; $('render-empty').hidden = false; $('render-button').disabled = true; $('render-download').hidden = true;
      }
    }
    lastError = '';
  } catch (error) {
    $('connection').textContent = 'ENGINE OFFLINE';
    if (lastError !== error.message) { notice('Service unavailable: ' + error.message); lastError = error.message; }
  } finally { setTimeout(poll, document.hidden ? 3500 : 1200); }
}
let previousTime = performance.now();
renderer.setAnimationLoop(now => {
  const delta = Math.min((now-previousTime)/1000, .1); previousTime = now;
  if (document.hidden) return;
  if (playing && duration) { currentTime = (currentTime + delta) % duration; mixer?.setTime(currentTime); }
  $('play').textContent = playing ? 'Ⅱ' : '▶';
  $('scrubber').value = currentTime;
  $('timecode').textContent = `${String(Math.floor(currentTime/60)).padStart(2,'0')}:${(currentTime%60).toFixed(2).padStart(5,'0')}`;
  const frameCount = totalFrames || Math.round(duration*fps);
  $('frame-label').textContent = `${duration ? Math.min(frameCount, Math.round(currentTime*fps)+1) : 0} / ${duration ? frameCount : 0}`;
  controls.update(); renderer.render(scene, camera);
});
poll();
