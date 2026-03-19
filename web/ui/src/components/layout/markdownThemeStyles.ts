/**
 * Markdown Theme Definitions
 *
 * Each theme defines CSS variable values for markdown styling.
 * The appropriate theme variables are applied to :root based on
 * user preference and current app theme (light/dark).
 */

export interface MarkdownThemeVars {
  headingColor: string;
  headingWeight: string;
  h1Size: string;
  h2Size: string;
  h3Size: string;
  linkColor: string;
  linkHoverDecoration: string;
  blockquoteBorder: string;
  blockquoteBg: string;
  inlineCodeBg: string;
  inlineCodeColor: string;
}

// Dark mode theme definitions
export const DARK_MD_THEMES: Record<string, MarkdownThemeVars> = {
  default: {
    headingColor: 'var(--text-primary)',
    headingWeight: '600',
    h1Size: '1.5em',
    h2Size: '1.3em',
    h3Size: '1.15em',
    linkColor: 'var(--accent)',
    linkHoverDecoration: 'underline',
    blockquoteBorder: 'var(--accent-assistant, #f87171)',
    blockquoteBg: 'rgba(248, 113, 113, 0.1)',
    inlineCodeBg: 'var(--bg-code, #1a1a1a)',
    inlineCodeColor: 'var(--text-primary)',
  },
  github: {
    headingColor: '#c9d1d9',
    headingWeight: '600',
    h1Size: '1.5em',
    h2Size: '1.3em',
    h3Size: '1.15em',
    linkColor: '#58a6ff',
    linkHoverDecoration: 'underline',
    blockquoteBorder: '#3b5998',
    blockquoteBg: 'rgba(59, 89, 152, 0.1)',
    inlineCodeBg: 'rgba(110, 118, 129, 0.4)',
    inlineCodeColor: '#c9d1d9',
  },
  notion: {
    headingColor: '#e6e6e6',
    headingWeight: '700',
    h1Size: '1.875em',
    h2Size: '1.5em',
    h3Size: '1.25em',
    linkColor: '#6b9fed',
    linkHoverDecoration: 'underline',
    blockquoteBorder: '#505050',
    blockquoteBg: 'rgba(80, 80, 80, 0.2)',
    inlineCodeBg: 'rgba(135, 131, 120, 0.15)',
    inlineCodeColor: '#eb5757',
  },
  obsidian: {
    headingColor: '#a88bfa',
    headingWeight: '600',
    h1Size: '1.5em',
    h2Size: '1.3em',
    h3Size: '1.15em',
    linkColor: '#7f6df2',
    linkHoverDecoration: 'underline',
    blockquoteBorder: '#7f6df2',
    blockquoteBg: 'rgba(127, 109, 242, 0.1)',
    inlineCodeBg: 'rgba(127, 109, 242, 0.2)',
    inlineCodeColor: '#e2e2e2',
  },
  typora: {
    headingColor: '#f0f0f0',
    headingWeight: '700',
    h1Size: '2em',
    h2Size: '1.6em',
    h3Size: '1.3em',
    linkColor: '#4183c4',
    linkHoverDecoration: 'underline',
    blockquoteBorder: '#b8b8b8',
    blockquoteBg: 'transparent',
    inlineCodeBg: 'rgba(27, 31, 35, 0.85)',
    inlineCodeColor: '#e8e8e8',
  },
  minimal: {
    headingColor: 'var(--text-primary)',
    headingWeight: '500',
    h1Size: '1.4em',
    h2Size: '1.2em',
    h3Size: '1.1em',
    linkColor: 'var(--text-secondary)',
    linkHoverDecoration: 'underline',
    blockquoteBorder: 'var(--text-tertiary)',
    blockquoteBg: 'transparent',
    inlineCodeBg: 'var(--bg-secondary)',
    inlineCodeColor: 'var(--text-primary)',
  },
};

