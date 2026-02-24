// Layout components
export { AppLayout } from './AppLayout';

// Layout context and hooks
export {
  LayoutProvider,
  useLayout,
  useBreakpoint,
  useMediaQuery,
  BREAKPOINTS,
} from './LayoutContext';

// Theme context and hooks
export {
  ThemeProvider,
  useTheme,
} from './ThemeContext';

// Preferences context and hooks
export {
  PreferencesProvider,
  usePreferences,
  usePreference,
} from './PreferencesContext';

// Types
export type {
  LayoutContextValue,
  LayoutMode,
  PanelId,
  PanelState,
  Breakpoint,
} from './LayoutContext';

export type {
  Theme,
  ResolvedTheme,
} from './ThemeContext';

export type {
  PreferenceKey,
  PreferencesContextValue,
} from './PreferencesContext';
