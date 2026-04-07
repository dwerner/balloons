/**
 * PushToTalkInput - Inline push-to-talk voice input widget
 *
 * A mic button that lives inside the input field. Hold to record,
 * release to commit text, slide left to cancel.
 *
 * Uses browser's getUserMedia() for microphone access and streams
 * raw PCM audio via WebSocket to a RealtimeSTT server.
 */

import React, { useState, useRef, useCallback, useEffect } from 'react';
import './PushToTalkInput.css';

// Audio settings
const CHANNELS = 1;

// Slide-to-cancel threshold (pixels)
const CANCEL_THRESHOLD = 80;

interface PushToTalkInputProps {
  /** Called with transcribed text as it streams */
  onTranscription: (text: string, isFinal: boolean) => void;
  /** Called when recording is cancelled via slide gesture */
  onCancel: () => void;
  /** Called when recording ends with commit (to finalize any partial text) */
  onCommit?: () => void;
  /** Called when recording state changes (for UI updates like readonly textarea) */
  onRecordingChange?: (isRecording: boolean) => void;
  /** Called when recording starts (for saving pre-recording state) */
  onRecordingStart?: () => void;
  /** Server host for RealtimeSTT WebSocket */
  serverHost?: string;
  /** WebSocket port for data connection */
  dataPort?: number;
  /** Whether the button should be disabled */
  disabled?: boolean;
}

// Helper to create the message format expected by RealtimeSTT server
function packAudioMessage(audioData: Int16Array, sampleRate: number): ArrayBuffer {
  const metadata = JSON.stringify({ sampleRate });
  const metadataBytes = new TextEncoder().encode(metadata);
  const metadataLength = metadataBytes.length;

  // Message format: 4-byte length (little endian) + metadata JSON + audio data
  const buffer = new ArrayBuffer(4 + metadataLength + audioData.byteLength);
  const view = new DataView(buffer);

  // Write metadata length (little endian)
  view.setUint32(0, metadataLength, true);

  // Write metadata JSON
  const uint8View = new Uint8Array(buffer);
  uint8View.set(metadataBytes, 4);

  // Write audio data
  const audioBytes = new Uint8Array(audioData.buffer);
  uint8View.set(audioBytes, 4 + metadataLength);

  return buffer;
}

