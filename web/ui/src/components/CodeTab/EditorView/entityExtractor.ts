/**
 * Entity extraction from source code (regex-based fallback).
 *
 * This provides basic entity extraction when LSP is not available.
 * For production, prefer LSP-based extraction for accuracy.
 */

import type { CodeEntity, CodeRelation } from './types';

/** Extract entities from TypeScript/JavaScript code */
function extractTSEntities(content: string, filePath: string): CodeEntity[] {
  const entities: CodeEntity[] = [];
  const lines = content.split('\n');

  // Patterns for different constructs
  const patterns = [
    // Class declarations
    { regex: /^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)/, type: 'class' as const },
    // Interface declarations
    { regex: /^(?:export\s+)?interface\s+(\w+)/, type: 'interface' as const },
    // Type declarations
    { regex: /^(?:export\s+)?type\s+(\w+)\s*=/, type: 'type' as const },
    // Function declarations (including async)
    { regex: /^(?:export\s+)?(?:async\s+)?function\s+(\w+)/, type: 'function' as const },
    // Arrow function const
    { regex: /^(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(.*\)\s*(?::\s*\w+)?\s*=>/, type: 'function' as const },
    // Const declarations (simple values)
    { regex: /^(?:export\s+)?const\s+(\w+)\s*(?::\s*[^=]+)?\s*=\s*[^(]/, type: 'constant' as const },
  ];

  let currentClass: string | null = null;
  let braceDepth = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const trimmed = line.trim();

    // Skip empty lines and comments
    if (!trimmed || trimmed.startsWith('//') || trimmed.startsWith('/*') || trimmed.startsWith('*')) {
      continue;
    }

    // Track brace depth for class scope
    braceDepth += (line.match(/{/g) || []).length;
    braceDepth -= (line.match(/}/g) || []).length;

    // Reset class context when exiting
    if (braceDepth === 0 && currentClass) {
      currentClass = null;
    }

    // Try each pattern
    for (const { regex, type } of patterns) {
      const match = trimmed.match(regex);
      if (match && match[1]) {
        const name = match[1];
        const isExported = trimmed.startsWith('export');
        const isAsync = trimmed.includes('async ');

        // Check for methods inside classes
        if (currentClass && (type === 'function' || trimmed.match(/^\w+\s*\(.*\)\s*{/))) {
          entities.push({
            id: `${filePath}:${i + 1}:${name}`,
            name,
            type: 'method',
            filePath,
            lineStart: i + 1,
            lineEnd: i + 1, // Simplified - would need brace matching for accurate end
            language: 'typescript',
            parentId: `${filePath}:class:${currentClass}`,
            isAsync,
            isExported,
          });
        } else {
          entities.push({
            id: `${filePath}:${i + 1}:${name}`,
            name,
            type,
            filePath,
            lineStart: i + 1,
            lineEnd: i + 1,
            language: 'typescript',
            isAsync,
            isExported,
          });

          // Track class for method detection
          if (type === 'class') {
            currentClass = name;
          }
        }
        break; // Only match one pattern per line
      }
    }

    // Check for class methods (not caught by patterns)
    if (currentClass) {
      const methodMatch = trimmed.match(/^(?:async\s+)?(\w+)\s*\(.*\)\s*(?::\s*\w+)?\s*{/);
      if (methodMatch && methodMatch[1] && !['if', 'for', 'while', 'switch', 'catch'].includes(methodMatch[1])) {
        const name = methodMatch[1];
        const isAsync = trimmed.startsWith('async');

        // Don't duplicate if already added
        const existing = entities.find(e => e.name === name && e.lineStart === i + 1);
        if (!existing) {
          entities.push({
            id: `${filePath}:${i + 1}:${name}`,
            name,
            type: 'method',
            filePath,
            lineStart: i + 1,
            lineEnd: i + 1,
            language: 'typescript',
            parentId: `${filePath}:class:${currentClass}`,
            isAsync,
          });
        }
      }
    }
  }

  return entities;
}

/** Extract entities from Python code */
function extractPythonEntities(content: string, filePath: string): CodeEntity[] {
  const entities: CodeEntity[] = [];
  const lines = content.split('\n');

  let currentClass: string | null = null;
  let classIndent = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const trimmed = line.trim();
    const indent = line.length - line.trimStart().length;

    // Skip empty lines and comments
    if (!trimmed || trimmed.startsWith('#')) {
      continue;
    }

    // Class declaration
    const classMatch = trimmed.match(/^class\s+(\w+)/);
    if (classMatch && classMatch[1]) {
      currentClass = classMatch[1];
      classIndent = indent;
      entities.push({
        id: `${filePath}:${i + 1}:${currentClass}`,
        name: currentClass,
        type: 'class',
        filePath,
        lineStart: i + 1,
        lineEnd: i + 1,
        language: 'python',
      });
      continue;
    }

    // Function/method declaration
    const funcMatch = trimmed.match(/^(?:async\s+)?def\s+(\w+)/);
    if (funcMatch && funcMatch[1]) {
      const name = funcMatch[1];
      const isAsync = trimmed.startsWith('async');

      // Check if it's a method (inside a class, deeper indent)
      if (currentClass && indent > classIndent) {
        entities.push({
          id: `${filePath}:${i + 1}:${name}`,
          name,
          type: 'method',
          filePath,
          lineStart: i + 1,
          lineEnd: i + 1,
          language: 'python',
          parentId: `${filePath}:class:${currentClass}`,
          isAsync,
        });
      } else {
        // Top-level function
        currentClass = null; // Exit class scope
        entities.push({
          id: `${filePath}:${i + 1}:${name}`,
          name,
          type: 'function',
          filePath,
          lineStart: i + 1,
          lineEnd: i + 1,
          language: 'python',
          isAsync,
        });
      }
      continue;
    }

    // Reset class context when we see top-level code
    if (indent <= classIndent && currentClass && !trimmed.startsWith('@')) {
      currentClass = null;
    }
  }

  return entities;
}

/** Extract entities from Rust code */
function extractRustEntities(content: string, filePath: string): CodeEntity[] {
  const entities: CodeEntity[] = [];
  const lines = content.split('\n');

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const trimmed = line.trim();

    // Skip empty lines and comments
    if (!trimmed || trimmed.startsWith('//') || trimmed.startsWith('/*')) {
      continue;
    }

    // Struct
    const structMatch = trimmed.match(/^(?:pub\s+)?struct\s+(\w+)/);
    if (structMatch && structMatch[1]) {
      entities.push({
        id: `${filePath}:${i + 1}:${structMatch[1]}`,
        name: structMatch[1],
        type: 'class', // Treat struct as class
        filePath,
        lineStart: i + 1,
        lineEnd: i + 1,
        language: 'rust',
        isExported: trimmed.startsWith('pub'),
      });
      continue;
    }

    // Enum
    const enumMatch = trimmed.match(/^(?:pub\s+)?enum\s+(\w+)/);
    if (enumMatch && enumMatch[1]) {
      entities.push({
        id: `${filePath}:${i + 1}:${enumMatch[1]}`,
        name: enumMatch[1],
        type: 'type',
        filePath,
        lineStart: i + 1,
        lineEnd: i + 1,
        language: 'rust',
        isExported: trimmed.startsWith('pub'),
      });
      continue;
    }

    // Trait
    const traitMatch = trimmed.match(/^(?:pub\s+)?trait\s+(\w+)/);
    if (traitMatch && traitMatch[1]) {
      entities.push({
        id: `${filePath}:${i + 1}:${traitMatch[1]}`,
        name: traitMatch[1],
        type: 'interface',
        filePath,
        lineStart: i + 1,
        lineEnd: i + 1,
        language: 'rust',
        isExported: trimmed.startsWith('pub'),
      });
      continue;
    }

    // Function
    const fnMatch = trimmed.match(/^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)/);
    if (fnMatch && fnMatch[1]) {
      entities.push({
        id: `${filePath}:${i + 1}:${fnMatch[1]}`,
        name: fnMatch[1],
        type: 'function',
        filePath,
        lineStart: i + 1,
        lineEnd: i + 1,
        language: 'rust',
        isAsync: trimmed.includes('async '),
        isExported: trimmed.startsWith('pub'),
      });
      continue;
    }

    // Const
    const constMatch = trimmed.match(/^(?:pub\s+)?const\s+(\w+)/);
    if (constMatch && constMatch[1]) {
      entities.push({
        id: `${filePath}:${i + 1}:${constMatch[1]}`,
        name: constMatch[1],
        type: 'constant',
        filePath,
        lineStart: i + 1,
        lineEnd: i + 1,
        language: 'rust',
        isExported: trimmed.startsWith('pub'),
      });
      continue;
    }
  }

  return entities;
}

/**
 * Extract code entities from file content.
 * Falls back to empty array for unsupported languages.
 */
export function extractEntities(content: string, filePath: string, language: string): CodeEntity[] {
  switch (language.toLowerCase()) {
    case 'typescript':
    case 'javascript':
      return extractTSEntities(content, filePath);
    case 'python':
      return extractPythonEntities(content, filePath);
    case 'rust':
      return extractRustEntities(content, filePath);
    default:
      // TODO: Add more language support
      return [];
  }
}

/**
 * Extract relations between entities (basic implementation).
 * A full implementation would use AST analysis.
 */
export function extractRelations(entities: CodeEntity[], _content: string): CodeRelation[] {
  const relations: CodeRelation[] = [];

  // Add parent-child relations (methods inside classes)
  for (const entity of entities) {
    if (entity.parentId) {
      const parent = entities.find(e =>
        e.id.includes(`:class:${entity.parentId?.split(':').pop()}`)
      );
      if (parent) {
        relations.push({
          sourceId: parent.id,
          targetId: entity.id,
          type: 'contains',
        });
      }
    }
  }

  // TODO: Analyze imports, function calls, extends/implements
  // This would require more sophisticated parsing

  return relations;
}
