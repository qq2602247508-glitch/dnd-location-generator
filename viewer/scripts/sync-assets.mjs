import { copyFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const viewerRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const prototypeRoot = path.resolve(viewerRoot, "..");
const assets = path.join(viewerRoot, "public", "assets");
await mkdir(assets, { recursive: true });

const files = [
  ["output/church-dm.glb", "church-dm.glb"],
  ["output/church-player.glb", "church-player.glb"],
  ["output/underdark-dm.glb", "underdark-dm.glb"],
  ["output/underdark-grid.json", "underdark-grid.json"],
  ["output/city-dm.glb", "city-dm.glb"],
  ["output/city-grid.json", "city-grid.json"],
  ["output/harbor-v2/scene.glb", "harbor-v2.glb"],
  ["output/harbor-v2/scene.runtime.json", "harbor-v2.runtime.json"],
  ["output/v22-scenes/river_valley/scene.glb", "river-valley-v22.glb"],
  ["output/v22-scenes/river_valley/scene.grid.json", "river-valley-v22.grid.json"],
  ["output/v22-scenes/sewer_dungeon/scene.glb", "sewer-dungeon-v22.glb"],
  ["output/v22-scenes/sewer_dungeon/scene.grid.json", "sewer-dungeon-v22.grid.json"],
  ["output/v22-scenes/dragonbone_rift/scene.glb", "dragonbone-rift-v22.glb"],
  ["output/v22-scenes/dragonbone_rift/scene.grid.json", "dragonbone-rift-v22.grid.json"],
  ["specs/church.json", "church.json"],
  ["specs/underdark.json", "underdark.json"],
  ["specs/city.json", "city.json"],
];

for (const [source, destination] of files) {
  await copyFile(path.join(prototypeRoot, source), path.join(assets, destination));
}
console.log(`Synced ${files.length} local prototype assets.`);
