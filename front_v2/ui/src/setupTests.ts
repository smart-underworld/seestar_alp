import "@testing-library/jest-dom";
import { vi } from "vitest";
import { readable, writable } from "svelte/store";

// Mock svelte-spa-router so components using `use:link` and `$location` don't error.
vi.mock("svelte-spa-router", () => ({
  default: vi.fn(),
  link: () => ({ destroy: () => {} }),
  location: readable("/"),
  push: vi.fn(),
  pop: vi.fn(),
  replace: vi.fn(),
}));
