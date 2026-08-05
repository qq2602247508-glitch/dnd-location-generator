import "./style.css";

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

type SceneKey = "church" | "underdark" | "city" | "harbor" | "old_clock" | "tower" | "manor" | "sewer" | "river_valley" | "sewer_dungeon" | "dragonbone_rift" | "profile_harbor" | "profile_outdoor" | "profile_pump_house";
type V22SceneKey = "river_valley" | "sewer_dungeon" | "dragonbone_rift";
type RuntimeSceneKey = "harbor" | "old_clock" | "tower" | "manor" | "sewer";
type ProfileSceneKey = "profile_harbor" | "profile_outdoor" | "profile_pump_house";
type ViewMode = "dm" | "player";
type ExperienceMode = "theatre" | "exploration" | "tactical";
type QualityPreset = "quality" | "balanced" | "performance";
type LayerFilter = "all" | number;
type CityScope = "outdoor" | string;

/**
 * V2.2 keeps player/DM access separate from how a scene is experienced.  The
 * legacy per-scene variables remain below so existing navigation code can be
 * migrated gradually; this is the single public state snapshot for new UI and
 * rendering behaviour.
 */
interface ViewerState {
  sceneKey: SceneKey;
  accessMode: ViewMode;
  experienceMode: ExperienceMode;
  focusId: string;
  layer: LayerFilter | string;
  selectedToken: number | null;
}

interface DmTuning {
  cutawayEnabled: boolean;
  cutawayOpacity: number;
  gridOpacity: number;
  fogDensity: number;
  exposure: number;
  tokenScale: number;
  showDmOnly: boolean;
  showHotspots: boolean;
  qualityPreset: QualityPreset;
}

interface MaterialSnapshot {
  material: THREE.Material;
  opacity: number;
  transparent: boolean;
  depthWrite: boolean;
}

interface SemanticMesh {
  mesh: THREE.Mesh;
  levelIds: string[];
  volumeIds: string[];
  prototypeKind: string;
  pickRole: string;
  visibility: string;
  worldBounds: THREE.Box3;
}

interface SemanticCatalog {
  root: THREE.Group | null;
  objects: SemanticMesh[];
  walls: SemanticMesh[];
  grids: SemanticMesh[];
  tactical: SemanticMesh[];
}

interface Bounds {
  row: number;
  col: number;
  width: number;
  height: number;
}

interface ChurchRoom {
  id: string;
  name: string;
  visibility?: "dm_only";
  bounds: Bounds;
}

interface ChurchLevel {
  level_index: number;
  name: string;
  rooms: ChurchRoom[];
}

interface ChurchSpec {
  site: { name: string; brief: string };
  levels: ChurchLevel[];
}

interface UnderdarkCell {
  row: number;
  col: number;
  elevation: number;
  zone: string;
  walkable: boolean;
  movement_cost: number;
}

interface UnderdarkGrid {
  width: number;
  height: number;
  anchors: Record<string, [number, number]>;
  cells: UnderdarkCell[];
}

interface CityRoom {
  id: string;
  name: string;
  bounds: Bounds;
}

interface CityFloor {
  floor_index: number;
  rooms: CityRoom[];
  connectors: CityConnector[];
}

interface CityConnector {
  from_room: string;
  to_room: string;
  from_cell: [number, number];
  to_cell: [number, number];
}

interface CityBuilding {
  id: string;
  name: string;
  floors: CityFloor[];
}

interface CitySpec {
  name: string;
  anchors: Record<string, [number, number]>;
  buildings: CityBuilding[];
}

interface CityCell {
  row: number;
  col: number;
  level_index: number;
  walkable: boolean;
  space_kind: "outdoor" | "interior";
  zone: string;
  building_id: string;
  room_id: string;
  movement_cost: number;
}

interface CityTransitionPoint {
  level_index: number;
  row: number;
  col: number;
  space_kind: "outdoor" | "interior";
  building_id?: string;
  room_id?: string;
}

interface CityTransition {
  id: string;
  type: "entrance" | "stairs";
  from: CityTransitionPoint;
  to: CityTransitionPoint;
}

interface CityGrid {
  anchors: Record<string, [number, number]>;
  cells: CityCell[];
  transitions: CityTransition[];
}

interface GenericRuntimeLevel {
  id: string;
  label: string;
  z_base_ft: number;
  volume_id: string;
}

interface GenericRuntimeCell {
  id: string;
  level_id: string;
  row: number;
  col: number;
  z_base_ft: number;
  walkable: boolean;
  surface: string;
  volume_id: string;
  room_id: string;
  visibility: "public" | "dm_only";
  movement: { walk?: number };
}

interface GenericRuntimeVolume {
  id: string;
  name: string;
  kind: string;
  archetype: string;
  level_ids: string[];
}

interface GenericRuntimeRoom {
  id: string;
  name: string;
  role: string;
  level_id: string;
  volume_id: string;
  visibility: "public" | "dm_only";
  tags: string[];
}

interface GenericRuntimeConnector {
  id: string;
  type: "door" | "stairs" | "ladder" | "bridge" | "hatch" | "secret_door";
  visibility: "public" | "dm_only";
  cell_ids: [string, string];
}

interface GenericRuntimeNavEdge {
  a: string;
  b: string;
  kind: "walk" | "door" | "stairs" | "ladder" | "bridge" | "hatch" | "secret_door";
  connector_id?: string;
  cost: number;
  interaction_required?: boolean;
  visibility?: "public" | "dm_only";
}

interface GenericSceneRuntime {
  schema_version: string;
  scene: { name: string; grid: { cell_size_ft: number }; levels: GenericRuntimeLevel[] };
  volumes: GenericRuntimeVolume[];
  rooms: GenericRuntimeRoom[];
  cells: GenericRuntimeCell[];
  connectors: GenericRuntimeConnector[];
  anchors: Array<{ id: string; kind: string; level_id: string; row: number; col: number; visibility: "public" | "dm_only" }>;
  nav: { mode: "explicit"; edges: GenericRuntimeNavEdge[] };
}

/**
 * Renderer-neutral tactical contract emitted by the V2.2 realizers.  Unlike
 * the legacy scene formats it has no room dependency: a wilderness ridge,
 * sewer loop, or mythic landmark can all be explored through the same grid.
 */
interface TacticalGridLevel {
  id: string;
  label: string;
  z_base_ft: number;
}

interface TacticalGridCell {
  id: string;
  level_id: string;
  row: number;
  col: number;
  elevation: number;
  surface: string;
  tags: string[];
  visibility: "public" | "dm_only";
  walkable: boolean;
  zone: string;
}

interface TacticalGridAnchor {
  id: string;
  name: string;
  kind: string;
  level_id: string;
  row: number;
  col: number;
  elevation: number;
  cell_id: string;
  tactical_role?: string;
  visibility: "public" | "dm_only";
  zone: string;
}

interface TacticalGridRoute {
  id: string;
  name: string;
  role: string;
  risk: string;
  traversal: string;
  visibility: "public" | "dm_only";
  cell_ids: string[];
}

interface TacticalGridFeature {
  id: string;
  kind: string;
  visibility: "public" | "dm_only";
  blocks_movement: boolean;
  cell_ids: string[];
  tags: string[];
  zone: string;
}

interface TacticalGridLink {
  a?: string;
  b?: string;
  from_cell_id?: string;
  to_cell_id?: string;
  from?: string;
  to?: string;
  visibility?: "public" | "dm_only";
}

interface TacticalGrid {
  schema_version: string;
  scene: {
    id: string;
    name: string;
    archetype: string;
    grid: { cell_size_ft: number; width: number; height: number };
  };
  levels: TacticalGridLevel[];
  cells: TacticalGridCell[];
  anchors: TacticalGridAnchor[];
  routes: TacticalGridRoute[];
  features: TacticalGridFeature[];
  links: TacticalGridLink[];
  room_dependencies: boolean;
}

interface V22SceneDescriptor {
  name: string;
  description: string;
  asset: string;
  gridAsset: string;
  theme: string;
}

interface RuntimePreset {
  id: string;
  label: string;
  focus: string;
  levelId: string | "all";
  experience: ExperienceMode;
}

interface RuntimeSceneDescriptor {
  name: string;
  shortName: string;
  description: string;
  asset: string;
  runtimeAsset: string;
  supportsPlayer: boolean;
  visibleFocusIds?: string[];
  presets: RuntimePreset[];
}

interface ProfileSceneDescriptor {
  name: string;
  description: string;
  category: "district" | "outdoor" | "building";
  asset: string;
  inputAsset: string;
  manifestAsset: string;
  camera: CameraState;
}

interface CellSelection {
  row: number;
  col: number;
  layer: number;
  area: string;
  walkable: boolean;
  movement: string;
  room?: ChurchRoom;
  building?: CityBuilding;
  cityRoom?: CityRoom;
  spaceKind?: string;
  levelId?: string;
  volumeId?: string;
  zBaseFt?: number;
  gridCell?: TacticalGridCell;
}

interface CameraState {
  position: THREE.Vector3;
  target: THREE.Vector3;
}

interface TokenState {
  row: number;
  col: number;
  layer: number;
  levelId?: string;
  zBaseFt?: number;
}

const CHURCH_FLOOR_HEIGHT = 3.4;
const CITY_FLOOR_HEIGHT = 3.4;
const UNDERDARK_ELEVATION_HEIGHT = 0.78;
const TOKEN_COLORS = [0xffa94d, 0x62e8ff, 0xc99cff, 0x69f0ae] as const;
const TOKEN_NAMES = ["先锋", "斥候", "施法者", "支援"] as const;
const V22_SCENES: Record<V22SceneKey, V22SceneDescriptor> = {
  river_valley: {
    name: "银瀑河谷",
    description: "河流、浅滩、山脊险径与瀑后密道组成的开阔野外战术场。",
    asset: "river-valley-v22.glb",
    gridAsset: "river-valley-v22.grid.json",
    theme: "河谷 · 高低差 · 渡河与洞口",
  },
  sewer_dungeon: {
    name: "暗流泵房地下城",
    description: "泵房、汇流口、检修环、闸门与暗流祭台构成的基础设施地下城。",
    asset: "sewer-dungeon-v22.glb",
    gridAsset: "sewer-dungeon-v22.grid.json",
    theme: "下水道 · 环路 · 机械与暗门",
  },
  dragonbone_rift: {
    name: "星陨龙骨裂谷",
    description: "无传统房间依赖的巨型龙骨裂谷：高程带、骨桥、浮岩与奥术喷口。",
    asset: "dragonbone-rift-v22.glb",
    gridAsset: "dragonbone-rift-v22.grid.json",
    theme: "奇观战术场 · 多高程 · 掩体与坠落风险",
  },
};
const RUNTIME_SCENES: Record<RuntimeSceneKey, RuntimeSceneDescriptor> = {
  harbor: {
    name: "潮钟港区 · 塔影与暗渠", shortName: "潮钟港区 V2",
    description: "地表、塔楼、暗渠与密室；移动严格读取 runtime 导航图。",
    asset: "harbor-v2.glb", runtimeAsset: "harbor-v2.runtime.json", supportsPlayer: false, presets: [],
  },
  old_clock: {
    name: "旧钟区 · 钟影与密渠", shortName: "旧钟区 V2.3",
    description: "不规则旧城街道、三层钟楼、两层旅店、屋顶路线与走私排水网。",
    asset: "old-clock-v23.glb", runtimeAsset: "old-clock-v23.runtime.json", supportsPlayer: true,
    visibleFocusIds: ["surface", "old_clock_tower", "crooked_bell_inn", "old_clock_roofscape", "old_clock_underworks"],
    presets: [
      { id: "district_overview", label: "街区总览", focus: "surface", levelId: "surface", experience: "theatre" },
      { id: "clock_exploration", label: "钟楼勘探", focus: "old_clock_tower", levelId: "old_clock_tower_l1", experience: "exploration" },
      { id: "roof_showdown", label: "屋顶对峙", focus: "old_clock_roofscape", levelId: "old_clock_roof_route", experience: "tactical" },
      { id: "underworks_pursuit", label: "地下追踪", focus: "old_clock_underworks", levelId: "old_clock_sewer_b1", experience: "tactical" },
    ],
  },
  tower: {
    name: "塔楼 · 旋梯与钟室", shortName: "塔楼 V2.5",
    description: "三层塔楼、旋梯厅、钟室与 DM 隐藏地窖；房间由声明式布局生成。",
    asset: "tower-archetype.glb", runtimeAsset: "tower-archetype.runtime.json", supportsPlayer: true,
    visibleFocusIds: ["tower"],
    presets: [
      { id: "tower_all", label: "塔楼总览", focus: "tower", levelId: "all", experience: "exploration" },
      { id: "tower_ground", label: "一层值守", focus: "tower", levelId: "tower_l1", experience: "tactical" },
      { id: "tower_bell", label: "三层钟室", focus: "tower", levelId: "tower_l3", experience: "tactical" },
    ],
  },
  manor: {
    name: "庄园宅邸 · 家族秘室", shortName: "庄园 V2.5",
    description: "门厅、会客厅、家族长廊与阁楼秘室；密门和 DM-only 酒窖保留。",
    asset: "manor-archetype.glb", runtimeAsset: "manor-archetype.runtime.json", supportsPlayer: true,
    visibleFocusIds: ["manor"],
    presets: [
      { id: "manor_all", label: "庄园总览", focus: "manor", levelId: "all", experience: "exploration" },
      { id: "manor_ground", label: "一层公共区", focus: "manor", levelId: "manor_ground", experience: "tactical" },
      { id: "manor_upper", label: "二层家族区", focus: "manor", levelId: "manor_upper", experience: "tactical" },
    ],
  },
  sewer: {
    name: "下水道 · 潮下检修网", shortName: "下水道 V2.5",
    description: "环形汇流渠、排污泵房与被埋旧祠；密门和暗室只对 DM 可见。",
    asset: "sewer-archetype.glb", runtimeAsset: "sewer-archetype.runtime.json", supportsPlayer: true,
    visibleFocusIds: ["sewer"],
    presets: [
      { id: "sewer_all", label: "检修网总览", focus: "sewer", levelId: "all", experience: "exploration" },
      { id: "sewer_tactical", label: "泵房战术", focus: "sewer", levelId: "sewer_b1", experience: "tactical" },
    ],
  },
};
const PROFILE_SCENES: Record<ProfileSceneKey, ProfileSceneDescriptor> = {
  profile_harbor: {
    name: "潮钟港区·编排版",
    description: "由街区规划器编排的港口样本：路网、地块、建筑层数与地标统一导出为 Blender 资产。",
    category: "district",
    asset: "profile-harbor-district.glb",
    inputAsset: "profile-harbor-district.input.json",
    manifestAsset: "profile-harbor-district.render-manifest.json",
    camera: { position: new THREE.Vector3(31, 27, 34), target: new THREE.Vector3(12, 1.4, -9) },
  },
  profile_outdoor: {
    name: "银瀑河谷·编排版",
    description: "由户外规划器编排的开阔野外战术场：水系、坡带、悬崖、路线与战术平台保持同一输入。",
    category: "outdoor",
    asset: "profile-silverfall-outdoor.glb",
    inputAsset: "profile-silverfall-outdoor.input.json",
    manifestAsset: "profile-silverfall-outdoor.render-manifest.json",
    camera: { position: new THREE.Vector3(34, 30, 36), target: new THREE.Vector3(14, 2.5, -10) },
  },
  profile_pump_house: {
    name: "暗流泵房·独立建筑版",
    description: "由建筑工厂编排的独立泵房样本：分层平台、设备核心与房间功能以统一建筑 profile 导出。",
    category: "building",
    asset: "profile-darkflow-pump-house.glb",
    inputAsset: "profile-darkflow-pump-house.input.json",
    manifestAsset: "profile-darkflow-pump-house.render-manifest.json",
    camera: { position: new THREE.Vector3(7, 7, 8), target: new THREE.Vector3(1.3, 1.6, -1.3) },
  },
};

