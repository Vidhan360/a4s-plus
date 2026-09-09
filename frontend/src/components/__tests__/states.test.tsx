import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { EmptyState, ErrorPanel, LoadingPanel } from '@/components/ui/states';
import { ApiError } from '@/lib/api-error';

describe('LoadingPanel', () => {
  it('announces itself to assistive technology', () => {
    render(<LoadingPanel label="Loading roster…" />);
    expect(screen.getByText('Loading roster…')).toBeInTheDocument();
  });
});

describe('EmptyState', () => {
  it('renders a title, description and optional action', () => {
    render(
      <EmptyState
        title="No alerts"
        description="The queue is clear."
        action={<button type="button">Refresh</button>}
      />,
    );
    expect(screen.getByText('No alerts')).toBeInTheDocument();
    expect(screen.getByText('The queue is clear.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
  });
});

describe('ErrorPanel', () => {
  it('presents a 403 as a permissions boundary, not a failure, and hides Retry', () => {
    const onRetry = vi.fn();
    render(
      <ErrorPanel
        error={new ApiError(403, 'forbidden', 'Missing permission security:simulate')}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByText('Your role does not include this view')).toBeInTheDocument();
    // Retrying a 403 can never succeed, so offering the button would be a lie.
    expect(screen.queryByRole('button', { name: /retry/i })).toBeNull();
  });

  it('offers a retry for transient failures and calls back when used', async () => {
    const onRetry = vi.fn();
    render(<ErrorPanel error={new ApiError(503, 'unavailable', 'Upstream down')} onRetry={onRetry} />);
    expect(screen.getByText('Could not load this panel')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('surfaces the request id so a failure can be traced in the audit log', () => {
    render(
      <ErrorPanel error={new ApiError(500, 'server_error', 'boom', null, 'req-abc123')} />,
    );
    expect(screen.getByText(/req-abc123/)).toBeInTheDocument();
  });

  it('uses the alert role so screen readers are notified', () => {
    render(<ErrorPanel error={new Error('offline')} />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('offline')).toBeInTheDocument();
  });
});
