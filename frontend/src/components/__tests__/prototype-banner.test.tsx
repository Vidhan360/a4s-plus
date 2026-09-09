import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PrototypeBanner } from '@/components/layout/prototype-banner';
import { DISCLAIMERS } from '@/lib/constants';

describe('PrototypeBanner', () => {
  it('states all three honesty labels', () => {
    render(<PrototypeBanner />);
    const banner = screen.getByTestId('prototype-banner');
    expect(banner).toHaveTextContent(DISCLAIMERS.prototype);
    expect(banner).toHaveTextContent(DISCLAIMERS.data);
    expect(banner).toHaveTextContent(DISCLAIMERS.validation);
  });

  it('cannot be dismissed', () => {
    // The disclaimer is a correctness requirement, not a notification, so the
    // component deliberately exposes no close affordance.
    render(<PrototypeBanner />);
    const banner = screen.getByTestId('prototype-banner');
    expect(banner.querySelectorAll('button')).toHaveLength(0);
  });
});
