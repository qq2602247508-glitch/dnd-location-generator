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
  ["output/old-clock-v23/scene.glb", "old-clock-v23.glb"],
  ["output/old-clock-v23/scene.runtime.json", "old-clock-v23.runtime.json"],
  ["output/archetypes/tower/scene.glb", "tower-archetype.glb"],
  ["output/archetypes/tower/scene.runtime.json", "tower-archetype.runtime.json"],
  ["output/archetypes/manor/scene.glb", "manor-archetype.glb"],
  ["output/archetypes/manor/scene.runtime.json", "manor-archetype.runtime.json"],
  ["output/archetypes/sewer/scene.glb", "sewer-archetype.glb"],
  ["output/archetypes/sewer/scene.runtime.json", "sewer-archetype.runtime.json"],
  ["output/v22-scenes/river_valley/scene.glb", "river-valley-v22.glb"],
  ["output/v22-scenes/river_valley/scene.grid.json", "river-valley-v22.grid.json"],
  ["output/v22-scenes/sewer_dungeon/scene.glb", "sewer-dungeon-v22.glb"],
  ["output/v22-scenes/sewer_dungeon/scene.grid.json", "sewer-dungeon-v22.grid.json"],
  ["output/v22-scenes/dragonbone_rift/scene.glb", "dragonbone-rift-v22.glb"],
  ["output/v22-scenes/dragonbone_rift/scene.grid.json", "dragonbone-rift-v22.grid.json"],
  ["output/profile-visual/harbor_district/scene.glb", "profile-harbor-district.glb"],
  ["output/profile-visual/harbor_district/scene.render-manifest.json", "profile-harbor-district.render-manifest.json"],
  ["output/profile-visual/harbor_district.json", "profile-harbor-district.input.json"],
  ["output/profile-visual/silverfall_outdoor/scene.glb", "profile-silverfall-outdoor.glb"],
  ["output/profile-visual/silverfall_outdoor/scene.render-manifest.json", "profile-silverfall-outdoor.render-manifest.json"],
  ["output/profile-visual/silverfall_outdoor.json", "profile-silverfall-outdoor.input.json"],
  ["output/profile-visual/darkflow_pump_house/scene.glb", "profile-darkflow-pump-house.glb"],
  ["output/profile-visual/darkflow_pump_house/scene.render-manifest.json", "profile-darkflow-pump-house.render-manifest.json"],
  ["output/profile-visual/darkflow_pump_house.json", "profile-darkflow-pump-house.input.json"],
  ["specs/church.json", "church.json"],
  ["specs/underdark.json", "underdark.json"],
  ["specs/city.json", "city.json"],
];

for (const [source, destination] of files) {
  await copyFile(path.join(prototypeRoot, source), path.join(assets, destination));
}
console.log(`Synced ${files.length} local prototype assets.`);