function isV22Scene(sceneKey: SceneKey): sceneKey is V22SceneKey {
  return sceneKey in V22_SCENES;
}

function isRuntimeScene(sceneKey: SceneKey): sceneKey is RuntimeSceneKey {
  return sceneKey in RUNTIME_SCENES;
}

function isProfileScene(sceneKey: SceneKey): sceneKey is ProfileSceneKey {
  return sceneKey in PROFILE_SCENES;
}

function required<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`缺少界面元素：${selector}`);
  return element;
}

const canvas = required<HTMLCanvasElement>("#scene-canvas");
const viewport = required<HTMLElement>(".viewport-shell");
const loading = required<HTMLElement>("#loading");
const sceneTitle = required<HTMLElement>("#scene-title");
const sceneDescription = required<HTMLElement>("#scene-description");
const modeNote = required<HTMLElement>("#mode-note");
const layerTitle = required<HTMLElement>("#layer-title");
const layerControls = required<HTMLElement>("#layer-controls");
const cityScopePanel = required<HTMLElement>("#city-scope-panel");
const cityScopeNote = required<HTMLElement>("#city-scope-note");
const cityReturn = required<HTMLButtonElement>("#city-return");
const cityBuildingControls = required<HTMLElement>("#city-building-controls");
const harborFocusPanel = required<HTMLElement>("#harbor-focus-panel");
const harborFocusNote = required<HTMLElement>("#harbor-focus-note");
const harborFocusControls = required<HTMLElement>("#harbor-focus-controls");
const cellInspector = required<HTMLElement>("#cell-inspector");
const tokenList = required<HTMLElement>("#token-list");
const hudScene = required<HTMLElement>("#hud-scene");
const hudFilter = required<HTMLElement>("#hud-filter");
const renderStats = required<HTMLElement>("#render-stats");
const fitButton = required<HTMLButtonElement>("#fit-view");
const resetButton = required<HTMLButtonElement>("#reset-view");
const modeButtons = [...document.querySelectorAll<HTMLButtonElement>("#mode-controls button")];
const sceneButtons = [...document.querySelectorAll<HTMLButtonElement>(".scene-button")];
const sidebar = required<HTMLElement>(".sidebar");
const layerPanel = layerControls.closest<HTMLElement>(".panel");
const tokenPanel = tokenList.closest<HTMLElement>(".token-panel");

// Kept in TypeScript rather than index.html so the prototype can be dropped into
// an older viewer shell without changing its document contract.
const experiencePanel = document.createElement("section");
experiencePanel.className = "panel experience-panel";
experiencePanel.innerHTML = `
  <div class="panel-heading"><span>体验模式</span><small>与权限独立</small></div>
  <div class="segmented experience-controls" id="experience-controls">
    <button type="button" data-experience="theatre">剧场</button>
    <button type="button" data-experience="exploration" class="active">探索</button>
    <button type="button" data-experience="tactical">战术</button>
  </div>`;
if (layerPanel) sidebar.insertBefore(experiencePanel, layerPanel);
else sidebar.append(experiencePanel);

const runtimePresetPanel = document.createElement("section");
runtimePresetPanel.className = "panel runtime-preset-panel";
runtimePresetPanel.hidden = true;
runtimePresetPanel.innerHTML = `
  <div class="panel-heading"><span>一键预设</span><small>V2.3 地点编译</small></div>
  <div class="runtime-preset-controls" id="runtime-preset-controls"></div>`;
if (layerPanel) sidebar.insertBefore(runtimePresetPanel, layerPanel);
else sidebar.append(runtimePresetPanel);
const runtimePresetControls = runtimePresetPanel.querySelector<HTMLElement>("#runtime-preset-controls")!;

const dmSettingsPanel = document.createElement("section");
dmSettingsPanel.className = "panel dm-settings-panel";
dmSettingsPanel.innerHTML = `
  <details open>
    <summary><span>DM 参数</span><small>会话内</small></summary>
    <div class="dm-settings-grid">
      <label class="setting-toggle"><input id="dm-cutaway-enabled" type="checkbox" checked> <span>动态近侧墙剖切</span></label>
      <label class="setting-range"><span>墙透明度 <output id="dm-cutaway-value">18%</output></span><input id="dm-cutaway-opacity" type="range" min="3" max="40" value="18"></label>
      <label class="setting-range"><span>格子透明度 <output id="dm-grid-value">52%</output></span><input id="dm-grid-opacity" type="range" min="0" max="90" value="52"></label>
      <label class="setting-range"><span>雾密度 <output id="dm-fog-value">0.008</output></span><input id="dm-fog-density" type="range" min="0" max="24" value="8"></label>
      <label class="setting-range"><span>曝光 <output id="dm-exposure-value">1.08</output></span><input id="dm-exposure" type="range" min="60" max="160" value="108"></label>
      <label class="setting-range"><span>Token 大小 <output id="dm-token-scale-value">100%</output></span><input id="dm-token-scale" type="range" min="55" max="160" value="100"></label>
      <label class="setting-toggle"><input id="dm-show-dm-only" type="checkbox" checked> <span>显示 DM 专属</span></label>
      <label class="setting-toggle"><input id="dm-show-hotspots" type="checkbox" checked> <span>显示连接点</span></label>
      <label class="setting-select"><span>质量预设</span><select id="dm-quality"><option value="quality">质量</option><option value="balanced" selected>平衡</option><option value="performance">性能</option></select></label>
    </div>
    <p class="debug-readout" id="dm-debug-readout">等待场景加载…</p>
  </details>`;
if (tokenPanel) sidebar.insertBefore(dmSettingsPanel, tokenPanel);
else sidebar.append(dmSettingsPanel);

const experienceButtons = [...experiencePanel.querySelectorAll<HTMLButtonElement>("button[data-experience]")];
const dmCutawayEnabled = required<HTMLInputElement>("#dm-cutaway-enabled");
const dmCutawayOpacity = required<HTMLInputElement>("#dm-cutaway-opacity");
const dmGridOpacity = required<HTMLInputElement>("#dm-grid-opacity");
const dmFogDensity = required<HTMLInputElement>("#dm-fog-density");
const dmExposure = required<HTMLInputElement>("#dm-exposure");
const dmTokenScale = required<HTMLInputElement>("#dm-token-scale");
const dmShowDmOnly = required<HTMLInputElement>("#dm-show-dm-only");
const dmShowHotspots = required<HTMLInputElement>("#dm-show-hotspots");
const dmQuality = required<HTMLSelectElement>("#dm-quality");
const dmCutawayValue = required<HTMLOutputElement>("#dm-cutaway-value");
const dmGridValue = required<HTMLOutputElement>("#dm-grid-value");
const dmFogValue = required<HTMLOutputElement>("#dm-fog-value");
const dmExposureValue = required<HTMLOutputElement>("#dm-exposure-value");
const dmTokenScaleValue = required<HTMLOutputElement>("#dm-token-scale-value");
const dmDebugReadout = required<HTMLElement>("#dm-debug-readout");

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.08;
renderer.shadowMap.enabled = false;

const world = new THREE.Scene();
world.background = new THREE.Color(0x05070d);
world.fog = new THREE.FogExp2(0x05070d, 0.0075);

const camera = new THREE.PerspectiveCamera(45, 1, 0.05, 500);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.075;
controls.screenSpacePanning = true;
controls.maxPolarAngle = Math.PI * 0.485;
controls.minDistance = 3;
controls.maxDistance = 180;

world.add(new THREE.HemisphereLight(0x92bfff, 0x100c18, 2.15));
const keyLight = new THREE.DirectionalLight(0xdceaff, 2.2);
keyLight.position.set(25, 42, 18);
world.add(keyLight);
const fillLight = new THREE.DirectionalLight(0x9e65ff, 1.25);
fillLight.position.set(-25, 22, -30);
world.add(fillLight);

const modelHolder = new THREE.Group();
modelHolder.name = "ActiveSceneModel";
world.add(modelHolder);
const tokenHolder = new THREE.Group();
tokenHolder.name = "TestTokens";
world.add(tokenHolder);
const transitionHotspotHolder = new THREE.Group();
transitionHotspotHolder.name = "CityTransitionHotspots";
world.add(transitionHotspotHolder);
const harborTransitionHotspotHolder = new THREE.Group();
harborTransitionHotspotHolder.name = "HarborTransitionHotspots";
world.add(harborTransitionHotspotHolder);

const selectionMarker = new THREE.Mesh(
  new THREE.RingGeometry(0.3, 0.46, 40),
  new THREE.MeshBasicMaterial({ color: 0xffcf66, side: THREE.DoubleSide, depthTest: false }),
);
selectionMarker.name = "CellSelectionMarker";
selectionMarker.rotation.x = -Math.PI / 2;
selectionMarker.renderOrder = 100;
selectionMarker.visible = false;
world.add(selectionMarker);

const loader = new GLTFLoader();
const modelCache = new Map<string, Promise<THREE.Group>>();
const cameraStates = new Map<SceneKey, CameraState>();
const tokenStates = new Map<SceneKey, TokenState[]>();
const underdarkCells = new Map<string, UnderdarkCell>();
const cityCells = new Map<string, CityCell>();
const harborCells = new Map<string, GenericRuntimeCell>();
const harborNav = new Map<string, GenericRuntimeNavEdge[]>();
const harborConnectors = new Map<string, GenericRuntimeConnector>();
const harborRooms = new Map<string, GenericRuntimeRoom>();
const oldClockCells = new Map<string, GenericRuntimeCell>();
const oldClockNav = new Map<string, GenericRuntimeNavEdge[]>();
const oldClockConnectors = new Map<string, GenericRuntimeConnector>();
const oldClockRooms = new Map<string, GenericRuntimeRoom>();
const archetypeRuntimes = new Map<RuntimeSceneKey, GenericSceneRuntime>();
const archetypeCells = new Map<RuntimeSceneKey, Map<string, GenericRuntimeCell>>();
const archetypeNav = new Map<RuntimeSceneKey, Map<string, GenericRuntimeNavEdge[]>>();
const archetypeConnectors = new Map<RuntimeSceneKey, Map<string, GenericRuntimeConnector>>();
const archetypeRooms = new Map<RuntimeSceneKey, Map<string, GenericRuntimeRoom>>();
const v22Grids = new Map<V22SceneKey, TacticalGrid>();
const v22Cells = new Map<V22SceneKey, Map<string, TacticalGridCell>>();
const v22RouteNeighbors = new Map<V22SceneKey, Map<string, Set<string>>>();
const v22BlockedCells = new Map<V22SceneKey, Set<string>>();
const tacticalSurfaces: THREE.Mesh[] = [];
const transitionSurfaces: THREE.Mesh[] = [];
const semanticInfo = new WeakMap<THREE.Mesh, SemanticMesh>();
const wallMaterialSnapshots = new WeakMap<THREE.Mesh, MaterialSnapshot[]>();
const gridMaterialSnapshots = new WeakMap<THREE.Mesh, MaterialSnapshot[]>();
const semanticCatalog: SemanticCatalog = { root: null, objects: [], walls: [], grids: [], tactical: [] };
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();

let churchSpec: ChurchSpec | null = null;
let underdarkGrid: UnderdarkGrid | null = null;
let citySpec: CitySpec | null = null;
let cityGrid: CityGrid | null = null;
let harborRuntime: GenericSceneRuntime | null = null;
let oldClockRuntime: GenericSceneRuntime | null = null;
let currentScene: SceneKey = "church";
let currentMode: ViewMode = "dm";
let currentLayer: LayerFilter = "all";
let currentCityScope: CityScope = "outdoor";
let currentHarborFocus = "surface";
let currentHarborLevelId: string | "all" = "surface";
let currentV22LevelId: string | "all" = "all";
let currentV22Elevation: LayerFilter = "all";
let cityDistrictCameraState: CameraState | null = null;
let cityNotice: string | null = null;
let currentRoot: THREE.Group | null = null;
let selectedToken: number | null = null;
let loadSequence = 0;
let pointerDown: { x: number; y: number } | null = null;
let lastFrameFps = 0;
let cutawayDirty = true;
let lastCutawayUpdate = 0;
let lastCutawayCameraPosition = new THREE.Vector3(Number.NaN, Number.NaN, Number.NaN);
let lastCutawayCameraTarget = new THREE.Vector3(Number.NaN, Number.NaN, Number.NaN);

const viewerState: ViewerState = {
  sceneKey: currentScene,
  accessMode: currentMode,
  experienceMode: "exploration",
  focusId: "surface",
  layer: currentLayer,
  selectedToken,
};

const dmTuning: DmTuning = {
  cutawayEnabled: true,
  cutawayOpacity: 0.18,
  gridOpacity: 0.52,
  fogDensity: 0.008,
  exposure: 1.08,
  tokenScale: 1,
  showDmOnly: true,
  showHotspots: true,
  qualityPreset: "balanced",
};

function syncViewerState(): void {
  viewerState.sceneKey = currentScene;
  viewerState.accessMode = currentMode;
  viewerState.focusId = currentScene === "city"
    ? currentCityScope
    : isRuntimeScene(currentScene)
      ? currentHarborFocus
      : isV22Scene(currentScene)
        ? currentV22LevelId
        : isProfileScene(currentScene)
          ? PROFILE_SCENES[currentScene].category
        : `${currentScene}:${currentLayer}`;
  viewerState.layer = isRuntimeScene(currentScene)
    ? currentHarborLevelId
    : isV22Scene(currentScene)
      ? currentV22Elevation
      : currentLayer;
  viewerState.selectedToken = selectedToken;
}

const assetUrl = (name: string): string => new URL(`assets/${name}`, document.baseURI).href;
const cellKey = (row: number, col: number): string => `${row}:${col}`;
const cityCellKey = (level: number, row: number, col: number): string => `${level}:${row}:${col}`;

function showLoading(message: string, error = false): void {
  loading.classList.remove("hidden");
  loading.innerHTML = error
    ? `<strong>场景加载失败</strong><small>${message}</small>`
    : `<span class="spinner"></span><strong>${message}</strong><small>全部资产来自本机</small>`;
}

function hideLoading(): void {
  loading.classList.add("hidden");
}

function clearCellSelection(): void {
  selectionMarker.visible = false;
  cellInspector.innerHTML = `
    <div><dt>坐标</dt><dd>尚未选择</dd></div>
    <div><dt>层级</dt><dd>—</dd></div>
    <div><dt>区域</dt><dd>—</dd></div>
    <div><dt>移动</dt><dd>—</dd></div>`;
}

async function fetchJson<T>(name: string): Promise<T> {
  const response = await fetch(assetUrl(name));
  if (!response.ok) throw new Error(`${name}：HTTP ${response.status}`);
  return response.json() as Promise<T>;
}

function runtimeFor(sceneKey: RuntimeSceneKey = currentScene as RuntimeSceneKey): GenericSceneRuntime | null {
  if (sceneKey === "old_clock") return oldClockRuntime;
  if (sceneKey === "harbor") return harborRuntime;
  return archetypeRuntimes.get(sceneKey) ?? null;
}

