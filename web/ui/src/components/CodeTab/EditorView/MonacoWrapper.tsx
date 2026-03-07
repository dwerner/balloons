/**
 * MonacoWrapper - Monaco editor integration with Balloons theming.
 *
 * Features:
 * - Auto-detects language from file extension
 * - Syncs with Balloons light/dark theme
 * - Reports cursor position for map sync
 * - Read-only mode (for now - editing comes later)
 */

import React, { useRef, useEffect, memo } from 'react';
import Editor from '@monaco-editor/react';
import type { OnMount, Monaco } from '@monaco-editor/react';
import type * as MonacoEditor from 'monaco-editor';
import { getMonacoLanguage } from './types';

export interface MonacoWrapperProps {
  /** File path (for language detection) */
  filePath: string;
  /** File content */
  content: string;
  /** Detected language */
  language: string;
  /** Whether dark mode is active */
  isDarkMode: boolean;
  /** Line to highlight (from map selection) */
  highlightLine?: number;
  /** Callback when cursor position changes */
  onCursorChange?: (line: number, column: number) => void;
  /** Callback when content changes (for future editing) */
  onContentChange?: (content: string) => void;
}

// Custom Balloons themes
const BALLOONS_DARK_THEME: MonacoEditor.editor.IStandaloneThemeData = {
  base: 'vs-dark',
  inherit: true,
  rules: [
    { token: 'comment', foreground: '6a737d', fontStyle: 'italic' },
    { token: 'keyword', foreground: 'ff7b72' },
    { token: 'string', foreground: 'a5d6ff' },
    { token: 'number', foreground: '79c0ff' },
    { token: 'type', foreground: 'ffa657' },
    { token: 'function', foreground: 'd2a8ff' },
    { token: 'variable', foreground: 'c9d1d9' },
  ],
  colors: {
    'editor.background': '#0d1117',
    'editor.foreground': '#c9d1d9',
    'editor.lineHighlightBackground': '#161b2233',
    'editor.selectionBackground': '#264f78',
    'editorCursor.foreground': '#58a6ff',
    'editorLineNumber.foreground': '#6e7681',
    'editorLineNumber.activeForeground': '#c9d1d9',
    'editor.inactiveSelectionBackground': '#264f7855',
  },
};

const BALLOONS_LIGHT_THEME: MonacoEditor.editor.IStandaloneThemeData = {
  base: 'vs',
  inherit: true,
  rules: [
    { token: 'comment', foreground: '6a737d', fontStyle: 'italic' },
    { token: 'keyword', foreground: 'cf222e' },
    { token: 'string', foreground: '0a3069' },
    { token: 'number', foreground: '0550ae' },
    { token: 'type', foreground: '953800' },
    { token: 'function', foreground: '8250df' },
    { token: 'variable', foreground: '24292f' },
  ],
  colors: {
    'editor.background': '#ffffff',
    'editor.foreground': '#24292f',
    'editor.lineHighlightBackground': '#f6f8fa',
    'editor.selectionBackground': '#0550ae33',
    'editorCursor.foreground': '#0550ae',
    'editorLineNumber.foreground': '#8c959f',
    'editorLineNumber.activeForeground': '#24292f',
    'editor.inactiveSelectionBackground': '#0550ae22',
  },
};

export const MonacoWrapper = memo(function MonacoWrapper({
  filePath,
  content,
  language,
  isDarkMode,
  highlightLine,
  onCursorChange,
  onContentChange,
}: MonacoWrapperProps) {
  const editorRef = useRef<MonacoEditor.editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<Monaco | null>(null);
  const decorationsRef = useRef<string[]>([]);

  // Handle editor mount
  const handleEditorMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;

    // Define custom themes
    monaco.editor.defineTheme('balloons-dark', BALLOONS_DARK_THEME);
    monaco.editor.defineTheme('balloons-light', BALLOONS_LIGHT_THEME);

    // Set initial theme
    monaco.editor.setTheme(isDarkMode ? 'balloons-dark' : 'balloons-light');

    // Listen for cursor position changes
    editor.onDidChangeCursorPosition((e) => {
      if (onCursorChange) {
        onCursorChange(e.position.lineNumber, e.position.column);
      }
    });

    // Focus the editor
    editor.focus();
  };

  // Update theme when dark mode changes
  useEffect(() => {
    if (monacoRef.current) {
      monacoRef.current.editor.setTheme(isDarkMode ? 'balloons-dark' : 'balloons-light');
    }
  }, [isDarkMode]);

  // Highlight a specific line (from map selection)
  useEffect(() => {
    if (!editorRef.current || !monacoRef.current || !highlightLine) return;

    const editor = editorRef.current;
    const monaco = monacoRef.current;

    // Remove old decorations
    decorationsRef.current = editor.deltaDecorations(decorationsRef.current, []);

    // Add new decoration
    decorationsRef.current = editor.deltaDecorations([], [
      {
        range: new monaco.Range(highlightLine, 1, highlightLine, 1),
        options: {
          isWholeLine: true,
          className: 'monaco-highlight-line',
          glyphMarginClassName: 'monaco-highlight-glyph',
        },
      },
    ]);

    // Reveal the line
    editor.revealLineInCenter(highlightLine);
  }, [highlightLine]);

  // Handle content changes
  const handleContentChange = (value: string | undefined) => {
    if (onContentChange && value !== undefined) {
      onContentChange(value);
    }
  };

  const monacoLanguage = getMonacoLanguage(language);

  return (
    <div className="monaco-wrapper">
      <Editor
        height="100%"
        language={monacoLanguage}
        value={content}
        theme={isDarkMode ? 'balloons-dark' : 'balloons-light'}
        onMount={handleEditorMount}
        onChange={handleContentChange}
        options={{
          readOnly: true, // Read-only for now
          minimap: { enabled: true, scale: 1 },
          fontSize: 13,
          fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', Consolas, monospace",
          fontLigatures: true,
          lineNumbers: 'on',
          lineNumbersMinChars: 4,
          folding: true,
          foldingStrategy: 'indentation',
          wordWrap: 'off',
          scrollBeyondLastLine: false,
          automaticLayout: true,
          cursorBlinking: 'smooth',
          cursorSmoothCaretAnimation: 'on',
          smoothScrolling: true,
          renderWhitespace: 'selection',
          bracketPairColorization: { enabled: true },
          guides: {
            bracketPairs: true,
            indentation: true,
          },
          padding: { top: 8, bottom: 8 },
        }}
      />
    </div>
  );
});

export default MonacoWrapper;
