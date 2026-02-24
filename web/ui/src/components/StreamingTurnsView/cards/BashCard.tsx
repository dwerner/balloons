/**
 * BashCard - Command execution display with syntax highlighting
 *
 * Design goals:
 * - Command shown prominently in header or immediately visible
 * - Description (if provided) as subtitle
 * - Output shown with bash syntax highlighting
 * - Exit code / error indication
 */

import React from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock, ToolResultBlock } from '../../../../../generated/types';
import { BaseToolCard, calculateToolPhase } from './BaseToolCard';
import { SyntaxHighlightedCode } from './SyntaxHighlighter';
import './cards.css';

interface BashCardProps {
  turn: SessionDataTurn;
  result?: SessionDataTurn | null;
}

// Check if tool input is still streaming
function isStreamingInput(input: Record<string, unknown>): boolean {
  return typeof input._streaming === 'string';
}

export function BashCard({ turn, result }: BashCardProps) {
  const { contentBlock, streaming, tokens } = turn;

  // Extract tool info
  const toolUseBlock = contentBlock?.type === 'tool_use'
    ? (contentBlock as ToolUseBlock)
    : null;

  const toolInput = toolUseBlock?.input || {};
  const inputIsStreaming = isStreamingInput(toolInput);

  // Extract Bash-specific inputs
  const command = (toolInput.command || '') as string;
  const description = (toolInput.description || '') as string;
  const timeout = toolInput.timeout as number | undefined;
  const runInBackground = toolInput.run_in_background as boolean | undefined;

  // Get result info
  const resultBlock = result?.contentBlock?.type === 'tool_result'
    ? (result.contentBlock as ToolResultBlock)
    : null;
  const hasResult = !!resultBlock;
  const resultContent = resultBlock?.content || '';
  const isError = resultBlock?.isError || false;

  // Calculate phase
  const hasInput = !inputIsStreaming && !!command;
  const phase = calculateToolPhase(streaming, hasInput, inputIsStreaming, hasResult, isError);

  // Truncate very long commands for header display
  const maxHeaderLength = 60;
  const shortCommand = command.length > maxHeaderLength
    ? command.slice(0, maxHeaderLength) + '...'
    : command;

  // Header shows description if available, otherwise truncated command
  const headerContent = command ? (
    <>
      {description ? (
        <span className="tool-description">{description}</span>
      ) : (
        <code className="tool-command-preview">{shortCommand}</code>
      )}
      {runInBackground && <span className="tool-badge">background</span>}
      {timeout && <span className="tool-badge">{timeout / 1000}s</span>}
    </>
  ) : inputIsStreaming ? (
    <span className="tool-building">building...</span>
  ) : null;

  // Truncate very long output
  const maxLength = 10000;
  const truncated = resultContent.length > maxLength;
  const displayOutput = truncated
    ? resultContent.slice(0, maxLength) + '\n... [output truncated]'
    : resultContent;

  // Raw data for debugging mode
  const rawData = { turn, result };

  return (
    <BaseToolCard
      toolName="Bash"
      headerContent={headerContent}
      phase={phase}
      tokens={tokens}
      className="bash-card"
      rawData={rawData}
    >
      {/* Show full command if we have description in header, or command is long */}
      {command && (description || command.length > maxHeaderLength) && (
        <pre className="tool-command">
          <code>$ {command}</code>
        </pre>
      )}

      {/* Show streaming indicator while building */}
      {inputIsStreaming && (
        <div className="tool-building-content">
          <span className="streaming-dots">
            <span className="dot">●</span>
            <span className="dot">●</span>
            <span className="dot">●</span>
          </span>
          <span>Building command...</span>
        </div>
      )}

      {/* Output */}
      {hasResult && (
        isError ? (
          <pre className="tool-output error">
            <code>{displayOutput || '(no output)'}</code>
          </pre>
        ) : (
          <SyntaxHighlightedCode
            code={displayOutput || '(no output)'}
            language="bash"
          />
        )
      )}

      {/* Executing state */}
      {!hasResult && phase === 'executing' && (
        <div className="tool-executing">Running command...</div>
      )}
    </BaseToolCard>
  );
}

export default BashCard;
