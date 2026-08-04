import "./style.css";

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

type SceneKey = "church" | "underdark" | "city" | "harbor";
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
  type: "door" | "stairs" | "hatch" | "secret_door";
  visibility: "public" | "dm_only";
  cell_ids: [string, string];
}

interface GenericRuntimeNavEdge {
  a: string;
  b: string;
  kind: "walk" | "door" | "stairs" | "hatch" | "secret_door";
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
let currentScene: SceneKey = "church";
let currentMode: ViewMode = "dm";
let currentLayer: LayerFilter = "all";
let currentCityScope: CityScope = "outdoor";
let currentHarborFocus = "surface";
let currentHarborLevelId: string | "all" = "surface";
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
  viewerState.focusId = currentScene === "city" ? currentCityScope : currentScene === "harbor" ? currentHarborFocus : `${currentScene}:${currentLayer}`;
  viewerState.layer = currentScene === "harbor" ? currentHarborLevelId : currentLayer;
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
  if (harborCells.size === 0) {
    for (const cell of harbor.cells) harborCells.set(cell.id, cell);
    for (const edge of harbor.nav.edges) {
      harborNav.set(edge.a, [...(harborNav.get(edge.a) ?? []), edge]);
      harborNav.set(edge.b, [...(harborNav.get(edge.b) ?? []), edge]);
    }
    for (const connector of harbor.connectors) harborConnectors.set(connector.id, connector);
    for (const room of harbor.rooms ?? []) harborRooms.set(room.id, room);
  }
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
  if (sceneKey === "underdark") return "underdark-dm.glb";
  if (sceneKey === "city") return "city-dm.glb";
  if (sceneKey === "harbor") return "harbor-v2.glb";
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

function fitView(): void {
  if (!currentRoot) return;
  currentRoot.updateWorldMatrix(true, true);
  const box = new THREE.Box3();
  currentRoot.traverse((object) => {
    if (!(object instanceof THREE.Mesh) || !object.visible) return;
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
      levelIds: currentScene === "harbor" ? objectHarborLevelIds(object) : [],
      volumeIds: currentScene === "harbor" ? objectHarborVolumeIds(object) : [],
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
  return harborRuntime?.scene.levels.find((level) => level.id === levelId);
}

function harborWorldHeight(zBaseFt: number): number {
  return zBaseFt / (harborRuntime?.scene.grid.cell_size_ft ?? 5);
}

function harborObjectVisible(object: THREE.Mesh): boolean {
  const levelIds = objectHarborLevelIds(object);
  const volumeIds = objectHarborVolumeIds(object);
  const kind = objectMetadata(object, "prototype_kind");
  const pickRole = objectMetadata(object, "pick_role");
  if (!levelIds.length) return currentHarborFocus === "surface";
  if (currentHarborFocus === "surface") {
    if (levelIds.includes("surface")) return true;
    return kind === "wall" || kind === "roof" || kind === "door";
  }
  if (!volumeIds.includes(currentHarborFocus) || kind === "roof" || pickRole === "hideable") return false;
  return currentHarborLevelId === "all" || levelIds.includes(currentHarborLevelId);
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
  renderer.toneMappingExposure = dmTuning.exposure;
  if (world.fog instanceof THREE.FogExp2) world.fog.density = dmTuning.fogDensity;
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
    if (currentScene === "harbor") {
      setObjectFilteredVisible(object, harborObjectVisible(object));
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
  if (currentScene === "harbor") updateHarborTransitionHotspots();
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
        : currentScene === "harbor"
          ? objectMetadata(object, "pick_role") === "tactical_floor" || objectMetadata(object, "prototype_kind") === "floor"
          : object.name.startsWith("Terrain_Elevation_");
    if (tactical) tacticalSurfaces.push(object);
    const transition = currentScene === "city" && (
      objectMetadata(object, "pick_role") === "transition"
      || objectMetadata(object, "prototype_kind") === "door"
      || objectMetadata(object, "prototype_kind") === "stairs"
      || /^(Door|Stair)_/.test(object.name)
    );
    if (transition) transitionSurfaces.push(object);
    const harborTransition = currentScene === "harbor" && (
      objectMetadata(object, "pick_role") === "connector"
      || Boolean(objectMetadata(object, "connector_id"))
      || ["door", "stairs", "hatch", "secret_door"].includes(objectMetadata(object, "prototype_kind"))
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
  if (currentScene !== "harbor") return;
  for (const connector of harborRuntime?.connectors ?? []) {
    for (const cellId of connector.cell_ids) {
      const cell = harborCells.get(cellId);
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
    object.visible = currentScene === "harbor"
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
  return harborCells.get(`${levelId}:${row}:${col}`);
}

function harborFocusAllows(cell: GenericRuntimeCell): boolean {
  return currentHarborFocus === "surface" ? cell.level_id === "surface" : cell.volume_id === currentHarborFocus;
}

function harborReachable(startId: string, targetId: string): boolean {
  if (startId === targetId) return true;
  const start = harborCells.get(startId);
  const target = harborCells.get(targetId);
  if (!start || !target || !harborFocusAllows(start) || !harborFocusAllows(target)) return false;
  const visited = new Set<string>([startId]);
  const queue = [startId];
  for (let index = 0; index < queue.length; index += 1) {
    const current = queue[index];
    if (!current) continue;
    for (const edge of harborNav.get(current) ?? []) {
      if (edge.interaction_required || edge.connector_id || edge.kind !== "walk") continue;
      const next = edge.a === current ? edge.b : edge.a;
      const cell = harborCells.get(next);
      if (!cell || visited.has(next) || !harborFocusAllows(cell)) continue;
      if (next === targetId) return true;
      visited.add(next);
      queue.push(next);
    }
  }
  return false;
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
  if (currentScene === "harbor") {
    const levelId = objectHarborLevelId(hit.object) || (currentHarborFocus === "surface" ? "surface" : currentHarborLevelId === "all" ? "" : currentHarborLevelId);
    if (!levelId) return null;
    const cell = harborCellAt(levelId, row, col);
    if (!cell?.walkable || !harborFocusAllows(cell) || (cell.visibility === "dm_only" && (currentMode !== "dm" || !dmTuning.showDmOnly))) return null;
    return {
      row, col, layer: 0, levelId: cell.level_id, zBaseFt: cell.z_base_ft, volumeId: cell.volume_id,
      area: harborRooms.get(cell.room_id)?.name || cell.room_id || cell.surface, spaceKind: cell.volume_id ? "建筑内部" : "港区地表",
      walkable: true, movement: `消耗 ${cell.movement.walk ?? 1} · 5 尺`,
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
  if (currentScene === "harbor") return 0;
  return layer * UNDERDARK_ELEVATION_HEIGHT;
}

function showSelection(cell: CellSelection): void {
  const markerHeight = currentScene === "harbor" ? harborWorldHeight(cell.zBaseFt ?? 0) : groundHeight(cell.layer);
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
  if (currentScene === "harbor") {
    const level = harborLevel(cell.levelId ?? "");
    cellInspector.innerHTML = `
      <div><dt>坐标</dt><dd>row ${cell.row} · col ${cell.col}</dd></div>
      <div><dt>层级</dt><dd>${level?.label ?? cell.levelId ?? "—"} · ${cell.zBaseFt ?? 0} ft</dd></div>
      <div><dt>焦点</dt><dd>${cell.volumeId || "港区地表"}</dd></div>
      <div><dt>区域</dt><dd>${cell.area}</dd></div>
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
  } else if (sceneKey === "harbor") {
    const start = harborRuntime?.anchors.find((anchor) => anchor.id === "party_start");
    const cells = [...harborCells.values()]
      .filter((cell) => cell.walkable && cell.level_id === (start?.level_id ?? "surface"))
      .sort((a, b) => {
        const da = Math.abs(a.row - (start?.row ?? 0)) + Math.abs(a.col - (start?.col ?? 0));
        const db = Math.abs(b.row - (start?.row ?? 0)) + Math.abs(b.col - (start?.col ?? 0));
        return da - db || a.row - b.row || a.col - b.col;
      });
    states = cells.slice(0, TOKEN_NAMES.length).map((cell) => ({ row: cell.row, col: cell.col, layer: 0, levelId: cell.level_id, zBaseFt: cell.z_base_ft }));
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
    const height = currentScene === "harbor" ? harborWorldHeight(state.zBaseFt ?? 0) : groundHeight(state.layer);
    token.position.set(state.col + 0.5, height + 0.035, -state.row - 0.5);
    token.userData.tokenIndex = index;
    tokenHolder.add(token);
  });
  updateTokenVisibility();
  renderTokenList();
}

function tokenIsVisible(state: TokenState): boolean {
  if (currentScene === "harbor") {
    const cell = state.levelId ? harborCellAt(state.levelId, state.row, state.col) : undefined;
    return Boolean(cell && harborFocusAllows(cell) && (currentHarborLevelId === "all" || cell.level_id === currentHarborLevelId));
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
  if (currentScene === "city") {
    const start = cityCellAt(state.layer, state.row, state.col);
    const target = cityCellAt(cell.layer, cell.row, cell.col);
    if (!start || !target || !cityCellsReachable(start, target)) {
      showCityNotice("该格不可达：请沿同层道路移动，跨房间、建筑或楼层请使用门/楼梯");
      return;
    }
    clearCityNotice();
  }
  if (currentScene === "harbor") {
    const start = state.levelId ? harborCellAt(state.levelId, state.row, state.col) : undefined;
    const target = cell.levelId ? harborCellAt(cell.levelId, cell.row, cell.col) : undefined;
    if (!start || !target || !harborReachable(start.id, target.id)) {
      showCityNotice("该格不可达：港区移动严格遵循 runtime.nav.edges，门、楼梯与暗门需点击连接点");
      return;
    }
    state.levelId = target.level_id;
    state.zBaseFt = target.z_base_ft;
    clearCityNotice();
  }
  state.row = cell.row;
  state.col = cell.col;
  state.layer = cell.layer;
  object.position.set(cell.col + 0.5, currentScene === "harbor" ? harborWorldHeight(state.zBaseFt ?? 0) + 0.035 : groundHeight(cell.layer) + 0.035, -cell.row - 0.5);
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
  applyLayerFilter();
  updateUi();
  if (returningOutside && cityDistrictCameraState) applyCameraState(cityDistrictCameraState);
  else fitView();
  return true;
}

function harborConnectorForObject(object: THREE.Object3D): GenericRuntimeConnector | undefined {
  const connectorId = objectMetadata(object, "connector_id");
  if (connectorId) return harborConnectors.get(connectorId);
  return undefined;
}

function applyHarborConnector(connector: GenericRuntimeConnector): boolean {
  if (selectedToken === null) {
    showCityNotice("请先选择一个 Token，再移动到门、楼梯或暗门旁");
    return false;
  }
  const states = ensureTokenStates("harbor");
  const state = states[selectedToken];
  if (!state?.levelId) return false;
  const candidates = connector.cell_ids
    .map((id) => ({ id, cell: harborCells.get(id) }))
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
  const edge = targetId ? (harborNav.get(source.id) ?? []).find((item) => item.connector_id === connector.id && (item.a === targetId || item.b === targetId)) : undefined;
  const target = targetId ? harborCells.get(targetId) : undefined;
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
  if (currentScene === "harbor" && pickHarborTransition()) return;
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
    if (currentScene === "harbor") currentHarborLevelId = "all";
    else currentLayer = "all";
    return;
  }
  if (viewerState.experienceMode !== "tactical") return;
  if (currentScene === "church" && currentLayer === "all") currentLayer = 1;
  if (currentScene === "underdark" && currentLayer === "all") currentLayer = 0;
  if (currentScene === "city" && currentCityScope !== "outdoor" && currentLayer === "all") {
    currentLayer = cityBuildingById(currentCityScope)?.floors[0]?.floor_index ?? 1;
  }
  if (currentScene === "harbor" && currentHarborLevelId === "all") {
    const first = (harborRuntime?.scene.levels ?? []).find((level) => currentHarborFocus === "surface" ? level.id === "surface" : level.volume_id === currentHarborFocus);
    currentHarborLevelId = first?.id ?? "surface";
  }
}

function renderExperienceUi(): void {
  const theatre = viewerState.experienceMode === "theatre";
  experienceButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.experience === viewerState.experienceMode);
  });
  dmSettingsPanel.hidden = currentMode !== "dm";
  if (layerPanel) layerPanel.hidden = theatre;
  if (tokenPanel) tokenPanel.hidden = theatre;
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
  const navEdges = currentScene === "harbor" ? harborRuntime?.nav.edges.length ?? 0 : currentScene === "city" ? cityGrid?.transitions.length ?? 0 : 0;
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
  if (currentScene === "harbor") {
    const levels = (harborRuntime?.scene.levels ?? []).filter((level) => currentHarborFocus === "surface" ? level.id === "surface" : level.volume_id === currentHarborFocus);
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
  const active = currentScene === "harbor" && viewerState.experienceMode !== "theatre";
  harborFocusPanel.hidden = !active;
  if (!active) return;
  const levels = harborRuntime?.scene.levels ?? [];
  const volumeIds = [...new Set(levels.map((level) => level.volume_id).filter(Boolean))];
  const volumeNames = new Map((harborRuntime?.volumes ?? []).map((volume) => [volume.id, volume.name]));
  harborFocusNote.textContent = currentHarborFocus === "surface" ? "港区地表 · 查看模式" : `${volumeNames.get(currentHarborFocus) ?? currentHarborFocus} · 查看模式`;
  harborFocusControls.innerHTML = "";
  for (const focus of ["surface", ...volumeIds]) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `building-button${currentHarborFocus === focus ? " active" : ""}`;
    button.textContent = focus === "surface" ? "查看 · 港区地表" : `查看 · ${volumeNames.get(focus) ?? focus.replaceAll("_", " ")}`;
    button.addEventListener("click", () => setHarborFocus(focus));
    harborFocusControls.append(button);
  }
}

function setHarborFocus(focus: string): void {
  if (currentScene !== "harbor" || focus === currentHarborFocus) return;
  currentHarborFocus = focus;
  const levels = (harborRuntime?.scene.levels ?? []).filter((level) => focus === "surface" ? level.id === "surface" : level.volume_id === focus);
  currentHarborLevelId = levels[0]?.id ?? "all";
  clearCityNotice();
  clearCellSelection();
  applyLayerFilter();
  updateUi();
  fitView();
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
  const name = currentScene === "church" ? "教堂" : currentScene === "city" ? "城市街区" : currentScene === "harbor" ? "潮钟港区 V2" : "幽暗地域";
  const experience = viewerState.experienceMode === "theatre" ? "剧场" : viewerState.experienceMode === "exploration" ? "探索" : "战术";
  hudScene.textContent = `${name} · ${currentMode === "dm" ? "DM" : "玩家"} · ${experience}`;
  if ((currentScene === "city" || currentScene === "harbor") && cityNotice) {
    hudFilter.textContent = cityNotice;
    return;
  }
  if (currentScene === "harbor") {
    const level = currentHarborLevelId === "all" ? undefined : harborLevel(currentHarborLevelId);
    const levelLabel = level?.label ?? currentHarborLevelId;
    hudFilter.textContent = currentHarborLevelId === "all"
      ? `${currentHarborFocus} · 全层`
      : levelLabel.includes("ft") ? levelLabel : `${levelLabel} · ${level?.z_base_ft ?? 0} ft`;
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
  const harbor = currentScene === "harbor";
  sceneTitle.textContent = church ? churchSpec?.site.name ?? "圣烛教堂" : city ? citySpec?.name ?? "暮钟区 · 灰石街区" : harbor ? harborRuntime?.scene.name ?? "潮钟港区 · 塔影与暗渠" : "幽暗地域 · 紫晶裂谷";
  sceneDescription.textContent = church
    ? churchSpec?.site.brief ?? "三层建筑、房间、楼梯与 DM 隐藏密室。"
    : city ? "街道、广场与 7 栋可进入建筑；切换内部战术范围。" : harbor ? "地表、塔楼、暗渠与密室；移动严格读取 runtime 导航图。" : "48×36 格的裂谷、桥梁、高地、遗迹与菌林。";
  modeNote.textContent = church ? "独立模型 · 权限" : "当前仅 DM 资产";
  layerTitle.textContent = currentScene === "underdark" ? "高度" : harbor ? "层级" : "楼层";
  sceneButtons.forEach((button) => button.classList.toggle("active", button.dataset.scene === currentScene));
  modeButtons.forEach((button) => {
    const mode = button.dataset.mode as ViewMode;
    button.disabled = !church && mode === "player";
    button.title = !church && mode === "player" ? `${city ? "城市街区" : harbor ? "潮钟港区" : "幽暗地域"}当前没有独立玩家资产` : "";
    button.classList.toggle("active", mode === currentMode);
  });
  renderLayerControls();
  renderCityScopeControls();
  renderHarborFocusControls();
  renderExperienceUi();
  updateHud();
}

async function activateScene(sceneKey: SceneKey, mode: ViewMode, sceneChanged: boolean): Promise<void> {
  const request = ++loadSequence;
  if (sceneChanged) saveCameraState();
  currentScene = sceneKey;
  currentMode = sceneKey === "underdark" || sceneKey === "city" || sceneKey === "harbor" ? "dm" : mode;
  if (sceneChanged) {
    currentLayer = "all";
    if (sceneKey === "city") currentCityScope = "outdoor";
    if (sceneKey === "harbor") {
      currentHarborFocus = "surface";
      currentHarborLevelId = "surface";
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
    if (currentScene !== "church" || next === currentMode) return;
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
