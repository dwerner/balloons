/**
 * BrowserTab - Browser instance management panel
 *
 * Shows:
 * - List of browser instances with status
 * - Screenshot/preview thumbnails
 * - Controls for each browser (navigate, refresh, close)
 * - Create new browser button
 * - Rename browser inline editing
 */

import React, { useState, useCallback, useEffect, useRef } from 'react';
import type { BrowserStateServiceClient } from '../../../../generated/client';
import type {
  BrowserInfo,
  BrowserListResult,
} from '../../../../generated/balloons-client';
import { useDialog } from '../Dialog';
import './BrowserTab.css';

// Status indicator component
function StatusIndicator({ status }: { status: string }) {
  const statusConfig: Record<string, { icon: string; className: string; label: string }> = {
    connecting: { icon: '\u{1F7E1}', className: 'status--connecting', label: 'Connecting' },
    connected: { icon: '\u{1F7E2}', className: 'status--connected', label: 'Connected' },
    disconnected: { icon: '\u{26AA}', className: 'status--disconnected', label: 'Disconnected' },
    error: { icon: '\u{1F534}', className: 'status--error', label: 'Error' },
  };

  const fallback = { icon: '\u{26AA}', className: 'status--unknown', label: 'Unknown' };
  const config = statusConfig[status || 'unknown'] || fallback;

  return (
    <span className={`browser-status ${config.className}`} title={config.label}>
      {config.icon}
    </span>
  );
}

// Action button component
function ActionButton({
  label,
  onClick,
  disabled = false,
  variant = 'default',
  title,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  variant?: 'default' | 'primary' | 'danger';
  title?: string;
}) {
  return (
    <button
      className={`browser-action browser-action--${variant}`}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      disabled={disabled}
      title={title}
    >
      {label}
    </button>
  );
}

// Browser item component
interface BrowserItemProps {
  browser: BrowserInfo;
  isDefault: boolean;
  isSelected: boolean;
  onSelect: () => void;
  onSetDefault: () => void;
  onRename: (newName: string) => void;
  onDestroy: () => void;
  onRefresh: () => void;
  onScreenshot: () => void;
}

function BrowserItem({
  browser,
  isDefault,
  isSelected,
  onSelect,
  onSetDefault,
  onRename,
  onDestroy,
  onRefresh,
  onScreenshot,
}: BrowserItemProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState(browser.name);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

  const handleSubmitRename = () => {
    if (editName && editName !== browser.name) {
      onRename(editName);
    }
    setIsEditing(false);
  };

  return (
    <div
      className={`browser-item ${isSelected ? 'browser-item--selected' : ''} ${isDefault ? 'browser-item--default' : ''}`}
      onClick={onSelect}
    >
      <div className="browser-item__header">
        <StatusIndicator status={browser.status} />
        {isEditing ? (
          <input
            ref={inputRef}
            className="browser-item__name-input"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            onBlur={handleSubmitRename}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                handleSubmitRename();
              } else if (e.key === 'Escape') {
                setEditName(browser.name);
                setIsEditing(false);
              }
            }}
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <span
            className="browser-item__name"
            onDoubleClick={(e) => {
              e.stopPropagation();
              setIsEditing(true);
            }}
            title="Double-click to rename"
          >
            {browser.name}
            {isDefault && <span className="browser-item__default-badge">default</span>}
          </span>
        )}
        <span className="browser-item__type">{browser.browserType}</span>
        {browser.headless && <span className="browser-item__headless-badge">headless</span>}
      </div>

      {browser.currentUrl && (
        <div className="browser-item__url" title={browser.currentUrl}>
          {browser.currentUrl}
        </div>
      )}

      {browser.currentTitle && (
        <div className="browser-item__title" title={browser.currentTitle}>
          {browser.currentTitle}
        </div>
      )}

      {browser.error && (
        <div className="browser-item__error">
          {browser.error}
        </div>
      )}

      <div className="browser-item__actions">
        {!isDefault && browser.status === 'connected' && (
          <ActionButton
            label="Set Default"
            onClick={onSetDefault}
            title="Set as default browser for tools"
          />
        )}
        {browser.status === 'connected' && (
          <>
            <ActionButton
              label="🔄"
              onClick={onRefresh}
              title="Refresh page"
            />
            <ActionButton
              label="📷"
              onClick={onScreenshot}
              title="Take screenshot"
            />
          </>
        )}
        <ActionButton
          label="✕"
          onClick={onDestroy}
          variant="danger"
          title="Close browser"
        />
      </div>
    </div>
  );
}

