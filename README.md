# D&D 多层“冰山式”场景原型

这是一个与现有 D&D 项目完全隔离的 Blender 原型。它把一份接近现有
`SiteGenerationPreview` 的 JSON 编译为三层教堂、5 尺格、房间、楼梯、密室、
DM 完整模型和玩家隐藏模型。

## 已实现

- 三层教堂、14 个房间、3 个 DM-only 密室；
- 8 道普通门、3 道暗门、1→2→3 层楼梯连接；
- 楼层爆炸总览、每层 DM 视图、玩家一层视图；
- DM / 玩家独立 GLB；
- 固定 seed 和源 JSON SHA-256；
- 结构验证、PNG/GLB/BLEND 输出验证。

原型不会读取或修改 D&D SQLite，不启动端口，也不依赖 Ollama。当前阶段的重点是
证明现有站点/楼层/房间合同可以安全转换为 3D。

## 本地 Three.js 查看器

`viewer/` 提供一个与现有 D&D 项目隔离的本地战术场景实验台，现已支持：

- 教堂 DM / 玩家独立 GLB 切换，玩家端不会加载 DM 密室资产；
- 教堂 L1–L3、幽暗地域 E0–E4 和城市建筑 L1–L2 实时过滤；
- 城市街区外景、7 栋建筑内部范围切换与街区镜头恢复；
- 城市门与楼梯可在 3D 场景中直接点击，且楼梯上下两端都能触发；
- 建筑侧栏仅用于 DM 预览，不会传送或改动 Token；
- 城市 Token 使用同层 BFS 判定可达性：墙体不可穿越，跨房间只允许通过声明的 connector；
- 跨建筑和跨楼层只能从相邻入口/楼梯执行 transition；
- 格子点击、房间/地形检查和不可通行格拦截；
- 4 个简单测试 Token，选择后可移动到合法格；
- 场景切换、场景级镜头保存、适应场景和重置镜头；
- FPS、draw calls 和三角面统计。
- Generator V2 港区使用字符串层级、任意空间体焦点与显式 runtime 导航边；
- 港区可在地表、四层信号塔和负 15 尺下水道之间通过 connector 移动。

查看器只通过本机 HTTP 加载本地资产，不依赖公网。运行前先按工作区规则检查端口：

```bash
cd /Users/inagi/我的
./port-inventory.sh --check 5192
cd /Users/inagi/我的/500-软件测试/510-软件/dnd-multilevel-scene-prototype/viewer
npm run dev
```

生产构建：

```bash
cd /Users/inagi/我的/500-软件测试/510-软件/dnd-multilevel-scene-prototype/viewer
npm run build
```

## 运行

```bash
python3 tests/verify_spec.py specs/church.json
/Applications/Blender.app/Contents/MacOS/Blender --background --python blender/build_scene.py
python3 tests/verify_outputs.py
```

macOS 上 Blender 后台渲染需要访问 Metal；受限沙箱可能必须在正常终端或经授权运行。

## 关键文件

- `specs/church.json`：固定教堂场景合同；
- `blender/build_scene.py`：程序化生成、渲染和 GLB 导出；
- `tests/verify_spec.py`：房间重叠、连通、暗门、楼梯检查；
- `tests/verify_outputs.py`：图片、GLB、BLEND 和 DM/玩家差异检查；
- `output/church-prototype.blend`：可在 Blender 中继续查看和编辑；
- `output/church-dm.glb` / `church-player.glb`：查看器使用的独立权限资产；
- `viewer/src/main.ts`：Three.js 查看器核心；
- `viewer/scripts/sync-assets.mjs`：把原型输出同步到本地静态资源目录。

## Generator V2 通用场景框架

V2 不再把所有内容硬编码为“城市建筑”。它把场景拆成 `terrain / parcel /
volume / level / room / connector / feature / anchor`，其中 building、tower、cave、
sewer、ship 和 dungeon 都只是可扩展的 volume 类型。门、暗门、楼梯、梯子、舱口、
隧道与桥统一使用 connector；Viewer 移动只读取 `scene.runtime.json` 的显式导航边。

首个压力场景“潮钟港区 · 塔影与暗渠”包含：

- `72×56` 个 5 尺格、弯曲岸线、主路、巷道与港水；
- 10 个空间体、17 个层级、33 个带中文语义名称的房间；
- 6 栋非矩形建筑与一座四层收分信号塔；
- 负 15 尺的环形下水道、两处地表舱口、暗室与 DM-only 密门；
- 34 个统一 connector、7,321 条显式导航边和 73 个场景 feature；
- 信号塔 L1–L4、盐风旅店 L1–L2 与潮下排水网拥有房间化家具、机械、生活痕迹和实体楼梯/舱口；
- 信号塔有窗、垛口与发光信标，旅店有可剖切坡屋顶、烟囱和招牌，港岸有栈桥、桩与吊臂；
- 同 spec、pack、生成器版本和 seed 连续生成的 plan/runtime 字节级一致。

一键生成规则方案与运行时：

```bash
python3 -m generator.v2.cli \
  specs/scenes/harbor_vertical_underground.json \
  --out output/harbor-v2
python3 tests/verify_scene_v2.py
```

