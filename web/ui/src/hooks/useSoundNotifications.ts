/**
 * useSoundNotifications - React hook for playing notification sounds
 *
 * Plays sounds when streaming events occur (stream done, stream error, etc.).
 * Sound preferences are stored in localStorage.
 *
 * Usage:
 *   const { playSound, soundEnabled, setSoundEnabled, soundConfig } = useSoundNotifications(client);
 *
 *   // The hook automatically plays sounds on sessionDataStreamDone events
 *   // when subscribed to a session
 *
 *   // Manually play a sound:
 *   await playSound('Chord.ogg');
 *
 *   // Toggle sounds:
 *   setSoundEnabled(!soundEnabled);
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import type { BalloonsClient, SoundInfo, SessionStreamDoneEvent, SessionStreamErrorEvent } from '../../../generated/balloons-client';

// localStorage keys
const STORAGE_KEY_ENABLED = 'balloons:sound:enabled';
const STORAGE_KEY_STREAM_DONE = 'balloons:sound:streamDone';
const STORAGE_KEY_STREAM_ERROR = 'balloons:sound:streamError';
const STORAGE_KEY_VOLUME = 'balloons:sound:volume';

// Default sounds
const DEFAULT_STREAM_DONE_SOUND = 'Chord.ogg';
const DEFAULT_STREAM_ERROR_SOUND = 'Glitch.ogg';
const DEFAULT_VOLUME = 0.5;

export interface SoundConfig {
  /** Whether sounds are enabled globally */
  enabled: boolean;
  /** Sound to play when streaming completes */
  streamDoneSound: string | null;
  /** Sound to play on stream error */
  streamErrorSound: string | null;
  /** Volume level (0-1) */
  volume: number;
}

export interface UseSoundNotificationsReturn {
  /** Play a sound by filename */
  playSound: (filename: string) => Promise<void>;
  /** Available sounds from the server */
  availableSounds: SoundInfo[];
  /** Whether sounds are enabled */
  soundEnabled: boolean;
  /** Toggle sound enabled state */
  setSoundEnabled: (enabled: boolean) => void;
  /** Full sound configuration */
  soundConfig: SoundConfig;
  /** Update sound for a specific event */
  setSoundForEvent: (event: 'streamDone' | 'streamError', filename: string | null) => void;
  /** Set volume (0-1) */
  setVolume: (volume: number) => void;
  /** Reload available sounds from server */
  refreshSounds: () => Promise<void>;
  /** Loading state */
  isLoading: boolean;
  /** Error state */
  error: string | null;
}

/**
 * Hook for managing notification sounds in the web UI.
 *
 * Automatically subscribes to streaming events and plays sounds when:
 * - A stream completes (sessionDataStreamDone)
 * - A stream errors (sessionDataStreamError)
 *
 * @param client - BalloonsClient instance
 * @param sessionId - Optional session ID to subscribe to for streaming events
 */