export function PushToTalkInput({
  onTranscription,
  onCancel,
  onCommit,
  onRecordingChange,
  onRecordingStart,
  serverHost = '192.168.0.120',
  dataPort = 8012,
  disabled = false,
}: PushToTalkInputProps) {
  const [isRecording, setIsRecording] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [slideOffset, setSlideOffset] = useState(0);
  const [isInCancelZone, setIsInCancelZone] = useState(false);

  // Track recording state for callbacks
  const isRecordingRef = useRef(false);
  // Track if we should cancel on release
  const shouldCancelRef = useRef(false);
  // Track the starting X position for slide gesture
  const startXRef = useRef(0);
  // Track if we've committed text this session (to know if cancel clears anything)
  const hasTextRef = useRef(false);
  // Track if session was cancelled (to ignore late transcriptions)
  const wasCancelledRef = useRef(false);

  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Clean up on unmount
  useEffect(() => {
    return () => {
      stopRecording(false);
    };
  }, []);

  const stopRecording = useCallback((commit: boolean) => {
    // Stop audio processing
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }

    // Close audio context
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    // Stop media stream tracks
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }

    // Close WebSocket
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    isRecordingRef.current = false;
    wasCancelledRef.current = !commit;
    setIsRecording(false);
    onRecordingChange?.(false);
    setIsConnected(false);
    setSlideOffset(0);
    setIsInCancelZone(false);

    // If committing, call onCommit to finalize any partial text
    // If not committing, call onCancel to restore previous state
    if (commit) {
      onCommit?.();
    } else {
      onCancel();
    }
    hasTextRef.current = false;
  }, [onCancel]);

  const startRecording = useCallback(async (startX: number) => {
    setError(null);
    startXRef.current = startX;
    shouldCancelRef.current = false;
    hasTextRef.current = false;
    wasCancelledRef.current = false;

    try {
      // Request microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: CHANNELS,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      streamRef.current = stream;

      // Create audio context
      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;

      const actualSampleRate = audioContext.sampleRate;

      // Connect WebSocket to RealtimeSTT server
      let wsUrl: string;
      if (window.location.protocol === 'https:') {
        wsUrl = `wss://${window.location.host}/stt-proxy`;
      } else {
        wsUrl = `ws://${serverHost}:${dataPort}`;
      }
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        isRecordingRef.current = true;
        setIsRecording(true);
        onRecordingChange?.(true);

        // Set up audio processing
        const source = audioContext.createMediaStreamSource(stream);
        const processor = audioContext.createScriptProcessor(4096, CHANNELS, CHANNELS);
        processorRef.current = processor;

        processor.onaudioprocess = (event) => {
          if (ws.readyState !== WebSocket.OPEN) return;

          const inputData = event.inputBuffer.getChannelData(0);
          const int16Data = new Int16Array(inputData.length);
          for (let i = 0; i < inputData.length; i++) {
            const sample = inputData[i] ?? 0;
            const s = Math.max(-1, Math.min(1, sample));
            int16Data[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
          }

          const message = packAudioMessage(int16Data, actualSampleRate);
          ws.send(message);
        };

        source.connect(processor);
        processor.connect(audioContext.destination);
      };

      ws.onmessage = (event) => {
        // Ignore messages if we've been cancelled
        if (wasCancelledRef.current) return;

        try {
          const data = JSON.parse(event.data);

          if (data.type === 'realtime') {
            hasTextRef.current = true;
            onTranscription(data.text || '', false);
          } else if (data.type === 'fullSentence') {
            hasTextRef.current = true;
            onTranscription(data.text || '', true);
          }
        } catch (e) {
          console.error('PushToTalkInput: Failed to parse message:', e);
        }
      };

      ws.onerror = (event) => {
        console.error('PushToTalkInput: WebSocket error:', event);
        setError('Connection error');
        stopRecording(false);
      };

      ws.onclose = () => {
        setIsConnected(false);
        if (isRecordingRef.current) {
          // Unexpected disconnect - commit what we have
          stopRecording(true);
        }
      };
    } catch (err) {
      console.error('PushToTalkInput: Error starting recording:', err);
      if (err instanceof Error) {
        if (err.name === 'NotAllowedError') {
          setError('Microphone access denied');
        } else if (err.name === 'NotFoundError') {
          setError('No microphone found');
        } else {
          setError(err.message);
        }
      } else {
        setError('Failed to start recording');
      }
      stopRecording(false);
    }
  }, [serverHost, dataPort, onTranscription, stopRecording]);

  // Handle pointer/touch events for push-to-talk
  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if (disabled) return;
    e.preventDefault();
    e.stopPropagation();

    // Blur any focused element (hides mobile keyboard)
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }

    // Save pre-recording state for cancel/restore
    onRecordingStart?.();

    // Immediately signal recording start (before WebSocket connects)
    // This makes the textarea readonly to prevent keyboard from appearing
    onRecordingChange?.(true);

    // Capture pointer for tracking outside the element
    (e.target as HTMLElement).setPointerCapture(e.pointerId);

    startRecording(e.clientX);
  }, [disabled, startRecording, onRecordingChange, onRecordingStart]);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!isRecordingRef.current) return;

    const deltaX = startXRef.current - e.clientX;
    const clampedOffset = Math.max(0, Math.min(deltaX, CANCEL_THRESHOLD + 20));

    setSlideOffset(clampedOffset);

    const inCancelZone = deltaX >= CANCEL_THRESHOLD;
    setIsInCancelZone(inCancelZone);
    shouldCancelRef.current = inCancelZone;
  }, []);

  const handlePointerUp = useCallback((e: React.PointerEvent) => {
    if (!isRecordingRef.current) return;

    (e.target as HTMLElement).releasePointerCapture(e.pointerId);

    // Commit or cancel based on position
    stopRecording(!shouldCancelRef.current);
  }, [stopRecording]);

  const handlePointerCancel = useCallback((e: React.PointerEvent) => {
    if (!isRecordingRef.current) return;

    (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    stopRecording(false);
  }, [stopRecording]);

  return (
    <div className={`ptt-container ${isRecording ? 'recording' : ''}`}>
      {/* Cancel zone indicator */}
      {isRecording && (
        <div
          className={`ptt-cancel-zone ${isInCancelZone ? 'active' : ''}`}
          style={{ opacity: Math.min(slideOffset / CANCEL_THRESHOLD, 1) }}
        >
          <span className="ptt-cancel-icon">✕</span>
        </div>
      )}

      {/* Mic button */}
      <button
        ref={buttonRef}
        type="button"
        className={`ptt-button ${isRecording ? 'recording' : ''} ${isInCancelZone ? 'cancel' : ''}`}
        style={isRecording ? { transform: `translateX(-${slideOffset}px)` } : undefined}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerCancel}
        onTouchStart={(e) => e.preventDefault()} /* Prevent keyboard from showing */
        onMouseDown={(e) => e.preventDefault()} /* Prevent focus shift */
        tabIndex={-1} /* Prevent focus which triggers mobile keyboard */
        disabled={disabled}
        title={
          error
            ? `Error: ${error}`
            : isRecording
              ? 'Release to send, slide left to cancel'
              : 'Hold to speak'
        }
      >
        <span className="ptt-icon">
          {isRecording ? (isInCancelZone ? '✕' : '◉') : '🎤'}
        </span>
      </button>

      {/* Slide hint during recording */}
      {isRecording && !isInCancelZone && (
        <div className="ptt-slide-hint">
          ← slide to cancel
        </div>
      )}
    </div>
  );
}

export default PushToTalkInput;
