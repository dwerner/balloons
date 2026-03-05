/**
 * VoiceInput - Speech-to-text component that streams to RealtimeSTT server
 *
 * Uses browser's getUserMedia() for microphone access and streams
 * raw PCM audio via WebSocket to a RealtimeSTT server.
 */

import React, { useState, useRef, useCallback, useEffect } from 'react';
import './VoiceInput.css';

// Audio settings
const CHANNELS = 1;

interface VoiceInputProps {
  /** Called with transcribed text as it streams */
  onTranscription: (text: string, isFinal: boolean) => void;
  /** Server host for RealtimeSTT WebSocket */
  serverHost?: string;
  /** WebSocket port for data connection */
  dataPort?: number;
  /** Whether the button should be disabled */
  disabled?: boolean;
  /** Called when user clicks clear - should reset voice text state */
  onClear?: () => void;
  /** Whether there's content to clear (shows clear button when true) */
  hasContent?: boolean;
  /** Whether there's partial (uncommitted) text */
  hasPartialText?: boolean;
  /** Called to commit partial text (e.g., on disconnect or manual commit) */
  onCommitPartial?: () => void;
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

export function VoiceInput({
  onTranscription,
  serverHost = '192.168.0.120',
  dataPort = 8012,
  disabled = false,
  onClear,
  hasContent = false,
  hasPartialText = false,
  onCommitPartial,
}: VoiceInputProps) {
  const [isRecording, setIsRecording] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wasDisconnected, setWasDisconnected] = useState(false);

  // Use ref to track recording state for callbacks (avoids stale closure)
  const isRecordingRef = useRef(false);

  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);

  // Clean up on unmount
  useEffect(() => {
    return () => {
      stopRecording();
    };
  }, []);

  const stopRecording = useCallback(() => {
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
    setIsRecording(false);
    setIsConnected(false);
  }, []);

  const startRecording = useCallback(async () => {
    setError(null);

    try {
      // Request microphone access
      // Note: Don't force sample rate - let browser use native rate and we'll resample
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: CHANNELS,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      streamRef.current = stream;

      // Create audio context - use default sample rate (matches stream)
      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;

      // Get actual sample rate - we'll send this to the server
      const actualSampleRate = audioContext.sampleRate;

      // Connect WebSocket to RealtimeSTT server
      // If we're on HTTPS, use the wss:// proxy endpoint instead of direct ws://
      let wsUrl: string;
      if (window.location.protocol === 'https:') {
        // Use proxy through the TLS dev server
        wsUrl = `wss://${window.location.host}/stt-proxy`;
      } else {
        // Direct connection (only works on localhost or HTTP)
        wsUrl = `ws://${serverHost}:${dataPort}`;
      }
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        isRecordingRef.current = true;
        setIsRecording(true);

        // Set up audio processing after WebSocket is connected
        const source = audioContext.createMediaStreamSource(stream);

        // Use ScriptProcessorNode to get raw audio data
        // Note: This is deprecated but AudioWorklet requires HTTPS or localhost
        const processor = audioContext.createScriptProcessor(4096, CHANNELS, CHANNELS);
        processorRef.current = processor;

        processor.onaudioprocess = (event) => {
          if (ws.readyState !== WebSocket.OPEN) return;

          // Get audio data from input buffer
          const inputData = event.inputBuffer.getChannelData(0);

          // Convert Float32 to Int16
          const int16Data = new Int16Array(inputData.length);
          for (let i = 0; i < inputData.length; i++) {
            // Clamp to [-1, 1] and scale to Int16 range
            const sample = inputData[i] ?? 0;
            const s = Math.max(-1, Math.min(1, sample));
            int16Data[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
          }

          // Pack and send to server with actual sample rate
          const message = packAudioMessage(int16Data, actualSampleRate);
          ws.send(message);
        };

        source.connect(processor);
        processor.connect(audioContext.destination);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === 'realtime') {
            // Real-time partial transcription
            onTranscription(data.text || '', false);
          } else if (data.type === 'fullSentence') {
            // Final transcription for a sentence
            onTranscription(data.text || '', true);
          }
          // Ignore other message types (recording_start, recording_stop, etc.)
        } catch (e) {
          console.error('VoiceInput: Failed to parse message:', e);
        }
      };

      ws.onerror = (event) => {
        console.error('VoiceInput: WebSocket error:', event);
        setError('Connection error');
        stopRecording();
      };

      ws.onclose = () => {
        setIsConnected(false);
        if (isRecordingRef.current) {
          // Show disconnection indicator
          setWasDisconnected(true);
          setError('Disconnected');
          // Commit any partial text before stopping (so user doesn't lose work)
          onCommitPartial?.();
          stopRecording();
          // Clear the disconnected state after a few seconds
          setTimeout(() => {
            setWasDisconnected(false);
            setError(null);
          }, 3000);
        }
      };
    } catch (err) {
      console.error('VoiceInput: Error starting recording:', err);
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
      stopRecording();
    }
  }, [serverHost, dataPort, onTranscription, stopRecording, isRecording]);

  const toggleRecording = useCallback(() => {
    // Use ref to avoid stale closure issue
    if (isRecordingRef.current) {
      stopRecording();
    } else {
      startRecording();
    }
  }, [startRecording, stopRecording]);

  const handleClear = useCallback(() => {
    if (onClear) {
      onClear();
    }
  }, [onClear]);

  const handleCommit = useCallback(() => {
    if (onCommitPartial) {
      onCommitPartial();
    }
  }, [onCommitPartial]);

  return (
    <div className="voice-input-container">
      <div className="voice-input-main">
        <button
          type="button"
          className={`voice-input-button ${isRecording ? 'recording' : ''} ${isConnected ? 'connected' : ''} ${wasDisconnected ? 'disconnected' : ''}`}
          onClick={toggleRecording}
          disabled={disabled}
          title={
            error
              ? `Error: ${error}`
              : isRecording
                ? 'Click to stop recording'
                : 'Click to start voice input'
          }
        >
          <span className="voice-icon">
            {wasDisconnected ? '⚠️' : isRecording ? '🔴' : '🎤'}
          </span>
          {isRecording && <span className="recording-indicator" />}
        </button>
      </div>
      <div className="voice-input-secondary">
        {hasPartialText && onCommitPartial && (
          <button
            type="button"
            className="voice-commit-button"
            onClick={handleCommit}
            title="Commit partial text"
          >
            ✓
          </button>
        )}
        {hasContent && onClear && (
          <button
            type="button"
            className="voice-clear-button"
            onClick={handleClear}
            title="Clear voice input"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

export default VoiceInput;
