import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// jsdom does not implement window.matchMedia — provide a minimal stub
// so next-themes and other media-query-dependent code can run in tests.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

// jsdom has no BroadcastChannel. Provide a deterministic in-memory one that
// delivers synchronously to other open instances of the same name (excluding
// the sender), so presentation-sync tests don't depend on event-loop timing.
class MemoryBroadcastChannel {
  static channels = new Map<string, Set<MemoryBroadcastChannel>>();
  name: string;
  onmessage: ((e: MessageEvent) => void) | null = null;
  constructor(name: string) {
    this.name = name;
    const set = MemoryBroadcastChannel.channels.get(name) ?? new Set();
    set.add(this);
    MemoryBroadcastChannel.channels.set(name, set);
  }
  postMessage(data: unknown) {
    for (const ch of MemoryBroadcastChannel.channels.get(this.name) ?? []) {
      if (ch !== this && ch.onmessage) ch.onmessage({ data } as MessageEvent);
    }
  }
  close() {
    MemoryBroadcastChannel.channels.get(this.name)?.delete(this);
  }
}
(globalThis as unknown as { BroadcastChannel: unknown }).BroadcastChannel =
  MemoryBroadcastChannel;

afterEach(() => cleanup());
