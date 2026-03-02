/**
 * SettingsTab - Application settings panel
 *
 * Contains cards for:
 * - Appearance Settings: Theme, wake lock
 * - Sound Settings: Enable/disable sounds, select sound files for events, volume control
 */

import React, { memo, useCallback } from 'react';
import type { SoundInfo } from '../../../../generated/types';
import type { SoundConfig } from '../../hooks/useSoundNotifications';
import { useTheme } from '../layout/ThemeContext';
import { useWakeLock } from '../../hooks/useWakeLock';
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