function runtimeCellsFor(sceneKey: RuntimeSceneKey = currentScene as RuntimeSceneKey): Map<string, GenericRuntimeCell> {
  if (sceneKey === "old_clock") return oldClockCells;
  if (sceneKey === "harbor") return harborCells;
  const existing = archetypeCells.get(sceneKey);
  if (existing) return existing;
  const created = new Map<string, GenericRuntimeCell>();
  archetypeCells.set(sceneKey, created);
  return created;
}

function runtimeNavFor(sceneKey: RuntimeSceneKey = currentScene as RuntimeSceneKey): Map<string, GenericRuntimeNavEdge[]> {
  if (sceneKey === "old_clock") return oldClockNav;
  if (sceneKey === "harbor") return harborNav;
  const existing = archetypeNav.get(sceneKey);
  if (existing) return existing;
  const created = new Map<string, GenericRuntimeNavEdge[]>();
  archetypeNav.set(sceneKey, created);
  return created;
}

function runtimeConnectorsFor(sceneKey: RuntimeSceneKey = currentScene as RuntimeSceneKey): Map<string, GenericRuntimeConnector> {
  if (sceneKey === "old_clock") return oldClockConnectors;
  if (sceneKey === "harbor") return harborConnectors;
  const existing = archetypeConnectors.get(sceneKey);
  if (existing) return existing;
  const created = new Map<string, GenericRuntimeConnector>();
  archetypeConnectors.set(sceneKey, created);
  return created;
}

function runtimeRoomsFor(sceneKey: RuntimeSceneKey = currentScene as RuntimeSceneKey): Map<string, GenericRuntimeRoom> {
  if (sceneKey === "old_clock") return oldClockRooms;
  if (sceneKey === "harbor") return harborRooms;
  const existing = archetypeRooms.get(sceneKey);
  if (existing) return existing;
  const created = new Map<string, GenericRuntimeRoom>();
  archetypeRooms.set(sceneKey, created);
  return created;
}

function indexRuntimeScene(sceneKey: RuntimeSceneKey, runtime: GenericSceneRuntime): void {
  const cells = runtimeCellsFor(sceneKey);
  const nav = runtimeNavFor(sceneKey);
  const connectors = runtimeConnectorsFor(sceneKey);
  const rooms = runtimeRoomsFor(sceneKey);
  if (cells.size) return;
  for (const cell of runtime.cells) cells.set(cell.id, cell);
  for (const edge of runtime.nav.edges) {
    nav.set(edge.a, [...(nav.get(edge.a) ?? []), edge]);
    nav.set(edge.b, [...(nav.get(edge.b) ?? []), edge]);
  }
  for (const connector of runtime.connectors) connectors.set(connector.id, connector);
  for (const room of runtime.rooms ?? []) rooms.set(room.id, room);
}

async function ensureRuntimeScene(sceneKey: RuntimeSceneKey): Promise<GenericSceneRuntime> {
  const cached = runtimeFor(sceneKey);
  if (cached) return cached;
  const runtime = await fetchJson<GenericSceneRuntime>(RUNTIME_SCENES[sceneKey].runtimeAsset);
  if (sceneKey === "old_clock") oldClockRuntime = runtime;
  else if (sceneKey === "harbor") harborRuntime = runtime;
  else archetypeRuntimes.set(sceneKey, runtime);
  indexRuntimeScene(sceneKey, runtime);
  return runtime;
}

async function ensureData(): Promise<void> {
  const [church, grid, city, cityData, harbor] = await Promise.all([
    churchSpec ? Promise.resolve(churchSpec) : fetchJson<ChurchSpec>("church.json"),
    underdarkGrid ? Promise.resolve(underdarkGrid) : fetchJson<UnderdarkGrid>("underdark-grid.json"),
    citySpec ? Promise.resolve(citySpec) : fetchJson<CitySpec>("city.json"),
    cityGrid ? Promise.resolve(cityGrid) : fetchJson<CityGrid>("city-grid.json"),
    harborRuntime ? Promise.resolve(harborRuntime) : fetchJson<GenericSceneRuntime>("harbor-v2.runtime.json"),
  ]);
  churchSpec = church;
  underdarkGrid = grid;
  citySpec = city;
  cityGrid = cityData;
  harborRuntime = harbor;
  if (underdarkCells.size === 0) {
    for (const cell of grid.cells) underdarkCells.set(cellKey(cell.row, cell.col), cell);
  }
  if (cityCells.size === 0) {
    for (const cell of cityData.cells) cityCells.set(cityCellKey(cell.level_index, cell.row, cell.col), cell);
  }
  indexRuntimeScene("harbor", harbor);
}

function v22Grid(sceneKey: SceneKey = currentScene): TacticalGrid | undefined {
  return isV22Scene(sceneKey) ? v22Grids.get(sceneKey) : undefined;
}

function v22CellAt(sceneKey: V22SceneKey, levelId: string, row: number, col: number): TacticalGridCell | undefined {
  return v22Cells.get(sceneKey)?.get(`${levelId}:${row}:${col}`);
}

function v22Level(sceneKey: V22SceneKey, levelId: string): TacticalGridLevel | undefined {
  return v22Grids.get(sceneKey)?.levels.find((level) => level.id === levelId);
}

function v22WorldHeight(elevationFt: number, sceneKey: SceneKey = currentScene): number {
  return elevationFt / (v22Grid(sceneKey)?.scene.grid.cell_size_ft ?? 5);
}

function v22CellAllowed(cell: TacticalGridCell): boolean {
  return cell.visibility !== "dm_only" || (currentMode === "dm" && dmTuning.showDmOnly);
}

function v22LinkEndpoints(link: TacticalGridLink): [string, string] | null {
  const a = link.a ?? link.from_cell_id ?? link.from;
  const b = link.b ?? link.to_cell_id ?? link.to;
  return typeof a === "string" && typeof b === "string" ? [a, b] : null;
}

function indexV22Grid(sceneKey: V22SceneKey, grid: TacticalGrid): void {
  const cells = new Map<string, TacticalGridCell>();
  const routeNeighbors = new Map<string, Set<string>>();
  const blocked = new Set<string>();
  const connect = (a: string, b: string): void => {
    if (!cells.has(a) || !cells.has(b) || a === b) return;
    (routeNeighbors.get(a) ?? routeNeighbors.set(a, new Set()).get(a)!).add(b);
    (routeNeighbors.get(b) ?? routeNeighbors.set(b, new Set()).get(b)!).add(a);
  };
  for (const cell of grid.cells) cells.set(cell.id, cell);
  for (const route of grid.routes ?? []) {
    for (let index = 1; index < route.cell_ids.length; index += 1) {
      const previous = route.cell_ids[index - 1];
      const next = route.cell_ids[index];
      if (previous && next) connect(previous, next);
    }
  }
  for (const link of grid.links ?? []) {
    const endpoints = v22LinkEndpoints(link);
    if (endpoints) connect(...endpoints);
  }
  for (const feature of grid.features ?? []) {
    if (!feature.blocks_movement) continue;
    feature.cell_ids.forEach((cellId) => blocked.add(cellId));
  }
  v22Cells.set(sceneKey, cells);
  v22RouteNeighbors.set(sceneKey, routeNeighbors);
  v22BlockedCells.set(sceneKey, blocked);
}

async function ensureV22Grid(sceneKey: V22SceneKey): Promise<TacticalGrid> {
  const cached = v22Grids.get(sceneKey);
  if (cached) return cached;
  const grid = await fetchJson<TacticalGrid>(V22_SCENES[sceneKey].gridAsset);
  v22Grids.set(sceneKey, grid);
  indexV22Grid(sceneKey, grid);
  return grid;
}

function loadModel(name: string): Promise<THREE.Group> {
  let promise = modelCache.get(name);
  if (!promise) {
    promise = loader.loadAsync(assetUrl(name)).then(({ scene }) => {
      scene.name = `Cached_${name}`;
      scene.traverse((object) => {
        if (!(object instanceof THREE.Mesh)) return;
        object.frustumCulled = true;
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        for (const material of materials) {
          if ("envMapIntensity" in material) material.envMapIntensity = 0.55;
        }
      });
      return scene;
    });
    modelCache.set(name, promise);
    promise.catch(() => modelCache.delete(name));
  }
  return promise;
}

function sceneAsset(sceneKey: SceneKey, mode: ViewMode): string {
  if (isV22Scene(sceneKey)) return V22_SCENES[sceneKey].asset;
  if (isRuntimeScene(sceneKey)) return RUNTIME_SCENES[sceneKey].asset;
  if (isProfileScene(sceneKey)) return PROFILE_SCENES[sceneKey].asset;
  if (sceneKey === "underdark") return "underdark-dm.glb";
  if (sceneKey === "city") return "city-dm.glb";
  return mode === "player" ? "church-player.glb" : "church-dm.glb";
}

function saveCameraState(): void {
  cameraStates.set(currentScene, {
    position: camera.position.clone(),
    target: controls.target.clone(),
  });
}

function scenePreset(sceneKey: SceneKey): CameraState {
  if (sceneKey === "church") return { position: new THREE.Vector3(27, 24, 24), target: new THREE.Vector3(10, 3.6, -8) };
  if (sceneKey === "city") return { position: new THREE.Vector3(47, 38, 32), target: new THREE.Vector3(16, 1.8, -14) };
  if (sceneKey === "harbor") return { position: new THREE.Vector3(82, 70, 66), target: new THREE.Vector3(32, 4, -26) };
  if (sceneKey === "old_clock") return { position: new THREE.Vector3(78, 62, 62), target: new THREE.Vector3(35, 4, -31) };
  if (sceneKey === "tower") return { position: new THREE.Vector3(34, 30, 34), target: new THREE.Vector3(12, 12, -9) };
  if (sceneKey === "manor") return { position: new THREE.Vector3(34, 26, 34), target: new THREE.Vector3(12, 6, -9) };
  if (sceneKey === "sewer") return { position: new THREE.Vector3(34, 20, 34), target: new THREE.Vector3(12, -3, -9) };
  if (isProfileScene(sceneKey)) return PROFILE_SCENES[sceneKey].camera;
  if (isV22Scene(sceneKey)) {
    const grid = v22Grid(sceneKey);
    if (grid) {
      const { width, height, cell_size_ft: cellSizeFt } = grid.scene.grid;
      const maxElevation = Math.max(...grid.cells.map((cell) => cell.elevation));
      const minElevation = Math.min(...grid.cells.map((cell) => cell.elevation));
      const target = new THREE.Vector3(width / 2, ((maxElevation + minElevation) / 2) / cellSizeFt, -height / 2);
      const span = Math.max(width, height);
      return {
        position: target.clone().add(new THREE.Vector3(span * 1.12, span * 0.84 + Math.max(0, maxElevation - minElevation) / cellSizeFt, span * 1.08)),
        target,
      };
    }
  }
  return { position: new THREE.Vector3(69, 53, 42), target: new THREE.Vector3(24, 1.3, -18) };
}

function applyCameraState(state: CameraState): void {
  camera.position.copy(state.position);
  controls.target.copy(state.target);
  controls.update();
}

function resetView(): void {
  applyCameraState(scenePreset(currentScene));
}

function isRuntimeBackdropForFit(object: THREE.Mesh): boolean {
  if (!isRuntimeScene(currentScene) || currentHarborFocus !== "surface") return false;
  const kind = String(object.userData.prototype_kind ?? "");
  const surfaceKind = String(object.userData.surface_kind ?? "");
  // Allocation ground and its full-canvas grid are useful context, but they
  // must not force the actual authored district into a tiny camera footprint.
  // Roads, buildings, connectors and dressing still define the fit bounds.
  return surfaceKind === "ground" && (kind === "surface" || kind === "grid");
}

function fitView(): void {
  if (!currentRoot) return;
  currentRoot.updateWorldMatrix(true, true);
  const box = new THREE.Box3();
  currentRoot.traverse((object) => {
    if (!(object instanceof THREE.Mesh) || !object.visible || isRuntimeBackdropForFit(object)) return;
    object.geometry.computeBoundingBox();
    if (!object.geometry.boundingBox) return;
    box.union(object.geometry.boundingBox.clone().applyMatrix4(object.matrixWorld));
  });
  if (box.isEmpty()) return;
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const direction = new THREE.Vector3(1, 0.82, 1).normalize();
  const halfFov = THREE.MathUtils.degToRad(camera.fov / 2);
  const distance = Math.max(5, (sphere.radius / Math.sin(halfFov)) * 1.14);
  controls.target.copy(sphere.center);
  camera.position.copy(sphere.center).addScaledVector(direction, distance);
  camera.near = Math.max(0.02, distance / 400);
  camera.far = Math.max(300, distance * 8);
  camera.updateProjectionMatrix();
  controls.update();
}

function objectLevel(object: THREE.Object3D): number | null {
  const extra = object.userData.level_index;
  if (typeof extra === "number" && extra >= 1 && extra <= 3) return extra;
  const name = object.name;
  const patterns = [/[GFS]rid[HV]?_l([123])_/i, /Floor_l([123])_/i, /(?:^|_)l([123])_/i, /Wall_([123])_/, /Pew_([123])_/, /Stair_stairs_([123])_/, /Label_.+_([123])$/];
  for (const pattern of patterns) {
    const match = name.match(pattern);
    if (match?.[1]) return Number(match[1]);
  }
  if (name === "PresentationBase") return null;
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) return null;
  const y = box.getCenter(new THREE.Vector3()).y;
  return THREE.MathUtils.clamp(Math.round(y / CHURCH_FLOOR_HEIGHT) + 1, 1, 3);
}

function objectElevation(object: THREE.Object3D): number | null {
  const extra = object.userData.elevation;
  if (typeof extra === "number" && extra >= 0 && extra <= 4) return extra;
  const terrainMatch = object.name.match(/^Terrain_Elevation_([0-4])/);
  if (terrainMatch?.[1]) return Number(terrainMatch[1]);
  if (/^(Chasm|Tactical_Grid)/.test(object.name)) return null;
  object.updateWorldMatrix(true, false);
  const position = object.getWorldPosition(new THREE.Vector3());
  const cell = underdarkCells.get(cellKey(Math.floor(-position.z), Math.floor(position.x)));
  return cell?.walkable ? cell.elevation : null;
}

function objectV22LevelId(object: THREE.Object3D): string {
  return objectMetadata(object, "level_id");
}

function objectV22Elevation(object: THREE.Object3D): number | null {
  const direct = object.userData.elevation_ft;
  if (typeof direct === "number" && Number.isFinite(direct)) return direct;
  if (typeof direct === "string" && direct.trim() !== "" && Number.isFinite(Number(direct))) return Number(direct);
  return null;
}

function objectMetadata(object: THREE.Object3D, key: string): string {
  const value = object.userData[key];
  return typeof value === "string" ? value : "";
}

function objectCityLevel(object: THREE.Object3D): number | null {
  const extra = object.userData.level_index;
  if (typeof extra === "number" && extra >= 0 && extra <= 2) return extra;
  const match = object.name.match(/(?:Floor|Grid|Wall|Roof(?:North|South)?|Stair)_([^_]+)_L([12])_/i);
  return match?.[2] ? Number(match[2]) : object.name.startsWith("City_Outdoor_") ? 0 : null;
}

function objectCityBuilding(object: THREE.Object3D): string {
  const extra = objectMetadata(object, "building_id");
  if (extra) return extra;
  const match = object.name.match(/(?:Floor|Grid|Wall|Roof(?:North|South)?|Stair)_([\w-]+?)_L\d/i)
    ?? object.name.match(/^Door_([\w-]+)_\d/i);
  return match?.[1] ?? "";
}

function objectHarborLevelId(object: THREE.Object3D): string {
  return objectMetadata(object, "level_id");
}

