import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

afterEach(() => cleanup());

// jsdom implements neither of these, and several components rely on them.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub;

// Recharts measures its container with offsetWidth/offsetHeight, which jsdom
// always reports as 0. Without this, every chart logs a width/height warning
// and renders nothing, which makes real assertion failures hard to spot.
for (const [prop, value] of [
  ['offsetWidth', 640],
  ['offsetHeight', 320],
] as const) {
  Object.defineProperty(HTMLElement.prototype, prop, {
    configurable: true,
    value,
  });
}