export function useSoundNotifications(
  client: BalloonsClient | null,
  sessionId?: string | null
): UseSoundNotificationsReturn {
  // Load initial state from localStorage
  const [soundEnabled, setSoundEnabledState] = useState<boolean>(() => {
    const stored = localStorage.getItem(STORAGE_KEY_ENABLED);
    return stored === null ? true : stored === 'true';
  });

  const [streamDoneSound, setStreamDoneSoundState] = useState<string | null>(() => {
    return localStorage.getItem(STORAGE_KEY_STREAM_DONE) ?? DEFAULT_STREAM_DONE_SOUND;
  });

  const [streamErrorSound, setStreamErrorSoundState] = useState<string | null>(() => {
    return localStorage.getItem(STORAGE_KEY_STREAM_ERROR) ?? DEFAULT_STREAM_ERROR_SOUND;
  });

  const [volume, setVolumeState] = useState<number>(() => {
    const stored = localStorage.getItem(STORAGE_KEY_VOLUME);
    return stored ? parseFloat(stored) : DEFAULT_VOLUME;
  });

  const [availableSounds, setAvailableSounds] = useState<SoundInfo[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Cache for loaded audio data (filename -> data URL)
  const audioCache = useRef<Map<string, string>>(new Map());

  // Currently playing audio (for cleanup)
  const currentAudio = useRef<HTMLAudioElement | null>(null);

  // Build sound config object
  const soundConfig = useMemo<SoundConfig>(() => ({
    enabled: soundEnabled,
    streamDoneSound,
    streamErrorSound,
    volume,
  }), [soundEnabled, streamDoneSound, streamErrorSound, volume]);

  // Persist enabled state
  const setSoundEnabled = useCallback((enabled: boolean) => {
    setSoundEnabledState(enabled);
    localStorage.setItem(STORAGE_KEY_ENABLED, String(enabled));
  }, []);

  // Persist volume
  const setVolume = useCallback((newVolume: number) => {
    const clamped = Math.max(0, Math.min(1, newVolume));
    setVolumeState(clamped);
    localStorage.setItem(STORAGE_KEY_VOLUME, String(clamped));
  }, []);

  // Update sound for event
  const setSoundForEvent = useCallback((event: 'streamDone' | 'streamError', filename: string | null) => {
    if (event === 'streamDone') {
      setStreamDoneSoundState(filename);
      if (filename) {
        localStorage.setItem(STORAGE_KEY_STREAM_DONE, filename);
      } else {
        localStorage.removeItem(STORAGE_KEY_STREAM_DONE);
      }
    } else {
      setStreamErrorSoundState(filename);
      if (filename) {
        localStorage.setItem(STORAGE_KEY_STREAM_ERROR, filename);
      } else {
        localStorage.removeItem(STORAGE_KEY_STREAM_ERROR);
      }
    }
  }, []);

  // Load available sounds from server
  const refreshSounds = useCallback(async () => {
    if (!client?.isConnected) {
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const sounds = await client.sounds.listSounds();
      setAvailableSounds(sounds);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(`Failed to load sounds: ${message}`);
    } finally {
      setIsLoading(false);
    }
  }, [client]);

  // Play a sound by filename
  const playSound = useCallback(async (filename: string) => {
    if (!soundEnabled || !client?.isConnected) {
      return;
    }

    try {
      // Check cache first
      let dataUrl = audioCache.current.get(filename);

      if (!dataUrl) {
        // Fetch sound data from server
        const soundData = await client.sounds.getSoundData(filename);
        if (!soundData) {
          console.warn(`[useSoundNotifications] Sound not found: ${filename}`);
          return;
        }

        // Create data URL
        dataUrl = `data:${soundData.mediaType};base64,${soundData.dataBase64}`;
        audioCache.current.set(filename, dataUrl);
      }

      // Stop any currently playing sound
      if (currentAudio.current) {
        currentAudio.current.pause();
        currentAudio.current = null;
      }

      // Create and play audio
      const audio = new Audio(dataUrl);
      audio.volume = volume;
      currentAudio.current = audio;

      await audio.play();

      // Clean up reference when done
      audio.onended = () => {
        if (currentAudio.current === audio) {
          currentAudio.current = null;
        }
      };
    } catch (err) {
      console.warn(`[useSoundNotifications] Failed to play sound ${filename}:`, err);
    }
  }, [soundEnabled, client, volume]);

  // Load sounds when client connects
  useEffect(() => {
    if (client?.isConnected) {
      refreshSounds();
    }
  }, [client?.isConnected, refreshSounds]);

  // Subscribe to streaming events
  useEffect(() => {
    if (!client?.isConnected || !sessionId) {
      return;
    }

    const unsubscribers: (() => void)[] = [];

    // Stream done event
    unsubscribers.push(
      client.sessionData.sessionDataStreamDone((event: SessionStreamDoneEvent) => {
        if (event.sessionId === sessionId && streamDoneSound) {
          playSound(streamDoneSound);
        }
      })
    );

    // Stream error event
    unsubscribers.push(
      client.sessionData.sessionDataStreamError((event: SessionStreamErrorEvent) => {
        if (event.sessionId === sessionId && streamErrorSound) {
          playSound(streamErrorSound);
        }
      })
    );

    return () => {
      unsubscribers.forEach(unsub => unsub());
    };
  }, [client, sessionId, streamDoneSound, streamErrorSound, playSound]);

  // Cleanup audio on unmount
  useEffect(() => {
    return () => {
      if (currentAudio.current) {
        currentAudio.current.pause();
        currentAudio.current = null;
      }
    };
  }, []);

  return {
    playSound,
    availableSounds,
    soundEnabled,
    setSoundEnabled,
    soundConfig,
    setSoundForEvent,
    setVolume,
    refreshSounds,
    isLoading,
    error,
  };
}

export default useSoundNotifications;