Blender 编译与产物验证：

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
  --background --python blender/build_scene_v2.py
python3 tests/verify_scene_v2_outputs.py
```

核心生成约 `0.07s`；runtime 约 `1.46MB`。V2.1 GLB 约 `11.1MB`，由 200 个
批量对象组成，34 个 connector 保留独立拾取节点。Feature 批次保留 volume/room
归属，跨层 connector 保留完整 level/volume 集合；Viewer 因此能在建筑剖切视图中
正确显示家具和上下层楼梯，同时避免内部门泄漏到地表视图。架构与扩展规范见
`docs/generator-v2-architecture.md`。

### V2.2 场景规划层

V2.2 在格子几何上游增加 `SceneProgram`。规划器先生成历史叠层、功能区、地标、
人流/货流/水流、基础设施、主路/环路/秘密路线、阵营和战术意图，再由后续 realizer
落到 plan/runtime。首批注册四类 planner：城镇、野外、基础设施地下城和不依赖房间的
奇观战术场景。

```bash
python3 tests/verify_scene_programs.py
python3 -m generator.v2.program_cli \
  specs/programs/dragonbone_rift.json \
  --out output/programs/dragonbone_rift.program.json
```

四个固定 seed fixture 均执行引用、路线选择、入口到目标、历史/地标/冒险节拍、
特殊场景零房间依赖及字节级确定性验证。完整合同见 `docs/scene-program-v2.2.md`。

AdventureDirector 使用独立 DM profile 生成 NPC、怪物遭遇、奖励和任务槽位；这些槽位
只保存位置、阵营、难度与风险意图，不含具体怪物 statblock。默认 Null adapter 不访问
或写入现有 DND 项目，未来正式 adapter 可以只重投内容而不重建场景几何。

```bash
python3 tests/verify_adventure_director.py
python3 -m generator.v2.adventure_cli \
  specs/programs/sewer_dungeon.json \
  --profile specs/dm_profiles/standard_level6.json \
  --out output/adventures/sewer_dungeon.adventure.json
```

### V2.2 几何与视觉实现场景

`SceneProgram` 现已能确定性落为统一的 `dnd-tactical-grid-1.0`。合同包含逐格高度、
可通行性、区域、表面、权限、锚点、实现后的路线、功能 feature，以及尚未解析的
NPC / 遭遇 / 奖励 / 任务槽位。潮钟港区映射既有 V2.1 runtime，不重复制造一套几何。

首批三种全新实现场景：

- 银瀑河谷：`64×56` 格、0–60 尺、单调下坡河流、浅滩与旧桥、洞口、瀑布和错位等高线；
- 暗流泵房：`56×56` 格、主渠低于走道 5 尺、四向汇流口、双检修环、泵机、闸门和秘密旧祠；
- 星陨龙骨裂谷：`61×61` 格、六档高度、无房间依赖、龙首/脊骨/肋骨、浮岩、裂隙与巨型生物平台。

生成并验证全部 grid：

```bash
python3 -m generator.v2.realize --all
python3 tests/verify_scene_realizers.py
```

Blender 使用同一个入口读取 grid，再按 archetype 分发独立视觉规则。战术顶面保持精确，
曲线、崖壁、植被、管网、骨架和生活痕迹只作为视觉皮肤，不改导航合同：

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python blender/build_v22_grid_scene.py -- \
  --input-dir output/v22-scenes/river_valley

/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python blender/build_v22_grid_scene.py -- \
  --input-dir output/v22-scenes/sewer_dungeon

/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python blender/build_v22_grid_scene.py -- \
  --input-dir output/v22-scenes/dragonbone_rift

python3 tests/verify_v22_scene_outputs.py
```

每个目录都包含 `scene.glb`、`scene-prototype.blend`、等距/俯视 PNG，以及记录输入和
输出 SHA-256 的 render manifest。产物门禁会检查 GLB v2、图片尺寸、metadata 引用、
DM-only 分批、语义对象种类和对象/顶点预算。

Viewer 提供与 DM / 玩家权限正交的剧场、探索、战术三模式。剧场隐藏格子与 Token，
探索保留环境阅读，战术收敛到可操作层；DM 还能调整近侧墙剖切、格子、雾、曝光、
Token 尺寸、权限对象、连接点和质量预设。

### V2.3 一键地点编译器

V2.3 新增 `LocationBrief -> pack resolver -> LocationProgram` 层。用户可以给出结构化
capability，也可以仅给一段中英文地点描述；原型使用确定性关键词适配层选择本地、
版本锁定的组合式 packs。未安装的 capability 会明确拒绝，不会让自由文本越过
门、楼梯、导航和权限验证。

首个压力 Brief 是「旧钟区 · 钟影与密渠」：11 个 packs、7 栋建筑、可进入的三层钟楼和
两层旅店、市场/窄巷/屋顶路线、负 15 尺排水网、DM-only 走私密室以及 10 个
NPC/遭遇/奖励/任务接口槽位。

```bash
python3 -m generator.v2.location_cli specs/locations/old_clock_quarter.json \
  --out output/locations/old_clock_quarter.location.json
python3 tests/verify_location_compiler.py
```

