// Preload for `bun test`:
//  - registers a happy-dom window so component tests (React Testing Library)
//    have document/window/localStorage
//  - registers jest-dom matchers (toBeInTheDocument, toHaveClass, ...) on
//    bun:test's expect
// Usage: bun test --preload ./happydom.ts
//
// IMPORTANT: happy-dom must be registered BEFORE any module that reads
// document at import time. @testing-library/jest-dom pulls in
// @testing-library/dom, whose `screen` binds to document.body at module
// evaluation. A static import here would be hoisted above register() and
// permanently bind `screen` to a body-less document, so the matchers are
// loaded via dynamic import after registration.
import { GlobalRegistrator } from '@happy-dom/global-registrator';

GlobalRegistrator.register();

// React 19 wants an explicit act() environment flag.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const { expect } = await import('bun:test');
const matchers = await import('@testing-library/jest-dom/matchers');
expect.extend(matchers as unknown as Parameters<typeof expect.extend>[0]);