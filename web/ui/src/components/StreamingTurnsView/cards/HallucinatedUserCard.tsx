/**
 * HallucinatedUserCard - Warning when Claude simulates user responses
 *
 * This card is displayed when the system detects Claude outputting
 * <user>...</user> blocks, which indicates the model is trying to
 * simulate a user response to continue the conversation on its own.
 *
 * This is a problematic pattern that should be flagged and stopped.
 */

import React, { useState } from 'react';
import { MarkdownContent } from '../../../MarkdownContent';
import './cards.css';

interface HallucinatedUserCardProps {
  content: string;
  context?: string;
  order?: number;
  timestamp?: string;
}

export const HallucinatedUserCard = React.memo(function HallucinatedUserCard({
  content,
  context,
  order,
  timestamp,
}: HallucinatedUserCardProps) {
  const [showContext, setShowContext] = useState(false);

  return (
    <div className="turn-card hallucinated-user-card">
      <div className="turn-card-header">
        {order !== undefined && <span className="turn-order">{order}</span>}
        <span className="turn-icon warning-icon">⚠️</span>
        <span className="turn-label">Hallucinated User Response</span>
        {timestamp && <span className="turn-timestamp">{timestamp}</span>}
      </div>

      <div className="turn-card-body">
        <div className="hallucination-warning">
          <div className="warning-message">
            <strong>Warning:</strong> Claude attempted to simulate a user response.
            This content was <em>not</em> sent by the user and has been flagged.
          </div>
        </div>

        <div className="hallucinated-content">
          <div className="hallucinated-label">
            <span className="label-text">Hallucinated Content</span>
            <span className="fake-user-badge">FAKE USER</span>
          </div>
          <div className="hallucinated-text">
            <MarkdownContent content={content} />
          </div>
        </div>

        {context && (
          <div className="hallucination-context-toggle">
            <button
              type="button"
              className="btn btn-link btn-small"
              onClick={() => setShowContext(!showContext)}
            >
              {showContext ? '▼ Hide' : '▶ Show'} surrounding context
            </button>
          </div>
        )}

        {showContext && context && (
          <div className="hallucination-context">
            <div className="context-label">Context</div>
            <pre className="context-text">
              <code>{context}</code>
            </pre>
          </div>
        )}

        <div className="hallucination-actions">
          <div className="action-hint">
            The model's agentic loop should be interrupted when this occurs.
            Please provide your own response to continue the conversation.
          </div>
        </div>
      </div>
    </div>
  );
});
