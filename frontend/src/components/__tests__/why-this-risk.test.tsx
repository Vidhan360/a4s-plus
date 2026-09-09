import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { WhyThisRisk } from '@/components/domain/why-this-risk';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { RiskFactor, TwinRiskState } from '@/lib/types';

function factor(overrides: Partial<RiskFactor>): RiskFactor {
  return {
    feature: 'spo2',
    label: 'SpO₂ 78% — severe hypoxaemia',
    severity: 0.9,
    weight: 30,
    contribution: 27,
    direction: 'below',
    value: 78,
    detail: 'Saturation is far below the 90% reference floor for this altitude band.',
    ...overrides,
  };
}

function riskState(overrides: Partial<TwinRiskState> = {}): TwinRiskState {
  const factors = [
    factor({}),
    factor({
      feature: 'heart_rate',
      label: 'Heart rate 142 bpm',
      severity: 0.6,
      weight: 20,
      contribution: 12,
      value: 142,
      detail: 'Sustained tachycardia relative to this soldier’s baseline.',
    }),
    factor({
      feature: 'body_temp_c',
      label: 'Body temperature 36.6 °C',
      severity: 0,
      weight: 15,
      contribution: 0,
      value: 36.6,
      detail: 'Within the reference band.',
    }),
  ];
  return {
    score: 78,
    category: 'CRITICAL',
    raw_ratio: 0.39,
    scale_ratio: 2,
    top_factors: factors.slice(0, 2),
    all_factors: factors,
    trends: { spo2: -3.4, heart_rate: 8 },
    recommended_action: 'Initiate descent and administer supplemental oxygen.',
    ...overrides,
  };
}

function renderPanel(state: TwinRiskState) {
  return render(
    <TooltipProvider>
      <WhyThisRisk risk={state} />
    </TooltipProvider>,
  );
}

describe('WhyThisRisk', () => {
  it('shows the exact weight × severity arithmetic for each contributing factor', () => {
    renderPanel(riskState());
    const panel = screen.getByTestId('why-this-risk');
    expect(panel).toHaveTextContent('severity 0.90 × weight 30.0 = 27.00');
    expect(panel).toHaveTextContent('severity 0.60 × weight 20.0 = 12.00');
  });

  it('hides factors that contribute nothing rather than padding the list', () => {
    renderPanel(riskState());
    expect(screen.queryByText(/Body temperature 36.6/)).toBeNull();
  });

  it('discloses the raw ratio and calibration used to reach the 0–100 score', () => {
    renderPanel(riskState());
    const panel = screen.getByTestId('why-this-risk');
    expect(panel).toHaveTextContent('0.390');
    expect(panel).toHaveTextContent('2.00');
  });

  it('renders the recommended action and short-window trends', () => {
    renderPanel(riskState());
    expect(
      screen.getByText('Initiate descent and administer supplemental oxygen.'),
    ).toBeInTheDocument();
    expect(screen.getByText(/spo2 -3.40/)).toBeInTheDocument();
    expect(screen.getByText(/heart_rate \+8.00/)).toBeInTheDocument();
  });

  it('explains an all-clear state instead of rendering an empty chart', () => {
    renderPanel(
      riskState({
        score: 4,
        category: 'LOW',
        all_factors: [factor({ contribution: 0, severity: 0 })],
        top_factors: [],
        trends: {},
      }),
    );
    expect(
      screen.getByText(/No vital is outside its reference band/),
    ).toBeInTheDocument();
  });
});