function objectMetadataList(object: THREE.Object3D, key: string): string[] {
  const raw = object.userData[key];
  if (Array.isArray(raw)) return raw.filter((value): value is string => typeof value === "string");
  const encoded = typeof raw === "string" ? raw : "";
  if (!encoded) return [];
  try {
    const values = JSON.parse(encoded) as unknown;
    return Array.isArray(values) ? values.filter((value): value is string => typeof value === "string") : [];
  } catch {
    return [];
  }
}

function objectHarborLevelIds(object: THREE.Object3D): string[] {
  const direct = objectHarborLevelId(object);
  return [...new Set([...(direct ? [direct] : []), ...objectMetadataList(object, "level_ids")])];
}

function objectHarborVolumeIds(object: THREE.Object3D): string[] {
  const direct = objectMetadata(object, "volume_id");
  const explicit = [...new Set([...(direct ? [direct] : []), ...objectMetadataList(object, "volume_ids")])];
  if (explicit.length) return explicit;
  return [...new Set(objectHarborLevelIds(object).map((levelId) => harborLevel(levelId)?.volume_id ?? "").filter(Boolean))];
}

function objectHarborVolumeId(object: THREE.Object3D): string {
  return objectHarborVolumeIds(object)[0] ?? "";
}

function meshMaterials(mesh: THREE.Mesh): THREE.Material[] {
  return Array.isArray(mesh.material) ? mesh.material : [mesh.material];
}

function cloneMeshMaterialsOnce(mesh: THREE.Mesh, snapshots: WeakMap<THREE.Mesh, MaterialSnapshot[]>): MaterialSnapshot[] {
  const existing = snapshots.get(mesh);
  if (existing) return existing;
  const cloned = meshMaterials(mesh).map((material) => material.clone());
  mesh.material = Array.isArray(mesh.material) ? cloned : cloned[0]!;
  const state = cloned.map((material) => ({
    material,
    opacity: material.opacity,
    transparent: material.transparent,
    depthWrite: material.depthWrite,
  }));
  snapshots.set(mesh, state);
  return state;
}

function restoreMaterialSnapshots(snapshots: WeakMap<THREE.Mesh, MaterialSnapshot[]>, meshes: SemanticMesh[]): void {
  for (const entry of meshes) {
    for (const state of snapshots.get(entry.mesh) ?? []) {
      state.material.opacity = state.opacity;
      state.material.transparent = state.transparent;
      state.material.depthWrite = state.depthWrite;
      state.material.needsUpdate = true;
    }
  }
}

function semanticBounds(mesh: THREE.Mesh): THREE.Box3 {
  mesh.updateWorldMatrix(true, false);
  mesh.geometry.computeBoundingBox();
  return mesh.geometry.boundingBox
    ? mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld)
    : new THREE.Box3().setFromObject(mesh);
}

function buildSemanticCatalog(root: THREE.Group): void {
  restoreMaterialSnapshots(wallMaterialSnapshots, semanticCatalog.walls);
  restoreMaterialSnapshots(gridMaterialSnapshots, semanticCatalog.grids);
  semanticCatalog.root = root;
  semanticCatalog.objects.length = 0;
  semanticCatalog.walls.length = 0;
  semanticCatalog.grids.length = 0;
  semanticCatalog.tactical.length = 0;
  root.updateWorldMatrix(true, true);
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    const prototypeKind = objectMetadata(object, "prototype_kind");
    const pickRole = objectMetadata(object, "pick_role");
    const entry: SemanticMesh = {
      mesh: object,
      levelIds: isRuntimeScene(currentScene) || isV22Scene(currentScene) ? objectHarborLevelIds(object) : [],
      volumeIds: isRuntimeScene(currentScene) ? objectHarborVolumeIds(object) : [],
      prototypeKind,
      pickRole,
      visibility: objectMetadata(object, "prototype_visibility") || objectMetadata(object, "visibility"),
      worldBounds: semanticBounds(object),
    };
    semanticInfo.set(object, entry);
    semanticCatalog.objects.push(entry);
    // Cutaway deliberately uses only export semantics, never names: false positives
    // on decorative meshes make a tactical map flicker and can break picking.
    if (prototypeKind === "wall" || pickRole === "occluder") {
      semanticCatalog.walls.push(entry);
      cloneMeshMaterialsOnce(object, wallMaterialSnapshots);
    }
    if (prototypeKind === "grid" || pickRole === "grid" || /(?:^|_)Grid(?:_|$)|Tactical_Grid/i.test(object.name)) {
      semanticCatalog.grids.push(entry);
      cloneMeshMaterialsOnce(object, gridMaterialSnapshots);
    }
    if (pickRole === "tactical_floor" || prototypeKind === "floor") semanticCatalog.tactical.push(entry);
  });
  markCutawayDirty();
}

function harborLevel(levelId: string): GenericRuntimeLevel | undefined {
  return runtimeFor()?.scene.levels.find((level) => level.id === levelId);
}

function harborWorldHeight(zBaseFt: number): number {
  return zBaseFt / (runtimeFor()?.scene.grid.cell_size_ft ?? 5);
}

function harborObjectVisible(object: THREE.Mesh): boolean {
  const levelIds = objectHarborLevelIds(object);
  const volumeIds = objectHarborVolumeIds(object);
  const kind = objectMetadata(object, "prototype_kind");
  const pickRole = objectMetadata(object, "pick_role");
  if (!levelIds.length) return currentHarborFocus === "surface";
  if (currentHarborFocus === "surface") {
    if (levelIds.includes("surface")) return true;
    if (currentScene === "old_clock") return ["wall", "roof", "archetype_detail", "life_trace"].includes(kind);
    return kind === "wall" || kind === "roof" || kind === "door";
  }
  const tacticalRoof = currentScene === "old_clock" && currentHarborFocus === "old_clock_roofscape";
  if (!volumeIds.includes(currentHarborFocus) || (!tacticalRoof && (kind === "roof" || pickRole === "hideable"))) return false;
  return currentHarborLevelId === "all" || levelIds.includes(currentHarborLevelId);
}

function v22ObjectVisible(object: THREE.Mesh): boolean {
  const levelId = objectV22LevelId(object);
  const elevation = objectV22Elevation(object);
  const levelAllowed = currentV22LevelId === "all" || !levelId || levelId === currentV22LevelId;
  const elevationAllowed = currentV22Elevation === "all" || elevation === null || elevation === currentV22Elevation;
  return levelAllowed && elevationAllowed;
}

function cityObjectVisible(object: THREE.Mesh): boolean {
  const level = objectCityLevel(object);
  const space = objectMetadata(object, "space_kind");
  const building = objectCityBuilding(object);
  const kind = objectMetadata(object, "prototype_kind");
  const isRoof = kind === "roof" || object.name.startsWith("Roof");
  if (currentCityScope === "outdoor") {
    if (space === "outdoor" || (!space && level === 0)) return true;
    // The generator deliberately keeps facades lightweight: exterior walls, roof rims
    // and doors establish a readable city silhouette while interior floor/grid/labels stay hidden.
    return kind === "wall" || kind === "roof" || kind === "door" || /^(Wall|Roof|Door)_/.test(object.name);
  }
  if (space !== "interior" || building !== currentCityScope || isRoof) return false;
  // The city export has one upward stair mesh. Keep it pickable while either
  // endpoint floor is in view so the same object supports going back down.
  if (kind === "stairs" || object.name.startsWith("Stair_")) return true;
  return currentLayer === "all" || level === currentLayer;
}

function objectAllowedByAccess(object: THREE.Object3D): boolean {
  const visibility = objectMetadata(object, "prototype_visibility") || objectMetadata(object, "visibility");
  if (visibility !== "dm_only") return true;
  return currentMode === "dm" && dmTuning.showDmOnly;
}

function hotspotAllowed(visibility = "public"): boolean {
  return viewerState.experienceMode !== "theatre"
    && dmTuning.showHotspots
    && (visibility !== "dm_only" || (currentMode === "dm" && dmTuning.showDmOnly));
}

function setObjectFilteredVisible(object: THREE.Mesh, visible: boolean): void {
  object.visible = visible && objectAllowedByAccess(object);
}

function markCutawayDirty(): void {
  cutawayDirty = true;
}

function visibleFocusBounds(): THREE.Box3 | null {
  const bounds = new THREE.Box3();
  const candidates = semanticCatalog.tactical.length
    ? semanticCatalog.tactical
    : tacticalSurfaces
      .map((mesh) => semanticInfo.get(mesh))
      .filter((entry): entry is SemanticMesh => Boolean(entry));
  for (const entry of candidates) {
    if (entry.mesh.visible) bounds.union(entry.worldBounds);
  }
  // V1 assets have few prototype annotations.  Their existing tactical surfaces
  // remain a safe fallback, while V2 uses metadata-only semantic entries above.
  if (bounds.isEmpty()) {
    for (const mesh of tacticalSurfaces) {
      if (mesh.visible) bounds.union(semanticInfo.get(mesh)?.worldBounds ?? semanticBounds(mesh));
    }
  }
  return bounds.isEmpty() ? null : bounds;
}

function applyGridVisuals(): void {
  const visible = viewerState.experienceMode !== "theatre";
  const multiplier = viewerState.experienceMode === "exploration" ? 0.48 : 1;
  for (const entry of semanticCatalog.grids) {
    const states = gridMaterialSnapshots.get(entry.mesh) ?? [];
    entry.mesh.visible = entry.mesh.visible && visible;
    for (const state of states) {
      state.material.opacity = visible ? Math.min(0.92, dmTuning.gridOpacity * multiplier) : 0;
      state.material.transparent = true;
      state.material.depthWrite = false;
      state.material.needsUpdate = true;
    }
  }
}

function restoreCutaway(): void {
  restoreMaterialSnapshots(wallMaterialSnapshots, semanticCatalog.walls);
}

function updateCutaway(now: number, force = false): void {
  const cameraMoved = camera.position.distanceToSquared(lastCutawayCameraPosition) > 0.025
    || controls.target.distanceToSquared(lastCutawayCameraTarget) > 0.025;
  if (cameraMoved) cutawayDirty = true;
  if (!force && (!cutawayDirty || now - lastCutawayUpdate < 100)) return;
  lastCutawayUpdate = now;
  lastCutawayCameraPosition.copy(camera.position);
  lastCutawayCameraTarget.copy(controls.target);
  cutawayDirty = false;

  if (viewerState.experienceMode === "theatre" || !dmTuning.cutawayEnabled || !semanticCatalog.walls.length) {
    restoreCutaway();
    return;
  }
  const focusBounds = visibleFocusBounds();
  if (!focusBounds) {
    restoreCutaway();
    return;
  }
  const focusCenter = focusBounds.getCenter(new THREE.Vector3());
  const towardCamera = camera.position.clone().sub(focusCenter);
  towardCamera.y = 0;
  if (towardCamera.lengthSq() < 0.0001) return;
  towardCamera.normalize();
  const tactical = viewerState.experienceMode === "tactical";
  const opacity = tactical ? Math.min(0.08, dmTuning.cutawayOpacity * 0.36) : dmTuning.cutawayOpacity;
  for (const entry of semanticCatalog.walls) {
    const wallBounds = entry.worldBounds;
    const overlapsFocusXZ = wallBounds.min.x <= focusBounds.max.x && wallBounds.max.x >= focusBounds.min.x
      && wallBounds.min.z <= focusBounds.max.z && wallBounds.max.z >= focusBounds.min.z;
    const wallCenter = wallBounds.getCenter(new THREE.Vector3());
    const wallOffset = wallCenter.sub(focusCenter);
    wallOffset.y = 0;
    const nearSide = overlapsFocusXZ && wallOffset.dot(towardCamera) > 0.08;
    for (const state of wallMaterialSnapshots.get(entry.mesh) ?? []) {
      state.material.opacity = nearSide ? opacity : state.opacity;
      state.material.transparent = nearSide || state.transparent;
      state.material.depthWrite = nearSide ? false : state.depthWrite;
      state.material.needsUpdate = true;
    }
  }
}

function applyRenderTuning(): void {
  const runtimeOverview = isRuntimeScene(currentScene) && currentHarborFocus === "surface";
  renderer.toneMappingExposure = dmTuning.exposure * (runtimeOverview ? 1.14 : 1);
  if (world.fog instanceof THREE.FogExp2) world.fog.density = dmTuning.fogDensity * (runtimeOverview ? .58 : 1);
  tokenHolder.scale.setScalar(dmTuning.tokenScale);
  resize();
  markCutawayDirty();
}

function pixelRatioForPreset(): number {
  const cap = dmTuning.qualityPreset === "quality" ? 1.75 : dmTuning.qualityPreset === "performance" ? 1 : 1.5;
  return Math.min(window.devicePixelRatio, cap);
}

function applyLayerFilter(): void {
  clearCellSelection();
  if (!currentRoot) return;
  currentRoot.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    if (currentScene === "city") {
      setObjectFilteredVisible(object, cityObjectVisible(object));
      return;
    }
    if (isRuntimeScene(currentScene)) {
      setObjectFilteredVisible(object, harborObjectVisible(object));
      return;
    }
    if (isV22Scene(currentScene)) {
      setObjectFilteredVisible(object, v22ObjectVisible(object));
      return;
    }
    if (currentLayer === "all") {
      setObjectFilteredVisible(object, true);
      return;
    }
    if (currentScene === "church") {
      const level = objectLevel(object);
      setObjectFilteredVisible(object, level === null || level === currentLayer);
      return;
    }
    if (object.name.startsWith("Tactical_Grid")) {
      // The current grid is one merged mesh spanning every elevation.
      setObjectFilteredVisible(object, false);
      return;
    }
    const elevation = objectElevation(object);
    setObjectFilteredVisible(object, elevation === null || elevation === currentLayer);
  });
  if (currentScene === "city") updateTransitionHotspotVisibility();
  if (isRuntimeScene(currentScene)) updateHarborTransitionHotspots();
  updateTokenVisibility();
  applyGridVisuals();
  markCutawayDirty();
  updateHud();
}

function rebuildTacticalSurfaces(): void {
  tacticalSurfaces.length = 0;
  transitionSurfaces.length = 0;
  currentRoot?.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    const tactical = currentScene === "church"
      ? objectMetadata(object, "prototype_kind") === "floor" || object.name.startsWith("Floor_")
      : currentScene === "city"
        ? objectMetadata(object, "pick_role") === "tactical_floor" || objectMetadata(object, "prototype_kind") === "floor" || /^Floor_City_|^City_Outdoor_/.test(object.name)
        : isRuntimeScene(currentScene)
          ? objectMetadata(object, "pick_role") === "tactical_floor" || objectMetadata(object, "prototype_kind") === "floor"
          : isV22Scene(currentScene)
            ? objectMetadata(object, "pick_role") === "tactical_floor" || objectMetadata(object, "prototype_kind") === "surface"
            : object.name.startsWith("Terrain_Elevation_");
    if (tactical) tacticalSurfaces.push(object);
    const transition = currentScene === "city" && (
      objectMetadata(object, "pick_role") === "transition"
      || objectMetadata(object, "prototype_kind") === "door"
      || objectMetadata(object, "prototype_kind") === "stairs"
      || /^(Door|Stair)_/.test(object.name)
    );
    if (transition) transitionSurfaces.push(object);
    const harborTransition = isRuntimeScene(currentScene) && (
      objectMetadata(object, "pick_role") === "connector"
      || Boolean(objectMetadata(object, "connector_id"))
      || ["door", "stairs", "ladder", "bridge", "hatch", "secret_door"].includes(objectMetadata(object, "prototype_kind"))
    );
    if (harborTransition) transitionSurfaces.push(object);
  });
  rebuildCityTransitionHotspots();
  rebuildHarborTransitionHotspots();
}