详细契约见 `docs/location-compiler-v2.3.md`。`generator/v2/location_realize.py` 已将冻结的
LocationProgram 落到既有 `dnd-scene-plan-2.0 / dnd-scene-runtime-2.0`：72×64 格、9 个空间体、
13 个层级、19 个房间、15 个连接器、10,117 条导航边，并提供街区、钟楼、屋顶和地下
四个展示预设。公开锚点连通、DM 密室隔离、两处地表舱口、楼梯/爬梯/屋顶桥和字节级
确定性均已自动验证。现有 DND 项目仍未修改。

```bash
python3 -m generator.v2.location_realize
python3 tests/verify_old_clock_v23.py
```

Blender 继续复用同一个 V2 编译器，新增钟面/大钟、屋顶栏杆和跨屋桥、市场雨棚/摊位/
手推车、晾衣绳、积水/车辙、湿砖管线与密室货物。战术屋顶是独立 runtime level，
不会被当成纯装饰屋顶。最终为 139 objects/draw calls、148,648 vertices、GLB 约 12.8 MB；
钟楼、旅店、市场、屋顶与下水道 metadata 及 DM-only 批次均通过产物门禁。

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python blender/build_scene_v2.py -- --input-dir output/old-clock-v23
python3 tests/verify_old_clock_v23_outputs.py
```

Viewer 已加入第八个场景“旧钟区 V2.3”，直接读取同一份 GLB 与权威 runtime。四个一键
预设分别聚焦街区总览、钟楼勘探、屋顶对峙和地下追踪；钟楼支持 L1–L3，歪钟旅店支持
L1–L2，屋顶路线和地下排水网使用各自的战术层级。4 个测试 Token、格子移动和
door / stairs / ladder / bridge / hatch / secret-door connector 共用同一套运行时逻辑。
玩家模式会隐藏 DM 参数、密室对象和秘密连接器，不需要加载第二套场景规则。

真实浏览器验收覆盖全部八个场景。旧钟区街区总览为 82 calls / 272,032 tris，钟楼 L1
为 23 calls / 5,196 tris，屋顶为 13 calls / 5,292 tris，地下 DM 视图为 36 calls /
38,904 tris；切换玩家地下视图后降为 22 calls / 36,348 tris。七个既有场景均保持非零
几何与正确标题，潮钟港区仍读取 7,321 条导航边；控制台无 warning 或 error。

## 尚未接入

- 现有数据库和 API；
- React 或现有 D&D 前端集成；
- 正式角色 Token、完整路径显示和战争迷雾；
- Ollama 自然语言转场景合同；
- 完全开放式、任意建筑类型的资产生成（当前由版本锁定的组合 pack 覆盖常用类型）。

这些边界是刻意保留的：先确认视觉方向，再决定是否把只读适配器接入现有项目。

## 大型幽暗地域原型

第二个原型验证自然场景和大地图：

- `48×36` 格，实际尺寸 `240×180` 尺；
- 1127 个可走格、601 个深渊/封闭格；
- 5 档高度，所有可走格按“相邻高差不超过一级”完全连通；
- 横贯地图的裂谷、两座桥、西部高地、北部遗迹、东部发光菌盆地；
- 46 株发光菌、28 组水晶、48 块岩石和低复杂度遗迹；
- 地形和战术格线批量合并，完整 GLB 约 3 MB。

关键文件：

- `specs/underdark.json`
- `generator/underdark_core.py`
- `blender/build_underdark.py`
- `tests/verify_underdark.py`
- `tests/verify_underdark_outputs.py`
- `output/underdark-prototype.blend`
- `output/underdark-dm.glb`

## 城市街区原型

第三个原型验证室外街区到建筑内部的连续战术空间：

- `32×28` 格，实际尺寸 `160×140` 尺；
- 7 栋可进入建筑，其中石鸦行会馆与铜盏旅店为双层；
- 644 个室外可走格全部连通，357 个室内可走格；
- 主街、支路、市场广场、路灯和水井；
- 7 条双向入口 transition 与 2 条双向楼梯 transition；
- 街区外景与建筑内部 scope、L1/L2 过滤、Token 入口转移和镜头聚焦/恢复；
- 门/楼梯是唯一的跨 scope、跨层通道，点击前要求已选 Token 且距离端点不超过 1 格；
- 普通格移动经过 BFS；室内跨房间边必须在 `specs/city.json` 的 connector 中声明；
- 入口合同会验证目标格确实属于声明的建筑、L1 和房间，避免视觉门与规则入口错位；
- 城市 GLB 约 2.8 MB，378 个导出对象全部带语义 extras。

生成与验证：

```bash
python3 tests/verify_city.py
/Applications/Blender.app/Contents/MacOS/Blender --background --python blender/build_city.py
python3 tests/verify_city_outputs.py
```

关键文件：

- `specs/city.json`
- `generator/city_core.py`
- `blender/build_city.py`
- `tests/verify_city.py`
- `tests/verify_city_outputs.py`
- `output/city-prototype.blend`
- `output/city-dm.glb`
- `output/city-grid.json`
