/**
 * Types mirroring the backend's `/api/v1` response shapes.
 *
 * These are hand-written rather than generated so that the console compiles
 * with `strict` on and so every field the UI relies on is explicit. Anything
 * genuinely open-ended (config values, explanation payloads) stays `unknown`
 * and is narrowed at the point of use.
 */

export interface PageMeta {
  total: number;
  limit: number;
  offset: number;
}

export interface Paged<T> {
  items: T[];
  meta: PageMeta;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface SessionUser {
  id: string;
  email: string;
  full_name: string;
  status: string;
  roles: string[];
  permissions: string[];
  last_login_at: string | null;
  password_changed_at: string | null;
}

export interface LoginResponse {
  tokens: TokenPair;
  user: SessionUser;
}

export interface Personnel {
  id: string;
  call_sign: string;
  name: string;
  age: number;
  unit: string;
  rank: string | null;
  status: string;
  baseline_heart_rate: number;
  baseline_spo2: number;
  sim_scenario: string | null;
  notes: string | null;
  is_simulated: boolean;
  created_at: string;
  updated_at: string;
}

/** Roster row: personnel plus the latest digital-twin projection. */
export interface PersonnelSummary extends Personnel {
  risk_score: number | null;
  risk_category: string | null;
  open_alert_count: number;
  is_stale: boolean;
  last_reading_at: string | null;
  latest_vitals: Record<string, number> | null;
}

export interface RosterSummary {
  items: PersonnelSummary[];
  total: number;
  by_status: Record<string, number>;
  by_risk: Record<string, number>;
  disclaimer: string;
}

export interface VitalReading {
  id: number;
  personnel_id: string;
  recorded_at: string;
  heart_rate: number;
  spo2: number;
  body_temp_c: number;
  respiratory_rate: number;
  bp_systolic: number;
  bp_diastolic: number;
  altitude_m: number;
  fatigue_score: number;
  activity_level: string;
  env_temp_c: number;
  wind_kph: number;
  latitude: number;
  longitude: number;
  grid_x: number | null;
  grid_y: number | null;
  source: string;
  scenario: string | null;
}

/** One weighted factor from the transparent rule engine. */
export interface RiskFactor {
  feature: string;
  label: string;
  severity: number;
  weight: number;
  contribution: number;
  direction: string;
  value: number | null;
  detail: string;
}

export interface RiskFactorsPayload {
  factors: RiskFactor[];
  top_factors: RiskFactor[];
  trends: Record<string, number>;
  max_possible_score: number;
}

export interface RiskAssessment {
  id: string;
  personnel_id: string;
  vital_reading_id: number | null;
  risk_score: number;
  category: string;
  engine: string;
  factors: RiskFactorsPayload;
  config_version: number;
  created_at: string;
}

/** One channel's attribution from a model explanation. */
export interface FeatureContribution {
  feature: string;
  label: string;
  value: number;
  contribution: number;
  direction: string;
}

export interface ContributionsPayload {
  method: string;
  method_description: string;
  contributions: FeatureContribution[];
  top_contributions: FeatureContribution[];
  /** Prose explanation composed by the backend explainer (a single paragraph). */
  narrative: string;
  class_probabilities: Record<string, number>;
  attention: number[] | null;
  fallback_reason: string | null;
}

export interface Prediction {
  id: string;
  personnel_id: string;
  model_name: string;
  model_version: string;
  horizon_minutes: number;
  risk_probability: number;
  predicted_category: string;
  contributions: ContributionsPayload;
  explanation_method: string;
  data_provenance: string;
  sequence_length: number | null;
  inference_ms: number | null;
  trajectory: Record<string, unknown> | null;
  created_at: string;
}

export interface ModelDescription {
  name: string;
  version: string;
  available: boolean;
  explanation_method: string;
  horizon_minutes: number;
  sequence_length: number;
  data_provenance: string;
  metrics: Record<string, unknown> | null;
  unavailable_reason: string | null;
}

export interface Alert {
  id: string;
  personnel_id: string | null;
  alert_type: string;
  severity: string;
  title: string;
  reason: string;
  recommended_action: string;
  triggering_data: Record<string, unknown>;
  status: string;
  dedup_key: string;
  occurrence_count: number;
  escalated_from: string | null;
  acknowledged_by_id: string | null;
  acknowledged_at: string | null;
  resolved_by_id: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
  last_triggered_at: string;
  created_at: string;
}

export interface AlertSummary {
  open: number;
  by_severity: Record<string, number>;
  by_type_24h: Record<string, number>;
  critical: Alert[];
}

export interface TwinRiskState {
  score: number;
  category: string;
  raw_ratio: number;
  scale_ratio: number;
  top_factors: RiskFactor[];
  all_factors: RiskFactor[];
  trends: Record<string, number>;
  recommended_action: string;
}

export interface TwinPredictionState {
  model_name: string;
  model_version: string;
  risk_probability: number;
  predicted_category: string;
  horizon_minutes: number;
  explanation_method: string;
  data_provenance: string;
  /** Prose explanation composed by the backend explainer (a single paragraph). */
  narrative: string;
  recommended_action: string;
  top_contributions: FeatureContribution[];
  class_probabilities?: Record<string, number>;
  attention?: number[] | null;
  inference_ms?: number | null;
}

export interface TwinState {
  personnel: {
    id: string;
    call_sign: string;
    name: string;
    age: number;
    unit: string;
    rank: string | null;
    status: string;
    baseline_heart_rate: number;
    baseline_spo2: number;
  };
  vitals: {
    recorded_at: string;
    age_seconds: number;
    heart_rate: number;
    spo2: number;
    body_temp_c: number;
    respiratory_rate: number;
    bp_systolic: number;
    bp_diastolic: number;
    fatigue_score: number;
    activity_level: string;
    deltas: Record<string, number>;
  };
  environment: {
    env_temp_c: number;
    wind_kph: number;
    altitude_m: number;
    wind_chill_note: string;
  };
  location: {
    latitude: number;
    longitude: number;
    grid_x: number | null;
    grid_y: number | null;
    altitude_m: number;
  };
  risk: TwinRiskState;
  prediction: TwinPredictionState | null;
  alerts: {
    open_count: number;
    highest_severity: string | null;
    recent: {
      id: string;
      severity: string;
      alert_type: string;
      title: string;
      reason: string;
      status: string;
      occurrence_count: number;
      created_at: string;
    }[];
  };
  history: {
    samples: number;
    series: {
      recorded_at: string;
      heart_rate: number;
      spo2: number;
      respiratory_rate: number;
      body_temp_c: number;
      fatigue_score: number;
      altitude_m: number;
      [key: string]: string | number;
    }[];
  };
  provenance: {
    source: string;
    scenario: string | null;
    is_simulated: boolean;
    disclaimer: string;
  };
  updated_at: string;
}

export interface DigitalTwin {
  personnel_id: string;
  call_sign: string;
  risk_score: number | null;
  risk_category: string | null;
  open_alert_count: number;
  is_stale: boolean;
  updated_at: string | null;
  state: TwinState;
}

export interface PersonnelDetail {
  personnel: PersonnelSummary;
  readings: VitalReading[];
  risk_history: RiskAssessment[];
  predictions: Prediction[];
  open_alerts: Alert[];
  twin: DigitalTwin | null;
}

export interface TerrainMap {
  id: string;
  name: string;
  width: number;
  height: number;
  cell_size_m: number;
  origin_lat: number;
  origin_lon: number;
  seed: number;
  min_elevation_m: number;
  max_elevation_m: number;
  is_synthetic: boolean;
  created_at: string;
}

export interface TerrainGrid {
  map: TerrainMap;
  elevation: number[][];
  avalanche: number[][];
  crevasse: number[][];
  weather: number[][];
  difficulty: number[][];
  blocked: boolean[][];
  terrain_type: string[][];
  legend: Record<string, unknown>;
  is_synthetic: boolean;
}

/** The API encodes path nodes as objects, not tuples. */
export interface PathNode {
  x: number;
  y: number;
}

export interface RouteCalculation {
  id?: string;
  route_id?: string;
  profile: string;
  cost_config: Record<string, unknown>;
  path: PathNode[];
  found: boolean;
  distance_m: number;
  ascent_m: number;
  descent_m: number;
  estimated_minutes: number;
  total_cost: number;
  risk_score: number;
  max_cell_risk: number;
  avoided_hazards: Record<string, unknown>;
  nodes_expanded: number;
  compute_ms: number;
  explanation: { summary?: string[]; [key: string]: unknown };
  created_at?: string;
}

export interface RoutePlanResponse {
  route: { id: string; name: string; calculations: RouteCalculation[] } | null;
  safest: RouteCalculation;
  shortest: RouteCalculation | null;
  comparison: {
    profiles: string[];
    delta: Record<string, number>;
    optimality_note: string;
  };
  hazard_alerts: { action: string; alert_id: string | null; title: string; severity: string }[];
  is_synthetic_terrain: boolean;
  map: { id: string; name: string; width: number; height: number; cell_size_m: number };
}

export interface Drone {
  id: string;
  call_sign: string;
  model: string;
  status: string;
  comms_status: string;
  battery_pct: number;
  altitude_m: number;
  heading_deg: number;
  speed_mps: number;
  signal_strength: number;
  grid_x: number;
  grid_y: number;
  latitude: number;
  longitude: number;
  waypoint_index: number;
  under_jamming: boolean;
  under_spoofing: boolean;
  reported_grid_x: number | null;
  reported_grid_y: number | null;
  autonomous_mode: boolean;
  mission_id: string | null;
  last_telemetry_at: string | null;
  is_simulated: boolean;
}

export interface SwarmStatus {
  drones: Drone[];
  formation: string;
  counts: Record<string, number>;
  mission: { id: string; name: string; formation: string; status: string } | null;
  recent_events: DroneEvent[];
  is_simulated: boolean;
  notice: string;
}

export interface DroneEvent {
  id: number;
  drone_id: string;
  event_type: string;
  severity: string;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface SecurityEvent {
  id: string;
  event_type: string;
  severity: string;
  origin: string;
  source: string;
  title: string;
  description: string;
  status: string;
  response_action: string | null;
  actor_user_id: string | null;
  subject_email: string | null;
  drone_id: string | null;
  ip: string | null;
  request_id: string | null;
  payload: Record<string, unknown>;
  handled_by_id: string | null;
  handled_at: string | null;
  created_at: string;
}

export interface SecurityPosture {
  open_events: number;
  by_severity: Record<string, number>;
  by_origin: Record<string, number>;
  failed_logins_24h: number;
  locked_accounts: number;
  recent: SecurityEvent[];
  controls: { control: string; status: string; detail: string }[];
}

export interface CryptoDemoResult {
  algorithm: string;
  label: string;
  notice: string;
  key_bits: number;
  nonce_bits: number;
  plaintext_length: number;
  ciphertext_b64: string;
  nonce_b64: string;
  key_b64: string;
  ciphertext_length: number;
  tag_bytes: number;
  aad: string | null;
  decrypted_matches_input: boolean;
  tamper_test: Record<string, unknown>;
  encrypt_ms: number;
  decrypt_ms: number;
}

export interface SimulationStatus {
  status: string;
  run_id: string | null;
  scenario: string | null;
  seed: number | null;
  speed: number;
  tick_count: number;
  sim_clock_seconds: number;
  sim_clock_iso: string | null;
  wall_started_at: string | null;
  last_tick_at: string | null;
  tick_seconds: number;
  sim_seconds_per_tick: number;
  tracked_personnel: number;
  tracked_drones: number;
  readings_emitted: number;
  alerts_raised: number;
  last_tick_duration_ms: number;
  scenario_assignments: Record<string, string>;
  available_scenarios: { code: string; label: string; description: string }[];
  is_simulated: boolean;
}

export interface DashboardSummary {
  generated_at: string;
  personnel_total: number;
  personnel_active: number;
  risk_distribution: Record<string, number>;
  average_risk: number;
  highest_risk: TwinSummary | null;
  open_alerts: number;
  alerts_by_severity: Record<string, number>;
  critical_alerts: Alert[];
  watchlist: TwinSummary[];
  drones: {
    total: number;
    by_status: Record<string, number>;
    by_comms: Record<string, number>;
    jammed: number;
    spoofed: number;
    autonomous: number;
    mean_battery_pct: number;
    is_simulated: boolean;
  };
  security: {
    open_events: number;
    by_severity: Record<string, number>;
    by_origin: Record<string, number>;
    failed_logins_24h: number;
    locked_accounts: number;
  };
  simulation: SimulationStatus;
  environment: {
    base_temp_c: number;
    wind_kph: number;
    front_intensity: number;
    visibility_km: number;
  } | null;
  prediction_models: { name: string; version: string; [key: string]: unknown }[];
  disclaimer: Record<string, string>;
}

/** Compact digital-twin projection used by the dashboard and roster. */
export interface TwinSummary {
  personnel_id: string;
  call_sign: string | null;
  name: string | null;
  unit: string | null;
  status: string | null;
  risk_score: number | null;
  risk_category: string | null;
  open_alert_count: number;
  heart_rate: number | null;
  spo2: number | null;
  altitude_m: number | null;
  grid_x: number | null;
  grid_y: number | null;
  predicted_category: string | null;
  risk_probability: number | null;
  model_name: string | null;
  is_stale: boolean;
  updated_at: string | null;
}

export interface ModelComparisonEntry {
  model: string;
  n_samples: number | null;
  accuracy: number;
  macro_f1: number;
  weighted_f1: number | null;
  macro_precision: number | null;
  macro_recall: number | null;
  elevated_f1: number | null;
  elevated_precision: number | null;
  elevated_recall: number | null;
  elevated_roc_auc: number | null;
  brier_score_elevated: number | null;
  per_class: Record<string, { precision: number; recall: number; f1: number; support: number }>;
  confusion_matrix: number[][] | null;
  confusion_matrix_labels: string[] | null;
  note: string;
}

export interface ModelComparison {
  models: ModelComparisonEntry[];
  source: string;
  caveats: string[];
}

export interface RiskTimelineBucket {
  bucket: string;
  mean_risk: number;
  max_risk: number;
  samples: number;
}

export interface AlertTimelineBucket {
  bucket: string;
  total: number;
  [severity: string]: string | number;
}

export interface TopRiskFactor {
  key: string;
  label: string;
  total_contribution: number;
  mean_contribution: number;
  occurrences: number;
}

export interface VitalsCorrelation {
  channel: string;
  label: string;
  pearson_r: number | null;
  samples: number;
  note: string;
}

export interface PerPersonAnalytics {
  personnel_id: string;
  call_sign: string;
  samples: number;
  mean_risk: number;
  peak_risk: number;
  latest_risk: number;
  scenario: string | null;
}

export interface Analytics {
  window_hours: number;
  generated_at: string;
  readings: number;
  risk_timeline: RiskTimelineBucket[];
  risk_distribution: Record<string, number>;
  alert_timeline: AlertTimelineBucket[];
  alerts_by_type: Record<string, number>;
  mean_time_to_acknowledge_seconds: number | null;
  top_risk_factors: TopRiskFactor[];
  vitals_correlation: VitalsCorrelation[];
  model_comparison: ModelComparisonEntry[];
  model_metrics_source: string;
  per_person: PerPersonAnalytics[];
  disclaimer: Record<string, string>;
}

export interface AuditLog {
  id: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  actor_user_id: string | null;
  actor_email: string | null;
  result: string;
  ip: string | null;
  user_agent: string | null;
  request_id: string | null;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface AdminUser {
  id: string;
  email: string;
  full_name: string;
  status: string;
  roles: string[];
  failed_login_count: number;
  locked_until: string | null;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConfigEntry {
  key: string;
  value: unknown;
  default_value: unknown;
  description: string;
  version: number;
  is_editable: boolean;
  is_customised: boolean;
  updated_at: string | null;
}

export interface ServiceMeta {
  name: string;
  version: string;
  team: string;
  tagline: string;
  prototype_status: string;
  data_mode: string;
  validation_status: string;
  capabilities: Record<string, boolean>;
  disclaimer: Record<string, string>;
}

export interface HealthStatus {
  status: string;
  version: string;
  environment: string;
  database: string;
  event_bus: string;
  ml_models: Record<string, unknown>;
  simulation: string;
  uptime_seconds: number;
  disclaimer: Record<string, string>;
}

export interface ModelInfo {
  name: string;
  version: string;
  trained_at: string | null;
  classes: string[];
  horizon_minutes: number;
  explainability: string;
  metrics?: Record<string, unknown> | null;
  is_trained: boolean;
  notes?: string | null;
}

/** Envelope pushed over the WebSocket stream. */
export type WsFrame =
  | {
      type: 'connection.ready';
      topics: string[];
      backend: string;
      user: { id: string; email: string; roles: string[] };
      server_time: string;
      is_simulated: boolean;
    }
  | { type: 'snapshot'; payload: DashboardSummary }
  | { type: 'event'; topic: string; event: string; payload: Record<string, unknown>; ts: string }
  | { type: 'heartbeat'; server_time: string }
  | { type: 'pong'; server_time: string }
  | { type: 'subscribed'; topics: string[] }
  | { type: 'notice'; message: string }
  | { type: 'error'; message: string };
