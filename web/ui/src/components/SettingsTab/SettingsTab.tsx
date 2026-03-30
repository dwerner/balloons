/**
 * SettingsTab - Application settings panel
 *
 * Contains cards for:
 * - Appearance Settings: Theme, wake lock
 * - Sound Settings: Enable/disable sounds, select sound files for events, volume control
 *
 * URL ROUTING: This is a global tab at #/settings
 * - Sub-sections could use hash fragments: #/settings#sounds
 * - See docs/url-routing.md for the full routing design
 */

import React, { memo, useCallback, useState } from 'react';
import type { SoundInfo } from '../../../../generated/types';
import type { SoundConfig } from '../../hooks/useSoundNotifications';
import { useTheme } from '../layout/ThemeContext';
import { useWakeLock } from '../../hooks/useWakeLock';
import { usePreferences, SYNTAX_THEMES_DARK, SYNTAX_THEMES_LIGHT, MD_THEMES, FONT_FAMILIES, FONT_FAMILIES_MONO } from '../layout/PreferencesContext';
import { SyntaxHighlightedCode } from '../StreamingTurnsView/cards/SyntaxHighlighter';
import { MarkdownContent } from '../../MarkdownContent';
import { getMarkdownThemeStyle } from '../layout/markdownThemeStyles';
import '../layout/MarkdownThemes.css';
import './SettingsTab.css';

// Sample code snippets for different languages
const CODE_SAMPLES = {
  typescript: `interface User {
  id: string;
  name: string;
  email?: string;
}

async function fetchUser(id: string): Promise<User> {
  const response = await fetch(\`/api/users/\${id}\`);
  if (!response.ok) {
    throw new Error('User not found');
  }
  return response.json();
}`,
  python: `from dataclasses import dataclass
from typing import Optional

@dataclass
class User:
    id: str
    name: str
    email: Optional[str] = None

async def fetch_user(user_id: str) -> User:
    """Fetch a user by ID."""
    async with session.get(f"/api/users/{user_id}") as resp:
        data = await resp.json()
        return User(**data)`,
  rust: `#[derive(Debug, Clone)]
struct User {
    id: String,
    name: String,
    email: Option<String>,
}

impl User {
    async fn fetch(id: &str) -> Result<Self, Error> {
        let url = format!("/api/users/{}", id);
        let resp = reqwest::get(&url).await?;
        let user: User = resp.json().await?;
        Ok(user)
    }
}`,
  go: `type User struct {
    ID    string \`json:"id"\`
    Name  string \`json:"name"\`
    Email string \`json:"email,omitempty"\`
}

func FetchUser(ctx context.Context, id string) (*User, error) {
    url := fmt.Sprintf("/api/users/%s", id)
    resp, err := http.Get(url)
    if err != nil {
        return nil, err
    }
    defer resp.Body.Close()

    var user User
    json.NewDecoder(resp.Body).Decode(&user)
    return &user, nil
}`,
  css: `.user-card {
  display: flex;
  flex-direction: column;
  padding: 16px;
  background: var(--bg-primary);
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.user-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
}`,
};

type CodeLanguage = keyof typeof CODE_SAMPLES;

/**
 * Preview component showing code samples in different languages
 */
const SyntaxThemePreview = memo(function SyntaxThemePreview() {
  const [selectedLang, setSelectedLang] = useState<CodeLanguage>('typescript');

  const languages: { id: CodeLanguage; name: string }[] = [
    { id: 'typescript', name: 'TypeScript' },
    { id: 'python', name: 'Python' },
    { id: 'rust', name: 'Rust' },
    { id: 'go', name: 'Go' },
    { id: 'css', name: 'CSS' },
  ];

  return (
    <div className="syntax-theme-preview">
      <div className="syntax-theme-preview__header">
        <span className="syntax-theme-preview__label">Preview</span>
        <div className="syntax-theme-preview__tabs">
          {languages.map(lang => (
            <button
              key={lang.id}
              className={`syntax-theme-preview__tab ${selectedLang === lang.id ? 'syntax-theme-preview__tab--active' : ''}`}
              onClick={() => setSelectedLang(lang.id)}
            >
              {lang.name}
            </button>
          ))}
        </div>
      </div>
      <div className="syntax-theme-preview__code">
        <SyntaxHighlightedCode
          code={CODE_SAMPLES[selectedLang]}
          language={selectedLang}
        />
      </div>
    </div>
  );
});

// Sample markdown content for preview
const MARKDOWN_SAMPLE = `# Heading 1

## Heading 2

### Heading 3

This is a paragraph with **bold text**, *italic text*, and \`inline code\`.

> This is a blockquote. It can contain multiple lines
> and is commonly used for callouts or quotes.

Here's a [link to documentation](https://example.com).

- First bullet point
- Second bullet point
- Third bullet point

1. First numbered item
2. Second numbered item
`;

/**
 * Preview component showing markdown with the selected theme.
 *
 * Uses inline CSS variables on the preview container for immediate live preview.
 * The global MarkdownThemeApplicator applies the same theme to :root for the
 * main content area, but inline styles here ensure the preview updates immediately
 * without waiting for the next render cycle.
 */
