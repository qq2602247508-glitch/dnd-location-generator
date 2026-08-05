# Scene Contract V3.0

V3.0 把场景生成拆成三个可扩展的顶层类别：`district`（街区/城市）、`building`
（单体建筑/设施）和 `outdoor`（户外/特殊战术空间）。它们不是三个专用生成器，而是
三个规划入口，下面共享同一个 Traits、Visual Pack、连接和战术运行时系统。

## SceneBrief

输入文件使用 `dnd-scene-brief-1.0`：

```json
{
  "schema_version": "dnd-scene-brief-1.0",
  "scene": {"id": "harbor_district", "name": "潮钟港区", "seed": 20260805},
  "category": "district",
  "kind": "city_district",
  "scale": "district",
  "traits": ["urban_density", "waterfront", "landmark", "mixed_buildings"],
  "planning": {
    "building_count": {"mode": "derived", "density": "varied"},
    "building_mix": [{"id": "inn", "name": "旅店", "weight": 3}],
    "landmarks": [{"id": "beacon", "name": "信号塔", "role": "orientation"}]
  },
  "gameplay": {"focus": "district_routes", "encounter_density": "medium"}
}
```

`planning.building_count.mode=derived` 是默认方式。街区建筑数量由规模、地块、密度、
道路和地标共同决定，不能被某个样本的固定栋数锁死；只有测试或特殊委托才允许显式
`target`。

## Traits 与 Visual Packs

Trait 只描述空间能力，例如 `vertical_landmark`、`water_flow`、`cave`、`courtyard`、
`secret_route`。Visual Pack 描述可复用的视觉角色，例如 `vertical_connections`、
`hydrology`、`urban_facades`、`room_dressing`。解析器会将显式 Pack、类别默认 Pack
和 Trait 派生 Pack 合并并排序，确保同一 Brief 字节级确定。

注册表位于 `generator/v2/scene_contract.py`。未知 Trait/Pack 直接拒绝，避免拼写错误
静默生成出空场景；新增能力时只增加注册项和对应 planner/pack 实现，不修改既有类别
分支。

## 后续流水线

```text
SceneBrief
  → ScenePlanner（宏观规划/建筑工厂/户外地形）
  → Trait + Pack resolver
  → plan/runtime realizer
  → Blender visual layer
  → streetscape/dressing
  → tactical runtime + NPC/encounter/reward slots
```

建筑先由 `BuildingFactory` 独立验收，再由 `DistrictComposer` 以实例方式拼入街区；
户外场景可以独立存在，也可以承载建筑、遗迹和地下入口。几何仍使用固定 seed 和
现有 `scene.plan.json` / `scene.runtime.json` 合同，Viewer 不需要知道上游属于哪种
类别。

## 验证

```bash
python3 tests/verify_scene_contract.py
python3 -m generator.v2.scene_contract_cli \
  specs/scene_briefs/harbor_district.json --resolve \
  --out output/scene-briefs/harbor_district.profile.json
```

本阶段只建立输入合同和解析器，不宣称建筑或街区视觉已经完成；视觉认证仍必须经过
远景、中景、建筑近景和战术视角四类证据，并使用 `docs/scene-quality-v2.4.md` 的结构
与视觉双门禁。
