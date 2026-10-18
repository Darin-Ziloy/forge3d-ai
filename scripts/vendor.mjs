import { cp, mkdir } from 'node:fs/promises';
const dest = new URL('../forge3d/web/vendor/', import.meta.url);
await mkdir(dest, { recursive: true });
for (const part of ['build/three.module.js', 'build/three.core.js', 'examples/jsm/controls/OrbitControls.js', 'examples/jsm/loaders/GLTFLoader.js', 'examples/jsm/utils/BufferGeometryUtils.js', 'examples/jsm/environments/RoomEnvironment.js', 'LICENSE']) {
  await mkdir(new URL(part.substring(0, part.lastIndexOf('/') + 1), dest), { recursive: true });
  await cp(new URL('../node_modules/three/' + part, import.meta.url), new URL(part, dest), {recursive: true});
}
console.log('Three.js copied locally; the viewer works offline.');