const MarkdownThemePreview = memo(function MarkdownThemePreview() {
  const { mdThemeDark, mdThemeLight } = usePreferences();
  const { resolvedTheme } = useTheme();

  const isDark = resolvedTheme !== 'light';
  const currentTheme = isDark ? mdThemeDark : mdThemeLight;

  // Get inline CSS variables for the current theme
  // This ensures the preview updates immediately when the user changes themes
  const themeStyle = getMarkdownThemeStyle(currentTheme, isDark);

  return (
    <div className="md-theme-preview" style={themeStyle}>
      <div className="md-theme-preview__header">
        <span className="md-theme-preview__label">Preview</span>
        {/* Color indicator using the inline CSS var to show current theme color */}
        <span style={{ color: 'var(--md-heading-color)', marginLeft: 8, fontWeight: 'bold' }}>●</span>
      </div>
      <div className="md-theme-preview__content">
        <MarkdownContent content={MARKDOWN_SAMPLE} />
      </div>
    </div>
  );
});

interface SettingsTabProps {
  /** Whether connected to the server */
  isConnected: boolean;
  /** Whether sounds are globally enabled */
  soundEnabled: boolean;
  /** Toggle sound enabled state */
  onToggleSound: () => void;
  /** Full sound configuration */
  soundConfig: SoundConfig;
  /** Available sounds from server */
  availableSounds: SoundInfo[];
  /** Update sound for a specific event */
  onSetSoundForEvent: (event: 'streamDone' | 'streamError', filename: string | null) => void;
  /** Set volume (0-1) */
  onSetVolume: (volume: number) => void;
  /** Play a sound preview */
  onPlaySound: (filename: string) => Promise<void>;
  /** Refresh available sounds */
  onRefreshSounds: () => Promise<void>;
  /** Loading state */
  isLoading: boolean;
  /** Error state */
  error: string | null;
}