function clearTransitionHotspots(): void {
  transitionHotspotHolder.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    object.geometry.dispose();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    materials.forEach((material) => material.dispose());
  });
  transitionHotspotHolder.clear();
}

function rebuildCityTransitionHotspots(): void {
  clearTransitionHotspots();
  if (currentScene !== "city") return;
  for (const transition of cityGrid?.transitions ?? []) {
    if (transition.type !== "stairs") continue;
    for (const point of [transition.from, transition.to]) {
      const hotspot = new THREE.Mesh(
        new THREE.RingGeometry(0.2, 0.34, 24),
        new THREE.MeshBasicMaterial({ color: 0x62e8ff, side: THREE.DoubleSide, transparent: true, opacity: 0.92, depthTest: false }),
      );
      hotspot.name = `TransitionHotspot_${transition.id}_L${point.level_index}`;
      hotspot.rotation.x = -Math.PI / 2;
      hotspot.position.set(point.col + 0.5, point.level_index === 0 ? 0.045 : (point.level_index - 1) * CITY_FLOOR_HEIGHT + 0.045, -point.row - 0.5);
      hotspot.renderOrder = 99;
      hotspot.userData.transition_id = transition.id;
      hotspot.userData.level_index = point.level_index;
      hotspot.userData.space_kind = point.space_kind;
      hotspot.userData.building_id = point.building_id ?? "";
      transitionHotspotHolder.add(hotspot);
      transitionSurfaces.push(hotspot);
    }
  }
  updateTransitionHotspotVisibility();
}

function updateTransitionHotspotVisibility(): void {
  transitionHotspotHolder.children.forEach((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    const level = typeof object.userData.level_index === "number" ? object.userData.level_index : -1;
    const space = objectMetadata(object, "space_kind");
    const building = objectMetadata(object, "building_id");
    const inScope = currentCityScope === "outdoor"
      ? space === "outdoor"
      : space === "interior" && building === currentCityScope;
    object.visible = currentScene === "city"
      && hotspotAllowed()
      && inScope
      && (currentLayer === "all" || level === currentLayer);
  });
}

function clearHarborTransitionHotspots(): void {
  harborTransitionHotspotHolder.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    object.geometry.dispose();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    materials.forEach((material) => material.dispose());
  });
  harborTransitionHotspotHolder.clear();
}

function rebuildHarborTransitionHotspots(): void {
  clearHarborTransitionHotspots();
  if (!isRuntimeScene(currentScene)) return;
  const cells = runtimeCellsFor();
  for (const connector of runtimeFor()?.connectors ?? []) {
    for (const cellId of connector.cell_ids) {
      const cell = cells.get(cellId);
      if (!cell) continue;
      const hotspot = new THREE.Mesh(
        new THREE.RingGeometry(0.22, 0.38, 24),
        new THREE.MeshBasicMaterial({ color: connector.visibility === "dm_only" ? 0xc99cff : 0x62e8ff, side: THREE.DoubleSide, transparent: true, opacity: 0.9, depthTest: false }),
      );
      hotspot.name = `HarborTransitionHotspot_${connector.id}_${cell.id}`;
      hotspot.rotation.x = -Math.PI / 2;
      hotspot.position.set(cell.col + 0.5, harborWorldHeight(cell.z_base_ft) + 0.05, -cell.row - 0.5);
      hotspot.renderOrder = 99;
      hotspot.userData.connector_id = connector.id;
      hotspot.userData.level_id = cell.level_id;
      hotspot.userData.volume_id = cell.volume_id;
      hotspot.userData.visibility = connector.visibility;
      harborTransitionHotspotHolder.add(hotspot);
      transitionSurfaces.push(hotspot);
    }
  }
  updateHarborTransitionHotspots();
}

function updateHarborTransitionHotspots(): void {
  harborTransitionHotspotHolder.children.forEach((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    const levelId = objectHarborLevelId(object);
    const volumeId = objectHarborVolumeId(object);
    const visibleFocus = currentHarborFocus === "surface" ? levelId === "surface" : volumeId === currentHarborFocus;
    object.visible = isRuntimeScene(currentScene)
      && hotspotAllowed(objectMetadata(object, "visibility"))
      && visibleFocus
      && (currentHarborLevelId === "all" || levelId === currentHarborLevelId);
  });
}

function roomAt(level: number, row: number, col: number): ChurchRoom | undefined {
  const levelData = churchSpec?.levels.find((item) => item.level_index === level);
  return levelData?.rooms.find(({ bounds }) =>
    row >= bounds.row && row < bounds.row + bounds.height && col >= bounds.col && col < bounds.col + bounds.width,
  );
}

function cityBuildingById(id: string): CityBuilding | undefined {
  return citySpec?.buildings.find((building) => building.id === id);
}

function cityRoomById(building: CityBuilding | undefined, roomId: string): CityRoom | undefined {
  return building?.floors.flatMap((floor) => floor.rooms).find((room) => room.id === roomId);
}

function cityCellAt(level: number, row: number, col: number): CityCell | undefined {
  return cityCells.get(cityCellKey(level, row, col));
}

function cityPointInScope(point: CityTransitionPoint, scope: CityScope): boolean {
  return scope === "outdoor"
    ? point.space_kind === "outdoor"
    : point.space_kind === "interior" && point.building_id === scope;
}

function cityCellInScope(cell: CityCell, scope: CityScope): boolean {
  return scope === "outdoor"
    ? cell.space_kind === "outdoor"
    : cell.space_kind === "interior" && cell.building_id === scope;
}

function cityConnectorKey(level: number, buildingId: string, a: [number, number], b: [number, number]): string {
  const [left, right] = [`${a[0]}:${a[1]}`, `${b[0]}:${b[1]}`].sort();
  return `${buildingId}:${level}:${left}|${right}`;
}

function cityConnectorEdges(): Set<string> {
  const edges = new Set<string>();
  for (const building of citySpec?.buildings ?? []) {
    for (const floor of building.floors) {
      for (const connector of floor.connectors ?? []) {
        edges.add(cityConnectorKey(floor.floor_index, building.id, connector.from_cell, connector.to_cell));
      }
    }
  }
  return edges;
}

function cityCanStep(from: CityCell, to: CityCell, connectorEdges: Set<string>): boolean {
  if (!to.walkable || from.level_index !== to.level_index) return false;
  if (Math.abs(from.row - to.row) + Math.abs(from.col - to.col) !== 1) return false;
  if (from.space_kind === "outdoor" || to.space_kind === "outdoor") {
    return from.space_kind === "outdoor" && to.space_kind === "outdoor" && from.level_index === 0;
  }
  if (from.building_id !== to.building_id) return false;
  if (from.room_id === to.room_id) return true;
  return connectorEdges.has(cityConnectorKey(from.level_index, from.building_id, [from.row, from.col], [to.row, to.col]));
}

function cityCellsReachable(start: CityCell, goal: CityCell): boolean {
  if (!cityCellInScope(start, currentCityScope) || !cityCellInScope(goal, currentCityScope)) return false;
  if (start.level_index !== goal.level_index) return false;
  const connectorEdges = cityConnectorEdges();
  const visited = new Set<string>([cityCellKey(start.level_index, start.row, start.col)]);
  const queue = [start];
  for (let index = 0; index < queue.length; index += 1) {
    const cell = queue[index];
    if (!cell) continue;
    if (cell.row === goal.row && cell.col === goal.col) return true;
    const neighbors: Array<[number, number]> = [[cell.row - 1, cell.col], [cell.row + 1, cell.col], [cell.row, cell.col - 1], [cell.row, cell.col + 1]];
    for (const [row, col] of neighbors) {
      const next = cityCellAt(cell.level_index, row, col);
      const key = cityCellKey(cell.level_index, row, col);
      if (!next || visited.has(key) || !cityCellInScope(next, currentCityScope) || !cityCanStep(cell, next, connectorEdges)) continue;
      visited.add(key);
      queue.push(next);
    }
  }
  return false;
}

function harborCellAt(levelId: string, row: number, col: number): GenericRuntimeCell | undefined {
  return runtimeCellsFor().get(`${levelId}:${row}:${col}`);
}

function harborFocusAllows(cell: GenericRuntimeCell): boolean {
  return currentHarborFocus === "surface" ? cell.level_id === "surface" : cell.volume_id === currentHarborFocus;
}

function harborReachable(startId: string, targetId: string): boolean {
  if (startId === targetId) return true;
  const cells = runtimeCellsFor();
  const nav = runtimeNavFor();
  const start = cells.get(startId);
  const target = cells.get(targetId);
  if (!start || !target || !harborFocusAllows(start) || !harborFocusAllows(target)) return false;
  const visited = new Set<string>([startId]);
  const queue = [startId];
  for (let index = 0; index < queue.length; index += 1) {
    const current = queue[index];
    if (!current) continue;
    for (const edge of nav.get(current) ?? []) {
      if (edge.interaction_required || edge.connector_id || edge.kind !== "walk") continue;
      const next = edge.a === current ? edge.b : edge.a;
      const cell = cells.get(next);
      if (!cell || visited.has(next) || !harborFocusAllows(cell)) continue;
      if (next === targetId) return true;
      visited.add(next);
      queue.push(next);
    }
  }
  return false;
}

function v22CellInFocus(cell: TacticalGridCell): boolean {
  return (currentV22LevelId === "all" || cell.level_id === currentV22LevelId)
    && (currentV22Elevation === "all" || cell.elevation === currentV22Elevation);
}

function v22CanStep(sceneKey: V22SceneKey, from: TacticalGridCell, to: TacticalGridCell): boolean {
  if (!from.walkable || !to.walkable || from.level_id !== to.level_id) return false;
  if (!v22CellAllowed(to) || v22BlockedCells.get(sceneKey)?.has(to.id)) return false;
  const routeEdge = v22RouteNeighbors.get(sceneKey)?.get(from.id)?.has(to.id) ?? false;
  if (routeEdge) return true;
  const orthogonal = Math.abs(from.row - to.row) + Math.abs(from.col - to.col) === 1;
  // Generic open terrain accepts ordinary five-foot climbs.  Larger jumps must
  // be declared by a route or link, so a player cannot walk straight through a
  // cliff, a sealed sewer wall, or an unplanned floating-island gap.
  return orthogonal && Math.abs(from.elevation - to.elevation) <= 5;
}

function v22Reachable(sceneKey: V22SceneKey, startId: string, targetId: string): boolean {
  if (startId === targetId) return true;
  const cells = v22Cells.get(sceneKey);
  const start = cells?.get(startId);
  const target = cells?.get(targetId);
  if (!cells || !start || !target || !v22CellAllowed(start) || !v22CellAllowed(target) || start.level_id !== target.level_id) return false;
  const visited = new Set<string>([start.id]);
  const queue = [start];
  for (let index = 0; index < queue.length; index += 1) {
    const current = queue[index];
    if (!current) continue;
    const adjacentIds = new Set<string>(v22RouteNeighbors.get(sceneKey)?.get(current.id) ?? []);
    const neighbors: Array<[number, number]> = [[current.row - 1, current.col], [current.row + 1, current.col], [current.row, current.col - 1], [current.row, current.col + 1]];
    for (const [row, col] of neighbors) {
      const neighbor = v22CellAt(sceneKey, current.level_id, row, col);
      if (neighbor) adjacentIds.add(neighbor.id);
    }
    for (const neighborId of adjacentIds) {
      const next = cells.get(neighborId);
      if (!next || visited.has(next.id) || !v22CanStep(sceneKey, current, next)) continue;
      if (next.id === targetId) return true;
      visited.add(next.id);
      queue.push(next);
    }
  }
  return false;
}

function v22RouteNamesAt(sceneKey: V22SceneKey, cellId: string): string[] {
  return (v22Grids.get(sceneKey)?.routes ?? [])
    .filter((route) => route.cell_ids.includes(cellId) && (route.visibility !== "dm_only" || (currentMode === "dm" && dmTuning.showDmOnly)))
    .map((route) => route.name);
}

function v22FeaturesAt(sceneKey: V22SceneKey, cellId: string): TacticalGridFeature[] {
  return (v22Grids.get(sceneKey)?.features ?? [])
    .filter((feature) => feature.cell_ids.includes(cellId) && (feature.visibility !== "dm_only" || (currentMode === "dm" && dmTuning.showDmOnly)));
}

function showCityNotice(message: string): void {
  cityNotice = message;
  selectionMarker.visible = false;
  cellInspector.innerHTML = `
    <div><dt>导航提示</dt><dd>${message}</dd></div>
    <div><dt>规则</dt><dd>跨建筑与跨楼层必须使用门或楼梯</dd></div>`;
  updateHud();
}

function clearCityNotice(): void {
  cityNotice = null;
}

function cellFromHit(hit: THREE.Intersection): CellSelection | null {
  const row = Math.floor(-hit.point.z);
  const col = Math.floor(hit.point.x);
  if (currentScene === "church") {
    const level = objectLevel(hit.object) ?? 1;
    const room = roomAt(level, row, col);
    if (!room) return null;
    if (currentMode === "player" && room.visibility === "dm_only") return null;
    return { row, col, layer: level, area: room.name, room, walkable: true, movement: "可进入 · 5 尺" };
  }
  if (currentScene === "city") {
    const level = objectCityLevel(hit.object) ?? (currentCityScope === "outdoor" ? 0 : 1);
    const cell = cityCells.get(cityCellKey(level, row, col));
    if (!cell?.walkable) return null;
    if (currentCityScope === "outdoor" && cell.space_kind !== "outdoor") return null;
    if (currentCityScope !== "outdoor" && cell.building_id !== currentCityScope) return null;
    const building = cityBuildingById(cell.building_id);
    const cityRoom = cityRoomById(building, cell.room_id);
    return {
      row, col, layer: level, area: cell.space_kind === "outdoor" ? cell.zone : cityRoom?.name ?? cell.room_id,
      building, cityRoom, spaceKind: cell.space_kind, walkable: true,
      movement: `消耗 ${cell.movement_cost} · 5 尺`,
    };
  }
  if (isRuntimeScene(currentScene)) {
    const levelId = objectHarborLevelId(hit.object) || (currentHarborFocus === "surface" ? "surface" : currentHarborLevelId === "all" ? "" : currentHarborLevelId);
    if (!levelId) return null;
    const cell = harborCellAt(levelId, row, col);
    if (!cell?.walkable || !harborFocusAllows(cell) || (cell.visibility === "dm_only" && (currentMode !== "dm" || !dmTuning.showDmOnly))) return null;
    return {
      row, col, layer: 0, levelId: cell.level_id, zBaseFt: cell.z_base_ft, volumeId: cell.volume_id,
      area: runtimeRoomsFor().get(cell.room_id)?.name || cell.room_id || cell.surface,
      spaceKind: cell.volume_id ? "可聚焦空间" : currentScene === "old_clock" ? "旧钟区地表" : "港区地表",
      walkable: true, movement: `消耗 ${cell.movement.walk ?? 1} · 5 尺`,
    };
  }
  if (isV22Scene(currentScene)) {
    const grid = v22Grid(currentScene);
    const levelId = objectV22LevelId(hit.object)
      || (currentV22LevelId === "all" ? grid?.levels[0]?.id : currentV22LevelId)
      || "surface";
    const cell = v22CellAt(currentScene, levelId, row, col);
    if (!cell?.walkable || !v22CellAllowed(cell) || !v22CellInFocus(cell) || v22BlockedCells.get(currentScene)?.has(cell.id)) return null;
    const routes = v22RouteNamesAt(currentScene, cell.id);
    const features = v22FeaturesAt(currentScene, cell.id);
    const context = [routes[0], features[0]?.kind.replaceAll("_", " ")].filter(Boolean).join(" · ");
    return {
      row, col, layer: cell.elevation, levelId: cell.level_id, zBaseFt: cell.elevation,
      area: context ? `${cell.zone} · ${context}` : cell.zone,
      spaceKind: cell.surface, walkable: true, gridCell: cell,
      movement: `可走 · ${cell.surface.replaceAll("_", " ")} · 5 尺`,
    };
  }
  const cell = underdarkCells.get(cellKey(row, col));
  if (!cell?.walkable) return null;
  return {
    row,
    col,
    layer: cell.elevation,
    area: cell.zone,
    walkable: true,
    movement: `消耗 ${cell.movement_cost} · 5 尺`,
  };
}

