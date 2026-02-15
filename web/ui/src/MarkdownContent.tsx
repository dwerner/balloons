import React, { useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

interface MarkdownContentProps {
  content: string;
}

// Custom dark theme based on oneDark, adjusted for our UI colors
const customTheme = {
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

// Memoized markdown components config - defined outside component to avoid recreation
const markdownComponents = {
  // Custom code block renderer with syntax highlighting
  code({ node, inline, className, children, ...props }: any) {
    const match = /language-(\w+)/.exec(className || '');
    const language = match ? match[1] : '';
    const codeString = String(children).replace(/\n$/, '');

    if (!inline && (match || codeString.includes('\n'))) {
      return (
        <div className="code-block-wrapper">
          {language && <div className="code-language">{language}</div>}
          <SyntaxHighlighter
            style={customTheme}
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

// remarkPlugins array - defined outside component to maintain referential equality
const remarkPlugins = [remarkGfm];

// Memoize the entire component to prevent re-renders when parent state changes
// (e.g., when typing in the input field)
export const MarkdownContent = React.memo(function MarkdownContent({ content }: MarkdownContentProps) {
  // Handle empty/null content - show a non-breaking space to maintain block height
  if (!content || !content.trim()) {
    return <span className="empty-content">{'\u00A0'}</span>;
  }

  return (
    <ReactMarkdown
      remarkPlugins={remarkPlugins}
      components={markdownComponents}
    >
      {content}
    </ReactMarkdown>
  );
});
