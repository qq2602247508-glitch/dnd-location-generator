# Scene Quality V2.4

V2.4 是独立于 planner、realizer、Blender 和 Viewer 的产物质量层。它读取已经冻结的
`scene.plan.json`、`scene.runtime.json`、render manifest 和同目录 GLB，不参与生成，也不
根据场景 ID 选择规则。

## 两类结果

硬门禁验证合同与安全性，包括 schema、场景身份、引用、导航连通、DM 权限隔离、
connector 端点、feature 落点、render receipt 和性能上限。硬门禁失败时，报告中的
`soft_score` 必须为 `null`，防止美术丰富度补偿不可游玩或泄密的场景。

软评分共 100 分：

| 维度 | 分值 | 当前可程序化证据 |
| --- | ---: | --- |
| 多样性 | 15 | feature/surface/variant/spatial entropy |
| 轮廓 | 15 | mask 重复率、单格尖刺、perimeter/area compactness |
| 路线、地标、层级 | 20 | level 覆盖、connector 类型、anchor/landmark 密度 |
| 生活痕迹 | 15 | feature 密度、种类、room/site 覆盖、语义 tags |
| 战术可读性 | 20 | nav degree、anchor 净空、connector 投影、阻塞密度 |
| 性能 | 15 | runtime/GLB/draw/vertex/build budget utilization |

`programmatic_pass_visual_pending` 只表示程序化阶段通过。标准化 DM/player 渲染评审尚未
写入 V2.4 evaluator，因此不能把该状态宣传为视觉认证完成。

## Layout fingerprint

`layout_fingerprint()` 明确排除 scene ID、名称、seed、叙事文本、feature variant 和随机
命名，只保留：

- grid 尺寸；
- level 高度、体量类型和归一化 mask；
- room role、visibility、level 与 mask；
- terrain kind 与 mask；
- connector 类型、visibility 和两端空间位置；
- runtime surface/elevation/walkability 分布。

同时输出短 token 集，用 Jaccard distance 衡量跨 seed 结构差异。仅改变 seed 或名称不会
制造虚假的布局多样性；真正改变 mask、层级或 connector 才会改变 fingerprint。

## 性能统计

render manifest 中的 `estimated_draw_calls` 和 `mesh_vertices` 可以是 builder 内部估算。
当同目录存在 `scene.glb` 时，quality CLI 直接读取 GLB JSON chunk：primitive 数是实际
draw-call 代理，POSITION accessor count 是实际顶点代理。GLB 数据优先于 manifest。

默认硬上限：runtime 10 MB、GLB 16 MB、250 primitives、450,000 vertices、Blender
构建 180 秒。历史 manifest 没有 timing receipt 时仍可评估，但 `build_seconds=0` 表示未知，
不是“零秒完成”。新流水线应通过 `--build-seconds` 写入外层实测值。

## 单场景报告

```bash
python3 -m generator.v2.quality_cli evaluate \
  --plan output/example/scene.plan.json \
  --runtime output/example/scene.runtime.json \
  --render-manifest output/example/scene-render-manifest.json \
  --out output/example/quality.report.json
```

报告 schema 为 `dnd-scene-quality-report-1.0`，包括硬门禁逐项证据、六维原始指标、
100 分软评分、layout fingerprint、输入 hash 与最终 report hash。

## Baseline 与三轮 cohort

Baseline 记录当前证据，不执行 cohort 阈值：

```bash
python3 -m generator.v2.quality_cli baseline \
  --root output/quality-seeds \
  --out output/quality-v24/baseline.json
```

正式轮次：

```bash
python3 -m generator.v2.quality_cli round \
  --name round2 \
  --root output/quality-seeds/round2 \
  --sample-reports-dir output/quality-v24/round2/samples \
  --out output/quality-v24/round2/cohort.json
```

默认协议由 `specs/quality/v2.4-policy.json` 控制：

| 轮次 | 样本下限 | score median / P10 | layout unique | clone 上限 | distance median / P10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| round1 | 8 | 65 / 55 | 65% | 35% | .10 / .02 |
| round2 | 24 | 75 / 65 | 80% | 20% | .15 / .03 |
| round3 | 64 | 80 / 70 | 90% | 5% | .20 / .05 |

每轮还要求零硬门禁失败，并单独检查每个推断 archetype 的 median，防止一个成熟类型掩盖
另一个类型的退化。统计 cohort 必须使用预先冻结的新 seed；同 seed 重跑只用于确定性门禁，
不能作为多样性样本。

## 与现有验证的边界

- `generator/v2/realize.py` 和各 fixture validator 继续负责几何/题型专属不变量；
- V2.4 不调用或修改 realizer；
- Blender 输出测试继续验证固定资产和材质回归；
- V2.4 只依赖通用 plan/runtime/render/GLB 合同；
- fixture 专属数量、建筑名称、材质名称和场景 ID 不得进入 quality policy 或 evaluator。

测试入口：

```bash
python3 tests/verify_quality_metrics.py
```