function groundHeight(layer: number): number {
  if (currentScene === "church") return (layer - 1) * CHURCH_FLOOR_HEIGHT;
  if (currentScene === "city") return layer === 0 ? 0 : (layer - 1) * CITY_FLOOR_HEIGHT;
  if (isRuntimeScene(currentScene)) return 0;
  if (isV22Scene(currentScene)) return v22WorldHeight(layer);
  return layer * UNDERDARK_ELEVATION_HEIGHT;
}

function showSelection(cell: CellSelection): void {
  const markerHeight = isRuntimeScene(currentScene) ? harborWorldHeight(cell.zBaseFt ?? 0) : groundHeight(cell.layer);
  selectionMarker.position.set(cell.col + 0.5, markerHeight + 0.035, -cell.row - 0.5);
  selectionMarker.visible = true;
  const labels = currentScene === "church"
    ? [`L${cell.layer}`, cell.area, cell.movement]
    : currentScene === "city"
      ? [cell.layer === 0 ? "街区外景" : `L${cell.layer}`, cell.spaceKind === "outdoor" ? "户外" : "建筑内部", cell.area, cell.movement]
      : [`E${cell.layer} · +${cell.layer * 5} 尺`, cell.area, cell.movement];
  if (currentScene === "city") {
    cellInspector.innerHTML = `
      <div><dt>坐标</dt><dd>row ${cell.row} · col ${cell.col}</dd></div>
      <div><dt>空间</dt><dd>${labels[0]} · ${labels[1]}</dd></div>
      <div><dt>建筑</dt><dd>${cell.building?.name ?? "灰石街区"}</dd></div>
      <div><dt>房间/区域</dt><dd>${labels[2]}</dd></div>
      <div><dt>移动</dt><dd>${labels[3]}</dd></div>`;
    return;
  }
  if (isRuntimeScene(currentScene)) {
    const level = harborLevel(cell.levelId ?? "");
    cellInspector.innerHTML = `
      <div><dt>坐标</dt><dd>row ${cell.row} · col ${cell.col}</dd></div>
      <div><dt>层级</dt><dd>${level?.label ?? cell.levelId ?? "—"} · ${cell.zBaseFt ?? 0} ft</dd></div>
      <div><dt>焦点</dt><dd>${cell.volumeId || (currentScene === "old_clock" ? "旧钟区地表" : "港区地表")}</dd></div>
      <div><dt>区域</dt><dd>${cell.area}</dd></div>
      <div><dt>移动</dt><dd>${cell.movement}</dd></div>`;
    return;
  }
  if (isV22Scene(currentScene) && cell.gridCell) {
    const grid = v22Grid(currentScene);
    const level = v22Level(currentScene, cell.gridCell.level_id);
    const anchor = grid?.anchors.find((item) => item.cell_id === cell.gridCell?.id && (item.visibility !== "dm_only" || (currentMode === "dm" && dmTuning.showDmOnly)));
    const routes = v22RouteNamesAt(currentScene, cell.gridCell.id);
    const features = v22FeaturesAt(currentScene, cell.gridCell.id);
    const details = [anchor?.name, ...routes, ...features.map((feature) => feature.kind.replaceAll("_", " "))].filter(Boolean).join(" · ") || "—";
    cellInspector.innerHTML = `
      <div><dt>坐标</dt><dd>row ${cell.row} · col ${cell.col}</dd></div>
      <div><dt>层级/高程</dt><dd>${level?.label ?? cell.gridCell.level_id} · ${cell.gridCell.elevation >= 0 ? "+" : ""}${cell.gridCell.elevation} ft</dd></div>
      <div><dt>地表/区域</dt><dd>${cell.gridCell.surface.replaceAll("_", " ")} · ${cell.gridCell.zone}</dd></div>
      <div><dt>路线/特性</dt><dd>${details}</dd></div>
      <div><dt>移动</dt><dd>${cell.movement}</dd></div>`;
    return;
  }
  cellInspector.innerHTML = `
    <div><dt>坐标</dt><dd>row ${cell.row} · col ${cell.col}</dd></div>
    <div><dt>层级</dt><dd>${labels[0]}</dd></div>
    <div><dt>区域</dt><dd>${labels[1]}</dd></div>
    <div><dt>移动</dt><dd>${labels[2]}</dd></div>`;
}

function makeToken(index: number): THREE.Group {
  const color = TOKEN_COLORS[index] ?? TOKEN_COLORS[0];
  const group = new THREE.Group();
  group.name = `TestToken_${index}`;
  const body = new THREE.Mesh(
    new THREE.CylinderGeometry(0.22, 0.31, 0.52, 16),
    new THREE.MeshStandardMaterial({ color, roughness: 0.38, metalness: 0.15, emissive: color, emissiveIntensity: 0.12 }),
  );
  body.position.y = 0.29;
  group.add(body);
  const base = new THREE.Mesh(
    new THREE.CylinderGeometry(0.37, 0.37, 0.08, 24),
    new THREE.MeshStandardMaterial({ color: 0x111927, roughness: 0.7, emissive: color, emissiveIntensity: 0.18 }),
  );
  base.position.y = 0.04;
  group.add(base);
  return group;
}

function ensureTokenStates(sceneKey: SceneKey): TokenState[] {
  const existing = tokenStates.get(sceneKey);
  if (existing) return existing;
  let states: TokenState[];
  if (sceneKey === "church") {
    states = [
      { row: 13, col: 8, layer: 1 },
      { row: 11, col: 8, layer: 1 },
      { row: 9, col: 6, layer: 1 },
      { row: 5, col: 6, layer: 1 },
    ];
  } else if (sceneKey === "underdark") {
    const start = underdarkGrid?.anchors.party_start ?? [18, 8];
    states = [...underdarkCells.values()]
      .filter((cell) => cell.walkable)
      .sort((a, b) => {
        const da = Math.abs(a.row - start[0]) + Math.abs(a.col - start[1]);
        const db = Math.abs(b.row - start[0]) + Math.abs(b.col - start[1]);
        return da - db || a.row - b.row || a.col - b.col;
      })
      .slice(0, TOKEN_NAMES.length)
      .map((cell) => ({ row: cell.row, col: cell.col, layer: cell.elevation }));
  } else if (isRuntimeScene(sceneKey)) {
    const runtime = runtimeFor(sceneKey);
    const start = runtime?.anchors.find((anchor) => anchor.id === "party_start");
    const cells = [...runtimeCellsFor(sceneKey).values()]
      .filter((cell) => cell.walkable && cell.level_id === (start?.level_id ?? "surface"))
      .sort((a, b) => {
        const da = Math.abs(a.row - (start?.row ?? 0)) + Math.abs(a.col - (start?.col ?? 0));
        const db = Math.abs(b.row - (start?.row ?? 0)) + Math.abs(b.col - (start?.col ?? 0));
        return da - db || a.row - b.row || a.col - b.col;
      });
    states = cells.slice(0, TOKEN_NAMES.length).map((cell) => ({ row: cell.row, col: cell.col, layer: 0, levelId: cell.level_id, zBaseFt: cell.z_base_ft }));
  } else if (isV22Scene(sceneKey)) {
    const grid = v22Grids.get(sceneKey);
    const entry = grid?.anchors.find((anchor) => anchor.kind === "entry" && anchor.visibility === "public")
      ?? grid?.anchors.find((anchor) => anchor.visibility === "public");
    const cells = [...(v22Cells.get(sceneKey)?.values() ?? [])]
      .filter((cell) => cell.walkable && cell.visibility === "public" && !v22BlockedCells.get(sceneKey)?.has(cell.id))
      .sort((a, b) => {
        const da = Math.abs(a.row - (entry?.row ?? 0)) + Math.abs(a.col - (entry?.col ?? 0));
        const db = Math.abs(b.row - (entry?.row ?? 0)) + Math.abs(b.col - (entry?.col ?? 0));
        return da - db || a.row - b.row || a.col - b.col;
      });
    states = cells.slice(0, TOKEN_NAMES.length).map((cell) => ({
      row: cell.row, col: cell.col, layer: cell.elevation, levelId: cell.level_id, zBaseFt: cell.elevation,
    }));
  } else if (isProfileScene(sceneKey)) {
    states = [];
  } else {
    const start = cityGrid?.anchors.party_start ?? [14, 15];
    const outdoor = [...cityCells.values()]
      .filter((cell) => cell.space_kind === "outdoor" && cell.walkable)
      .sort((a, b) => {
        const da = Math.abs(a.row - start[0]) + Math.abs(a.col - start[1]);
        const db = Math.abs(b.row - start[0]) + Math.abs(b.col - start[1]);
        return da - db || a.row - b.row || a.col - b.col;
      });
    states = outdoor.slice(0, TOKEN_NAMES.length).map((cell) => ({ row: cell.row, col: cell.col, layer: 0 }));
  }
  tokenStates.set(sceneKey, states);
  return states;
}

function clearTokenObjects(): void {
  tokenHolder.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    object.geometry.dispose();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    materials.forEach((material) => material.dispose());
  });
  tokenHolder.clear();
}

function rebuildTokens(): void {
  clearTokenObjects();
  const states = ensureTokenStates(currentScene);
  states.forEach((state, index) => {
    const token = makeToken(index);
    const height = isRuntimeScene(currentScene) ? harborWorldHeight(state.zBaseFt ?? 0) : groundHeight(state.layer);
    token.position.set(state.col + 0.5, height + 0.035, -state.row - 0.5);
    token.userData.tokenIndex = index;
    tokenHolder.add(token);
  });
  updateTokenVisibility();
  renderTokenList();
}

function tokenIsVisible(state: TokenState): boolean {
  if (isRuntimeScene(currentScene)) {
    const cell = state.levelId ? harborCellAt(state.levelId, state.row, state.col) : undefined;
    return Boolean(cell && harborFocusAllows(cell) && (currentHarborLevelId === "all" || cell.level_id === currentHarborLevelId));
  }
  if (isV22Scene(currentScene)) {
    const cell = state.levelId ? v22CellAt(currentScene, state.levelId, state.row, state.col) : undefined;
    return Boolean(cell && v22CellAllowed(cell) && v22CellInFocus(cell));
  }
  if (currentScene === "city") {
    const cell = cityCells.get(cityCellKey(state.layer, state.row, state.col));
    if (!cell) return false;
    if (currentCityScope === "outdoor") return cell.space_kind === "outdoor";
    return cell.building_id === currentCityScope && (currentLayer === "all" || state.layer === currentLayer);
  }
  if (currentLayer !== "all" && state.layer !== currentLayer) return false;
  if (currentScene === "church" && currentMode === "player") {
    return roomAt(state.layer, state.row, state.col)?.visibility !== "dm_only";
  }
  return true;
}

function updateTokenVisibility(): void {
  const states = ensureTokenStates(currentScene);
  tokenHolder.visible = viewerState.experienceMode !== "theatre";
  tokenHolder.scale.setScalar(dmTuning.tokenScale);
  tokenHolder.children.forEach((token, index) => {
    const state = states[index];
    token.visible = state ? tokenIsVisible(state) : false;
  });
}

function renderTokenList(): void {
  tokenList.innerHTML = "";
  TOKEN_NAMES.forEach((name, index) => {
    const button = document.createElement("button");
    button.className = `token-button${selectedToken === index ? " active" : ""}`;
    button.type = "button";
    const color = TOKEN_COLORS[index] ?? TOKEN_COLORS[0];
    button.innerHTML = `<span class="token-swatch" style="color:#${color.toString(16).padStart(6, "0")};background:currentColor"></span><span>${name}</span>`;
    button.addEventListener("click", () => {
      selectedToken = selectedToken === index ? null : index;
      renderTokenList();
    });
    tokenList.append(button);
  });
}

function moveSelectedToken(cell: CellSelection): void {
  if (viewerState.experienceMode === "theatre" || selectedToken === null || !cell.walkable) return;
  if (currentLayer !== "all" && cell.layer !== currentLayer) return;
  const states = ensureTokenStates(currentScene);
  const state = states[selectedToken];
  const object = tokenHolder.children[selectedToken];
  if (!state || !object) return;
  if (isV22Scene(currentScene)) {
    const start = state.levelId ? v22CellAt(currentScene, state.levelId, state.row, state.col) : undefined;
    const target = cell.gridCell;
    if (!start || !target || !v22CellInFocus(target) || !v22Reachable(currentScene, start.id, target.id)) {
      showCityNotice("该格不可达：需沿同层可走格移动；高差超过 5 尺时必须走已声明路线或连接点");
      return;
    }
    state.levelId = target.level_id;
    state.zBaseFt = target.elevation;
    clearCityNotice();
  }
  if (currentScene === "city") {
    const start = cityCellAt(state.layer, state.row, state.col);
    const target = cityCellAt(cell.layer, cell.row, cell.col);
    if (!start || !target || !cityCellsReachable(start, target)) {
      showCityNotice("该格不可达：请沿同层道路移动，跨房间、建筑或楼层请使用门/楼梯");
      return;
    }
    clearCityNotice();
  }
  if (isRuntimeScene(currentScene)) {
    const start = state.levelId ? harborCellAt(state.levelId, state.row, state.col) : undefined;
    const target = cell.levelId ? harborCellAt(cell.levelId, cell.row, cell.col) : undefined;
    if (!start || !target || !harborReachable(start.id, target.id)) {
      showCityNotice("该格不可达：移动严格遵循 runtime.nav.edges，门、楼梯、爬梯、舱口与暗门需点击连接点");
      return;
    }
    state.levelId = target.level_id;
    state.zBaseFt = target.z_base_ft;
    clearCityNotice();
  }
  state.row = cell.row;
  state.col = cell.col;
  state.layer = cell.layer;
  object.position.set(cell.col + 0.5, isRuntimeScene(currentScene) ? harborWorldHeight(state.zBaseFt ?? 0) + 0.035 : groundHeight(cell.layer) + 0.035, -cell.row - 0.5);
  object.visible = tokenIsVisible(state);
  selectedToken = null;
  renderTokenList();
}

function transitionForObject(object: THREE.Object3D): CityTransition | undefined {
  const transitionId = objectMetadata(object, "transition_id");
  if (transitionId) return cityGrid?.transitions.find((transition) => transition.id === transitionId);
  const buildingId = objectCityBuilding(object);
  const kind = objectMetadata(object, "prototype_kind");
  if (kind === "door" || object.name.startsWith("Door_")) {
    return cityGrid?.transitions.find((transition) => transition.type === "entrance" && transition.to.building_id === buildingId);
  }
  if (kind === "stairs" || object.name.startsWith("Stair_")) {
    const objectLevel = objectCityLevel(object);
    return cityGrid?.transitions.find((transition) =>
      transition.type === "stairs" && transition.to.building_id === buildingId
      && (objectLevel === null || transition.from.level_index === objectLevel || transition.to.level_index === objectLevel),
    );
  }
  return undefined;
}

