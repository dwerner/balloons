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
import { usePreferences } from '../layout/PreferencesContext';
import './SettingsTab.css';

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

  // Voice input preferences
  const {
    voiceInputEnabled,
    voiceInputHost,
    voiceInputPort,
    setPreference,
    setStringPreference,
  } = usePreferences();

  // Local state for voice input form inputs (to avoid constant saves while typing)
  const [localHost, setLocalHost] = useState(voiceInputHost);
  const [localPort, setLocalPort] = useState(voiceInputPort);

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
