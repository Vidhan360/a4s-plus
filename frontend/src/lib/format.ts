import { format, formatDistanceToNowStrict, parseISO } from 'date-fns';

/** Parse an API timestamp, tolerating both `Z` and offset forms. */
export function parseTs(value: string | null | undefined): Date | null {
  if (!value) return null;
  try {
    const parsed = parseISO(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  } catch {
    return null;
  }
}

export function formatDateTime(value: string | null | undefined): string {
  const parsed = parseTs(value);
  return parsed ? format(parsed, 'dd MMM yyyy HH:mm:ss') : '—';
}

export function formatTime(value: string | null | undefined): string {
  const parsed = parseTs(value);
  return parsed ? format(parsed, 'HH:mm:ss') : '—';
}

export function formatRelative(value: string | null | undefined): string {
  const parsed = parseTs(value);
  if (!parsed) return '—';
  return `${formatDistanceToNowStrict(parsed)} ago`;
}

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatInt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return Math.round(value).toLocaleString();
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—';
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`;
  if (m > 0) return `${m}m ${String(s).padStart(2, '0')}s`;
  return `${s}s`;
}

export function titleCase(value: string): string {
  return value
    .toLowerCase()
    .split(/[\s_]+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/** Human label for a feature/vital key coming from the backend. */
const FEATURE_LABELS: Record<string, string> = {
  spo2: 'SpO₂',
  heart_rate: 'Heart rate',
  body_temp_c: 'Body temperature',
  respiratory_rate: 'Respiratory rate',
  bp_systolic: 'Systolic BP',
  bp_diastolic: 'Diastolic BP',
  altitude_m: 'Altitude',
  fatigue_score: 'Fatigue',
  env_temp_c: 'Ambient temperature',
  wind_kph: 'Wind speed',
  exertion: 'Exertion',
  d_heart_rate: 'Heart-rate trend',
  d_spo2: 'SpO₂ trend',
  d_respiratory_rate: 'Respiratory-rate trend',
  d_altitude_m: 'Altitude trend',
  d_fatigue_score: 'Fatigue trend',
};

export function featureLabel(key: string): string {
  return FEATURE_LABELS[key] ?? titleCase(key);
}

const UNITS: Record<string, string> = {
  spo2: '%',
  heart_rate: 'bpm',
  body_temp_c: '°C',
  respiratory_rate: '/min',
  bp_systolic: 'mmHg',
  bp_diastolic: 'mmHg',
  altitude_m: 'm',
  env_temp_c: '°C',
  wind_kph: 'km/h',
};

export function unitFor(key: string): string {
  return UNITS[key] ?? '';
}
