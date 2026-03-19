/**
 * PreferencesContext - Persistent UI preferences
 *
 * Stores user preferences in localStorage and provides them via React context.
 * Preferences include things like whether tool cards expand by default.
 */

import React, { createContext, useContext, useState, useCallback, useMemo, useEffect, startTransition } from 'react';

// Storage key prefix
const STORAGE_PREFIX = 'balloons:prefs:';

// Preference keys (boolean)
export type PreferenceKey = 'expandToolCards' | 'showTokenCounts' | 'voiceInputEnabled';

// Default values for each boolean preference
const DEFAULTS: Record<PreferenceKey, boolean> = {
  expandToolCards: false, // Default: collapse tool cards (diffs, reads)
  showTokenCounts: true,  // Default: show token counts in headers
  voiceInputEnabled: false, // Default: voice input disabled
};

// String preference keys
export type StringPreferenceKey = 'voiceInputHost' | 'voiceInputPort' | 'depthIndicatorStyle' | 'historyLoadMode'
  | 'bgPatternSidebar' | 'bgPatternMain' | 'bgPatternDetail'
  | 'diffColorAdded' | 'diffColorRemoved'
  | 'syntaxThemeDark' | 'syntaxThemeLight'
  | 'mdThemeDark' | 'mdThemeLight'
  | 'fontFamily' | 'fontFamilyMono';

// Available syntax highlighting themes
export const SYNTAX_THEMES_DARK = [
  { id: 'oneDark', name: 'One Dark (default)' },
  { id: 'dracula', name: 'Dracula' },
  { id: 'nightOwl', name: 'Night Owl' },
  { id: 'nord', name: 'Nord' },
  { id: 'atomDark', name: 'Atom Dark' },
  { id: 'materialDark', name: 'Material Dark' },
  { id: 'materialOceanic', name: 'Material Oceanic' },
  { id: 'gruvboxDark', name: 'Gruvbox Dark' },
  { id: 'synthwave84', name: 'Synthwave 84' },
  { id: 'shadesOfPurple', name: 'Shades of Purple' },
  { id: 'duotoneDark', name: 'Duotone Dark' },
  { id: 'duotoneSpace', name: 'Duotone Space' },
  { id: 'duotoneSea', name: 'Duotone Sea' },
  { id: 'hopscotch', name: 'Hopscotch' },
  { id: 'okaidia', name: 'Okaidia' },
  { id: 'coldarkDark', name: 'Coldark Dark' },
  { id: 'a11yDark', name: 'A11y Dark' },
] as const;

export const SYNTAX_THEMES_LIGHT = [
  { id: 'oneLight', name: 'One Light (default)' },
  { id: 'ghcolors', name: 'GitHub' },
  { id: 'materialLight', name: 'Material Light' },
  { id: 'gruvboxLight', name: 'Gruvbox Light' },
  { id: 'solarizedlight', name: 'Solarized Light' },
  { id: 'duotoneLight', name: 'Duotone Light' },
  { id: 'coy', name: 'Coy' },
  { id: 'prism', name: 'Prism' },
  { id: 'coldarkCold', name: 'Coldark Cold' },
  { id: 'a11yLight', name: 'A11y One Light' },
] as const;

export type SyntaxThemeDark = typeof SYNTAX_THEMES_DARK[number]['id'];
export type SyntaxThemeLight = typeof SYNTAX_THEMES_LIGHT[number]['id'];

// Available markdown themes
export const MD_THEMES = [
  { id: 'default', name: 'Default' },
  { id: 'github', name: 'GitHub' },
  { id: 'notion', name: 'Notion' },
  { id: 'obsidian', name: 'Obsidian' },
  { id: 'typora', name: 'Typora' },
  { id: 'minimal', name: 'Minimal' },
] as const;

export type MdTheme = typeof MD_THEMES[number]['id'];

