/**
 * MarkdownThemeApplicator - Applies markdown theme CSS variables based on preferences
 *
 * This component doesn't render anything - it just applies the selected
 * markdown theme's CSS variables to the document root whenever the
 * theme preference or app theme changes.
 */

import { useEffect } from 'react';
import { useTheme } from './ThemeContext';
import { usePreferences } from './PreferencesContext';
import { applyMarkdownTheme } from './markdownThemeStyles';

export function MarkdownThemeApplicator(): null {
  const { resolvedTheme } = useTheme();
  const { mdThemeDark, mdThemeLight } = usePreferences();

  useEffect(() => {
    const isDark = resolvedTheme !== 'light';
    const themeId = isDark ? mdThemeDark : mdThemeLight;
    applyMarkdownTheme(themeId, isDark);
  }, [resolvedTheme, mdThemeDark, mdThemeLight]);

  return null;
}

export default MarkdownThemeApplicator;
