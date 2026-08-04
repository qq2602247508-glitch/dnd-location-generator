# Generator V2：通用 D&D 场景编译架构

## 目标

Generator V2 不是“随机城市工具”，而是一条可验证的场景编译链。它要用同一套
空间语法表达港区、村落、塔楼、庄园、洞穴、矿坑、神殿、船只、地下城与下水道，
并保证 Blender 视觉、Three.js 拾取和未来 D&D 规则端使用同一份导航真相。

“万能”由可扩展的 archetype/theme pack 实现，而不是让大模型直接生成几何。
本地模型只负责把自然语言整理成受限的 SceneBrief、命名和叙事文本；拓扑、房间、
门、楼梯、寻路和验证必须由本地确定性代码完成。

## 四份产物

1. `scene.spec.json`：短小的创作意图、seed、预算、选择的生成包与硬约束。
2. `scene.plan.json`：冻结后的空间方案；地形、地块、空间体、楼层、房间、连接器和
   features 都已经落到明确 cell mask，不允许渲染器再次猜测。
3. `scene.runtime.json`：游戏规则合同；包含 cell、显式 nav edge、connector、anchor 和
   movement/visibility 数据。Viewer 与未来 D&D 项目只消费这一层。
4. `scene.glb`：显示资产；extras 只保存 `runtime_ref` 等引用，不成为规则真相。

`scene.manifest.json` 记录 spec、pack、generator、plan、runtime 和 GLB 的版本、hash、
seed stream、预算与验证报告，使旧战役可以复现并阻止 pack 升级后静默漂移。

## 通用空间语法

- `terrain`：岸线、水面、道路、高台、坡地、洞穴地面、污水渠等连续或格状地形。
- `route`：道路、河道、隧道、下水道主干等宏观路径意图；生成后光栅化为 terrain。
- `parcel`：地块与放置约束，不直接代表可走区域。
- `volume`：可聚焦的三维空间容器，类型可以是 building、tower、cave、sewer、ship、
  dungeon 或 district，并可嵌套。
- `level`：使用稳定字符串 ID，并显式保存 `z_base_ft` 与 `height_ft`。楼层名称不再
  兼作高度，因此塔楼 L4、地窖、负 15 尺下水道可同时存在。
- `room`：level 内的语义空间，使用 RLE cell mask；矩形只是可选原语。
- `connector`：统一 door、arch、gate、secret_door、stairs、ladder、ramp、hatch、
  tunnel、bridge 与 portal。两个端点必须显式声明，消费者不猜门外格或楼梯落点。
- `feature`：道具、光源、危险、掩体、机关、刷怪点与叙事簇；声明占格与净空需求。
- `anchor`：出生点、剧情入口、遭遇区、镜头焦点等稳定引用。

## 确定性流水线

1. 校验 spec 与 pack 版本，并从主 seed 派生 `macro/terrain/routes/parcels/volumes/
   rooms/features` 等命名随机流。
2. 生成地形、水岸和高差，再生成弯曲道路、码头、隧道与地下主干。
3. 从道路分割地块，并以约束方式放置空间体；地下体允许跨越多个地表地块。
4. 先生成房间拓扑图，再把房间铺入每层 mask；从真实共享 cell edge 求解门。
5. 生成跨层/跨空间 connector，然后放置 features；门口、楼梯、出生点和主通道必须
   保留净空。
6. 编译所有合法 nav edge。普通边只允许同 level 四邻格，任何跨墙、跨层或非四邻
   移动都必须引用 connector。
7. 执行连通、几何、权限、坐标、确定性与预算验证；失败只允许阶段内有限重试。
8. plan 编译为 Blender IR、runtime 和 GLB；同 seed、spec、pack hash 与生成器版本必须
   产生逐字节相同的 plan/runtime。

## 首个压力场景

`harbor_vertical_underground_v2` 同时验证：

- 72×56 港区、弯曲岸线、码头、弯曲主路和巷道；
- 至少 4 个非矩形地块/建筑；
- 一座逐层收分的四层信号塔；
- 负 15 尺的下水道环路、两处地表 hatch、污水渠、暗室与密门；
- 港口箱堆、缆绳、灯火、排水口、菌斑和鼠群等有净空约束的叙事簇。

首阶段验收目标：核心生成低于 10 秒、Blender 离线构建低于 3 分钟、runtime 小于
10 MB、初始 draw calls 小于 500，且旧 church/underdark/city 全部回归通过。

## 与 V1 的关系

V1 原型继续作为回归基线。V2 不手工维护第二份 city 数据；后续只在能力允许时从
V2 plan/runtime 投影出 V1 兼容文件。负层、任意 mask 或新 connector 类型若无法表达，
兼容器必须给出 capability warning，不能静默丢失。

