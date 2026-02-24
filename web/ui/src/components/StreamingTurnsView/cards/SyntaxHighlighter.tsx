/**
 * SyntaxHighlighter - Reusable syntax highlighting component for tool cards
 *
 * Uses react-syntax-highlighter with a theme that matches our green-tinted UI.
 * Supports automatic language detection from file extensions.
 * Theme-aware: uses light theme when app is in light mode.
 */

import React, { useMemo, useDeferredValue } from 'react';
import { Prism as PrismHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { useTheme } from '../../layout';

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

// Custom dark theme based on oneDark, adjusted for our green-tinted UI
const customDarkCodeTheme = {
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

// Custom light theme based on oneLight
const customLightCodeTheme = {
  ...oneLight,
  'pre[class*="language-"]': {
    ...oneLight['pre[class*="language-"]'],
    background: 'var(--bg-code, #f8f8f8)',
    margin: 0,
    padding: '8px',
    borderRadius: '4px',
    fontSize: '11px',
    lineHeight: '1.4',
  },
  'code[class*="language-"]': {
    ...oneLight['code[class*="language-"]'],
    background: 'transparent',
    fontSize: '11px',
    lineHeight: '1.4',
  },
};

// Custom diff themes
const customDarkDiffTheme = {
  ...customDarkCodeTheme,
  'pre[class*="language-"]': {
    ...customDarkCodeTheme['pre[class*="language-"]'],
    padding: 0,
  },
};

const customLightDiffTheme = {
  ...customLightCodeTheme,
  'pre[class*="language-"]': {
    ...customLightCodeTheme['pre[class*="language-"]'],
    padding: 0,
  },
};

interface SyntaxHighlightedCodeProps {
  code: string;
  language?: string;
  filePath?: string;
  showLineNumbers?: boolean;
  /** Wrap long lines instead of horizontal scroll (useful for JSON) */
  wrapLongLines?: boolean;
}

export function SyntaxHighlightedCode({
  code,
  language,
  filePath,
  showLineNumbers = false,
  wrapLongLines = false,
}: SyntaxHighlightedCodeProps) {
  // Get current theme - use deferred value to make theme changes non-blocking
  const { resolvedTheme: currentTheme } = useTheme();
  const resolvedTheme = useDeferredValue(currentTheme);
  const isLightTheme = resolvedTheme === 'light';
  const theme = isLightTheme ? customLightCodeTheme : customDarkCodeTheme;

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
    <PrismHighlighter
      style={theme}
      language={lang}
      PreTag="div"
      showLineNumbers={showLineNumbers}
      wrapLines={true}
      wrapLongLines={wrapLongLines}
      lineNumberStyle={{
        minWidth: '2.5em',
        paddingRight: '1em',
        color: isLightTheme ? 'var(--text-tertiary, #888)' : 'var(--text-tertiary, #5c7a5c)',
        userSelect: 'none',
      }}
      customStyle={wrapLongLines ? {
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        overflowWrap: 'break-word',
      } : undefined}
      codeTagProps={wrapLongLines ? {
        style: {
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          overflowWrap: 'break-word',
        }
      } : undefined}
    >
      {code}
    </PrismHighlighter>
  );
}

interface DiffHighlightedCodeProps {
  diffLines: string[];
  /** Language for syntax highlighting (inferred from file extension in header) */
  language?: string;
  /** File path for language detection */
  filePath?: string;
}

/**
 * Single diff line with syntax highlighting
 */
function DiffLine({
  type,
  prefix,
  content,
  language,
  isLightTheme,
}: {
  type: 'header' | 'add' | 'remove' | 'context';
  prefix: string;
  content: string;
  language: string;
  isLightTheme: boolean;
}) {
  const theme = isLightTheme ? customLightDiffTheme : customDarkDiffTheme;

  let className = 'diff-line diff-context';
  if (type === 'header') className = 'diff-line diff-header';
  else if (type === 'add') className = 'diff-line diff-add';
  else if (type === 'remove') className = 'diff-line diff-remove';

  // Header lines don't get syntax highlighting
  if (type === 'header') {
    return (
      <div className={className}>
        {content}
      </div>
    );
  }

  return (
    <div className={className}>
      <span className="diff-prefix">{prefix}</span>
      <PrismHighlighter
        style={theme}
        language={language}
        PreTag="span"
        customStyle={{
          display: 'inline',
          margin: 0,
          padding: 0,
          background: 'transparent',
        }}
      >
        {content || ' '}
      </PrismHighlighter>
    </div>
  );
}

export function DiffHighlightedCode({ diffLines, language, filePath }: DiffHighlightedCodeProps) {
  const { resolvedTheme: currentTheme } = useTheme();
  const resolvedTheme = useDeferredValue(currentTheme);
  const isLightTheme = resolvedTheme === 'light';

  // Determine language from props or try to extract from diff header
  const lang = useMemo(() => {
    if (language) return language;
    if (filePath) return getLanguageFromPath(filePath);
    // Try to extract from diff header (--- a/file.tsx or +++ b/file.tsx)
    for (const line of diffLines) {
      if (line.startsWith('---') || line.startsWith('+++')) {
        const match = line.match(/[ab]\/(.+)$/);
        if (match && match[1]) {
          return getLanguageFromPath(match[1]);
        }
      }
    }
    return 'text';
  }, [language, filePath, diffLines]);

  if (diffLines.length === 0) return null;

  // Parse each line into type, prefix, and content
  const processedLines = diffLines.map(line => {
    if (line.startsWith('+++') || line.startsWith('---')) {
      return { type: 'header' as const, prefix: '', content: line };
    } else if (line.startsWith('+')) {
      return { type: 'add' as const, prefix: '+', content: line.slice(1) };
    } else if (line.startsWith('-')) {
      return { type: 'remove' as const, prefix: '-', content: line.slice(1) };
    } else if (line.startsWith(' ')) {
      return { type: 'context' as const, prefix: ' ', content: line.slice(1) };
    }
    return { type: 'context' as const, prefix: ' ', content: line };
  });

  return (
    <div className="tool-diff-view">
      {processedLines.map((line, idx) => (
        <DiffLine
          key={idx}
          type={line.type}
          prefix={line.prefix}
          content={line.content}
          language={lang}
          isLightTheme={isLightTheme}
        />
      ))}
    </div>
  );
}

interface GrepHighlightedResultsProps {
  content: string;
  pattern?: string;
}

export function GrepHighlightedResults({
  content,
  pattern,
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
    <div className="grep-results">
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