export const SettingsTab = memo(function SettingsTab({
  isConnected,
  soundEnabled,
  onToggleSound,
  soundConfig,
  availableSounds,
  onSetSoundForEvent,
  onSetVolume,
  onPlaySound,
  onRefreshSounds,
  isLoading,
  error,
}: SettingsTabProps) {
  // Theme and wake lock hooks
  const { resolvedTheme, setTheme } = useTheme();
  const { isActive: wakeLockActive, isSupported: wakeLockSupported, toggle: toggleWakeLock } = useWakeLock();

  // Preferences
  const {
    voiceInputEnabled,
    voiceInputHost,
    voiceInputPort,
    depthIndicatorStyle,
    historyLoadMode,
    autoscrollSpeed,
    autoscrollInstant,
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
    cardBgOpacity,
    cardBgPattern,
    cardBgPatternOpacity,
    cardBgPatternScale,
    allBackgroundPatterns,
    customBackgrounds,
    addCustomBackground,
    updateCustomBackground,
    removeCustomBackground,
    setPreference,
    setStringPreference,
    getNumericPreference,
    setNumericPreference,
  } = usePreferences();

  // Local state for voice input form inputs (to avoid constant saves while typing)
  const [localHost, setLocalHost] = useState(voiceInputHost);
  const [localPort, setLocalPort] = useState(voiceInputPort);

  // Local state for adding/editing custom backgrounds
  const [showAddCustomBg, setShowAddCustomBg] = useState(false);
  const [editingBgId, setEditingBgId] = useState<string | null>(null);
  const [customBgName, setCustomBgName] = useState('');
  const [customBgSvg, setCustomBgSvg] = useState('');
  const [customBgType, setCustomBgType] = useState<'custom-pattern' | 'custom-full' | 'custom-image'>('custom-pattern');
  const [customBgFitMode, setCustomBgFitMode] = useState<'cover' | 'contain' | 'fill' | 'none'>('cover');
  const [imagePreview, setImagePreview] = useState<string | null>(null);

  // Handle adding a custom background
  const handleAddCustomBg = useCallback(() => {
    if (customBgName.trim() && customBgSvg.trim()) {
      const fitMode = (customBgType === 'custom-full' || customBgType === 'custom-image') ? customBgFitMode : undefined;
      if (editingBgId) {
        updateCustomBackground(editingBgId, customBgName.trim(), customBgSvg.trim(), customBgType, fitMode);
        setEditingBgId(null);
      } else {
        addCustomBackground(customBgName.trim(), customBgSvg.trim(), customBgType, fitMode);
      }
      setCustomBgName('');
      setCustomBgSvg('');
      setCustomBgFitMode('cover');
      setImagePreview(null);
      setShowAddCustomBg(false);
    }
  }, [customBgName, customBgSvg, customBgType, customBgFitMode, editingBgId, addCustomBackground, updateCustomBackground]);

  // Handle image file selection
  const handleImageFile = useCallback((file: File) => {
    if (!file.type.startsWith('image/')) {
      return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
      const dataUrl = e.target?.result as string;
      setCustomBgSvg(dataUrl);
      setImagePreview(dataUrl);
      setCustomBgType('custom-image');
      if (!customBgName.trim()) {
        setCustomBgName(file.name.replace(/\.[^/.]+$/, ''));
      }
    };
    reader.readAsDataURL(file);
  }, [customBgName]);

  // Handle paste event for images
  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;

    for (const item of items) {
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) {
          e.preventDefault();
          handleImageFile(file);
          return;
        }
      }
    }
  }, [handleImageFile]);

  // Handle drop event for images
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const files = e.dataTransfer?.files;
    if (files && files.length > 0) {
      const file = files[0];
      if (file && file.type.startsWith('image/')) {
        handleImageFile(file);
      }
    }
  }, [handleImageFile]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
  }, []);

  // Start editing a custom background
  const handleEditCustomBg = useCallback((bg: { id: string; name: string; svg: string; type: 'custom-pattern' | 'custom-full' | 'custom-image'; fitMode?: 'cover' | 'contain' | 'fill' | 'none' }) => {
    setEditingBgId(bg.id);
    setCustomBgName(bg.name);
    setCustomBgSvg(bg.svg);
    setCustomBgType(bg.type);
    setCustomBgFitMode(bg.fitMode || 'cover');
    // For images, set up preview
    if (bg.type === 'custom-image') {
      setImagePreview(bg.svg);
    } else {
      setImagePreview(null);
    }
    setShowAddCustomBg(true);
  }, []);

  // Cancel editing
  const handleCancelEdit = useCallback(() => {
    setEditingBgId(null);
    setCustomBgName('');
    setCustomBgSvg('');
    setCustomBgFitMode('cover');
    setImagePreview(null);
    setShowAddCustomBg(false);
  }, []);

  // Save voice input settings when blurred
  const handleVoiceHostBlur = useCallback(() => {
    if (localHost !== voiceInputHost) {
      setStringPreference('voiceInputHost', localHost);
    }
  }, [localHost, voiceInputHost, setStringPreference]);

  const handleVoicePortBlur = useCallback(() => {
    if (localPort !== voiceInputPort) {
      setStringPreference('voiceInputPort', localPort);
    }
  }, [localPort, voiceInputPort, setStringPreference]);

  // Handle volume change
  const handleVolumeChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    onSetVolume(parseFloat(e.target.value));
  }, [onSetVolume]);

  // Handle sound selection
  const handleStreamDoneChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value;
    onSetSoundForEvent('streamDone', value === '' ? null : value);
  }, [onSetSoundForEvent]);

  const handleStreamErrorChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value;
    onSetSoundForEvent('streamError', value === '' ? null : value);
  }, [onSetSoundForEvent]);

  // Preview sound
  const handlePreview = useCallback(async (filename: string | null) => {
    if (filename) {
      await onPlaySound(filename);
    }
  }, [onPlaySound]);

  if (!isConnected) {
    return (
      <div className="settings-tab">
        <div className="settings-tab__disconnected">
          Connect to server to configure settings
        </div>
      </div>
    );
  }

  return (
    <div className="settings-tab">
      {/* Appearance Settings Card */}
      <div className="settings-card">
        <div className="settings-card__header">
          <h3 className="settings-card__title">Appearance</h3>
        </div>

        <div className="settings-card__content">
          <div className="appearance-settings">
            {/* Theme selector */}
            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Theme</span>
                <span className="appearance-settings__label-description">
                  Choose your preferred color scheme
                </span>
              </div>
              <div className="appearance-settings__control">
                <select
                  className="appearance-settings__select"
                  value={resolvedTheme}
                  onChange={(e) => setTheme(e.target.value as 'dark' | 'dark-flat' | 'light')}
                >
                  <option value="dark">Dark</option>
                  <option value="dark-flat">Dark Flat</option>
                  <option value="light">Light</option>
                </select>
              </div>
            </div>

            {/* Wake lock toggle */}
            {wakeLockSupported && (
              <div className="appearance-settings__row">
                <div className="appearance-settings__label">
                  <span className="appearance-settings__label-text">Keep Screen Awake</span>
                  <span className="appearance-settings__label-description">
                    Prevent screen from sleeping while app is open
                  </span>
                </div>
                <div className="appearance-settings__control">
                  <label className="appearance-settings__toggle">
                    <input
                      type="checkbox"
                      checked={wakeLockActive}
                      onChange={toggleWakeLock}
                    />
                    <span className="appearance-settings__toggle-slider" />
                  </label>
                </div>
              </div>
            )}

            {/* Depth indicator style */}
            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Depth Indicator Style</span>
                <span className="appearance-settings__label-description">
                  How to show session tree depth in Leaves mode
                </span>
              </div>
              <div className="appearance-settings__control">
                <select
                  className="appearance-settings__select"
                  value={depthIndicatorStyle}
                  onChange={(e) => setStringPreference('depthIndicatorStyle', e.target.value)}
                >
                  <option value="chevrons">Chevrons (stacked notches)</option>
                  <option value="fractal">Dragon Curve (video wall)</option>
                </select>
              </div>
            </div>

            {/* History loading mode */}
            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">History Loading</span>
                <span className="appearance-settings__label-description">
                  How to load conversation history on session open
                </span>
              </div>
              <div className="appearance-settings__control">
                <select
                  className="appearance-settings__select"
                  value={historyLoadMode}
                  onChange={(e) => setStringPreference('historyLoadMode', e.target.value)}
                >
                  <option value="reverse">Newest first (fast startup)</option>
                  <option value="forward">Oldest first (chronological)</option>
                  <option value="lazy">On-demand (scroll to load)</option>
                </select>
              </div>
            </div>

            {/* Auto-scroll instant toggle */}
            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Instant Auto-scroll</span>
                <span className="appearance-settings__label-description">
                  Jump to bottom immediately instead of animating
                </span>
              </div>
              <div className="appearance-settings__control">
                <label className="appearance-settings__toggle">
                  <input
                    type="checkbox"
                    checked={autoscrollInstant}
                    onChange={() => setPreference('autoscrollInstant', !autoscrollInstant)}
                  />
                  <span className="appearance-settings__toggle-slider" />
                </label>
              </div>
            </div>

            {/* Auto-scroll speed slider */}
            <div className={`appearance-settings__row ${autoscrollInstant ? 'appearance-settings__row--disabled' : ''}`}>
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Auto-scroll Speed</span>
                <span className="appearance-settings__label-description">
                  Speed when following new content ({autoscrollSpeed} px/s)
                </span>
              </div>
              <div className="appearance-settings__control appearance-settings__control--slider">
                <input
                  type="range"
                  className="appearance-settings__slider"
                  min={100}
                  max={400}
                  step={25}
                  value={autoscrollSpeed}
                  onChange={(e) => setNumericPreference('autoscrollSpeed', parseInt(e.target.value, 10))}
                  disabled={autoscrollInstant}
                />
              </div>
            </div>

            {/* Diff colors */}
            <div className="appearance-settings__section-divider" />

            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Diff Color: Additions</span>
                <span className="appearance-settings__label-description">
                  Color for added lines in diffs
                </span>
              </div>
              <div className="appearance-settings__control">
                <input
                  type="color"
                  className="appearance-settings__color-picker"
                  value={diffColorAdded}
                  onChange={(e) => setStringPreference('diffColorAdded', e.target.value)}
                />
              </div>
            </div>

            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Diff Color: Removals</span>
                <span className="appearance-settings__label-description">
                  Color for removed lines in diffs
                </span>
              </div>
              <div className="appearance-settings__control">
                <input
                  type="color"
                  className="appearance-settings__color-picker"
                  value={diffColorRemoved}
                  onChange={(e) => setStringPreference('diffColorRemoved', e.target.value)}
                />
              </div>
            </div>

            {/* Syntax highlighting themes */}
            <div className="appearance-settings__section-divider" />

            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Syntax Theme (Dark)</span>
                <span className="appearance-settings__label-description">
                  Code highlighting theme for dark mode
                </span>
              </div>
              <div className="appearance-settings__control">
                <select
                  className="appearance-settings__select"
                  value={syntaxThemeDark}
                  onChange={(e) => setStringPreference('syntaxThemeDark', e.target.value)}
                >
                  {SYNTAX_THEMES_DARK.map((theme) => (
                    <option key={theme.id} value={theme.id}>
                      {theme.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Syntax Theme (Light)</span>
                <span className="appearance-settings__label-description">
                  Code highlighting theme for light mode
                </span>
              </div>
              <div className="appearance-settings__control">
                <select
                  className="appearance-settings__select"
                  value={syntaxThemeLight}
                  onChange={(e) => setStringPreference('syntaxThemeLight', e.target.value)}
                >
                  {SYNTAX_THEMES_LIGHT.map((theme) => (
                    <option key={theme.id} value={theme.id}>
                      {theme.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Code preview */}
            <SyntaxThemePreview />

            {/* Markdown themes */}
            <div className="appearance-settings__section-divider" />

            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Markdown Theme (Dark)</span>
                <span className="appearance-settings__label-description">
                  Styling for headings, links, blockquotes in dark mode
                </span>
              </div>
              <div className="appearance-settings__control">
                <select
                  className="appearance-settings__select"
                  value={mdThemeDark}
                  onChange={(e) => setStringPreference('mdThemeDark', e.target.value)}
                >
                  {MD_THEMES.map((theme) => (
                    <option key={theme.id} value={theme.id}>
                      {theme.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Markdown Theme (Light)</span>
                <span className="appearance-settings__label-description">
                  Styling for headings, links, blockquotes in light mode
                </span>
              </div>
              <div className="appearance-settings__control">
                <select
                  className="appearance-settings__select"
                  value={mdThemeLight}
                  onChange={(e) => setStringPreference('mdThemeLight', e.target.value)}
                >
                  {MD_THEMES.map((theme) => (
                    <option key={theme.id} value={theme.id}>
                      {theme.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Markdown preview */}
            <MarkdownThemePreview />

            {/* Font settings */}
            <div className="appearance-settings__section-divider" />

            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">UI Font</span>
                <span className="appearance-settings__label-description">
                  Font for text throughout the interface
                </span>
              </div>
              <div className="appearance-settings__control">
                <select
                  className="appearance-settings__select"
                  value={fontFamily}
                  onChange={(e) => setStringPreference('fontFamily', e.target.value)}
                >
                  {FONT_FAMILIES.map((font) => (
                    <option key={font.id} value={font.id}>
                      {font.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">UI Font Size</span>
                <span className="appearance-settings__label-description">
                  Base font size: {fontSize}px
                </span>
              </div>
              <div className="appearance-settings__control">
                <input
                  type="range"
                  className="appearance-settings__slider"
                  min="10"
                  max="20"
                  step="1"
                  value={fontSize}
                  onChange={(e) => setNumericPreference('fontSize', Number(e.target.value))}
                />
              </div>
            </div>

            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Code Font</span>
                <span className="appearance-settings__label-description">
                  Monospace font for code and editors
                </span>
              </div>
              <div className="appearance-settings__control">
                <select
                  className="appearance-settings__select"
                  value={fontFamilyMono}
                  onChange={(e) => setStringPreference('fontFamilyMono', e.target.value)}
                >
                  {FONT_FAMILIES_MONO.map((font) => (
                    <option key={font.id} value={font.id}>
                      {font.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Code Font Size</span>
                <span className="appearance-settings__label-description">
                  Monospace font size: {fontSizeMono}px
                </span>
              </div>
              <div className="appearance-settings__control">
                <input
                  type="range"
                  className="appearance-settings__slider"
                  min="10"
                  max="20"
                  step="1"
                  value={fontSizeMono}
                  onChange={(e) => setNumericPreference('fontSizeMono', Number(e.target.value))}
                />
              </div>
            </div>

            {/* Font preview */}
            <div className="font-preview">
              <div className="font-preview__header">
                <span className="font-preview__label">Preview</span>
              </div>
              <div className="font-preview__content">
                <div className="font-preview__section">
                  <span className="font-preview__section-label">
                    UI Font: {FONT_FAMILIES.find(f => f.id === fontFamily)?.name || 'System'}
                  </span>
                  <p className="font-preview__ui-text">
                    The quick brown fox jumps over the lazy dog. 0123456789
                  </p>
                </div>
                <div className="font-preview__section">
                  <span className="font-preview__section-label">
                    Code Font: {FONT_FAMILIES_MONO.find(f => f.id === fontFamilyMono)?.name || 'System Mono'}
                  </span>
                  <div className="font-preview__code-wrapper">
                    <SyntaxHighlightedCode
                      code={`const greeting = "Hello, World!";\nfunction fibonacci(n: number): number {\n  return n <= 1 ? n : fibonacci(n-1) + fibonacci(n-2);\n}`}
                      language="typescript"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Background Patterns Settings Card */}
      <div className="settings-card">
        <div className="settings-card__header">
          <h3 className="settings-card__title">Background Patterns</h3>
        </div>

        <div className="settings-card__content">
          <div className="appearance-settings">
            {/* Sidebar pattern */}
            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Left Pane (Sidebar)</span>
                <span className="appearance-settings__label-description">
                  Background pattern for the session list
                </span>
              </div>
              <div className="appearance-settings__control">
                <select
                  className="appearance-settings__select"
                  value={bgPatternSidebar}
                  onChange={(e) => setStringPreference('bgPatternSidebar', e.target.value)}
                >
                  {allBackgroundPatterns.map((pattern) => (
                    <option key={pattern.id} value={pattern.id}>
                      {pattern.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Sidebar opacity */}
            <div className={`appearance-settings__row appearance-settings__row--indent ${bgPatternSidebar === 'none' ? 'appearance-settings__row--disabled' : ''}`}>
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Opacity</span>
                <span className="appearance-settings__label-description">
                  {Math.round(bgOpacitySidebar * 100)}%
                </span>
              </div>
              <div className="appearance-settings__control appearance-settings__control--slider">
                <input
                  type="range"
                  className="appearance-settings__slider"
                  min={0}
                  max={0.5}
                  step={0.02}
                  value={bgOpacitySidebar}
                  onChange={(e) => setNumericPreference('bgOpacitySidebar', parseFloat(e.target.value))}
                  disabled={bgPatternSidebar === 'none'}
                />
              </div>
            </div>

            {/* Sidebar scale */}
            <div className={`appearance-settings__row appearance-settings__row--indent ${bgPatternSidebar === 'none' ? 'appearance-settings__row--disabled' : ''}`}>
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Scale</span>
                <span className="appearance-settings__label-description">
                  {bgScaleSidebar.toFixed(1)}x
                </span>
              </div>
              <div className="appearance-settings__control appearance-settings__control--slider">
                <input
                  type="range"
                  className="appearance-settings__slider"
                  min={0.5}
                  max={3}
                  step={0.1}
                  value={bgScaleSidebar}
                  onChange={(e) => setNumericPreference('bgScaleSidebar', parseFloat(e.target.value))}
                  disabled={bgPatternSidebar === 'none'}
                />
              </div>
            </div>

            {/* Main pane pattern */}
            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Center Pane (Chat)</span>
                <span className="appearance-settings__label-description">
                  Background pattern for the conversation
                </span>
              </div>
              <div className="appearance-settings__control">
                <select
                  className="appearance-settings__select"
                  value={bgPatternMain}
                  onChange={(e) => setStringPreference('bgPatternMain', e.target.value)}
                >
                  {allBackgroundPatterns.map((pattern) => (
                    <option key={pattern.id} value={pattern.id}>
                      {pattern.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Main opacity */}
            <div className={`appearance-settings__row appearance-settings__row--indent ${bgPatternMain === 'none' ? 'appearance-settings__row--disabled' : ''}`}>
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Opacity</span>
                <span className="appearance-settings__label-description">
                  {Math.round(bgOpacityMain * 100)}%
                </span>
              </div>
              <div className="appearance-settings__control appearance-settings__control--slider">
                <input
                  type="range"
                  className="appearance-settings__slider"
                  min={0}
                  max={0.5}
                  step={0.02}
                  value={bgOpacityMain}
                  onChange={(e) => setNumericPreference('bgOpacityMain', parseFloat(e.target.value))}
                  disabled={bgPatternMain === 'none'}
                />
              </div>
            </div>

            {/* Main scale */}
            <div className={`appearance-settings__row appearance-settings__row--indent ${bgPatternMain === 'none' ? 'appearance-settings__row--disabled' : ''}`}>
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Scale</span>
                <span className="appearance-settings__label-description">
                  {bgScaleMain.toFixed(1)}x
                </span>
              </div>
              <div className="appearance-settings__control appearance-settings__control--slider">
                <input
                  type="range"
                  className="appearance-settings__slider"
                  min={0.5}
                  max={3}
                  step={0.1}
                  value={bgScaleMain}
                  onChange={(e) => setNumericPreference('bgScaleMain', parseFloat(e.target.value))}
                  disabled={bgPatternMain === 'none'}
                />
              </div>
            </div>

            {/* Detail pane pattern */}
            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Right Pane (Detail)</span>
                <span className="appearance-settings__label-description">
                  Background pattern for the detail panel
                </span>
              </div>
              <div className="appearance-settings__control">
                <select
                  className="appearance-settings__select"
                  value={bgPatternDetail}
                  onChange={(e) => setStringPreference('bgPatternDetail', e.target.value)}
                >
                  {allBackgroundPatterns.map((pattern) => (
                    <option key={pattern.id} value={pattern.id}>
                      {pattern.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Detail opacity */}
            <div className={`appearance-settings__row appearance-settings__row--indent ${bgPatternDetail === 'none' ? 'appearance-settings__row--disabled' : ''}`}>
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Opacity</span>
                <span className="appearance-settings__label-description">
                  {Math.round(bgOpacityDetail * 100)}%
                </span>
              </div>
              <div className="appearance-settings__control appearance-settings__control--slider">
                <input
                  type="range"
                  className="appearance-settings__slider"
                  min={0}
                  max={0.5}
                  step={0.02}
                  value={bgOpacityDetail}
                  onChange={(e) => setNumericPreference('bgOpacityDetail', parseFloat(e.target.value))}
                  disabled={bgPatternDetail === 'none'}
                />
              </div>
            </div>

            {/* Detail scale */}
            <div className={`appearance-settings__row appearance-settings__row--indent ${bgPatternDetail === 'none' ? 'appearance-settings__row--disabled' : ''}`}>
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Scale</span>
                <span className="appearance-settings__label-description">
                  {bgScaleDetail.toFixed(1)}x
                </span>
              </div>
              <div className="appearance-settings__control appearance-settings__control--slider">
                <input
                  type="range"
                  className="appearance-settings__slider"
                  min={0.5}
                  max={3}
                  step={0.1}
                  value={bgScaleDetail}
                  onChange={(e) => setNumericPreference('bgScaleDetail', parseFloat(e.target.value))}
                  disabled={bgPatternDetail === 'none'}
                />
              </div>
            </div>

            {/* Card backgrounds section */}
            <div className="appearance-settings__section-divider" />

            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Chat Card Transparency</span>
                <span className="appearance-settings__label-description">
                  Opacity of turn card backgrounds: {Math.round(cardBgOpacity * 100)}%
                </span>
              </div>
              <div className="appearance-settings__control">
                <input
                  type="range"
                  className="appearance-settings__slider"
                  min="0.5"
                  max="1"
                  step="0.05"
                  value={cardBgOpacity}
                  onChange={(e) => setNumericPreference('cardBgOpacity', Number(e.target.value))}
                />
              </div>
            </div>

            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Card Background Pattern</span>
                <span className="appearance-settings__label-description">
                  Background pattern for chat cards
                </span>
              </div>
              <div className="appearance-settings__control">
                <select
                  className="appearance-settings__select"
                  value={cardBgPattern}
                  onChange={(e) => setStringPreference('cardBgPattern', e.target.value)}
                >
                  {allBackgroundPatterns.map((pattern) => (
                    <option key={pattern.id} value={pattern.id}>
                      {pattern.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {cardBgPattern !== 'none' && (
              <>
                <div className="appearance-settings__row appearance-settings__row--indent">
                  <div className="appearance-settings__label">
                    <span className="appearance-settings__label-text">Pattern Opacity</span>
                    <span className="appearance-settings__label-description">
                      {Math.round(cardBgPatternOpacity * 100)}%
                    </span>
                  </div>
                  <div className="appearance-settings__control">
                    <input
                      type="range"
                      className="appearance-settings__slider"
                      min="0"
                      max="0.5"
                      step="0.02"
                      value={cardBgPatternOpacity}
                      onChange={(e) => setNumericPreference('cardBgPatternOpacity', Number(e.target.value))}
                    />
                  </div>
                </div>

                <div className="appearance-settings__row appearance-settings__row--indent">
                  <div className="appearance-settings__label">
                    <span className="appearance-settings__label-text">Pattern Scale</span>
                    <span className="appearance-settings__label-description">
                      {cardBgPatternScale.toFixed(1)}x
                    </span>
                  </div>
                  <div className="appearance-settings__control">
                    <input
                      type="range"
                      className="appearance-settings__slider"
                      min="0.5"
                      max="3"
                      step="0.1"
                      value={cardBgPatternScale}
                      onChange={(e) => setNumericPreference('cardBgPatternScale', Number(e.target.value))}
                    />
                  </div>
                </div>
              </>
            )}

            {/* Code block transparency */}
            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Code Block Transparency</span>
                <span className="appearance-settings__label-description">
                  Opacity of code blocks and diffs: {Math.round(getNumericPreference('codeBlockBgOpacity') * 100)}%
                </span>
              </div>
              <div className="appearance-settings__control">
                <input
                  type="range"
                  className="appearance-settings__slider"
                  min="0.5"
                  max="1"
                  step="0.05"
                  value={getNumericPreference('codeBlockBgOpacity')}
                  onChange={(e) => setNumericPreference('codeBlockBgOpacity', Number(e.target.value))}
                />
              </div>
            </div>

            {/* Custom backgrounds section */}
            <div className="appearance-settings__section-divider" />

            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Custom Backgrounds</span>
                <span className="appearance-settings__label-description">
                  Add your own SVG patterns, images, or full backgrounds
                </span>
              </div>
              <div className="appearance-settings__control">
                <button
                  className="settings-btn"
                  onClick={() => showAddCustomBg ? handleCancelEdit() : setShowAddCustomBg(true)}
                >
                  {showAddCustomBg ? 'Cancel' : 'Add New'}
                </button>
              </div>
            </div>

            {/* Add/Edit custom background form */}
            {showAddCustomBg && (
              <div
                className="custom-bg-form"
                onPaste={handlePaste}
                onDrop={handleDrop}
                onDragOver={handleDragOver}
              >
                <div className="custom-bg-form__header">
                  {editingBgId ? 'Edit Background' : 'Add Background'}
                </div>
                <div className="custom-bg-form__row">
                  <input
                    type="text"
                    className="custom-bg-form__input"
                    placeholder="Name (e.g., My Pattern)"
                    value={customBgName}
                    onChange={(e) => setCustomBgName(e.target.value)}
                  />
                </div>
                <div className="custom-bg-form__row">
                  <select
                    className="custom-bg-form__select"
                    value={customBgType}
                    onChange={(e) => {
                      const newType = e.target.value as 'custom-pattern' | 'custom-full' | 'custom-image';
                      setCustomBgType(newType);
                      // Clear image preview if switching away from image type
                      if (newType !== 'custom-image') {
                        setImagePreview(null);
                      }
                    }}
                  >
                    <option value="custom-pattern">Repeating SVG Pattern</option>
                    <option value="custom-full">Full SVG Background</option>
                    <option value="custom-image">Image Background</option>
                  </select>
                </div>
                {/* Fit mode selector - for full backgrounds and images */}
                {(customBgType === 'custom-full' || customBgType === 'custom-image') && (
                  <div className="custom-bg-form__row">
                    <select
                      className="custom-bg-form__select"
                      value={customBgFitMode}
                      onChange={(e) => setCustomBgFitMode(e.target.value as 'cover' | 'contain' | 'fill' | 'none')}
                    >
                      <option value="cover">Cover (crop to fill)</option>
                      <option value="contain">Contain (fit inside)</option>
                      <option value="fill">Fill (stretch)</option>
                      <option value="none">None (original size)</option>
                    </select>
                  </div>
                )}
                {/* Image upload/paste area */}
                {customBgType === 'custom-image' && (
                  <div className="custom-bg-form__row">
                    <div className="custom-bg-form__image-drop-zone">
                      {imagePreview ? (
                        <div className="custom-bg-form__image-preview">
                          <img src={imagePreview} alt="Preview" />
                          <button
                            className="custom-bg-form__image-clear"
                            onClick={() => {
                              setImagePreview(null);
                              setCustomBgSvg('');
                            }}
                          >
                            ×
                          </button>
                        </div>
                      ) : (
                        <div className="custom-bg-form__image-placeholder">
                          <input
                            type="file"
                            accept="image/*"
                            className="custom-bg-form__file-input"
                            onChange={(e) => {
                              const file = e.target.files?.[0];
                              if (file) handleImageFile(file);
                            }}
                          />
                          <span>Drop image here, paste, or click to upload</span>
                        </div>
                      )}
                    </div>
                  </div>
                )}
                {/* SVG textarea - for pattern and full SVG types */}
                {customBgType !== 'custom-image' && (
                  <div className="custom-bg-form__row">
                    <textarea
                      className="custom-bg-form__textarea"
                      placeholder="Paste SVG code here..."
                      value={customBgSvg}
                      onChange={(e) => setCustomBgSvg(e.target.value)}
                      rows={4}
                    />
                  </div>
                )}
                <div className="custom-bg-form__row custom-bg-form__actions">
                  <button
                    className="settings-btn"
                    onClick={handleCancelEdit}
                  >
                    Cancel
                  </button>
                  <button
                    className="settings-btn settings-btn--primary"
                    onClick={handleAddCustomBg}
                    disabled={!customBgName.trim() || !customBgSvg.trim()}
                  >
                    {editingBgId ? 'Save Changes' : 'Add Background'}
                  </button>
                </div>
              </div>
            )}

            {/* List of custom backgrounds */}
            {customBackgrounds.length > 0 && (
              <div className="custom-bg-list">
                {customBackgrounds.map((bg) => (
                  <div key={bg.id} className="custom-bg-item">
                    <span className="custom-bg-item__name">{bg.name}</span>
                    <span className="custom-bg-item__type">
                      {bg.type === 'custom-pattern' ? 'Pattern' :
                       bg.type === 'custom-image' ? `Image (${bg.fitMode || 'cover'})` :
                       `Full (${bg.fitMode || 'cover'})`}
                    </span>
                    <button
                      className="custom-bg-item__edit"
                      onClick={() => handleEditCustomBg(bg)}
                      title="Edit"
                    >
                      ✎
                    </button>
                    <button
                      className="custom-bg-item__delete"
                      onClick={() => removeCustomBackground(bg.id)}
                      title="Delete"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Info about patterns */}
            <div className="appearance-settings__info">
              <span className="appearance-settings__info-text">
                SVG patterns inspired by <a href="https://www.svgbackgrounds.com/set/free-svg-backgrounds-and-patterns/" target="_blank" rel="noopener noreferrer">SVG Backgrounds</a>.
                Paste SVG code from there or create your own!
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Voice Input Settings Card */}
      <div className="settings-card">
        <div className="settings-card__header">
          <h3 className="settings-card__title">Voice Input</h3>
        </div>

        <div className="settings-card__content">
          <div className="appearance-settings">
            {/* Enable/disable toggle */}
            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">Enable Voice Input</span>
                <span className="appearance-settings__label-description">
                  Show microphone button in input area for speech-to-text
                </span>
              </div>
              <div className="appearance-settings__control">
                <label className="appearance-settings__toggle">
                  <input
                    type="checkbox"
                    checked={voiceInputEnabled}
                    onChange={() => setPreference('voiceInputEnabled', !voiceInputEnabled)}
                  />
                  <span className="appearance-settings__toggle-slider" />
                </label>
              </div>
            </div>

            {/* Server host */}
            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">STT Server Host</span>
                <span className="appearance-settings__label-description">
                  RealtimeSTT server hostname or IP address
                </span>
              </div>
              <div className="appearance-settings__control">
                <input
                  type="text"
                  className="appearance-settings__input"
                  value={localHost}
                  onChange={(e) => setLocalHost(e.target.value)}
                  onBlur={handleVoiceHostBlur}
                  placeholder="192.168.0.120"
                  disabled={!voiceInputEnabled}
                />
              </div>
            </div>

            {/* Server port */}
            <div className="appearance-settings__row">
              <div className="appearance-settings__label">
                <span className="appearance-settings__label-text">STT Server Port</span>
                <span className="appearance-settings__label-description">
                  WebSocket port for audio streaming (default: 8012)
                </span>
              </div>
              <div className="appearance-settings__control">
                <input
                  type="text"
                  className="appearance-settings__input"
                  value={localPort}
                  onChange={(e) => setLocalPort(e.target.value)}
                  onBlur={handleVoicePortBlur}
                  placeholder="8012"
                  disabled={!voiceInputEnabled}
                />
              </div>
            </div>

            {/* Info about setting up RealtimeSTT */}
            <div className="appearance-settings__info">
              <span className="appearance-settings__info-text">
                Requires a <a href="https://github.com/KoljaB/RealtimeSTT" target="_blank" rel="noopener noreferrer">RealtimeSTT</a> server.
                Run with: <code>stt-server --control 8011 --data 8012</code>
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Sound Settings Card */}
      <div className="settings-card">
        <div className="settings-card__header">
          <h3 className="settings-card__title">Sound Notifications</h3>
          <div className="settings-card__header-actions">
            <button
              className="settings-btn"
              onClick={onRefreshSounds}
              disabled={isLoading}
              title="Refresh available sounds from server"
            >
              {isLoading ? 'Loading...' : 'Refresh'}
            </button>
          </div>
        </div>

        <div className="settings-card__content">
          <div className="sound-settings">
            {/* Global toggle */}
            <label className="sound-settings__toggle">
              <input
                type="checkbox"
                checked={soundEnabled}
                onChange={onToggleSound}
              />
              <span className="sound-settings__toggle-label">Enable Sounds</span>
              <span className="sound-settings__toggle-description">
                {soundEnabled
                  ? 'Notification sounds will play for streaming events'
                  : 'All notification sounds are muted'}
              </span>
            </label>

            {/* Volume control */}
            <div className="sound-settings__volume">
              <div className="sound-settings__volume-header">
                <span className="sound-settings__volume-label">Volume</span>
                <span className="sound-settings__volume-value">{Math.round(soundConfig.volume * 100)}%</span>
              </div>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={soundConfig.volume}
                onChange={handleVolumeChange}
                className="sound-settings__volume-slider"
                disabled={!soundEnabled}
              />
            </div>

            {/* Error display */}
            {error && (
              <div className="sound-settings__error">
                {error}
              </div>
            )}

            {/* Sound event configuration */}
            <div className={`sound-events ${!soundEnabled ? 'sound-events--disabled' : ''}`}>
              <span className="sound-events__section-title">Event Sounds</span>

              {/* Stream Done */}
              <div className="sound-event">
                <div className="sound-event__header">
                  <div>
                    <span className="sound-event__label">Stream Complete</span>
                    <span className="sound-event__description">
                      Plays when Claude finishes responding
                    </span>
                  </div>
                </div>
                <div className="sound-event__controls">
                  <select
                    className="sound-event__select"
                    value={soundConfig.streamDoneSound ?? ''}
                    onChange={handleStreamDoneChange}
                    disabled={!soundEnabled}
                  >
                    <option value="">None (silent)</option>
                    {availableSounds.map(sound => (
                      <option key={sound.filename} value={sound.filename}>
                        {sound.filename}
                      </option>
                    ))}
                  </select>
                  <button
                    className="sound-event__play-btn"
                    onClick={() => handlePreview(soundConfig.streamDoneSound)}
                    disabled={!soundEnabled || !soundConfig.streamDoneSound}
                    title="Preview sound"
                  >
                    Preview
                  </button>
                </div>
              </div>

              {/* Stream Error */}
              <div className="sound-event">
                <div className="sound-event__header">
                  <div>
                    <span className="sound-event__label">Stream Error</span>
                    <span className="sound-event__description">
                      Plays when streaming encounters an error
                    </span>
                  </div>
                </div>
                <div className="sound-event__controls">
                  <select
                    className="sound-event__select"
                    value={soundConfig.streamErrorSound ?? ''}
                    onChange={handleStreamErrorChange}
                    disabled={!soundEnabled}
                  >
                    <option value="">None (silent)</option>
                    {availableSounds.map(sound => (
                      <option key={sound.filename} value={sound.filename}>
                        {sound.filename}
                      </option>
                    ))}
                  </select>
                  <button
                    className="sound-event__play-btn"
                    onClick={() => handlePreview(soundConfig.streamErrorSound)}
                    disabled={!soundEnabled || !soundConfig.streamErrorSound}
                    title="Preview sound"
                  >
                    Preview
                  </button>
                </div>
              </div>
            </div>

            {/* Available sounds reference */}
            {availableSounds.length > 0 && (
              <div className="sound-settings__available">
                <span className="sound-settings__available-title">
                  {availableSounds.length} sound{availableSounds.length !== 1 ? 's' : ''} available in ~/.balloons/sounds/
                </span>
                <div className="sound-settings__available-list">
                  {availableSounds.map(sound => (
                    <span key={sound.filename} className="sound-settings__available-item">
                      {sound.filename}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
});

export default SettingsTab;
