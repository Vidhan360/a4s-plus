import { describe, expect, it } from 'vitest';

import {
  featureLabel,
  formatDuration,
  formatInt,
  formatNumber,
  formatPercent,
  formatRelative,
  parseTs,
  titleCase,
} from '@/lib/format';

describe('parseTs', () => {
  it('parses Z-suffixed and offset timestamps', () => {
    expect(parseTs('2026-01-02T03:04:05Z')?.toISOString()).toBe('2026-01-02T03:04:05.000Z');
    expect(parseTs('2026-01-02T03:04:05+00:00')?.toISOString()).toBe('2026-01-02T03:04:05.000Z');
  });

  it('returns null for missing or unparseable values', () => {
    expect(parseTs(null)).toBeNull();
    expect(parseTs(undefined)).toBeNull();
    expect(parseTs('')).toBeNull();
    expect(parseTs('not a date')).toBeNull();
  });
});

describe('numeric formatters', () => {
  it('uses an em dash for absent values rather than 0 or NaN', () => {
    // Showing "0" for missing telemetry would be a data-honesty bug, not a
    // cosmetic one: an operator cannot distinguish "no reading" from "zero".
    for (const fn of [formatNumber, formatInt, formatPercent, formatDuration]) {
      expect(fn(null)).toBe('—');
      expect(fn(undefined)).toBe('—');
      expect(fn(Number.NaN)).toBe('—');
    }
  });

  it('formats numbers to a fixed precision', () => {
    expect(formatNumber(0.891342, 4)).toBe('0.8913');
    expect(formatNumber(12, 0)).toBe('12');
    expect(formatInt(1234.6)).toBe('1,235');
  });

  it('formats probabilities as percentages', () => {
    expect(formatPercent(0.9357, 2)).toBe('93.57%');
    expect(formatPercent(0)).toBe('0.0%');
  });

  it('formats durations across unit boundaries', () => {
    expect(formatDuration(0)).toBe('0s');
    expect(formatDuration(45)).toBe('45s');
    expect(formatDuration(125)).toBe('2m 05s');
    expect(formatDuration(3725)).toBe('1h 02m');
    expect(formatDuration(-5)).toBe('0s');
  });
});

describe('formatRelative', () => {
  it('describes a past instant relative to now', () => {
    const twoMinutesAgo = new Date(Date.now() - 120_000).toISOString();
    expect(formatRelative(twoMinutesAgo)).toMatch(/ago$/);
  });

  it('falls back to an em dash when there is no timestamp', () => {
    expect(formatRelative(null)).toBe('—');
  });
});

describe('label helpers', () => {
  it('title-cases snake_case enum values', () => {
    expect(titleCase('GRADUAL_DETERIORATION')).toBe('Gradual Deterioration');
    expect(titleCase('MEDICAL_OFFICER')).toBe('Medical Officer');
  });

  it('maps known feature keys to typographically correct labels', () => {
    expect(featureLabel('spo2')).toBe('SpO₂');
    expect(featureLabel('d_heart_rate')).toBe('Heart-rate trend');
  });

  it('falls back to title case for unknown feature keys', () => {
    expect(featureLabel('some_new_channel')).toBe('Some New Channel');
  });
});
