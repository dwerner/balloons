import React, { memo, useCallback, useEffect, useMemo, useState } from 'react';
import Editor from '@monaco-editor/react';
import type { BalloonsClient, RunnerContextPreviewResult as GeneratedRunnerContextPreviewResult } from '../../../../generated/balloons-client';
import { createLogger } from '../../utils/debugLog';

const debugLog = createLogger('RunnerContextPreview');

interface RunnerContextPreviewProps {
  sessionId: string | null;
  client: BalloonsClient | null;
  enabledTools?: string[];
  backendName?: string | null;
  refreshKey?: string;
  isLoading?: boolean;
}

interface TreeNode {
  id: string;
  kind: string;
  label: string;
  summary?: string;
  text?: string;
  role?: string;
  contextMode?: string;
  blockType?: string;
  data?: Record<string, unknown>;
  children?: TreeNode[];
}

type RunnerContextPreviewResult = Omit<GeneratedRunnerContextPreviewResult, 'tree'> & {
  tree?: TreeNode[];
};

function formatLength(len: number): string {
  if (len < 1000) return `${len} chars`;
  const kt = Math.round(len / 100) / 10;
  return `${kt.toFixed(1)}k chars`;
}

function getNodeBadges(node: TreeNode): string[] {
  const badges: string[] = [];
  if (node.kind) badges.push(node.kind);
  if (node.role) badges.push(node.role);
  if (node.blockType) badges.push(node.blockType);
  if (node.contextMode) badges.push(`mode:${node.contextMode}`);
  return badges;
}

function TreeNodeView({
  node,
  onSelect,
  selectedId,
}: {
  node: TreeNode;
  onSelect: (node: TreeNode) => void;
  selectedId: string | null;
}) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = !!node.children?.length;
  const isSelected = node.id === selectedId;

  return (
    <li className="ctx-runner-tree__node">
      <div
        className={`ctx-runner-tree__row ${isSelected ? 'ctx-runner-tree__row--selected' : ''}`}
        onClick={() => onSelect(node)}
      >
        <button
          className="ctx-runner-tree__toggle"
          onClick={(e) => {
            e.stopPropagation();
            if (hasChildren) setExpanded(v => !v);
          }}
        >
          {hasChildren ? (expanded ? '▾' : '▸') : '·'}
        </button>
        <span className="ctx-runner-tree__label">{node.label}</span>
        {node.summary && <span className="ctx-runner-tree__summary">{node.summary}</span>}
      </div>
      {hasChildren && expanded && (
        <ul className="ctx-runner-tree__children">
          {node.children!.map((child) => (
            <TreeNodeView key={child.id} node={child} onSelect={onSelect} selectedId={selectedId} />
          ))}
        </ul>
      )}
    </li>
  );
}

