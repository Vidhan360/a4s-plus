import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { RiskBadge } from '@/components/domain/risk-badge';

describe('RiskBadge', () => {
  it('renders the category and rounded score', () => {
    render(<RiskBadge category="HIGH" score={72.4} />);
    expect(screen.getByText('HIGH')).toBeInTheDocument();
    expect(screen.getByText('72')).toBeInTheDocument();
  });

  it('exposes the precise score in the tooltip title', () => {
    const { container } = render(<RiskBadge category="CRITICAL" score={91.25} />);
    expect(container.firstElementChild).toHaveAttribute('title', 'Risk score 91.3/100');
  });

  it('says "No data" instead of implying a low risk when the category is absent', () => {
    // Rendering an absent category as LOW would be a data-honesty failure:
    // "we have not assessed this person" is not the same as "this person is fine".
    render(<RiskBadge category={null} />);
    expect(screen.getByText('No data')).toBeInTheDocument();
  });

  it('omits the score entirely when none is supplied', () => {
    const { container } = render(<RiskBadge category="LOW" />);
    expect(screen.getByText('LOW')).toBeInTheDocument();
    expect(container.querySelector('.tabular-nums')).toBeNull();
    expect(container.firstElementChild).not.toHaveAttribute('title');
  });

  it('only animates for a critical category, and only when asked', () => {
    const { container: critical } = render(<RiskBadge category="CRITICAL" pulse />);
    expect(critical.firstElementChild?.className).toContain('animate-pulse-ring');

    const { container: high } = render(<RiskBadge category="HIGH" pulse />);
    expect(high.firstElementChild?.className).not.toContain('animate-pulse-ring');
  });

  it('accepts lower-case categories from the API', () => {
    render(<RiskBadge category="moderate" score={40} />);
    expect(screen.getByText('moderate')).toBeInTheDocument();
  });
});
