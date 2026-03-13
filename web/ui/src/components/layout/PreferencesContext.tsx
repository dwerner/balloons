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
export type StringPreferenceKey = 'voiceInputHost' | 'voiceInputPort' | 'depthIndicatorStyle';

// Default values for string preferences
const STRING_DEFAULTS: Record<StringPreferenceKey, string> = {
  voiceInputHost: '192.168.0.120',
  voiceInputPort: '8012',
  depthIndicatorStyle: 'chevrons', // 'chevrons' | 'fractal'
};

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

  // Generic getter/setter (boolean)
  getPreference: (key: PreferenceKey) => boolean;
  setPreference: (key: PreferenceKey, value: boolean) => void;
  togglePreference: (key: PreferenceKey) => void;

  // String preference getter/setter
  getStringPreference: (key: StringPreferenceKey) => string;
  setStringPreference: (key: StringPreferenceKey, value: string) => void;
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

export function PreferencesProvider({ children }: { children: React.ReactNode }) {
  // Individual boolean preference states
  const [expandToolCards, setExpandToolCards] = useState(() => loadPreference('expandToolCards'));
  const [showTokenCounts, setShowTokenCounts] = useState(() => loadPreference('showTokenCounts'));
  const [voiceInputEnabled, setVoiceInputEnabled] = useState(() => loadPreference('voiceInputEnabled'));

  // String preference states
  const [voiceInputHost, setVoiceInputHost] = useState(() => loadStringPreference('voiceInputHost'));
  const [voiceInputPort, setVoiceInputPort] = useState(() => loadStringPreference('voiceInputPort'));
  const [depthIndicatorStyle, setDepthIndicatorStyle] = useState(() => loadStringPreference('depthIndicatorStyle') as 'chevrons' | 'fractal');

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
      default: return STRING_DEFAULTS[key];
    }
  }, [voiceInputHost, voiceInputPort, depthIndicatorStyle]);

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
    getPreference,
    setPreference,
    togglePreference,
    getStringPreference,
    setStringPreference,
  }), [expandToolCards, showTokenCounts, voiceInputEnabled, voiceInputHost, voiceInputPort, depthIndicatorStyle, getPreference, setPreference, togglePreference, getStringPreference, setStringPreference]);

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
