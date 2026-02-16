/**
 * Tests for parseForkProposal function.
 *
 * These are basic unit tests for the parsing logic.
 */

import { parseForkProposal } from './ForkProposalTurn';

// Test helper for creating balloons-tool content
function wrapInBalloonsToolTag(json: object): string {
  return `<balloons-tool>\n${JSON.stringify(json, null, 2)}\n</balloons-tool>`;
}

// Basic parsing tests
const testCases = [
  {
    name: 'parses basic fork proposal',
    content: wrapInBalloonsToolTag({
      name: 'propose_fork',
      args: {
        name: 'implement-feature',
        description: 'Implement the new feature',
        context_plan: [
          { exchange_range: '0', mode: 'copy', reason: 'Requirements' },
          { exchange_range: '1-3', mode: 'compress', reason: 'Background' },
        ],
        initial_prompt: 'Let\'s start implementing...',
      },
    }),
    expected: {
      name: 'implement-feature',
      description: 'Implement the new feature',
      contextPlanLength: 2,
      initialPrompt: 'Let\'s start implementing...',
    },
  },
  {
    name: 'parses fork proposal with inherit binding',
    content: wrapInBalloonsToolTag({
      name: 'propose_fork',
      args: {
        name: 'continue-work',
        description: 'Continue the work',
        context_plan: [],
        bind_to: 'inherit',
      },
    }),
    expected: {
      name: 'continue-work',
      bindToInherit: true,
    },
  },
  {
    name: 'parses fork proposal with explicit binding',
    content: wrapInBalloonsToolTag({
      name: 'propose_fork',
      args: {
        name: 'impl-todo',
        description: 'Implement todo',
        context_plan: [],
        bind_to: {
          entity_type: 'todo',
          entity_id: 'abc123',
          role: 'implementation',
        },
      },
    }),
    expected: {
      name: 'impl-todo',
      bindToEntityType: 'todo',
      bindToEntityId: 'abc123',
      bindToRole: 'implementation',
    },
  },
  {
    name: 'returns null for non-fork tool',
    content: wrapInBalloonsToolTag({
      name: 'session_info',
      args: {},
    }),
    expected: null,
  },
  {
    name: 'returns null for invalid JSON',
    content: '<balloons-tool>{ invalid json }</balloons-tool>',
    expected: null,
  },
  {
    name: 'returns null for missing tag',
    content: 'Just some regular text without a tool call',
    expected: null,
  },
];

// Run tests
console.log('Running ForkProposalTurn parser tests...\n');
let passed = 0;
let failed = 0;

for (const tc of testCases) {
  const result = parseForkProposal(tc.content);

  let success = true;
  const errors: string[] = [];

  if (tc.expected === null) {
    if (result !== null) {
      success = false;
      errors.push(`Expected null but got: ${JSON.stringify(result)}`);
    }
  } else {
    if (result === null) {
      success = false;
      errors.push('Expected non-null result but got null');
    } else {
      if (tc.expected.name && result.name !== tc.expected.name) {
        success = false;
        errors.push(`name: expected "${tc.expected.name}", got "${result.name}"`);
      }
      if (tc.expected.description && result.description !== tc.expected.description) {
        success = false;
        errors.push(`description: expected "${tc.expected.description}", got "${result.description}"`);
      }
      if (tc.expected.contextPlanLength !== undefined && result.contextPlan.length !== tc.expected.contextPlanLength) {
        success = false;
        errors.push(`contextPlan length: expected ${tc.expected.contextPlanLength}, got ${result.contextPlan.length}`);
      }
      if (tc.expected.initialPrompt && result.initialPrompt !== tc.expected.initialPrompt) {
        success = false;
        errors.push(`initialPrompt: expected "${tc.expected.initialPrompt}", got "${result.initialPrompt}"`);
      }
      if (tc.expected.bindToInherit !== undefined && result.bindToInherit !== tc.expected.bindToInherit) {
        success = false;
        errors.push(`bindToInherit: expected ${tc.expected.bindToInherit}, got ${result.bindToInherit}`);
      }
      if (tc.expected.bindToEntityType && result.bindTo?.entityType !== tc.expected.bindToEntityType) {
        success = false;
        errors.push(`bindTo.entityType: expected "${tc.expected.bindToEntityType}", got "${result.bindTo?.entityType}"`);
      }
    }
  }

  if (success) {
    console.log(`\u2713 ${tc.name}`);
    passed++;
  } else {
    console.log(`\u2717 ${tc.name}`);
    for (const err of errors) {
      console.log(`  - ${err}`);
    }
    failed++;
  }
}

console.log(`\n${passed} passed, ${failed} failed`);

if (failed > 0) {
  process.exit(1);
}
