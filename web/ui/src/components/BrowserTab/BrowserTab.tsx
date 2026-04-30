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
  TabInfo,
  TabListResult,
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
  tabs: TabInfo[];
  onSelect: () => void;
  onSetDefault: () => void;
  onRename: (newName: string) => void;
  onDestroy: () => void;
  onRefresh: () => void;
  onScreenshot: () => void;
  onNewTab: () => void;
  onSwitchTab: (handle: string) => void;
  onCloseTab: () => void;
  onSeePreview?: () => void;
  onScreenshotToChat?: () => void;
}

function BrowserItem({
  browser,
  isDefault,
  isSelected,
  tabs,
  onSelect,
  onSetDefault,
  onRename,
  onDestroy,
  onRefresh,
  onScreenshot,
  onNewTab,
  onSwitchTab,
  onCloseTab,
  onSeePreview,
  onScreenshotToChat,
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

      {/* Tabs section - only show when connected and selected */}
      {isSelected && browser.status === 'connected' && tabs.length > 0 && (
        <div className="browser-item__tabs">
          <div className="browser-item__tabs-header">
            <span className="browser-item__tabs-label">Tabs ({tabs.length})</span>
            <ActionButton
              label="+"
              onClick={onNewTab}
              title="Open new tab"
            />
          </div>
          <div className="browser-item__tabs-list">
            {tabs.map((tab, index) => (
              <div
                key={tab.handle}
                className={`browser-item__tab ${tab.isActive ? 'browser-item__tab--active' : ''}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onSwitchTab(tab.handle);
                }}
                title={tab.url || `Tab ${index + 1}`}
              >
                <span className="browser-item__tab-index">{index + 1}</span>
                <span className="browser-item__tab-title">
                  {tab.title || tab.url || `Tab ${index + 1}`}
                </span>
                {tab.isActive && (
                  <ActionButton
                    label="✕"
                    onClick={onCloseTab}
                    variant="danger"
                    title="Close tab"
                  />
                )}
              </div>
            ))}
          </div>
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
              title="Take screenshot (preview)"
            />
            {onSeePreview && (
              <ActionButton
                label="👁️"
                onClick={onSeePreview}
                title="View page structure"
              />
            )}
            {onScreenshotToChat && (
              <ActionButton
                label="📷→💬"
                onClick={onScreenshotToChat}
                title="Save screenshot and send path to chat"
              />
            )}
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
  onSendToChat,
}: {
  dataUrl: string;
  browserName: string;
  onClose: () => void;
  onSendToChat?: () => void;
}) {
  return (
    <div className="screenshot-modal-overlay" onClick={onClose}>
      <div className="screenshot-modal" onClick={(e) => e.stopPropagation()}>
        <div className="screenshot-modal__header">
          <span>Screenshot: {browserName}</span>
          <div className="screenshot-modal__header-actions">
            {onSendToChat && (
              <button onClick={onSendToChat} title="Save and send path to chat">
                📷→💬
              </button>
            )}
            <button onClick={onClose}>✕</button>
          </div>
        </div>
        <div className="screenshot-modal__content">
          <img src={dataUrl} alt={`Screenshot of ${browserName}`} />
        </div>
      </div>
    </div>
  );
}

// Page structure preview modal (browser_see)
function SeePreviewModal({
  content,
  browserName,
  onClose,
  onSendToChat,
}: {
  content: string;
  browserName: string;
  onClose: () => void;
  onSendToChat?: () => void;
}) {
  // Try to parse and pretty-print JSON
  let displayContent = content;
  try {
    const parsed = JSON.parse(content);
    displayContent = JSON.stringify(parsed, null, 2);
  } catch {
    // Not JSON, use as-is
  }

  return (
    <div className="see-modal-overlay" onClick={onClose}>
      <div className="see-modal" onClick={(e) => e.stopPropagation()}>
        <div className="see-modal__header">
          <span>Page Structure: {browserName}</span>
          <div className="see-modal__header-actions">
            {onSendToChat && (
              <button onClick={onSendToChat} title="Send to chat">
                →💬
              </button>
            )}
            <button onClick={onClose}>✕</button>
          </div>
        </div>
        <div className="see-modal__content">
          <pre className="see-modal__json">{displayContent}</pre>
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
  /** Callback to send a message to the chat (e.g., "browser_see result: ..." or screenshot path) */
  sendMessage?: (message: string) => void;
}

export function BrowserTab({
  browserClient,
  isLoading = false,
  sendMessage,
}: BrowserTabProps) {
  const { confirm, alert } = useDialog();
  const [browsers, setBrowsers] = useState<BrowserInfo[]>([]);
  const [defaultBrowser, setDefaultBrowser] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [selectedBrowser, setSelectedBrowser] = useState<string | null>(null);
  const [screenshot, setScreenshot] = useState<{ dataUrl: string; browserName: string } | null>(null);
  const [seePreview, setSeePreview] = useState<{ content: string; browserName: string } | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [browserTabs, setBrowserTabs] = useState<Record<string, TabInfo[]>>({});

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

  // Load tabs for a browser
  const loadTabs = useCallback(
    async (name: string) => {
      if (!browserClient) return;

      try {
        const result = await browserClient.listTabs(name);
        if (result.success && result.tabs) {
          setBrowserTabs((prev) => ({ ...prev, [name]: result.tabs! }));
        }
      } catch (e) {
        console.error('Failed to load tabs:', e);
      }
    },
    [browserClient]
  );

  // Load tabs when selecting a browser
  useEffect(() => {
    if (selectedBrowser) {
      loadTabs(selectedBrowser);
    }
  }, [selectedBrowser, loadTabs]);

  // Tab actions
  const handleNewTab = useCallback(
    async (name: string) => {
      if (!browserClient) return;

      try {
        const result = await browserClient.newTab(undefined, name);
        if (result.success) {
          // Reload tabs
          loadTabs(name);
        } else {
          await alert({ title: 'Error', message: result.error || 'Failed to open new tab' });
        }
      } catch (e) {
        await alert({ title: 'Error', message: e instanceof Error ? e.message : 'Failed to open new tab' });
      }
    },
    [browserClient, alert, loadTabs]
  );

  const handleSwitchTab = useCallback(
    async (name: string, handle: string) => {
      if (!browserClient) return;

      try {
        const result = await browserClient.switchTab(handle, name);
        if (result.success) {
          // Reload tabs to update active state
          loadTabs(name);
        } else {
          await alert({ title: 'Error', message: result.error || 'Failed to switch tab' });
        }
      } catch (e) {
        await alert({ title: 'Error', message: e instanceof Error ? e.message : 'Failed to switch tab' });
      }
    },
    [browserClient, alert, loadTabs]
  );

  const handleCloseTab = useCallback(
    async (name: string) => {
      if (!browserClient) return;

      try {
        const result = await browserClient.closeTab(name);
        if (result.success) {
          // Reload tabs
          loadTabs(name);
        } else {
          await alert({ title: 'Error', message: result.error || 'Failed to close tab' });
        }
      } catch (e) {
        await alert({ title: 'Error', message: e instanceof Error ? e.message : 'Failed to close tab' });
      }
    },
    [browserClient, alert, loadTabs]
  );

  // Show browser_see preview modal
  const handleSeePreview = useCallback(
    async (name: string) => {
      if (!browserClient) return;

      try {
        const result = await browserClient.see(name);
        if (result.success && result.content) {
          setSeePreview({ content: result.content, browserName: name });
        } else {
          await alert({ title: 'Error', message: result.error || 'Failed to get page structure' });
        }
      } catch (e) {
        await alert({ title: 'Error', message: e instanceof Error ? e.message : 'Failed to get page structure' });
      }
    },
    [browserClient, alert]
  );

  // Send see preview content to chat
  const handleSendSeeToChat = useCallback(() => {
    if (!seePreview || !sendMessage) return;
    sendMessage(`Browser "${seePreview.browserName}" page structure:\n\`\`\`json\n${seePreview.content}\n\`\`\``);
    setSeePreview(null);
  }, [seePreview, sendMessage]);

  // Take screenshot, save to temp file, send path to chat
  const handleScreenshotToChat = useCallback(
    async (name: string) => {
      if (!browserClient || !sendMessage) return;

      try {
        // Pass true for saveToFile to get file path instead of data URL
        const result = await browserClient.screenshot(name, true);
        if (result.success && result.filePath) {
          sendMessage(`Screenshot saved: ${result.filePath}`);
        } else if (result.success && result.dataUrl) {
          // Fallback to data URL if file path not available
          sendMessage(`Screenshot of browser "${name}":\n${result.dataUrl}`);
        } else {
          await alert({ title: 'Error', message: result.error || 'Failed to take screenshot' });
        }
      } catch (e) {
        await alert({ title: 'Error', message: e instanceof Error ? e.message : 'Failed to take screenshot' });
      }
    },
    [browserClient, sendMessage, alert]
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
              tabs={browserTabs[browser.name] || []}
              onSelect={() => setSelectedBrowser(browser.name)}
              onSetDefault={() => handleSetDefault(browser.name)}
              onRename={(newName) => handleRename(browser.name, newName)}
              onDestroy={() => handleDestroy(browser.name)}
              onRefresh={() => handleRefresh(browser.name)}
              onScreenshot={() => handleScreenshot(browser.name)}
              onNewTab={() => handleNewTab(browser.name)}
              onSwitchTab={(handle) => handleSwitchTab(browser.name, handle)}
              onCloseTab={() => handleCloseTab(browser.name)}
              onSeePreview={() => handleSeePreview(browser.name)}
              onScreenshotToChat={sendMessage ? () => handleScreenshotToChat(browser.name) : undefined}
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
          onSendToChat={sendMessage ? async () => {
            await handleScreenshotToChat(screenshot.browserName);
            setScreenshot(null);
          } : undefined}
        />
      )}

      {seePreview && (
        <SeePreviewModal
          content={seePreview.content}
          browserName={seePreview.browserName}
          onClose={() => setSeePreview(null)}
          onSendToChat={sendMessage ? handleSendSeeToChat : undefined}
        />
      )}
    </div>
  );
}

export default BrowserTab;
