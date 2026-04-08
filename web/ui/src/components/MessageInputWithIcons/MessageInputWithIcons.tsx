/**
 * MessageInputWithIcons - Wraps the message input with inline icons
 *
 * Combines the textarea with attachment and voice icons inside the field,
 * similar to Signal's input design.
 */

import React, { forwardRef, useRef, useImperativeHandle, useCallback, memo, useState } from 'react';
import { PushToTalkInput } from '../VoiceInput/PushToTalkInput';
import './MessageInputWithIcons.css';

export interface MessageInputWithIconsHandle {
  getValue: () => string;
  setValue: (value: string) => void;
  focus: () => void;
}

interface MessageInputWithIconsProps {
  placeholder?: string;
  disabled?: boolean;
  onSubmit: (message: string) => void;
  onPaste: (e: React.ClipboardEvent<HTMLTextAreaElement>) => void;
  onChange?: (value: string) => void;
  partialText?: string;
  // Attachment
  onAttachClick: () => void;
  attachDisabled?: boolean;
  // Voice input
  voiceEnabled?: boolean;
  voiceServerHost?: string;
  voiceDataPort?: number;
  onVoiceTranscription?: (text: string, isFinal: boolean) => void;
  onVoiceCancel?: () => void;
  onVoiceCommit?: () => void;
  onVoiceRecordingStart?: () => void;
  voiceDisabled?: boolean;
}

const MessageInputWithIconsInner = forwardRef<MessageInputWithIconsHandle, MessageInputWithIconsProps>(
  function MessageInputWithIcons({
    placeholder,
    disabled,
    onSubmit,
    onPaste,
    onChange,
    partialText,
    onAttachClick,
    attachDisabled,
    voiceEnabled,
    voiceServerHost,
    voiceDataPort,
    onVoiceTranscription,
    onVoiceCancel,
    onVoiceCommit,
    onVoiceRecordingStart,
    voiceDisabled,
  }, ref) {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const valueRef = useRef('');
    const [isRecording, setIsRecording] = useState(false);
    const [hasContent, setHasContent] = useState(false);

    // Store callbacks in refs to avoid re-creating handlers
    const onSubmitRef = useRef(onSubmit);
    const onPasteRef = useRef(onPaste);
    const onChangeRef = useRef(onChange);
    onSubmitRef.current = onSubmit;
    onPasteRef.current = onPaste;
    onChangeRef.current = onChange;

    // Expose imperative handle
    useImperativeHandle(ref, () => ({
      getValue: () => valueRef.current,
      setValue: (value: string) => {
        valueRef.current = value;
        if (textareaRef.current) {
          textareaRef.current.value = value;
        }
        setHasContent(value.trim().length > 0);
      },
      focus: () => textareaRef.current?.focus(),
    }), []);

    const handleChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
      valueRef.current = e.target.value;
      setHasContent(e.target.value.trim().length > 0);
      onChangeRef.current?.(e.target.value);
    }, []);

    const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const value = valueRef.current.trim();
        if (value) {
          onSubmitRef.current(value);
        }
      }
    }, []);

    const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      onPasteRef.current(e);
    }, []);

    return (
      <div className="input-with-icons">
        {/* Partial text overlay (voice transcription preview) */}
        {partialText && (
          <div className="input-with-icons-partial">
            <span className="partial-text">{partialText}</span>
          </div>
        )}

        {/* Main input container */}
        <div className={`input-with-icons-container ${hasContent ? 'has-content' : ''}`}>
          {/* Textarea */}
          <textarea
            ref={textareaRef}
            className="input-with-icons-field"
            placeholder={isRecording ? "Recording..." : placeholder}
            defaultValue=""
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            disabled={disabled}
            readOnly={isRecording} /* Prevent keyboard during voice recording */
            rows={1}
          />

          {/* Right-side icons inside the field */}
          <div className="input-with-icons-actions">
            {/* Attachment button */}
            <button
              type="button"
              className="input-icon-button attach"
              onClick={onAttachClick}
              onMouseDown={(e) => e.preventDefault()} /* Prevent focus shift */
              onTouchStart={(e) => e.stopPropagation()} /* Don't prevent - need click to work */
              tabIndex={-1}
              disabled={attachDisabled || disabled}
              title="Attach image (or paste from clipboard)"
            >
              📎
            </button>

            {/* Voice input (push-to-talk) */}
            {voiceEnabled && onVoiceTranscription && onVoiceCancel && (
              <PushToTalkInput
                serverHost={voiceServerHost}
                dataPort={voiceDataPort}
                onTranscription={onVoiceTranscription}
                onCancel={onVoiceCancel}
                onCommit={onVoiceCommit}
                onRecordingStart={onVoiceRecordingStart}
                onRecordingChange={setIsRecording}
                disabled={voiceDisabled || disabled}
              />
            )}
          </div>
        </div>
      </div>
    );
  }
);

// Custom memo comparison
export const MessageInputWithIcons = memo(MessageInputWithIconsInner, (prevProps, nextProps) => {
  return prevProps.placeholder === nextProps.placeholder &&
    prevProps.disabled === nextProps.disabled &&
    prevProps.partialText === nextProps.partialText &&
    prevProps.attachDisabled === nextProps.attachDisabled &&
    prevProps.voiceEnabled === nextProps.voiceEnabled &&
    prevProps.voiceDisabled === nextProps.voiceDisabled;
});

export default MessageInputWithIcons;
