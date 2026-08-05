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
  ["output/profile-visual/visual_tower/scene.glb", "profile-visual-tower.glb"],
  ["output/profile-visual/visual_tower/scene.render-manifest.json", "profile-visual-tower.render-manifest.json"],
  ["output/profile-visual/visual_tower.json", "profile-visual-tower.input.json"],
  ["output/profile-visual/visual_manor/scene.glb", "profile-visual-manor.glb"],
  ["output/profile-visual/visual_manor/scene.render-manifest.json", "profile-visual-manor.render-manifest.json"],
  ["output/profile-visual/visual_manor.json", "profile-visual-manor.input.json"],
  ["output/profile-visual/visual_sewer/scene.glb", "profile-visual-sewer.glb"],
  ["output/profile-visual/visual_sewer/scene.render-manifest.json", "profile-visual-sewer.render-manifest.json"],
  ["output/profile-visual/visual_sewer.json", "profile-visual-sewer.input.json"],
  ...["barracks", "cavern", "church", "fortress", "inn", "library", "lighthouse", "mine", "ruin", "tavern", "temple", "warehouse", "workshop"].flatMap((type) => [
    [`output/profile-visual/visual_${type}/scene.glb`, `profile-visual-${type}.glb`],
    [`output/profile-visual/visual_${type}/scene.render-manifest.json`, `profile-visual-${type}.render-manifest.json`],
    [`output/profile-visual/visual_${type}.json`, `profile-visual-${type}.input.json`],
  ]),
  ["specs/church.json", "church.json"],
  ["specs/underdark.json", "underdark.json"],
  ["specs/city.json", "city.json"],
];

for (const [source, destination] of files) {
  await copyFile(path.join(prototypeRoot, source), path.join(assets, destination));
}
console.log(`Synced ${files.length} local prototype assets.`);
