import React, { useMemo, useDeferredValue, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { useTheme } from './components/layout';

// Copy button component for code blocks
function CopyButton({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  }, [code]);

  return (
    <button
      className="code-copy-button"
      onClick={handleCopy}
      title={copied ? 'Copied!' : 'Copy code'}
      aria-label={copied ? 'Copied!' : 'Copy code'}
    >
      {copied ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      )}
    </button>
  );
}

interface MarkdownContentProps {
  content: string;
}

// Custom dark theme based on oneDark, adjusted for our UI colors
const customDarkTheme = {
  ...oneDark,
  'pre[class*="language-"]': {
    ...oneDark['pre[class*="language-"]'],
    background: '#0d1117',
    margin: 0,
    padding: '12px',
    borderRadius: '6px',
    fontSize: '13px',
    lineHeight: '1.5',
  },
  'code[class*="language-"]': {
    ...oneDark['code[class*="language-"]'],
    background: 'transparent',
    fontSize: '13px',
    lineHeight: '1.5',
  },
};

// Custom light theme based on oneLight, adjusted for our UI colors
const customLightTheme = {
  ...oneLight,
  'pre[class*="language-"]': {
    ...oneLight['pre[class*="language-"]'],
    background: '#f8f8f8',
    margin: 0,
    padding: '12px',
    borderRadius: '6px',
    fontSize: '13px',
    lineHeight: '1.5',
  },
  'code[class*="language-"]': {
    ...oneLight['code[class*="language-"]'],
    background: 'transparent',
    fontSize: '13px',
    lineHeight: '1.5',
  },
};

// remarkPlugins array - defined outside component to maintain referential equality
const remarkPlugins = [remarkGfm];

// Create markdown components with theme awareness
function createMarkdownComponents(isLightTheme: boolean) {
  const theme = isLightTheme ? customLightTheme : customDarkTheme;

  return {
    // Custom code block renderer with syntax highlighting
    code({ node, inline, className, children, ...props }: any) {
      const match = /language-(\w+)/.exec(className || '');
      const language = match ? match[1] : '';
      const codeString = String(children).replace(/\n$/, '');

      if (!inline && (match || codeString.includes('\n'))) {
        return (
          <div className="code-block-wrapper">
            <div className="code-block-header">
              {language && <div className="code-language">{language}</div>}
              <CopyButton code={codeString} />
            </div>
            <SyntaxHighlighter
              style={theme}
              language={language || 'text'}
              PreTag="div"
              {...props}
            >
              {codeString}
            </SyntaxHighlighter>
          </div>
        );
      }

      // Inline code
      return (
        <code className="inline-code" {...props}>
          {children}
        </code>
      );
    },
    // Custom link renderer to open in new tab
    a({ node, children, href, ...props }: any) {
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
          {children}
        </a>
      );
    },
  };
}

/**
 * Strip internal protocol markup from content before rendering.
 *
 * This removes:
 * - <balloons-tool>...</balloons-tool> blocks (tool invocations)
 * - <balloons-tool-result>...</balloons-tool-result> blocks (tool results)
 *
 * These are internal protocol elements that should not be visible to users.
 * The regex handles multiline content within the tags.
 */
function stripInternalMarkup(content: string): string {
  // Remove <balloons-tool>...</balloons-tool> blocks (multiline, non-greedy)
  let cleaned = content.replace(/<balloons-tool>[\s\S]*?<\/balloons-tool>/g, '');

  // Remove <balloons-tool-result ...>...</balloons-tool-result> blocks (multiline, non-greedy)
  // The opening tag may have attributes like tool="..." id="..."
  cleaned = cleaned.replace(/<balloons-tool-result[^>]*>[\s\S]*?<\/balloons-tool-result>/g, '');

  // Clean up any resulting multiple blank lines (more than 2 newlines in a row)
  cleaned = cleaned.replace(/\n{3,}/g, '\n\n');

  return cleaned.trim();
}

// Memoize the entire component to prevent re-renders when parent state changes
// (e.g., when typing in the input field)
export const MarkdownContent = React.memo(function MarkdownContent({ content }: MarkdownContentProps) {
  // Get current theme
  const { resolvedTheme } = useTheme();
  const isLightTheme = resolvedTheme === 'light';

  // Use deferred value for content - allows React to interrupt rendering during scroll
  // This makes the UI more responsive when rapidly scrolling through many messages
  const deferredContent = useDeferredValue(content);

  // Memoize components to prevent recreation on every render (only change when theme changes)
  const markdownComponents = useMemo(
    () => createMarkdownComponents(isLightTheme),
    [isLightTheme]
  );

  // Handle empty/null content - show a non-breaking space to maintain block height
  if (!deferredContent || !deferredContent.trim()) {
    return <span className="empty-content">{'\u00A0'}</span>;
  }

  // Strip internal protocol markup before rendering
  const cleanedContent = stripInternalMarkup(deferredContent);

  // If stripping leaves empty content, show non-breaking space
  if (!cleanedContent) {
    return <span className="empty-content">{'\u00A0'}</span>;
  }

  return (
    <ReactMarkdown
      remarkPlugins={remarkPlugins}
      components={markdownComponents}
    >
      {cleanedContent}
    </ReactMarkdown>
  );
});