// Available font families (sans-serif for UI)
export const FONT_FAMILIES = [
  { id: 'system', name: 'System Default', value: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif' },
  { id: 'inter', name: 'Inter', value: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif' },
  { id: 'roboto', name: 'Roboto', value: '"Roboto", -apple-system, sans-serif' },
  { id: 'open-sans', name: 'Open Sans', value: '"Open Sans", -apple-system, sans-serif' },
  { id: 'lato', name: 'Lato', value: '"Lato", -apple-system, sans-serif' },
  { id: 'source-sans', name: 'Source Sans Pro', value: '"Source Sans Pro", -apple-system, sans-serif' },
  { id: 'nunito', name: 'Nunito', value: '"Nunito", -apple-system, sans-serif' },
  { id: 'poppins', name: 'Poppins', value: '"Poppins", -apple-system, sans-serif' },
  { id: 'ibm-plex', name: 'IBM Plex Sans', value: '"IBM Plex Sans", -apple-system, sans-serif' },
  { id: 'atkinson', name: 'Atkinson Hyperlegible', value: '"Atkinson Hyperlegible", -apple-system, sans-serif' },
] as const;

// Available monospace font families (for code/editor)
export const FONT_FAMILIES_MONO = [
  { id: 'system-mono', name: 'System Monospace', value: 'ui-monospace, "SF Mono", Monaco, "Cascadia Mono", "Segoe UI Mono", "Roboto Mono", "Oxygen Mono", "Ubuntu Monospace", "Source Code Pro", "Fira Mono", "Droid Sans Mono", "Courier New", monospace' },
  { id: 'fira-code', name: 'Fira Code', value: '"Fira Code", ui-monospace, monospace' },
  { id: 'jetbrains-mono', name: 'JetBrains Mono', value: '"JetBrains Mono", ui-monospace, monospace' },
  { id: 'source-code-pro', name: 'Source Code Pro', value: '"Source Code Pro", ui-monospace, monospace' },
  { id: 'cascadia-code', name: 'Cascadia Code', value: '"Cascadia Code", ui-monospace, monospace' },
  { id: 'roboto-mono', name: 'Roboto Mono', value: '"Roboto Mono", ui-monospace, monospace' },
  { id: 'ibm-plex-mono', name: 'IBM Plex Mono', value: '"IBM Plex Mono", ui-monospace, monospace' },
  { id: 'inconsolata', name: 'Inconsolata', value: '"Inconsolata", ui-monospace, monospace' },
  { id: 'hack', name: 'Hack', value: '"Hack", ui-monospace, monospace' },
  { id: 'ubuntu-mono', name: 'Ubuntu Mono', value: '"Ubuntu Mono", ui-monospace, monospace' },
  { id: 'anonymous-pro', name: 'Anonymous Pro', value: '"Anonymous Pro", ui-monospace, monospace' },
  { id: 'iosevka', name: 'Iosevka', value: '"Iosevka", ui-monospace, monospace' },
  { id: 'victor-mono', name: 'Victor Mono', value: '"Victor Mono", ui-monospace, monospace' },
] as const;

export type FontFamilyId = typeof FONT_FAMILIES[number]['id'];
export type FontFamilyMonoId = typeof FONT_FAMILIES_MONO[number]['id'];

// Numeric preference keys
export type NumericPreferenceKey = 'autoscrollSpeed' | 'bgOpacitySidebar' | 'bgOpacityMain' | 'bgOpacityDetail'
  | 'bgScaleSidebar' | 'bgScaleMain' | 'bgScaleDetail'
  | 'fontSize' | 'fontSizeMono';

// History loading modes
export type HistoryLoadMode = 'forward' | 'reverse' | 'lazy';

// Default values for string preferences
const STRING_DEFAULTS: Record<StringPreferenceKey, string> = {
  voiceInputHost: '192.168.0.120',
  voiceInputPort: '8012',
  depthIndicatorStyle: 'chevrons', // 'chevrons' | 'fractal'
  historyLoadMode: 'reverse', // 'forward' | 'reverse' | 'lazy' - reverse shows bottom faster
  bgPatternSidebar: 'none',
  bgPatternMain: 'none',
  bgPatternDetail: 'none',
  diffColorAdded: '#22c55e', // Green for additions
  diffColorRemoved: '#ef4444', // Red for removals
  syntaxThemeDark: 'oneDark', // Syntax highlighting theme for dark mode
  syntaxThemeLight: 'oneLight', // Syntax highlighting theme for light mode
  mdThemeDark: 'default', // Markdown theme for dark mode
  mdThemeLight: 'default', // Markdown theme for light mode
  fontFamily: 'system', // Global UI font family
  fontFamilyMono: 'system-mono', // Global monospace/code font family
};

// Default values for numeric preferences
const NUMERIC_DEFAULTS: Record<NumericPreferenceKey, number> = {
  autoscrollSpeed: 125, // pixels per second for auto-scroll animation
  bgOpacitySidebar: 0.1, // 0-1, transparency of background pattern
  bgOpacityMain: 0.1,
  bgOpacityDetail: 0.1,
  bgScaleSidebar: 1, // 0.5-3, scale multiplier for pattern
  bgScaleMain: 1,
  bgScaleDetail: 1,
  fontSize: 14, // Base font size in px
  fontSizeMono: 13, // Monospace font size in px
};

// Built-in background patterns
export const BUILTIN_BG_PATTERNS = [
  { id: 'none', name: 'None', type: 'none' as const },
  { id: 'subtle-prism', name: 'Subtle Prism', type: 'pattern' as const },
  { id: 'endless-constellation', name: 'Endless Constellation', type: 'pattern' as const },
  { id: 'wavey-fingerprint', name: 'Wavey Fingerprint', type: 'pattern' as const },
  { id: 'large-triangles', name: 'Large Triangles', type: 'pattern' as const },
  { id: 'circuit-board', name: 'Circuit Board', type: 'pattern' as const },
  { id: 'topography', name: 'Topography', type: 'pattern' as const },
  { id: 'hexagons', name: 'Hexagons', type: 'pattern' as const },
  { id: 'diagonal-lines', name: 'Diagonal Lines', type: 'pattern' as const },
  { id: 'plus-signs', name: 'Plus Signs', type: 'pattern' as const },
  { id: 'dots', name: 'Dots', type: 'pattern' as const },
  { id: 'protruding-squares', name: 'Protruding Squares', type: 'pattern' as const },
];

// Fit modes for custom full backgrounds
export type CustomBgFitMode = 'cover' | 'contain' | 'fill' | 'none';

// Custom background type (user-pasted SVGs)
export interface CustomBackground {
  id: string;
  name: string;
  type: 'custom-pattern' | 'custom-full' | 'custom-image'; // pattern repeats, full stretches, image is full-bleed
  svg: string; // The SVG content (or image data URL for custom-image)
  fitMode?: CustomBgFitMode; // For full backgrounds and images: how to fit (default: cover)
}

// Storage key for custom backgrounds
const CUSTOM_BG_STORAGE_KEY = 'balloons:custom-backgrounds';

// Load custom backgrounds from localStorage
function loadCustomBackgrounds(): CustomBackground[] {
  if (typeof window === 'undefined') return [];
  try {
    const stored = localStorage.getItem(CUSTOM_BG_STORAGE_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

// Save custom backgrounds to localStorage
function saveCustomBackgrounds(backgrounds: CustomBackground[]): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(CUSTOM_BG_STORAGE_KEY, JSON.stringify(backgrounds));
}

// Combined type for all background options
export type BgPatternOption = {
  id: string;
  name: string;
  type: 'none' | 'pattern' | 'custom-pattern' | 'custom-full';
};

// For backward compatibility, export BG_PATTERNS as a function that includes custom ones
export function getAllBackgroundPatterns(customBgs: CustomBackground[]): BgPatternOption[] {
  const builtIn: BgPatternOption[] = BUILTIN_BG_PATTERNS;
  const custom: BgPatternOption[] = customBgs.map(bg => ({
    id: bg.id,
    name: bg.name,
    type: bg.type,
  }));
  return [...builtIn, ...custom];
}

// Legacy export for compatibility
export const BG_PATTERNS = BUILTIN_BG_PATTERNS;

// Pattern ID can be a built-in pattern or a custom one (custom: prefix)
export type BgPatternId = string;

export interface PreferencesContextValue {
  // Individual preference getters (boolean)
  expandToolCards: boolean;
  showTokenCounts: boolean;
  voiceInputEnabled: boolean;

  // Voice input settings (string)
  voiceInputHost: string;
  voiceInputPort: string;

  // Depth indicator style
  depthIndicatorStyle: 'chevrons' | 'fractal';

  // History loading mode
  historyLoadMode: HistoryLoadMode;

  // Autoscroll speed (numeric)
  autoscrollSpeed: number;

  // Background pattern settings
  bgPatternSidebar: BgPatternId;
  bgPatternMain: BgPatternId;
  bgPatternDetail: BgPatternId;
  bgOpacitySidebar: number;
  bgOpacityMain: number;
  bgOpacityDetail: number;
  bgScaleSidebar: number;
  bgScaleMain: number;
  bgScaleDetail: number;

  // Diff colors
  diffColorAdded: string;
  diffColorRemoved: string;

  // Syntax highlighting themes
  syntaxThemeDark: SyntaxThemeDark;
  syntaxThemeLight: SyntaxThemeLight;

  // Markdown themes
  mdThemeDark: MdTheme;
  mdThemeLight: MdTheme;

  // Fonts
  fontFamily: FontFamilyId;
  fontFamilyMono: FontFamilyMonoId;
  fontSize: number;
  fontSizeMono: number;

  // Custom backgrounds
  customBackgrounds: CustomBackground[];
  allBackgroundPatterns: BgPatternOption[];
  addCustomBackground: (name: string, svg: string, type: 'custom-pattern' | 'custom-full' | 'custom-image', fitMode?: CustomBgFitMode) => string;
  updateCustomBackground: (id: string, name: string, svg: string, type: 'custom-pattern' | 'custom-full' | 'custom-image', fitMode?: CustomBgFitMode) => void;
  removeCustomBackground: (id: string) => void;
  getCustomBackground: (id: string) => CustomBackground | undefined;

  // Generic getter/setter (boolean)
  getPreference: (key: PreferenceKey) => boolean;
  setPreference: (key: PreferenceKey, value: boolean) => void;
  togglePreference: (key: PreferenceKey) => void;

  // String preference getter/setter
  getStringPreference: (key: StringPreferenceKey) => string;
  setStringPreference: (key: StringPreferenceKey, value: string) => void;

  // Numeric preference getter/setter
  getNumericPreference: (key: NumericPreferenceKey) => number;
  setNumericPreference: (key: NumericPreferenceKey, value: number) => void;
}

const PreferencesContext = createContext<PreferencesContextValue | null>(null);

// Load a boolean preference from localStorage
function loadPreference(key: PreferenceKey): boolean {
  if (typeof window === 'undefined') return DEFAULTS[key];
  const stored = localStorage.getItem(STORAGE_PREFIX + key);
  if (stored === 'true') return true;
  if (stored === 'false') return false;
  return DEFAULTS[key];
}

// Save a boolean preference to localStorage
function savePreference(key: PreferenceKey, value: boolean): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(STORAGE_PREFIX + key, String(value));
}

// Load a string preference from localStorage
function loadStringPreference(key: StringPreferenceKey): string {
  if (typeof window === 'undefined') return STRING_DEFAULTS[key];
  const stored = localStorage.getItem(STORAGE_PREFIX + key);
  return stored ?? STRING_DEFAULTS[key];
}

// Save a string preference to localStorage
function saveStringPreference(key: StringPreferenceKey, value: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(STORAGE_PREFIX + key, value);
}

// Load a numeric preference from localStorage
function loadNumericPreference(key: NumericPreferenceKey): number {
  if (typeof window === 'undefined') return NUMERIC_DEFAULTS[key];
  const stored = localStorage.getItem(STORAGE_PREFIX + key);
  if (stored) {
    const parsed = parseFloat(stored);
    if (!isNaN(parsed)) return parsed;
  }
  return NUMERIC_DEFAULTS[key];
}

// Save a numeric preference to localStorage
function saveNumericPreference(key: NumericPreferenceKey, value: number): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(STORAGE_PREFIX + key, String(value));
}

export function PreferencesProvider({ children }: { children: React.ReactNode }) {
  // Individual boolean preference states
  const [expandToolCards, setExpandToolCards] = useState(() => loadPreference('expandToolCards'));
  const [showTokenCounts, setShowTokenCounts] = useState(() => loadPreference('showTokenCounts'));
  const [voiceInputEnabled, setVoiceInputEnabled] = useState(() => loadPreference('voiceInputEnabled'));

  // String preference states
  const [voiceInputHost, setVoiceInputHost] = useState(() => loadStringPreference('voiceInputHost'));
  const [voiceInputPort, setVoiceInputPort] = useState(() => loadStringPreference('voiceInputPort'));
  const [depthIndicatorStyle, setDepthIndicatorStyle] = useState(() => loadStringPreference('depthIndicatorStyle') as 'chevrons' | 'fractal');
  const [historyLoadMode, setHistoryLoadMode] = useState(() => loadStringPreference('historyLoadMode') as HistoryLoadMode);

  // Background pattern states
  const [bgPatternSidebar, setBgPatternSidebar] = useState(() => loadStringPreference('bgPatternSidebar') as BgPatternId);
  const [bgPatternMain, setBgPatternMain] = useState(() => loadStringPreference('bgPatternMain') as BgPatternId);
  const [bgPatternDetail, setBgPatternDetail] = useState(() => loadStringPreference('bgPatternDetail') as BgPatternId);

  // Numeric preference states
  const [autoscrollSpeed, setAutoscrollSpeed] = useState(() => loadNumericPreference('autoscrollSpeed'));
  const [bgOpacitySidebar, setBgOpacitySidebar] = useState(() => loadNumericPreference('bgOpacitySidebar'));
  const [bgOpacityMain, setBgOpacityMain] = useState(() => loadNumericPreference('bgOpacityMain'));
  const [bgOpacityDetail, setBgOpacityDetail] = useState(() => loadNumericPreference('bgOpacityDetail'));
  const [bgScaleSidebar, setBgScaleSidebar] = useState(() => loadNumericPreference('bgScaleSidebar'));
  const [bgScaleMain, setBgScaleMain] = useState(() => loadNumericPreference('bgScaleMain'));
  const [bgScaleDetail, setBgScaleDetail] = useState(() => loadNumericPreference('bgScaleDetail'));

  // Diff color states
  const [diffColorAdded, setDiffColorAdded] = useState(() => loadStringPreference('diffColorAdded'));
  const [diffColorRemoved, setDiffColorRemoved] = useState(() => loadStringPreference('diffColorRemoved'));

  // Syntax highlighting theme states
  const [syntaxThemeDark, setSyntaxThemeDark] = useState(() => loadStringPreference('syntaxThemeDark') as SyntaxThemeDark);
  const [syntaxThemeLight, setSyntaxThemeLight] = useState(() => loadStringPreference('syntaxThemeLight') as SyntaxThemeLight);

  // Markdown theme states
  const [mdThemeDark, setMdThemeDark] = useState(() => loadStringPreference('mdThemeDark') as MdTheme);
  const [mdThemeLight, setMdThemeLight] = useState(() => loadStringPreference('mdThemeLight') as MdTheme);

  // Font states
  const [fontFamily, setFontFamily] = useState(() => loadStringPreference('fontFamily') as FontFamilyId);
  const [fontFamilyMono, setFontFamilyMono] = useState(() => loadStringPreference('fontFamilyMono') as FontFamilyMonoId);
  const [fontSize, setFontSize] = useState(() => loadNumericPreference('fontSize'));
  const [fontSizeMono, setFontSizeMono] = useState(() => loadNumericPreference('fontSizeMono'));

  // Custom backgrounds state
  const [customBackgrounds, setCustomBackgrounds] = useState<CustomBackground[]>(() => loadCustomBackgrounds());

  // Combined list of all background options
  const allBackgroundPatterns = useMemo(() =>
    getAllBackgroundPatterns(customBackgrounds),
    [customBackgrounds]
  );

  // Apply diff colors as CSS variables
  useEffect(() => {
    document.documentElement.style.setProperty('--diff-color-added', diffColorAdded);
    document.documentElement.style.setProperty('--diff-color-removed', diffColorRemoved);
  }, [diffColorAdded, diffColorRemoved]);

  // Apply fonts as CSS variables
  useEffect(() => {
    const fontDef = FONT_FAMILIES.find(f => f.id === fontFamily);
    const fontMonoDef = FONT_FAMILIES_MONO.find(f => f.id === fontFamilyMono);

    const root = document.documentElement;
    if (fontDef) {
      root.style.setProperty('--font-family', fontDef.value);
    }
    if (fontMonoDef) {
      root.style.setProperty('--font-mono', fontMonoDef.value);
    }
    root.style.setProperty('--font-size-base', `${fontSize}px`);
    root.style.setProperty('--font-size-mono', `${fontSizeMono}px`);
  }, [fontFamily, fontFamilyMono, fontSize, fontSizeMono]);

  // Add a custom background
  const addCustomBackground = useCallback((name: string, svg: string, type: 'custom-pattern' | 'custom-full' | 'custom-image', fitMode?: CustomBgFitMode): string => {
    const id = `custom-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const newBg: CustomBackground = { id, name, type, svg, fitMode: fitMode || 'cover' };
    setCustomBackgrounds(prev => {
      const updated = [...prev, newBg];
      saveCustomBackgrounds(updated);
      return updated;
    });
    return id;
  }, []);

  // Remove a custom background
  const removeCustomBackground = useCallback((id: string) => {
    setCustomBackgrounds(prev => {
      const updated = prev.filter(bg => bg.id !== id);
      saveCustomBackgrounds(updated);
      return updated;
    });
  }, []);

  // Update a custom background
  const updateCustomBackground = useCallback((id: string, name: string, svg: string, type: 'custom-pattern' | 'custom-full' | 'custom-image', fitMode?: CustomBgFitMode) => {
    setCustomBackgrounds(prev => {
      const updated = prev.map(bg => bg.id === id ? { ...bg, name, svg, type, fitMode: fitMode || 'cover' } : bg);
      saveCustomBackgrounds(updated);
      return updated;
    });
  }, []);

  // Get a custom background by ID
  const getCustomBackground = useCallback((id: string): CustomBackground | undefined => {
    return customBackgrounds.find(bg => bg.id === id);
  }, [customBackgrounds]);

  // Generic boolean getter
  const getPreference = useCallback((key: PreferenceKey): boolean => {
    switch (key) {
      case 'expandToolCards': return expandToolCards;
      case 'showTokenCounts': return showTokenCounts;
      case 'voiceInputEnabled': return voiceInputEnabled;
      default: return DEFAULTS[key];
    }
  }, [expandToolCards, showTokenCounts, voiceInputEnabled]);

  // Generic boolean setter with persistence - use startTransition to mark as non-urgent
  const setPreference = useCallback((key: PreferenceKey, value: boolean) => {
    savePreference(key, value);
    startTransition(() => {
      switch (key) {
        case 'expandToolCards':
          setExpandToolCards(value);
          break;
        case 'showTokenCounts':
          setShowTokenCounts(value);
          break;
        case 'voiceInputEnabled':
          setVoiceInputEnabled(value);
          break;
      }
    });
  }, []);

  // Toggle a boolean preference
  const togglePreference = useCallback((key: PreferenceKey) => {
    const current = getPreference(key);
    setPreference(key, !current);
  }, [getPreference, setPreference]);

  // String preference getter
  const getStringPreference = useCallback((key: StringPreferenceKey): string => {
    switch (key) {
      case 'voiceInputHost': return voiceInputHost;
      case 'voiceInputPort': return voiceInputPort;
      case 'depthIndicatorStyle': return depthIndicatorStyle;
      case 'historyLoadMode': return historyLoadMode;
      case 'bgPatternSidebar': return bgPatternSidebar;
      case 'bgPatternMain': return bgPatternMain;
      case 'bgPatternDetail': return bgPatternDetail;
      case 'diffColorAdded': return diffColorAdded;
      case 'diffColorRemoved': return diffColorRemoved;
      case 'syntaxThemeDark': return syntaxThemeDark;
      case 'syntaxThemeLight': return syntaxThemeLight;
      case 'mdThemeDark': return mdThemeDark;
      case 'mdThemeLight': return mdThemeLight;
      case 'fontFamily': return fontFamily;
      case 'fontFamilyMono': return fontFamilyMono;
      default: return STRING_DEFAULTS[key];
    }
  }, [voiceInputHost, voiceInputPort, depthIndicatorStyle, historyLoadMode, bgPatternSidebar, bgPatternMain, bgPatternDetail, diffColorAdded, diffColorRemoved, syntaxThemeDark, syntaxThemeLight, mdThemeDark, mdThemeLight, fontFamily, fontFamilyMono]);

  // String preference setter with persistence
  const setStringPreference = useCallback((key: StringPreferenceKey, value: string) => {
    saveStringPreference(key, value);
    startTransition(() => {
      switch (key) {
        case 'voiceInputHost':
          setVoiceInputHost(value);
          break;
        case 'voiceInputPort':
          setVoiceInputPort(value);
          break;
        case 'depthIndicatorStyle':
          setDepthIndicatorStyle(value as 'chevrons' | 'fractal');
          break;
        case 'historyLoadMode':
          setHistoryLoadMode(value as HistoryLoadMode);
          break;
        case 'bgPatternSidebar':
          setBgPatternSidebar(value as BgPatternId);
          break;
        case 'bgPatternMain':
          setBgPatternMain(value as BgPatternId);
          break;
        case 'bgPatternDetail':
          setBgPatternDetail(value as BgPatternId);
          break;
        case 'diffColorAdded':
          setDiffColorAdded(value);
          break;
        case 'diffColorRemoved':
          setDiffColorRemoved(value);
          break;
        case 'syntaxThemeDark':
          setSyntaxThemeDark(value as SyntaxThemeDark);
          break;
        case 'syntaxThemeLight':
          setSyntaxThemeLight(value as SyntaxThemeLight);
          break;
        case 'mdThemeDark':
          setMdThemeDark(value as MdTheme);
          break;
        case 'mdThemeLight':
          setMdThemeLight(value as MdTheme);
          break;
        case 'fontFamily':
          setFontFamily(value as FontFamilyId);
          break;
        case 'fontFamilyMono':
          setFontFamilyMono(value as FontFamilyMonoId);
          break;
      }
    });
  }, []);

  // Numeric preference getter
  const getNumericPreference = useCallback((key: NumericPreferenceKey): number => {
    switch (key) {
      case 'autoscrollSpeed': return autoscrollSpeed;
      case 'bgOpacitySidebar': return bgOpacitySidebar;
      case 'bgOpacityMain': return bgOpacityMain;
      case 'bgOpacityDetail': return bgOpacityDetail;
      case 'bgScaleSidebar': return bgScaleSidebar;
      case 'bgScaleMain': return bgScaleMain;
      case 'bgScaleDetail': return bgScaleDetail;
      case 'fontSize': return fontSize;
      case 'fontSizeMono': return fontSizeMono;
      default: return NUMERIC_DEFAULTS[key];
    }
  }, [autoscrollSpeed, bgOpacitySidebar, bgOpacityMain, bgOpacityDetail, bgScaleSidebar, bgScaleMain, bgScaleDetail, fontSize, fontSizeMono]);

  // Numeric preference setter with persistence
  const setNumericPreference = useCallback((key: NumericPreferenceKey, value: number) => {
    saveNumericPreference(key, value);
    startTransition(() => {
      switch (key) {
        case 'autoscrollSpeed':
          setAutoscrollSpeed(value);
          break;
        case 'bgOpacitySidebar':
          setBgOpacitySidebar(value);
          break;
        case 'bgOpacityMain':
          setBgOpacityMain(value);
          break;
        case 'bgOpacityDetail':
          setBgOpacityDetail(value);
          break;
        case 'bgScaleSidebar':
          setBgScaleSidebar(value);
          break;
        case 'bgScaleMain':
          setBgScaleMain(value);
          break;
        case 'bgScaleDetail':
          setBgScaleDetail(value);
          break;
        case 'fontSize':
          setFontSize(value);
          break;
        case 'fontSizeMono':
          setFontSizeMono(value);
          break;
      }
    });
  }, []);

  const value = useMemo(() => ({
    expandToolCards,
    showTokenCounts,
    voiceInputEnabled,
    voiceInputHost,
    voiceInputPort,
    depthIndicatorStyle,
    historyLoadMode,
    autoscrollSpeed,
    bgPatternSidebar,
    bgPatternMain,
    bgPatternDetail,
    bgOpacitySidebar,
    bgOpacityMain,
    bgOpacityDetail,
    bgScaleSidebar,
    bgScaleMain,
    bgScaleDetail,
    diffColorAdded,
    diffColorRemoved,
    syntaxThemeDark,
    syntaxThemeLight,
    mdThemeDark,
    mdThemeLight,
    fontFamily,
    fontFamilyMono,
    fontSize,
    fontSizeMono,
    customBackgrounds,
    allBackgroundPatterns,
    addCustomBackground,
    updateCustomBackground,
    removeCustomBackground,
    getCustomBackground,
    getPreference,
    setPreference,
    togglePreference,
    getStringPreference,
    setStringPreference,
    getNumericPreference,
    setNumericPreference,
  }), [expandToolCards, showTokenCounts, voiceInputEnabled, voiceInputHost, voiceInputPort, depthIndicatorStyle, historyLoadMode, autoscrollSpeed, bgPatternSidebar, bgPatternMain, bgPatternDetail, bgOpacitySidebar, bgOpacityMain, bgOpacityDetail, bgScaleSidebar, bgScaleMain, bgScaleDetail, diffColorAdded, diffColorRemoved, syntaxThemeDark, syntaxThemeLight, mdThemeDark, mdThemeLight, fontFamily, fontFamilyMono, fontSize, fontSizeMono, customBackgrounds, allBackgroundPatterns, addCustomBackground, updateCustomBackground, removeCustomBackground, getCustomBackground, getPreference, setPreference, togglePreference, getStringPreference, setStringPreference, getNumericPreference, setNumericPreference]);

  return (
    <PreferencesContext.Provider value={value}>
      {children}
    </PreferencesContext.Provider>
  );
}

export function usePreferences(): PreferencesContextValue {
  const context = useContext(PreferencesContext);
  if (!context) {
    throw new Error('usePreferences must be used within a PreferencesProvider');
  }
  return context;
}

// Convenience hook for a single preference
export function usePreference(key: PreferenceKey): [boolean, (value: boolean) => void] {
  const { getPreference, setPreference } = usePreferences();
  const value = getPreference(key);
  const setValue = useCallback((newValue: boolean) => setPreference(key, newValue), [key, setPreference]);
  return [value, setValue];
}
