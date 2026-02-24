/**
 * PreferencesContext - Persistent UI preferences
 *
 * Stores user preferences in localStorage and provides them via React context.
 * Preferences include things like whether tool cards expand by default.
 */

import React, { createContext, useContext, useState, useCallback, useMemo, useEffect, startTransition } from 'react';

// Storage key prefix
const STORAGE_PREFIX = 'balloons:prefs:';

// Preference keys
export type PreferenceKey = 'expandToolCards' | 'showTokenCounts';

// Default values for each preference
const DEFAULTS: Record<PreferenceKey, boolean> = {
  expandToolCards: false, // Default: collapse tool cards (diffs, reads)
  showTokenCounts: true,  // Default: show token counts in headers
};

export interface PreferencesContextValue {
  // Individual preference getters
  expandToolCards: boolean;
  showTokenCounts: boolean;

  // Generic getter/setter
  getPreference: (key: PreferenceKey) => boolean;
  setPreference: (key: PreferenceKey, value: boolean) => void;
  togglePreference: (key: PreferenceKey) => void;
}

const PreferencesContext = createContext<PreferencesContextValue | null>(null);

// Load a preference from localStorage
function loadPreference(key: PreferenceKey): boolean {
  if (typeof window === 'undefined') return DEFAULTS[key];
  const stored = localStorage.getItem(STORAGE_PREFIX + key);
  if (stored === 'true') return true;
  if (stored === 'false') return false;
  return DEFAULTS[key];
}

// Save a preference to localStorage
function savePreference(key: PreferenceKey, value: boolean): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(STORAGE_PREFIX + key, String(value));
}

export function PreferencesProvider({ children }: { children: React.ReactNode }) {
  // Individual preference states
  const [expandToolCards, setExpandToolCards] = useState(() => loadPreference('expandToolCards'));
  const [showTokenCounts, setShowTokenCounts] = useState(() => loadPreference('showTokenCounts'));

  // Generic getter
  const getPreference = useCallback((key: PreferenceKey): boolean => {
    switch (key) {
      case 'expandToolCards': return expandToolCards;
      case 'showTokenCounts': return showTokenCounts;
      default: return DEFAULTS[key];
    }
  }, [expandToolCards, showTokenCounts]);

  // Generic setter with persistence - use startTransition to mark as non-urgent
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
      }
    });
  }, []);

  // Toggle a preference
  const togglePreference = useCallback((key: PreferenceKey) => {
    const current = getPreference(key);
    setPreference(key, !current);
  }, [getPreference, setPreference]);

  const value = useMemo(() => ({
    expandToolCards,
    showTokenCounts,
    getPreference,
    setPreference,
    togglePreference,
  }), [expandToolCards, showTokenCounts, getPreference, setPreference, togglePreference]);

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
