# SceneProgram V2.2

`SceneProgram` 位于自然语言 brief 与格子几何之间。它不保存 cell mask，也不替代
`scene.plan.json`；它负责说明一个地方为什么存在、如何运转、玩家会遇到哪些有意义的
路线选择，以及几何实现阶段不能丢失哪些空间意图。

## 编译链

```text
program spec
  -> deterministic planner
  -> scene.program.json
  -> AdventureDirector / content slots
  -> geometry realizer
  -> scene.plan.json
  -> scene.runtime.json + GLB
```

当前规划器注册表包含：

- `city_district`：功能分区、地标、人流、货流、巡逻与地下服务流；
- `wilderness`：分水岭、河谷、山脊、道路、渡河点与洞穴；
- `infrastructure_dungeon`：原始用途、汇流渠、泵房、检修环、路口与占据者；
- `special_site`：不依赖房间的奇观型战术空间、高度平台、危险与地标路线。

## 核心字段

- `history_layers`：地质/建造/改造/占据的时间叠层；
- `zones`：功能或地貌区域；
- `nodes`：入口、路口、目标、状态控制点、秘密与首领节点；
- `routes`：主路线、回环、替代路线、垂直路线和秘密路线；
- `flows`：人流、货流、水流、排污、巡逻或怪物活动；
- `landmarks`：全局或局部方向锚点；
- `infrastructure`：道路、水系、管网、机械等功能系统；
- `factions`：区域控制者与使用者；
- `tactical_directives`：高地、掩体、瓶颈、环境状态与大型战场要求；
- `adventure_beats`：进入、选择、发现、升级与高潮位置。

## 硬验证

- 实体 ID 全局唯一，路线/流线/区域引用必须存在；
- 至少一个公共入口与一个目标/首领，且目标从入口可达；
- 必须同时有主路线、替代或回环路线以及秘密路线；
- 至少两层历史、一个地标和四个冒险节拍；
- 同 spec、seed 和 planner 版本生成的 canonical JSON 必须逐字节相同；
- `special_site` 明确声明 `rooms: none`，不能借房间系统伪装成奇观场景；
- 规划质量分低于 85 时拒绝进入几何阶段。

当前四个 fixture 的质量分为 97–100。质量分是进入下一阶段的门槛，不代替后续的
几何连通、D&D 规则、Blender 预算和真实浏览器视觉验收。

## Spatial Grammar V2.4

V2.4 在原有字段验证之前增加一个跨 archetype 的空间约束层，代码位于
`generator/v2/spatial_grammar.py`，由 `validate_program()` 强制调用。求解器是纯函数式
的：输入冻结的 SceneProgram，输出稳定的 grammar report，不回写输入，也不参与
`program_sha256`，所以旧的 Blender/Viewer 产物仍然可以复用。

约束分为三层：

1. 拓扑层：实体 ID 唯一，节点/区域/路线/流线/地标/基础设施引用完整；入口能到达
   objective/boss；必须有 primary、alternate/loop 和 DM-only secret 路线；用
   `E - V + components` 计算路线循环秩并满足 `required_cycles`。
2. 因果层：`shoreline` 必须有作业水岸与流线；`watershed` 必须存在 `high_to_low`
   水流；`infrastructure_flow` 必须同时有 utility flow 和 machine network；
   `mythic_landmark` 必须有方向地标和垂直玩法。
3. Archetype 层：城市要求 district + nested rooms，野外允许可选洞穴房间，基础设施
   地下城要求 functional chambers，special site 必须是 `rooms: none`。

这套约束是“规划可行性”门，不是视觉评分；几何连通、格子规则、Blender 预算和视觉
认证仍在后续阶段独立执行。这样新增塔楼、庄园、船、矿坑或下水道 pack 时，AI 只需填入
同一套空间语法，确定性 realizer 会在更早阶段拒绝自相矛盾的规划。

## AdventureDirector 与 DND 接口边界

`AdventureDirector` 消费冻结后的 program 和 DM profile，生成六阶段节奏、路线选项、
环境互动以及四类未解析内容槽位：

- `population`：NPC/阵营身份、活动区域与线索角色；
- `encounters`：位置、难度、CR 意图范围、波次和增援角色；
- `rewards`：风险引用、奖励等级、公开或 DM-only 可见性；
- `hooks`：调查、控制、营救等任务目标接口。

DM profile 当前包含队伍等级/人数、遭遇难度/密度/首领比例，以及奖励等级/隐藏比例。
修改 profile 只重建 adventure/content section，不允许改变 SceneProgram 空间 hash。

`DndContentAdapter` 是未来正式接入点。原型默认使用 `NullDndContentAdapter`：它原样
保留槽位，明确声明不生成 statblock、不写外部项目，并支持未来在不重建几何的情况下
重新解析 NPC、怪物和奖励。
