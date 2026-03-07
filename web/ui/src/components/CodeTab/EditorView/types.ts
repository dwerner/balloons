/**
 * Type definitions for the Editor + Code Map split view.
 */

/** A file open in the editor */
export interface EditorFile {
  /** Absolute path to the file */
  path: string;
  /** File content (loaded) */
  content?: string;
  /** Detected language */
  language: string;
  /** Whether to include in the code map */
  includedInMap: boolean;
  /** Whether file has unsaved changes */
  isDirty: boolean;
}

/** A code entity extracted from a file (for the map) */
export interface CodeEntity {
  /** Unique ID (file:line:name) */
  id: string;
  /** Entity name (function, class, etc.) */
  name: string;
  /** Entity type */
  type: 'class' | 'function' | 'method' | 'interface' | 'type' | 'constant' | 'variable' | 'module';
  /** File path */
  filePath: string;
  /** Start line in the file */
  lineStart: number;
  /** End line in the file */
  lineEnd: number;
  /** Language of the file */
  language: string;
  /** Parent entity ID (e.g., method inside class) */
  parentId?: string;
  /** Whether this is async (functions/methods) */
  isAsync?: boolean;
  /** Whether this is exported */
  isExported?: boolean;
}

/** A relationship between entities */
export interface CodeRelation {
  /** Source entity ID */
  sourceId: string;
  /** Target entity ID */
  targetId: string;
  /** Type of relationship */
  type: 'calls' | 'extends' | 'implements' | 'imports' | 'contains';
  /** Optional label */
  label?: string;
}

/** State for the Editor + Map split view */
export interface EditorViewState {
  /** Open files */
  files: EditorFile[];
  /** Currently active file path */
  activeFilePath: string | null;
  /** Whether the map pane is visible */
  mapVisible: boolean;
  /** Split ratio (0-1, percentage for editor) */
  splitRatio: number;
  /** Selected node in the map (syncs with cursor) */
  selectedNodeId: string | null;
  /** Entities extracted from files included in map */
  entities: CodeEntity[];
  /** Relations between entities */
  relations: CodeRelation[];
}

/** Language to color mapping */
export const LANGUAGE_COLORS: Record<string, string> = {
  typescript: '#3178c6',
  javascript: '#f7df1e',
  python: '#3776ab',
  rust: '#dea584',
  go: '#00add8',
  java: '#b07219',
  cpp: '#f34b7d',
  c: '#555555',
  ruby: '#701516',
  php: '#4f5d95',
  swift: '#ffac45',
  kotlin: '#a97bff',
  scala: '#c22d40',
  haskell: '#5e5086',
  elixir: '#6e4a7e',
  clojure: '#db5855',
  css: '#264de4',
  html: '#e34c26',
  json: '#292929',
  yaml: '#cb171e',
  markdown: '#083fa1',
  sql: '#e38c00',
  shell: '#89e051',
  default: '#6e7681',
};

/** Get color for a language */
export function getLanguageColor(language: string): string {
  return LANGUAGE_COLORS[language.toLowerCase()] ?? LANGUAGE_COLORS.default ?? '#6e7681';
}

/** Detect language from file path */
export function detectLanguage(filePath: string): string {
  const ext = filePath.split('.').pop()?.toLowerCase() || '';
  const extMap: Record<string, string> = {
    ts: 'typescript',
    tsx: 'typescript',
    js: 'javascript',
    jsx: 'javascript',
    mjs: 'javascript',
    cjs: 'javascript',
    py: 'python',
    rs: 'rust',
    go: 'go',
    java: 'java',
    cpp: 'cpp',
    cc: 'cpp',
    cxx: 'cpp',
    c: 'c',
    h: 'c',
    hpp: 'cpp',
    rb: 'ruby',
    php: 'php',
    swift: 'swift',
    kt: 'kotlin',
    kts: 'kotlin',
    scala: 'scala',
    hs: 'haskell',
    ex: 'elixir',
    exs: 'elixir',
    clj: 'clojure',
    cljs: 'clojure',
    css: 'css',
    scss: 'css',
    sass: 'css',
    less: 'css',
    html: 'html',
    htm: 'html',
    json: 'json',
    yaml: 'yaml',
    yml: 'yaml',
    md: 'markdown',
    sql: 'sql',
    sh: 'shell',
    bash: 'shell',
    zsh: 'shell',
  };
  return extMap[ext] || ext || 'plaintext';
}

/** Map language to Monaco language ID */
export function getMonacoLanguage(language: string): string {
  const map: Record<string, string> = {
    typescript: 'typescript',
    javascript: 'javascript',
    python: 'python',
    rust: 'rust',
    go: 'go',
    java: 'java',
    cpp: 'cpp',
    c: 'c',
    ruby: 'ruby',
    php: 'php',
    swift: 'swift',
    kotlin: 'kotlin',
    scala: 'scala',
    haskell: 'haskell',
    elixir: 'elixir',
    clojure: 'clojure',
    css: 'css',
    html: 'html',
    json: 'json',
    yaml: 'yaml',
    markdown: 'markdown',
    sql: 'sql',
    shell: 'shell',
    plaintext: 'plaintext',
  };
  return map[language] || 'plaintext';
}
