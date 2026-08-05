# Location Compiler V2.3

V2.3 把「再添加一张硬编码地图」改成组合式地点编译。输入是简短的
`LocationBrief`，输出是冻结的 `LocationProgram`；两者之间由本地、确定性的
pack resolver 完成，不让大模型直接决定格子、门、楼梯或导航。

## 契约

- `dnd-location-brief-1.0`：场景、seed、尺寸、自然语言 prompt、必需 capability 和队伍档案。
- `dnd-location-program-1.0`：版本化 packs、历史叠层、功能区、建筑/楼层/房间层级、地表/屋顶/地下路线、生活痕迹和内容槽位。
- `resolved_packs`：每个 pack 都锁定 id/version/provides；未被本机 pack 覆盖的 capability 必须拒绝编译。

当 `required_capabilities` 为空时，原型可从中英文 prompt 提取受限 capability。这是可测的
关键词适配层，不是自由文本几何生成；未来 Ollama/DeepSeek 只需替换 Brief adapter。

## 旧钟区压力场景

首个组合结果锁定 11 个 packs，包含 7 栋建筑、可进入的三层钟楼与两层旅店、
市场回环、窄巷侧路、屋顶追逐线、负 15 尺排水网和 DM-only 走私密室。NPC、
遭遇、奖励和任务仍是 unresolved slots，不访问现有 DND 项目。

```bash
python3 -m generator.v2.location_cli specs/locations/old_clock_quarter.json \
  --out output/locations/old_clock_quarter.location.json
python3 tests/verify_location_compiler.py
```
