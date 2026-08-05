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

## BuildingFactory（建筑独立生成入口）

`BuildingBrief` 是单体建筑的第二层合同。它只描述建筑身份、类型、规模、楼层请求、
房间语法和能力包，不把某一个样本锁死为专用生成器。`BuildingFactory` 根据注册配方
解析出可被 Blender、独立战术场景或 `DistrictComposer` 复用的 `BuildingProfile`：

- `family` / `footprint` / `frontage`：建筑家族、平面语法和街道界面；
- `vertical_grammar` / `floor_policy`：楼梯、夹层、吊桥、竖井和楼层策略；
- `room_grammar`：功能房间集合，允许密室、服务路线和目标空间参与规划；
- `traits` / `packs`：与三大类合同共享的能力和视觉角色；
- `quality_profile`：远景、中景、近景、战术四视角的建筑验收证据。

当前原型注册了塔楼、庄园、教堂、旅店、工坊、仓库、暗流泵房、矿井和神殿九种
可组合配方。泵房使用 `channel_adjacent_split_level` +
`low_channel_catwalk_pump_deck`，明确保留水道、低位渠道、检修猫道和泵机平台的
穿插关系；它不是简单的“两层房间叠加”。注册新建筑时只需增加配方和 fixture，
不修改街区或户外类别分支。

验证和独立解析：

```bash
python3 tests/verify_building_factory.py
python3 -m generator.v2.building_factory_cli \
  specs/buildings/darkflow_pump_house.json --resolve \
  --out output/buildings/darkflow_pump_house.profile.json
```

本阶段验证的是规划合同、可复现性和立体语法，不宣称 Blender 几何已经达到视觉
黄金标准；建筑几何会在后续 Visual Packs / Blender 阶段通过四视角视觉门禁验收。

## DistrictComposer（街区/城市编排入口）

`DistrictComposer` 位于建筑工厂之上，负责“如何把建筑组成一个有城市感的地方”，
而不是重新生成建筑本体。它从 district `SceneBrief` 推导：

- 规模与密度驱动的建筑数量，不用固定七栋或固定模板；
- 带弯折的主街、交叉街、货运水岸路和支巷，路网先于地块生成；
- 不规则地块、建筑朝向和 frontage，让街区不再是整齐棋盘；
- 地标宿主、远中近三层天际线和入口/人流/货流锚点；
- 每栋建筑对应一个独立 `BuildingProfile`，可被后续 Blender 层替换或复用。

输出是 `dnd-district-profile-1.0`。当前仍是规划层，不直接改写旧的
`scene.plan.json` / `scene.runtime.json`，因此不会破坏已有 DND 场景。验证会检查路网
连通、建筑与道路不重叠、地标在边界内、地块一一对应以及立面朝向存在变化。

```bash
python3 tests/verify_district_composer.py
python3 -m generator.v2.district_composer_cli \
  specs/districts/harbor_district_composer.json \
  --out output/districts/harbor_district.profile.json
```

街区的视觉验收仍需远景（整体布局/天际线）、中景（街道和地块）、建筑近景以及
战术视角四类证据；结构验证通过不等于视觉完成。

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