function transitionDistance(state: TokenState, point: CityTransitionPoint): number | null {
  if (state.layer !== point.level_index) return null;
  return Math.abs(state.row - point.row) + Math.abs(state.col - point.col);
}

function applyCityTransition(transition: CityTransition): boolean {
  const states = ensureTokenStates("city");
  if (selectedToken === null) {
    showCityNotice("请先选择一个 Token，再移动到门/楼梯旁");
    return false;
  }
  const index = selectedToken;
  const state = states[index];
  if (!state) return false;
  const endpoints: Array<{ source: CityTransitionPoint; target: CityTransitionPoint }> = [
    { source: transition.from, target: transition.to },
    { source: transition.to, target: transition.from },
  ];
  const usable = endpoints
    .map((entry) => ({ ...entry, distance: transitionDistance(state, entry.source) }))
    .filter((entry): entry is { source: CityTransitionPoint; target: CityTransitionPoint; distance: number } =>
      entry.distance !== null && entry.distance <= 1 && cityPointInScope(entry.source, currentCityScope),
    )
    .sort((left, right) => left.distance - right.distance)[0];
  if (!usable) {
    showCityNotice("先移动到门/楼梯旁，再执行跨建筑或跨楼层移动");
    return false;
  }

  const enteringInterior = usable.source.space_kind === "outdoor" && usable.target.space_kind === "interior";
  const returningOutside = usable.target.space_kind === "outdoor";
  if (enteringInterior) cityDistrictCameraState = { position: camera.position.clone(), target: controls.target.clone() };

  state.row = usable.target.row;
  state.col = usable.target.col;
  state.layer = usable.target.level_index;
  currentCityScope = usable.target.space_kind === "outdoor" ? "outdoor" : usable.target.building_id ?? "outdoor";
  currentLayer = usable.target.space_kind === "outdoor" ? "all" : usable.target.level_index;
  selectedToken = null;
  clearCityNotice();
  clearCellSelection();
  rebuildTokens();
  applyRenderTuning();
  applyLayerFilter();
  updateUi();
  if (returningOutside && cityDistrictCameraState) applyCameraState(cityDistrictCameraState);
  else fitView();
  return true;
}

function harborConnectorForObject(object: THREE.Object3D): GenericRuntimeConnector | undefined {
  const connectorId = objectMetadata(object, "connector_id");
  if (connectorId) return runtimeConnectorsFor().get(connectorId);
  return undefined;
}

function applyHarborConnector(connector: GenericRuntimeConnector): boolean {
  if (selectedToken === null) {
    showCityNotice("请先选择一个 Token，再移动到门、楼梯或暗门旁");
    return false;
  }
  if (!isRuntimeScene(currentScene)) return false;
  const states = ensureTokenStates(currentScene);
  const state = states[selectedToken];
  if (!state?.levelId) return false;
  const candidates = connector.cell_ids
    .map((id) => ({ id, cell: runtimeCellsFor().get(id) }))
    .filter((entry): entry is { id: string; cell: GenericRuntimeCell } => Boolean(entry.cell));
  const source = candidates
    .map((entry) => ({ ...entry, distance: entry.cell.level_id === state.levelId ? Math.abs(entry.cell.row - state.row) + Math.abs(entry.cell.col - state.col) : Number.POSITIVE_INFINITY }))
    .filter((entry) => entry.distance <= 1)
    .sort((left, right) => left.distance - right.distance)[0];
  if (!source) {
    showCityNotice("先移动到门/楼梯/暗门旁，再执行连接移动");
    return false;
  }
  const targetId = connector.cell_ids.find((id) => id !== source.id);
  const edge = targetId ? (runtimeNavFor().get(source.id) ?? []).find((item) => item.connector_id === connector.id && (item.a === targetId || item.b === targetId)) : undefined;
  const target = targetId ? runtimeCellsFor().get(targetId) : undefined;
  if (!edge || !target) {
    showCityNotice("该连接在 runtime.nav.edges 中不可用");
    return false;
  }
  state.row = target.row;
  state.col = target.col;
  state.levelId = target.level_id;
  state.zBaseFt = target.z_base_ft;
  currentHarborFocus = target.volume_id || "surface";
  currentHarborLevelId = target.level_id;
  selectedToken = null;
  clearCityNotice();
  clearCellSelection();
  rebuildTokens();
  applyLayerFilter();
  updateUi();
  fitView();
  return true;
}

function pickHarborTransition(): boolean {
  const hits = raycaster.intersectObjects(transitionSurfaces.filter((surface) => surface.visible), false);
  for (const hit of hits) {
    const connector = harborConnectorForObject(hit.object);
    if (!connector) continue;
    applyHarborConnector(connector);
    return true;
  }
  return false;
}

function pickCityTransition(): boolean {
  const hits = raycaster.intersectObjects(transitionSurfaces.filter((surface) => surface.visible), false);
  for (const hit of hits) {
    const transition = transitionForObject(hit.object);
    if (!transition) continue;
    applyCityTransition(transition);
    return true;
  }
  return false;
}

function pick(event: PointerEvent): void {
  if (viewerState.experienceMode === "theatre") return;
  const rect = canvas.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  if (currentScene === "city" && pickCityTransition()) return;
  if (isRuntimeScene(currentScene) && pickHarborTransition()) return;
  const candidates = tacticalSurfaces.filter((surface) => surface.visible);
  for (const hit of raycaster.intersectObjects(candidates, false)) {
    const cell = cellFromHit(hit);
    if (!cell) continue;
    showSelection(cell);
    moveSelectedToken(cell);
    return;
  }
}

function normalizeExperienceFocus(): void {
  if (viewerState.experienceMode === "theatre") {
    if (isRuntimeScene(currentScene)) currentHarborLevelId = "all";
    else if (isV22Scene(currentScene)) {
      currentV22LevelId = "all";
      currentV22Elevation = "all";
    } else currentLayer = "all";
    return;
  }
  if (viewerState.experienceMode !== "tactical") return;
  if (currentScene === "church" && currentLayer === "all") currentLayer = 1;
  if (currentScene === "underdark" && currentLayer === "all") currentLayer = 0;
  if (currentScene === "city" && currentCityScope !== "outdoor" && currentLayer === "all") {
    currentLayer = cityBuildingById(currentCityScope)?.floors[0]?.floor_index ?? 1;
  }
  if (isRuntimeScene(currentScene) && currentHarborLevelId === "all") {
    const first = (runtimeFor()?.scene.levels ?? []).find((level) => currentHarborFocus === "surface" ? level.id === "surface" : level.volume_id === currentHarborFocus);
    currentHarborLevelId = first?.id ?? "surface";
  }
  if (isV22Scene(currentScene)) {
    const grid = v22Grid(currentScene);
    const levelExists = currentV22LevelId !== "all" && Boolean(grid?.levels.some((level) => level.id === currentV22LevelId));
    if (!levelExists) currentV22LevelId = grid?.levels[0]?.id ?? "surface";
    const elevations = [...new Set((grid?.cells ?? []).filter((cell) => cell.walkable && cell.level_id === currentV22LevelId).map((cell) => cell.elevation))].sort((a, b) => a - b);
    if (currentV22Elevation === "all" || !elevations.includes(currentV22Elevation)) {
      currentV22Elevation = elevations[0] ?? "all";
    }
  }
}

function renderExperienceUi(): void {
  const theatre = viewerState.experienceMode === "theatre";
  experienceButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.experience === viewerState.experienceMode);
  });
  dmSettingsPanel.hidden = currentMode !== "dm";
  if (layerPanel) layerPanel.hidden = theatre || isProfileScene(currentScene);
  if (tokenPanel) tokenPanel.hidden = theatre || isProfileScene(currentScene);
  dmCutawayEnabled.checked = dmTuning.cutawayEnabled;
  dmCutawayOpacity.value = String(Math.round(dmTuning.cutawayOpacity * 100));
  dmGridOpacity.value = String(Math.round(dmTuning.gridOpacity * 100));
  dmFogDensity.value = String(Math.round(dmTuning.fogDensity * 1000));
  dmExposure.value = String(Math.round(dmTuning.exposure * 100));
  dmTokenScale.value = String(Math.round(dmTuning.tokenScale * 100));
  dmShowDmOnly.checked = dmTuning.showDmOnly;
  dmShowHotspots.checked = dmTuning.showHotspots;
  dmQuality.value = dmTuning.qualityPreset;
  dmCutawayValue.textContent = `${Math.round(dmTuning.cutawayOpacity * 100)}%`;
  dmGridValue.textContent = `${Math.round(dmTuning.gridOpacity * 100)}%`;
  dmFogValue.textContent = dmTuning.fogDensity.toFixed(3);
  dmExposureValue.textContent = dmTuning.exposure.toFixed(2);
  dmTokenScaleValue.textContent = `${Math.round(dmTuning.tokenScale * 100)}%`;
  updateDebugReadout();
}

function updateDebugReadout(): void {
  const visibleMeshes = semanticCatalog.objects.filter((entry) => entry.mesh.visible).length;
  const visibleTactical = tacticalSurfaces.filter((surface) => surface.visible).length;
  const visibleTransitions = transitionSurfaces.filter((surface) => surface.visible).length;
  const navEdges = isRuntimeScene(currentScene)
    ? runtimeFor()?.nav.edges.length ?? 0
    : currentScene === "city"
      ? cityGrid?.transitions.length ?? 0
      : isV22Scene(currentScene)
        ? (v22Grids.get(currentScene)?.routes.reduce((count, route) => count + Math.max(0, route.cell_ids.length - 1), 0) ?? 0)
        : 0;
  dmDebugReadout.textContent = `${lastFrameFps || "—"} FPS · ${renderer.info.render.calls} calls · ${renderer.info.render.triangles.toLocaleString()} tris\n可见 ${visibleMeshes} meshes · 战术面 ${visibleTactical} · 连接 ${visibleTransitions} · 导航边 ${navEdges}`;
}

function setExperienceMode(next: ExperienceMode): void {
  if (next === viewerState.experienceMode) return;
  viewerState.experienceMode = next;
  selectedToken = null;
  normalizeExperienceFocus();
  syncViewerState();
  renderLayerControls();
  renderCityScopeControls();
  renderHarborFocusControls();
  applyLayerFilter();
  renderExperienceUi();
  renderRuntimePresets();
  if (next === "theatre") resetView();
  else if (next === "tactical") fitView();
  updateCutaway(performance.now(), true);
}

function updateDmTuningFromControls(): void {
  dmTuning.cutawayEnabled = dmCutawayEnabled.checked;
  dmTuning.cutawayOpacity = Number(dmCutawayOpacity.value) / 100;
  dmTuning.gridOpacity = Number(dmGridOpacity.value) / 100;
  dmTuning.fogDensity = Number(dmFogDensity.value) / 1000;
  dmTuning.exposure = Number(dmExposure.value) / 100;
  dmTuning.tokenScale = Number(dmTokenScale.value) / 100;
  dmTuning.showDmOnly = dmShowDmOnly.checked;
  dmTuning.showHotspots = dmShowHotspots.checked;
  dmTuning.qualityPreset = dmQuality.value as QualityPreset;
  applyRenderTuning();
  applyLayerFilter();
  renderExperienceUi();
  updateCutaway(performance.now(), true);
}

function renderLayerControls(): void {
  if (isProfileScene(currentScene)) {
    layerControls.innerHTML = "";
    return;
  }
  if (isRuntimeScene(currentScene)) {
    const levels = (runtimeFor()?.scene.levels ?? []).filter((level) => currentHarborFocus === "surface" ? level.id === "surface" : level.volume_id === currentHarborFocus);
    layerControls.innerHTML = "";
    const choices: Array<string | "all"> = levels.length > 1 ? ["all", ...levels.map((level) => level.id)] : levels.map((level) => level.id);
    for (const value of choices) {
      const level = value === "all" ? undefined : harborLevel(value);
      const button = document.createElement("button");
      button.type = "button";
      button.disabled = viewerState.experienceMode === "theatre";
      button.className = currentHarborLevelId === value ? "active" : "";
      button.textContent = value === "all" ? "全层" : level?.label ?? value;
      button.title = value === "all" ? "显示焦点范围内全部层级" : `${value} · ${level?.z_base_ft ?? 0} ft`;
      button.addEventListener("click", () => {
        currentHarborLevelId = value;
        renderLayerControls();
        applyLayerFilter();
        fitView();
      });
      layerControls.append(button);
    }
    return;
  }
  if (isV22Scene(currentScene)) {
    const grid = v22Grid(currentScene);
    layerControls.innerHTML = "";
    if (!grid) return;
    const appendControl = (text: string, active: boolean, group: "level" | "elevation", onClick: () => void, title: string): void => {
      const button = document.createElement("button");
      button.type = "button";
      button.disabled = viewerState.experienceMode === "theatre";
      button.className = `v22-filter v22-filter-${group}${active ? " active" : ""}`;
      button.textContent = text;
      button.title = title;
      button.addEventListener("click", onClick);
      layerControls.append(button);
    };
    if (grid.levels.length > 1) {
      appendControl("全层", currentV22LevelId === "all", "level", () => {
        currentV22LevelId = "all";
        currentV22Elevation = "all";
        renderLayerControls();
        applyLayerFilter();
      }, "显示全部地图层");
    }
    for (const level of grid.levels) {
      const label = level.label === "Surface" ? "地图层" : level.label;
      appendControl(`层 · ${label}`, currentV22LevelId === level.id, "level", () => {
        currentV22LevelId = level.id;
        currentV22Elevation = "all";
        renderLayerControls();
        applyLayerFilter();
      }, `${level.id} · 基准 ${level.z_base_ft} ft`);
    }
    const scopedCells = grid.cells.filter((cell) => cell.walkable && (currentV22LevelId === "all" || cell.level_id === currentV22LevelId));
    const elevations = [...new Set(scopedCells.map((cell) => cell.elevation))].sort((a, b) => a - b);
    appendControl("全部高度", currentV22Elevation === "all", "elevation", () => {
      currentV22Elevation = "all";
      renderLayerControls();
      applyLayerFilter();
    }, "显示当前地图层的全部高程");
    for (const elevation of elevations) {
      appendControl(`${elevation >= 0 ? "+" : ""}${elevation}′`, currentV22Elevation === elevation, "elevation", () => {
        currentV22Elevation = elevation;
        renderLayerControls();
        applyLayerFilter();
      }, `仅显示 ${elevation >= 0 ? "+" : ""}${elevation} ft 高程的可走格`);
    }
    return;
  }
  const cityBuilding = currentScene === "city" ? cityBuildingById(currentCityScope) : undefined;
  const values: readonly ("all" | number)[] = currentScene === "church"
    ? ["all", 1, 2, 3]
    : currentScene === "city"
      ? currentCityScope === "outdoor" ? ["all"] : ["all", ...(cityBuilding?.floors.map((floor) => floor.floor_index) ?? [1])]
      : ["all", 0, 1, 2, 3, 4];
  layerControls.innerHTML = "";
  values.forEach((value) => {
    const button = document.createElement("button");
    button.type = "button";
    button.disabled = viewerState.experienceMode === "theatre";
    button.className = currentLayer === value ? "active" : "";
    button.textContent = value === "all" ? (currentScene === "city" && currentCityScope === "outdoor" ? "街区" : "全部") : currentScene === "underdark" ? `E${value}` : `L${value}`;
    button.addEventListener("click", () => {
      currentLayer = value;
      renderLayerControls();
      applyLayerFilter();
    });
    layerControls.append(button);
  });
}