// Light mode theme definitions
export const LIGHT_MD_THEMES: Record<string, MarkdownThemeVars> = {
  default: {
    headingColor: 'var(--text-primary)',
    headingWeight: '600',
    h1Size: '1.5em',
    h2Size: '1.3em',
    h3Size: '1.15em',
    linkColor: 'var(--accent)',
    linkHoverDecoration: 'underline',
    blockquoteBorder: 'var(--accent-assistant, #dc2626)',
    blockquoteBg: 'rgba(220, 38, 38, 0.08)',
    inlineCodeBg: 'var(--bg-code, #f0f0f0)',
    inlineCodeColor: 'var(--text-primary)',
  },
  github: {
    headingColor: '#24292f',
    headingWeight: '600',
    h1Size: '1.5em',
    h2Size: '1.3em',
    h3Size: '1.15em',
    linkColor: '#0969da',
    linkHoverDecoration: 'underline',
    blockquoteBorder: '#d0d7de',
    blockquoteBg: 'rgba(208, 215, 222, 0.2)',
    inlineCodeBg: 'rgba(175, 184, 193, 0.2)',
    inlineCodeColor: '#24292f',
  },
  notion: {
    headingColor: '#37352f',
    headingWeight: '700',
    h1Size: '1.875em',
    h2Size: '1.5em',
    h3Size: '1.25em',
    linkColor: '#2f81f7',
    linkHoverDecoration: 'underline',
    blockquoteBorder: '#e3e2e0',
    blockquoteBg: 'rgba(227, 226, 224, 0.3)',
    inlineCodeBg: 'rgba(135, 131, 120, 0.15)',
    inlineCodeColor: '#eb5757',
  },
  obsidian: {
    headingColor: '#705dcf',
    headingWeight: '600',
    h1Size: '1.5em',
    h2Size: '1.3em',
    h3Size: '1.15em',
    linkColor: '#705dcf',
    linkHoverDecoration: 'underline',
    blockquoteBorder: '#705dcf',
    blockquoteBg: 'rgba(112, 93, 207, 0.08)',
    inlineCodeBg: 'rgba(112, 93, 207, 0.12)',
    inlineCodeColor: '#1e1e1e',
  },
  typora: {
    headingColor: '#333',
    headingWeight: '700',
    h1Size: '2em',
    h2Size: '1.6em',
    h3Size: '1.3em',
    linkColor: '#4183c4',
    linkHoverDecoration: 'underline',
    blockquoteBorder: '#dfe2e5',
    blockquoteBg: 'transparent',
    inlineCodeBg: '#f3f4f4',
    inlineCodeColor: '#333',
  },
  minimal: {
    headingColor: 'var(--text-primary)',
    headingWeight: '500',
    h1Size: '1.4em',
    h2Size: '1.2em',
    h3Size: '1.1em',
    linkColor: 'var(--text-secondary)',
    linkHoverDecoration: 'underline',
    blockquoteBorder: 'var(--text-tertiary)',
    blockquoteBg: 'transparent',
    inlineCodeBg: 'var(--bg-secondary)',
    inlineCodeColor: 'var(--text-primary)',
  },
};

/**
 * Apply markdown theme CSS variables to document root
 */
export function applyMarkdownTheme(themeId: string, isDark: boolean): void {
  const themes = isDark ? DARK_MD_THEMES : LIGHT_MD_THEMES;
  const theme = themes[themeId] ?? themes.default;

  if (!theme) {
    console.warn('[MarkdownTheme] No theme found for:', themeId);
    return;
  }

  const root = document.documentElement;
  root.style.setProperty('--md-heading-color', theme.headingColor);
  root.style.setProperty('--md-heading-weight', theme.headingWeight);
  root.style.setProperty('--md-h1-size', theme.h1Size);
  root.style.setProperty('--md-h2-size', theme.h2Size);
  root.style.setProperty('--md-h3-size', theme.h3Size);
  root.style.setProperty('--md-link-color', theme.linkColor);
  root.style.setProperty('--md-link-hover-decoration', theme.linkHoverDecoration);
  root.style.setProperty('--md-blockquote-border', theme.blockquoteBorder);
  root.style.setProperty('--md-blockquote-bg', theme.blockquoteBg);
  root.style.setProperty('--md-inline-code-bg', theme.inlineCodeBg);
  root.style.setProperty('--md-inline-code-color', theme.inlineCodeColor);
}