export const RunnerContextPreview = memo(function RunnerContextPreview({
  sessionId,
  client,
  enabledTools,
  backendName,
  refreshKey,
  isLoading = false,
}: RunnerContextPreviewProps) {
  const [result, setResult] = useState<RunnerContextPreviewResult | null>(null);
  const [selectedNode, setSelectedNode] = useState<TreeNode | null>(null);
  const [activeView, setActiveView] = useState<'tree' | 'raw'>('tree');
  const [activeRawTab, setActiveRawTab] = useState<'compiled' | 'packaged' | 'system'>('compiled');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const normalizedEnabledTools = useMemo(
    () => [...(enabledTools ?? [])].sort((a, b) => a.localeCompare(b)),
    [enabledTools]
  );

  const loadPreview = useCallback(async () => {
    if (!client || !sessionId) return;

    setIsRefreshing(true);
    setError(null);
    try {
      const next = await client.sessions.getRunnerContextPreview(sessionId, normalizedEnabledTools);
      const typedNext = next as RunnerContextPreviewResult;
      setResult(typedNext);
      setSelectedNode((prev) => {
        if (prev && typedNext.tree?.some((node) => node.id === prev.id)) {
          return prev;
        }
        return typedNext.tree?.[0] ?? null;
      });
      debugLog('Loaded structured runner context preview', {
        sessionId,
        backendName,
        backendType: typedNext.backendType,
        enabledToolsCount: normalizedEnabledTools.length,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      setResult(null);
      debugLog('Error loading structured runner context preview', {
        sessionId,
        backendName,
        error: msg,
      });
    } finally {
      setIsRefreshing(false);
    }
  }, [client, sessionId, normalizedEnabledTools, backendName]);

  useEffect(() => {
    if (!isLoading) {
      loadPreview();
    }
  }, [isLoading, loadPreview, refreshKey]);

  useEffect(() => {
    if (!client || !sessionId) return;

    const unsubscribe = client.sessionData.sessionDataSessionUpdated((event) => {
      if (event.sessionId === sessionId) {
        loadPreview();
      }
    });

    return unsubscribe;
  }, [client, sessionId, loadPreview]);

  if (!sessionId) {
    return (
      <div className="ctx-runner-preview ctx-runner-preview--empty">
        <div className="ctx-tab-view__empty-state">
          <h2>No Session Selected</h2>
          <p>Select a session to preview runner context.</p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return <div className="ctx-runner-preview__loading">Loading runner context...</div>;
  }

  const rawValue = activeRawTab === 'compiled'
    ? (result?.rawText || '')
    : activeRawTab === 'system'
      ? (result?.systemPrompt || '')
      : (result?.packagedMessagesJson || '');
  const rawLanguage = activeRawTab === 'packaged' ? 'json' : 'markdown';
  const selectedDetails = selectedNode
    ? JSON.stringify({
        id: selectedNode.id,
        kind: selectedNode.kind,
        label: selectedNode.label,
        summary: selectedNode.summary,
        role: selectedNode.role,
        contextMode: selectedNode.contextMode,
        blockType: selectedNode.blockType,
        text: selectedNode.text,
        data: selectedNode.data,
        childCount: selectedNode.children?.length ?? 0,
      }, null, 2)
    : '';

  return (
    <div className="ctx-runner-preview">
      <div className="ctx-runner-preview__header">
        <div>
          <div className="ctx-runner-preview__title">Runner Context Preview</div>
          <div className="ctx-runner-preview__subtitle">
            Structured tree plus backend-packaged raw context for debugging.
          </div>
        </div>
        <div className="ctx-runner-preview__meta">
          <span className="ctx-runner-preview__pill">Backend: {result?.backendName || backendName || 'unknown'}</span>
          <span className="ctx-runner-preview__pill">Type: {result?.backendType || 'unknown'}</span>
          <span className="ctx-runner-preview__pill">Tools: {result?.effectiveEnabledTools?.length ?? normalizedEnabledTools.length}</span>
          <span className="ctx-runner-preview__pill">Turns: {result?.turnCount ?? 0}</span>
          <span className="ctx-runner-preview__pill">Messages: {result?.messageCount ?? 0}</span>
          <span className="ctx-runner-preview__pill">System: {formatLength(result?.systemPromptLength || 0)}</span>
          <span className="ctx-runner-preview__pill">Compiled: {formatLength(result?.rawLength || 0)}</span>
          <span className="ctx-runner-preview__pill">Packaged: {formatLength(result?.packagedMessagesLength || 0)}</span>
          <button className="ctx-runner-preview__refresh" onClick={loadPreview} disabled={isRefreshing}>
            {isRefreshing ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </div>

      <div className="ctx-runner-preview__toolbar">
        <button className={`ctx-tab-view__subtab ${activeView === 'tree' ? 'ctx-tab-view__subtab--active' : ''}`} onClick={() => setActiveView('tree')}>Tree</button>
        <button className={`ctx-tab-view__subtab ${activeView === 'raw' ? 'ctx-tab-view__subtab--active' : ''}`} onClick={() => setActiveView('raw')}>Raw</button>
      </div>

      {error && <div className="ctx-runner-preview__error">{error}</div>}

      {activeView === 'tree' ? (
        <div className="ctx-runner-preview__split">
          <div className="ctx-runner-preview__tree-pane">
            <ul className="ctx-runner-tree">
              {(result?.tree || []).map((node) => (
                <TreeNodeView key={node.id} node={node} onSelect={setSelectedNode} selectedId={selectedNode?.id ?? null} />
              ))}
            </ul>
          </div>
          <div className="ctx-runner-preview__details-pane">
            <div className="ctx-runner-preview__details-header">Node Details</div>
            {selectedNode && (
              <div className="ctx-runner-preview__details-meta">
                <div className="ctx-runner-preview__details-title">{selectedNode.label}</div>
                <div className="ctx-runner-preview__details-badges">
                  {getNodeBadges(selectedNode).map((badge) => (
                    <span key={badge} className="ctx-runner-preview__detail-pill">{badge}</span>
                  ))}
                </div>
              </div>
            )}
            <Editor
              height="100%"
              defaultLanguage="json"
              value={selectedDetails}
              theme="vs-dark"
              options={{ readOnly: true, minimap: { enabled: false }, wordWrap: 'on', fontSize: 13, lineNumbers: 'on', scrollBeyondLastLine: false }}
            />
          </div>
        </div>
      ) : (
        <div className="ctx-runner-preview__raw-wrap">
          <div className="ctx-runner-preview__raw-tabs">
            <button className={`ctx-tab-view__subtab ${activeRawTab === 'compiled' ? 'ctx-tab-view__subtab--active' : ''}`} onClick={() => setActiveRawTab('compiled')}>Compiled</button>
            <button className={`ctx-tab-view__subtab ${activeRawTab === 'system' ? 'ctx-tab-view__subtab--active' : ''}`} onClick={() => setActiveRawTab('system')}>System Prompt</button>
            <button className={`ctx-tab-view__subtab ${activeRawTab === 'packaged' ? 'ctx-tab-view__subtab--active' : ''}`} onClick={() => setActiveRawTab('packaged')}>Packaged ({result?.packagedFormat || 'raw'})</button>
          </div>
          <div className="ctx-runner-preview__editor">
            <Editor
              height="100%"
              defaultLanguage={rawLanguage}
              value={rawValue}
              theme="vs-dark"
              options={{ readOnly: true, minimap: { enabled: false }, wordWrap: 'on', fontSize: 13, lineNumbers: 'on', scrollBeyondLastLine: false, renderWhitespace: 'selection' }}
            />
          </div>
        </div>
      )}
    </div>
  );
});

export default RunnerContextPreview;
