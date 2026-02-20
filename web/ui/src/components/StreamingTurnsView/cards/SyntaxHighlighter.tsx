/**
 * SyntaxHighlighter - Reusable syntax highlighting component for tool cards
 *
 * Uses react-syntax-highlighter with a theme that matches our green-tinted UI.
 * Supports automatic language detection from file extensions.
 */

import React, { useMemo } from 'react';
import { Prism as PrismHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

// Map file extensions to Prism language identifiers
const extensionToLanguage: Record<string, string> = {
  // JavaScript/TypeScript
  'js': 'javascript',
  'jsx': 'jsx',
  'ts': 'typescript',
  'tsx': 'tsx',
  'mjs': 'javascript',
  'cjs': 'javascript',

  // Python
  'py': 'python',
  'pyi': 'python',
  'pyw': 'python',

  // Rust
  'rs': 'rust',

  // Go
  'go': 'go',

  // C/C++
  'c': 'c',
  'h': 'c',
  'cpp': 'cpp',
  'hpp': 'cpp',
  'cc': 'cpp',
  'cxx': 'cpp',

  // Java/Kotlin
  'java': 'java',
  'kt': 'kotlin',
  'kts': 'kotlin',

  // Web
  'html': 'html',
  'htm': 'html',
  'css': 'css',
  'scss': 'scss',
  'sass': 'sass',
  'less': 'less',

  // Data formats
  'json': 'json',
  'yaml': 'yaml',
  'yml': 'yaml',
  'toml': 'toml',
  'xml': 'xml',

  // Shell
  'sh': 'bash',
  'bash': 'bash',
  'zsh': 'bash',
  'fish': 'bash',

  // Ruby
  'rb': 'ruby',
  'rake': 'ruby',
  'gemspec': 'ruby',

  // PHP
  'php': 'php',

  // SQL
  'sql': 'sql',

  // Markdown/Docs
  'md': 'markdown',
  'mdx': 'markdown',
  'rst': 'rest',

  // Config
  'ini': 'ini',
  'conf': 'ini',
  'cfg': 'ini',
  'env': 'bash',

  // Dockerfile
  'dockerfile': 'docker',

  // Makefile (no extension typically)
  'makefile': 'makefile',
  'mk': 'makefile',

  // Swift
  'swift': 'swift',

  // Lua
  'lua': 'lua',

  // Elixir
  'ex': 'elixir',
  'exs': 'elixir',

  // Haskell
  'hs': 'haskell',

  // Scala
  'scala': 'scala',
  'sc': 'scala',

  // R
  'r': 'r',

  // Diff
  'diff': 'diff',
  'patch': 'diff',
};

// Get language from file path
export function getLanguageFromPath(filePath: string): string {
  if (!filePath) return 'text';

  // Check for special filenames
  const fileName = filePath.split('/').pop()?.toLowerCase() || '';

  if (fileName === 'dockerfile' || fileName.startsWith('dockerfile.')) {
    return 'docker';
  }
  if (fileName === 'makefile' || fileName === 'gnumakefile') {
    return 'makefile';
  }
  if (fileName === '.gitignore' || fileName === '.dockerignore') {
    return 'gitignore';
  }
  if (fileName === '.env' || fileName.startsWith('.env.')) {
    return 'bash';
  }

  // Get extension
  const ext = fileName.split('.').pop()?.toLowerCase();
  if (!ext) return 'text';

  return extensionToLanguage[ext] || 'text';
}

// Custom theme based on oneDark, adjusted for our green-tinted UI
const customCodeTheme = {
  ...oneDark,
  'pre[class*="language-"]': {
    ...oneDark['pre[class*="language-"]'],
    background: 'var(--bg-code, #081210)',
    margin: 0,
    padding: '8px',
    borderRadius: '4px',
    fontSize: '11px',
    lineHeight: '1.4',
  },
  'code[class*="language-"]': {
    ...oneDark['code[class*="language-"]'],
    background: 'transparent',
    fontSize: '11px',
    lineHeight: '1.4',
  },
};

// Custom diff theme with green/red highlighting
const customDiffTheme = {
  ...customCodeTheme,
  'pre[class*="language-"]': {
    ...customCodeTheme['pre[class*="language-"]'],
    padding: 0,
  },
};

interface SyntaxHighlightedCodeProps {
  code: string;
  language?: string;
  filePath?: string;
  maxHeight?: string;
  showLineNumbers?: boolean;
}

export function SyntaxHighlightedCode({
  code,
  language,
  filePath,
  maxHeight = '400px',
  showLineNumbers = false,
}: SyntaxHighlightedCodeProps) {
  // Determine language from prop or file path
  const lang = useMemo(() => {
    if (language) return language;
    if (filePath) return getLanguageFromPath(filePath);
    return 'text';
  }, [language, filePath]);

  // Handle empty code
  if (!code || !code.trim()) {
    return <pre className="tool-file-content"><code>(empty)</code></pre>;
  }

  return (
    <div style={{ maxHeight, overflow: 'auto' }}>
      <PrismHighlighter
        style={customCodeTheme}
        language={lang}
        PreTag="div"
        showLineNumbers={showLineNumbers}
        wrapLines={true}
        lineNumberStyle={{
          minWidth: '2.5em',
          paddingRight: '1em',
          color: 'var(--text-tertiary, #5c7a5c)',
          userSelect: 'none',
        }}
      >
        {code}
      </PrismHighlighter>
    </div>
  );
}

interface DiffHighlightedCodeProps {
  diffLines: string[];
  maxHeight?: string;
}

export function DiffHighlightedCode({ diffLines, maxHeight = '300px' }: DiffHighlightedCodeProps) {
  if (diffLines.length === 0) return null;

  return (
    <div className="tool-diff-view" style={{ maxHeight, overflow: 'auto' }}>
      {diffLines.map((line, idx) => {
        let className = 'diff-line diff-context';
        if (line.startsWith('+++') || line.startsWith('---')) {
          className = 'diff-line diff-header';
        } else if (line.startsWith('+')) {
          className = 'diff-line diff-add';
        } else if (line.startsWith('-')) {
          className = 'diff-line diff-remove';
        }
        return (
          <div key={idx} className={className}>
            {line}
          </div>
        );
      })}
    </div>
  );
}

interface GrepHighlightedResultsProps {
  content: string;
  pattern?: string;
  maxHeight?: string;
}

export function GrepHighlightedResults({
  content,
  pattern,
  maxHeight = '300px',
}: GrepHighlightedResultsProps) {
  // Parse grep output and highlight matches
  const highlightedLines = useMemo(() => {
    if (!content) return [];

    const lines = content.split('\n');

    return lines.map((line, idx) => {
      // Try to parse grep-style output: file:line:content or just file:content
      const colonMatch = line.match(/^([^:]+):(\d+:)?(.*)$/);

      if (colonMatch) {
        const [, file, lineNum, rest] = colonMatch;

        // Highlight the pattern in the content if we have it
        let highlightedContent = rest;
        if (pattern && rest) {
          try {
            const regex = new RegExp(`(${escapeRegex(pattern)})`, 'gi');
            highlightedContent = rest.replace(regex, '<mark>$1</mark>');
          } catch {
            // Invalid regex, just use plain text
          }
        }

        return {
          key: idx,
          file: file,
          lineNum: lineNum?.replace(':', '') || null,
          content: highlightedContent,
          hasHighlight: highlightedContent !== rest,
        };
      }

      // Plain line (no file:line: prefix)
      return {
        key: idx,
        file: null,
        lineNum: null,
        content: line,
        hasHighlight: false,
      };
    });
  }, [content, pattern]);

  if (highlightedLines.length === 0) {
    return <div className="tool-search-results">No matches found</div>;
  }

  return (
    <div className="grep-results" style={{ maxHeight, overflow: 'auto' }}>
      {highlightedLines.map((item) => (
        <div key={item.key} className="grep-result-line">
          {item.file && (
            <span className="grep-file">{item.file}</span>
          )}
          {item.lineNum && (
            <span className="grep-line-num">{item.lineNum}</span>
          )}
          <span
            className="grep-content"
            dangerouslySetInnerHTML={{ __html: item.content || '' }}
          />
        </div>
      ))}
    </div>
  );
}

// Escape special regex characters
function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export default SyntaxHighlightedCode;