function renderHarborFocusControls(): void {
  const runtimeSceneKey = isRuntimeScene(currentScene) ? currentScene : null;
  const active = runtimeSceneKey !== null && viewerState.experienceMode !== "theatre";
  harborFocusPanel.hidden = !active;
  if (!active || runtimeSceneKey === null) return;
  const runtime = runtimeFor();
  const descriptor = RUNTIME_SCENES[runtimeSceneKey];
  const levels = runtime?.scene.levels ?? [];
  const allVolumeIds = [...new Set(levels.map((level) => level.volume_id).filter(Boolean))];
  const allowed = descriptor.visibleFocusIds;
  const volumeIds = allowed ? allVolumeIds.filter((id) => allowed.includes(id)) : allVolumeIds;
  const volumeNames = new Map((runtime?.volumes ?? []).map((volume) => [volume.id, volume.name]));
  const hasSurface = levels.some((level) => level.id === "surface");
  const surfaceName = currentScene === "old_clock" ? "旧钟区地表" : currentScene === "harbor" ? "港区地表" : "地表";
  harborFocusNote.textContent = currentHarborFocus === "surface" ? `${surfaceName} · 查看模式` : `${volumeNames.get(currentHarborFocus) ?? currentHarborFocus} · 查看模式`;
  harborFocusControls.innerHTML = "";
  for (const focus of [...(hasSurface ? ["surface"] : []), ...volumeIds]) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `building-button${currentHarborFocus === focus ? " active" : ""}`;
    button.textContent = focus === "surface" ? `查看 · ${surfaceName}` : `查看 · ${volumeNames.get(focus) ?? focus.replaceAll("_", " ")}`;
    button.addEventListener("click", () => setHarborFocus(focus));
    harborFocusControls.append(button);
  }
}

function setHarborFocus(focus: string): void {
  if (!isRuntimeScene(currentScene) || focus === currentHarborFocus) return;
  currentHarborFocus = focus;
  const levels = (runtimeFor()?.scene.levels ?? []).filter((level) => focus === "surface" ? level.id === "surface" : level.volume_id === focus);
  currentHarborLevelId = levels[0]?.id ?? "all";
  clearCityNotice();
  clearCellSelection();
  applyRenderTuning();
  applyLayerFilter();
  updateUi();
  fitView();
}

function renderRuntimePresets(): void {
  const active = isRuntimeScene(currentScene) && (RUNTIME_SCENES[currentScene].presets?.length ?? 0) > 0;
  runtimePresetPanel.hidden = !active;
  runtimePresetControls.innerHTML = "";
  if (!active) return;
  for (const preset of RUNTIME_SCENES[currentScene as RuntimeSceneKey].presets) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `building-button${currentHarborFocus === preset.focus && currentHarborLevelId === preset.levelId && viewerState.experienceMode === preset.experience ? " active" : ""}`;
    button.textContent = preset.label;
    button.addEventListener("click", () => {
      currentHarborFocus = preset.focus;
      currentHarborLevelId = preset.levelId;
      viewerState.experienceMode = preset.experience;
      selectedToken = null;
      clearCityNotice();
      clearCellSelection();
      syncViewerState();
      applyRenderTuning();
      applyLayerFilter();
      updateUi();
      fitView();
    });
    runtimePresetControls.append(button);
  }
}

function renderCityScopeControls(): void {
  const isCity = currentScene === "city" && viewerState.experienceMode !== "theatre";
  cityScopePanel.hidden = !isCity;
  if (!isCity) return;
  const building = cityBuildingById(currentCityScope);
  cityScopeNote.textContent = building ? `${building.name} · DM 查看模式` : "街区外景 · 建筑入口";
  cityReturn.disabled = currentCityScope === "outdoor";
  cityBuildingControls.innerHTML = "";
  for (const item of citySpec?.buildings ?? []) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `building-button${currentCityScope === item.id ? " active" : ""}`;
    button.textContent = `查看 · ${item.name}${item.floors.length > 1 ? " · 2 层" : ""}`;
    button.addEventListener("click", () => setCityScope(item.id));
    cityBuildingControls.append(button);
  }
}

function setCityScope(nextScope: CityScope): void {
  if (currentScene !== "city" || nextScope === currentCityScope) return;
  const enteringFromDistrict = currentCityScope === "outdoor" && nextScope !== "outdoor";
  const returningToDistrict = currentCityScope !== "outdoor" && nextScope === "outdoor";
  if (enteringFromDistrict) {
    cityDistrictCameraState = { position: camera.position.clone(), target: controls.target.clone() };
  }
  currentCityScope = nextScope;
  currentLayer = "all";
  clearCityNotice();
  clearCellSelection();
  applyLayerFilter();
  renderLayerControls();
  renderCityScopeControls();
  updateHud();
  if (returningToDistrict && cityDistrictCameraState) applyCameraState(cityDistrictCameraState);
  else fitView();
}

function updateHud(): void {
  syncViewerState();
  const name = currentScene === "church"
    ? "教堂"
    : currentScene === "city"
      ? "城市街区"
      : isRuntimeScene(currentScene)
        ? RUNTIME_SCENES[currentScene].shortName
        : isV22Scene(currentScene)
        ? V22_SCENES[currentScene].name
          : isProfileScene(currentScene)
            ? PROFILE_SCENES[currentScene].name
          : "幽暗地域";
  const experience = viewerState.experienceMode === "theatre" ? "剧场" : viewerState.experienceMode === "exploration" ? "探索" : "战术";
  hudScene.textContent = `${name} · ${currentMode === "dm" ? "DM" : "玩家"} · ${experience}`;
  if (cityNotice) {
    hudFilter.textContent = cityNotice;
    return;
  }
  if (isRuntimeScene(currentScene)) {
    const level = currentHarborLevelId === "all" ? undefined : harborLevel(currentHarborLevelId);
    const levelLabel = level?.label ?? currentHarborLevelId;
    hudFilter.textContent = currentHarborLevelId === "all"
      ? `${currentHarborFocus} · 全层`
      : levelLabel.includes("ft") ? levelLabel : `${levelLabel} · ${level?.z_base_ft ?? 0} ft`;
    return;
  }
  if (isV22Scene(currentScene)) {
    const level = currentV22LevelId === "all" ? undefined : v22Level(currentScene, currentV22LevelId);
    const levelLabel = currentV22LevelId === "all" ? "全部地图层" : level?.label === "Surface" ? "地图层" : level?.label ?? currentV22LevelId;
    hudFilter.textContent = currentV22Elevation === "all"
      ? `${levelLabel} · 全部高度`
      : `${levelLabel} · ${currentV22Elevation >= 0 ? "+" : ""}${currentV22Elevation} ft`;
    return;
  }
  if (isProfileScene(currentScene)) {
    hudFilter.textContent = `${PROFILE_SCENES[currentScene].category} · Blender 静态预览`;
    return;
  }
  hudFilter.textContent = currentLayer === "all"
    ? currentScene === "underdark" ? "全部高度" : currentScene === "city" && currentCityScope === "outdoor" ? "街区外景" : "全部楼层"
    : currentScene === "underdark" ? `仅 E${currentLayer}` : `仅 L${currentLayer}`;
}

function updateUi(): void {
  syncViewerState();
  const church = currentScene === "church";
  const city = currentScene === "city";
  const runtimeDescriptor = isRuntimeScene(currentScene) ? RUNTIME_SCENES[currentScene] : undefined;
  const runtimeScene = Boolean(runtimeDescriptor);
  const v22Descriptor = isV22Scene(currentScene) ? V22_SCENES[currentScene] : undefined;
  const v22 = Boolean(v22Descriptor);
  const profileDescriptor = isProfileScene(currentScene) ? PROFILE_SCENES[currentScene] : undefined;
  const profileScene = Boolean(profileDescriptor);
  sceneTitle.textContent = church
    ? churchSpec?.site.name ?? "圣烛教堂"
    : city
      ? citySpec?.name ?? "暮钟区 · 灰石街区"
      : runtimeDescriptor
        ? runtimeFor()?.scene.name ?? runtimeDescriptor.name
        : v22Descriptor
        ? v22Descriptor.name
          : profileDescriptor
            ? profileDescriptor.name
          : "幽暗地域 · 紫晶裂谷";
  sceneDescription.textContent = church
    ? churchSpec?.site.brief ?? "三层建筑、房间、楼梯与 DM 隐藏密室。"
    : city
      ? "街道、广场与 7 栋可进入建筑；切换内部战术范围。"
      : runtimeDescriptor
        ? runtimeDescriptor.description
        : v22Descriptor
          ? v22Descriptor.description
          : profileDescriptor
            ? profileDescriptor.description
          : "48×36 格的裂谷、桥梁、高地、遗迹与菌林。";
  modeNote.textContent = church ? "独立模型 · 权限" : v22 || runtimeDescriptor?.supportsPlayer ? "同一资产 · public / DM 专属" : profileScene ? "Blender 静态资产 · 规划输入" : "当前仅 DM 资产";
  layerTitle.textContent = currentScene === "underdark" ? "高度" : runtimeScene ? "层级" : v22 ? "层级 / 高度" : profileScene ? "编排输入" : "楼层";
  sceneButtons.forEach((button) => button.classList.toggle("active", button.dataset.scene === currentScene));
  modeButtons.forEach((button) => {
    const mode = button.dataset.mode as ViewMode;
    const playerModeSupported = church || v22 || Boolean(runtimeDescriptor?.supportsPlayer);
    button.disabled = !playerModeSupported && mode === "player";
    button.title = !playerModeSupported && mode === "player" ? `${city ? "城市街区" : runtimeScene ? runtimeDescriptor?.shortName : profileScene ? profileDescriptor?.name : "幽暗地域"}当前没有独立玩家资产` : "";
    button.classList.toggle("active", mode === currentMode);
  });
  renderLayerControls();
  renderCityScopeControls();
  renderHarborFocusControls();
  renderRuntimePresets();
  renderExperienceUi();
  updateHud();
}

async function activateScene(sceneKey: SceneKey, mode: ViewMode, sceneChanged: boolean): Promise<void> {
  const request = ++loadSequence;
  if (sceneChanged) saveCameraState();
  currentScene = sceneKey;
  currentMode = sceneKey === "underdark" || sceneKey === "city" || isProfileScene(sceneKey) || (sceneKey === "harbor" && !RUNTIME_SCENES.harbor.supportsPlayer) ? "dm" : mode;
  if (sceneChanged) {
    currentLayer = "all";
    if (sceneKey === "city") currentCityScope = "outdoor";
    if (isRuntimeScene(sceneKey)) {
      const descriptor = RUNTIME_SCENES[sceneKey];
      currentHarborFocus = descriptor.visibleFocusIds?.find((id) => id !== "surface") ?? "surface";
      currentHarborLevelId = currentHarborFocus === "surface" ? "surface" : "all";
    }
    if (isV22Scene(sceneKey)) {
      currentV22LevelId = "all";
      currentV22Elevation = "all";
    }
  }
  normalizeExperienceFocus();
  selectedToken = null;
  clearCityNotice();
  clearCellSelection();
  updateUi();
  showLoading("正在加载场景");
  try {
    await ensureData();
    if (isRuntimeScene(currentScene)) {
      const runtime = await ensureRuntimeScene(currentScene);
      // A newly selected archetype may have no `surface` level.  Normalize
      // the level after its runtime has loaded so a one-level scene (such as
      // the sewer) cannot start with the stale global `surface` selection and
      // hide every generated mesh until the user clicks the floor filter.
      if (currentHarborFocus !== "surface") {
        const scopedLevels = runtime.scene.levels.filter((level) => level.volume_id === currentHarborFocus);
        if (!scopedLevels.some((level) => level.id === currentHarborLevelId)) {
          currentHarborLevelId = scopedLevels.length > 1 ? "all" : scopedLevels[0]?.id ?? "surface";
        }
      } else if (!runtime.scene.levels.some((level) => level.id === currentHarborLevelId)) {
        currentHarborLevelId = "surface";
      }
    }
    if (isV22Scene(currentScene)) await ensureV22Grid(currentScene);
    normalizeExperienceFocus();
    const root = await loadModel(sceneAsset(currentScene, currentMode));
    if (request !== loadSequence) return;
    restoreCutaway();
    modelHolder.clear();
    currentRoot = root;
    modelHolder.add(root);
    buildSemanticCatalog(root);
    rebuildTacticalSurfaces();
    rebuildTokens();
    applyRenderTuning();
    applyLayerFilter();
    if (sceneChanged) {
      const saved = cameraStates.get(currentScene);
      if (saved) applyCameraState(saved);
      else fitView();
    } else if (camera.position.lengthSq() === 0) {
      resetView();
    }
    updateUi();
    hideLoading();
  } catch (error) {
    if (request !== loadSequence) return;
    currentRoot = null;
    modelHolder.clear();
    clearTokenObjects();
    const message = error instanceof Error ? error.message : String(error);
    showLoading(message, true);
    console.error(error);
  }
}

sceneButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const next = button.dataset.scene as SceneKey;
    if (next === currentScene) return;
    void activateScene(next, next === "church" ? currentMode : "dm", true);
  });
});

modeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const next = button.dataset.mode as ViewMode;
    const playerRuntime = isRuntimeScene(currentScene) && RUNTIME_SCENES[currentScene].supportsPlayer;
    if ((currentScene !== "church" && !isV22Scene(currentScene) && !playerRuntime) || next === currentMode) return;
    void activateScene(currentScene, next, false);
  });
});

experienceButtons.forEach((button) => {
  button.addEventListener("click", () => setExperienceMode(button.dataset.experience as ExperienceMode));
});

[dmCutawayEnabled, dmCutawayOpacity, dmGridOpacity, dmFogDensity, dmExposure, dmTokenScale, dmShowDmOnly, dmShowHotspots].forEach((control) => {
  control.addEventListener("input", updateDmTuningFromControls);
  control.addEventListener("change", updateDmTuningFromControls);
});
dmQuality.addEventListener("change", updateDmTuningFromControls);

fitButton.addEventListener("click", fitView);
resetButton.addEventListener("click", resetView);
cityReturn.addEventListener("click", () => setCityScope("outdoor"));
canvas.addEventListener("pointerdown", (event) => {
  if (event.button === 0) pointerDown = { x: event.clientX, y: event.clientY };
});
canvas.addEventListener("pointerup", (event) => {
  if (!pointerDown || event.button !== 0) return;
  const distance = Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y);
  pointerDown = null;
  if (distance <= 5) pick(event);
});
canvas.addEventListener("pointercancel", () => { pointerDown = null; });

function resize(): void {
  const width = Math.max(1, viewport.clientWidth);
  const height = Math.max(1, viewport.clientHeight);
  renderer.setPixelRatio(pixelRatioForPreset());
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

const resizeObserver = new ResizeObserver(resize);
resizeObserver.observe(viewport);
window.addEventListener("resize", resize);
resize();
resetView();

let statStarted = performance.now();
let statFrames = 0;
renderer.setAnimationLoop((time) => {
  controls.update();
  updateCutaway(time);
  renderer.render(world, camera);
  statFrames += 1;
  const elapsed = time - statStarted;
  if (elapsed >= 750) {
    const fps = Math.round((statFrames * 1000) / elapsed);
    const info = renderer.info.render;
    lastFrameFps = fps;
    renderStats.textContent = `${fps} FPS · ${info.calls} calls · ${info.triangles.toLocaleString()} tris`;
    updateDebugReadout();
    statFrames = 0;
    statStarted = time;
  }
});

void activateScene("church", "dm", false);