// Screenshot preview modal
function ScreenshotModal({
  dataUrl,
  browserName,
  onClose,
}: {
  dataUrl: string;
  browserName: string;
  onClose: () => void;
}) {
  return (
    <div className="screenshot-modal-overlay" onClick={onClose}>
      <div className="screenshot-modal" onClick={(e) => e.stopPropagation()}>
        <div className="screenshot-modal__header">
          <span>Screenshot: {browserName}</span>
          <button onClick={onClose}>✕</button>
        </div>
        <div className="screenshot-modal__content">
          <img src={dataUrl} alt={`Screenshot of ${browserName}`} />
        </div>
      </div>
    </div>
  );
}

// Create browser modal
function CreateBrowserModal({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (config: {
    name?: string;
    browserType: string;
    headless: boolean;
    webdriverUrl?: string;
    initialUrl?: string;
  }) => void;
}) {
  const [name, setName] = useState('');
  const [browserType, setBrowserType] = useState('chrome');
  const [headless, setHeadless] = useState(true);
  const [webdriverUrl, setWebdriverUrl] = useState('');
  const [initialUrl, setInitialUrl] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onCreate({
      name: name || undefined,
      browserType,
      headless,
      webdriverUrl: webdriverUrl || undefined,
      initialUrl: initialUrl || undefined,
    });
  };

  return (
    <div className="browser-modal-overlay" onClick={onClose}>
      <div className="browser-modal" onClick={(e) => e.stopPropagation()}>
        <div className="browser-modal__header">
          <span>Create Browser</span>
          <button onClick={onClose}>✕</button>
        </div>
        <form className="browser-modal__form" onSubmit={handleSubmit}>
          <div className="browser-modal__field">
            <label htmlFor="browser-name">Name (optional)</label>
            <input
              id="browser-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Auto-generated if empty"
            />
          </div>

          <div className="browser-modal__field">
            <label htmlFor="browser-type">Browser Type</label>
            <select
              id="browser-type"
              value={browserType}
              onChange={(e) => setBrowserType(e.target.value)}
            >
              <option value="chrome">Chrome</option>
              <option value="firefox">Firefox</option>
            </select>
          </div>

          <div className="browser-modal__field">
            <label htmlFor="initial-url">Initial URL (optional)</label>
            <input
              id="initial-url"
              type="text"
              value={initialUrl}
              onChange={(e) => setInitialUrl(e.target.value)}
              placeholder="https://example.com"
            />
          </div>

          <div className="browser-modal__field browser-modal__field--checkbox">
            <label>
              <input
                type="checkbox"
                checked={headless}
                onChange={(e) => setHeadless(e.target.checked)}
              />
              Headless mode
            </label>
          </div>

          <div className="browser-modal__field">
            <label htmlFor="webdriver-url">WebDriver URL (optional)</label>
            <input
              id="webdriver-url"
              type="text"
              value={webdriverUrl}
              onChange={(e) => setWebdriverUrl(e.target.value)}
              placeholder="Leave empty to auto-start"
            />
          </div>

          <div className="browser-modal__actions">
            <button type="button" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="browser-modal__submit">
              Create Browser
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Navigation bar for selected browser
function NavigationBar({
  url,
  onNavigate,
  onBack,
  onForward,
  onRefresh,
}: {
  url: string;
  onNavigate: (url: string) => void;
  onBack: () => void;
  onForward: () => void;
  onRefresh: () => void;
}) {
  const [inputUrl, setInputUrl] = useState(url);

  useEffect(() => {
    setInputUrl(url);
  }, [url]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (inputUrl) {
      onNavigate(inputUrl);
    }
  };

  return (
    <div className="browser-nav-bar">
      <button onClick={onBack} title="Back">←</button>
      <button onClick={onForward} title="Forward">→</button>
      <button onClick={onRefresh} title="Refresh">🔄</button>
      <form className="browser-nav-bar__form" onSubmit={handleSubmit}>
        <input
          type="text"
          value={inputUrl}
          onChange={(e) => setInputUrl(e.target.value)}
          placeholder="Enter URL..."
        />
        <button type="submit">Go</button>
      </form>
    </div>
  );
}

// Main component props
export interface BrowserTabProps {
  /** Browser service client */
  browserClient?: BrowserStateServiceClient;
  /** Whether loading */
  isLoading?: boolean;
}

export function BrowserTab({
  browserClient,
  isLoading = false,
}: BrowserTabProps) {
  const { confirm, alert } = useDialog();
  const [browsers, setBrowsers] = useState<BrowserInfo[]>([]);
  const [defaultBrowser, setDefaultBrowser] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [selectedBrowser, setSelectedBrowser] = useState<string | null>(null);
  const [screenshot, setScreenshot] = useState<{ dataUrl: string; browserName: string } | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);

  // Load browser list
  const loadBrowsers = useCallback(async () => {
    if (!browserClient) return;

    try {
      setIsRefreshing(true);
      const result = await browserClient.listBrowsers();
      setBrowsers(result.browsers);
      setDefaultBrowser(result.defaultBrowser ?? null);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load browsers');
    } finally {
      setIsRefreshing(false);
    }
  }, [browserClient]);

  // Initial load
  useEffect(() => {
    loadBrowsers();
  }, [loadBrowsers]);

  // Subscribe to events
  useEffect(() => {
    if (!browserClient) return;

    const unsub = browserClient.browserEvent((event) => {
      if (event.eventType === 'created' && event.browser) {
        setBrowsers((prev) => [...prev, event.browser!]);
      } else if (event.eventType === 'destroyed') {
        setBrowsers((prev) => prev.filter((b) => b.name !== event.browserName));
        if (selectedBrowser === event.browserName) {
          setSelectedBrowser(null);
        }
      } else if (event.eventType === 'status_changed' && event.browser) {
        setBrowsers((prev) =>
          prev.map((b) => (b.name === event.browserName ? event.browser! : b))
        );
      } else if (event.eventType === 'navigated' && event.browser) {
        setBrowsers((prev) =>
          prev.map((b) => (b.name === event.browserName ? event.browser! : b))
        );
      }
    });

    return () => unsub();
  }, [browserClient, selectedBrowser]);

  // Create browser
  const handleCreate = useCallback(
    async (config: {
      name?: string;
      browserType: string;
      headless: boolean;
      webdriverUrl?: string;
      initialUrl?: string;
    }) => {
      if (!browserClient) return;

      try {
        const result = await browserClient.createBrowser(
          config.name,
          config.browserType,
          config.headless,
          config.webdriverUrl
        );
        if (!result.success) {
          await alert({ title: 'Error', message: result.error || 'Failed to create browser' });
        } else if (config.initialUrl && result.browser) {
          // Navigate to initial URL after browser is created
          await browserClient.goto(config.initialUrl, result.browser.name);
        }
        setShowCreateModal(false);
      } catch (e) {
        await alert({ title: 'Error', message: e instanceof Error ? e.message : 'Failed to create browser' });
      }
    },
    [browserClient, alert]
  );

  // Destroy browser
  const handleDestroy = useCallback(
    async (name: string) => {
      if (!browserClient) return;

      const confirmed = await confirm({
        title: 'Close Browser',
        message: `Are you sure you want to close browser "${name}"?`,
        variant: 'danger',
        confirmText: 'Close',
      });
      if (!confirmed) return;

      try {
        const result = await browserClient.destroyBrowser(name);
        if (!result.success) {
          await alert({ title: 'Error', message: result.error || 'Failed to close browser' });
        }
      } catch (e) {
        await alert({ title: 'Error', message: e instanceof Error ? e.message : 'Failed to close browser' });
      }
    },
    [browserClient, confirm, alert]
  );

  // Rename browser
  const handleRename = useCallback(
    async (oldName: string, newName: string) => {
      if (!browserClient) return;

      try {
        const result = await browserClient.renameBrowser(oldName, newName);
        if (!result.success) {
          await alert({ title: 'Error', message: result.error || 'Failed to rename browser' });
        } else {
          // Update local state
          setBrowsers((prev) =>
            prev.map((b) => (b.name === oldName ? { ...b, name: newName } : b))
          );
          if (defaultBrowser === oldName) {
            setDefaultBrowser(newName);
          }
          if (selectedBrowser === oldName) {
            setSelectedBrowser(newName);
          }
        }
      } catch (e) {
        await alert({ title: 'Error', message: e instanceof Error ? e.message : 'Failed to rename browser' });
      }
    },
    [browserClient, alert, defaultBrowser, selectedBrowser]
  );

  // Set default browser
  const handleSetDefault = useCallback(
    async (name: string) => {
      if (!browserClient) return;

      try {
        const result = await browserClient.setDefault(name);
        if (result.success) {
          setDefaultBrowser(name);
        } else {
          await alert({ title: 'Error', message: result.error || 'Failed to set default browser' });
        }
      } catch (e) {
        await alert({ title: 'Error', message: e instanceof Error ? e.message : 'Failed to set default browser' });
      }
    },
    [browserClient, alert]
  );

  // Navigation actions
  const handleGoto = useCallback(
    async (url: string) => {
      if (!browserClient || !selectedBrowser) return;

      try {
        const result = await browserClient.goto(url, selectedBrowser);
        if (!result.success) {
          await alert({ title: 'Error', message: result.error || 'Failed to navigate' });
        }
      } catch (e) {
        await alert({ title: 'Error', message: e instanceof Error ? e.message : 'Failed to navigate' });
      }
    },
    [browserClient, selectedBrowser, alert]
  );

  const handleBack = useCallback(async () => {
    if (!browserClient || !selectedBrowser) return;
    try {
      await browserClient.back(selectedBrowser);
    } catch (e) {
      console.error('Back failed:', e);
    }
  }, [browserClient, selectedBrowser]);

  const handleForward = useCallback(async () => {
    if (!browserClient || !selectedBrowser) return;
    try {
      await browserClient.forward(selectedBrowser);
    } catch (e) {
      console.error('Forward failed:', e);
    }
  }, [browserClient, selectedBrowser]);

  const handleRefresh = useCallback(
    async (name?: string) => {
      if (!browserClient) return;
      const browserName = name || selectedBrowser;
      if (!browserName) return;

      try {
        await browserClient.refresh(browserName);
      } catch (e) {
        console.error('Refresh failed:', e);
      }
    },
    [browserClient, selectedBrowser]
  );

  const handleScreenshot = useCallback(
    async (name: string) => {
      if (!browserClient) return;

      try {
        const result = await browserClient.screenshot(name);
        if (result.success && result.dataUrl) {
          setScreenshot({ dataUrl: result.dataUrl, browserName: name });
        } else {
          await alert({ title: 'Error', message: result.error || 'Failed to take screenshot' });
        }
      } catch (e) {
        await alert({ title: 'Error', message: e instanceof Error ? e.message : 'Failed to take screenshot' });
      }
    },
    [browserClient, alert]
  );

  // Get selected browser info
  const selectedBrowserInfo = browsers.find((b) => b.name === selectedBrowser);

  // Loading state
  if (isLoading || (!browsers.length && !error && isRefreshing)) {
    return (
      <div className="browser-tab browser-tab--loading">
        <div className="browser-loading">Loading browser state...</div>
      </div>
    );
  }

  // Error state
  if (error && !browsers.length) {
    return (
      <div className="browser-tab browser-tab--error">
        <div className="browser-error">
          <span className="browser-error__icon">⚠️</span>
          <span className="browser-error__message">{error}</span>
          <ActionButton label="Retry" onClick={loadBrowsers} variant="primary" />
        </div>
      </div>
    );
  }

  return (
    <div className="browser-tab">
      {/* Header */}
      <div className="browser-tab__header">
        <h3>Browsers</h3>
        <div className="browser-tab__header-actions">
          <ActionButton
            label={isRefreshing ? '\u{1F504}' : '\u{21BB}'}
            onClick={loadBrowsers}
            disabled={isRefreshing}
            title="Refresh list"
          />
          <ActionButton
            label="+ New Browser"
            onClick={() => setShowCreateModal(true)}
            variant="primary"
          />
        </div>
      </div>

      {/* Browser list */}
      <div className="browser-tab__list">
        {browsers.length === 0 ? (
          <div className="browser-tab__empty">
            <p>No browsers active</p>
            <p>Click "New Browser" to create one</p>
          </div>
        ) : (
          browsers.map((browser) => (
            <BrowserItem
              key={browser.name}
              browser={browser}
              isDefault={browser.name === defaultBrowser}
              isSelected={browser.name === selectedBrowser}
              onSelect={() => setSelectedBrowser(browser.name)}
              onSetDefault={() => handleSetDefault(browser.name)}
              onRename={(newName) => handleRename(browser.name, newName)}
              onDestroy={() => handleDestroy(browser.name)}
              onRefresh={() => handleRefresh(browser.name)}
              onScreenshot={() => handleScreenshot(browser.name)}
            />
          ))
        )}
      </div>

      {/* Navigation bar for selected browser */}
      {selectedBrowserInfo && selectedBrowserInfo.status === 'connected' && (
        <NavigationBar
          url={selectedBrowserInfo.currentUrl || ''}
          onNavigate={handleGoto}
          onBack={handleBack}
          onForward={handleForward}
          onRefresh={() => handleRefresh()}
        />
      )}

      {/* Modals */}
      {showCreateModal && (
        <CreateBrowserModal
          onClose={() => setShowCreateModal(false)}
          onCreate={handleCreate}
        />
      )}

      {screenshot && (
        <ScreenshotModal
          dataUrl={screenshot.dataUrl}
          browserName={screenshot.browserName}
          onClose={() => setScreenshot(null)}
        />
      )}
    </div>
  );
}

export default BrowserTab;
