/**
 * GroceryTab - Main UI for the grocery shopping plugin
 *
 * Features:
 * - Store selection
 * - Product search
 * - Cart management
 * - Browser automation status
 */

import React, { useState, useEffect, useRef } from 'react';
import './GroceryTab.css';

// Plugin context from host
export interface PluginContext {
  sendMessage?: (message: string) => void;
  sessionId?: string;
  subscribeToDomainEvents?: (
    domainId: string,
    callback: (event: DomainEventData) => void
  ) => () => void;
  requestDomainState?: (domainId: string) => Promise<boolean>;
  isLLMResponding?: boolean;
  /** Call a @ws_expose method on a domain plugin */
  callDomainMethod?: (
    methodName: string,
    params?: Record<string, unknown> | null
  ) => Promise<Record<string, unknown>>;
}

export interface DomainEventData {
  sessionId: string;
  domainId: string;
  eventType: string;
  data: Record<string, unknown>;
}

interface CartItem {
  product_code: string;
  name: string;
  price: number;
  quantity: number;
  brand?: string;
  size?: string;
}

interface GroceryState {
  store_id?: string;
  banner?: string;
  browser_host?: string;
  cart_count: number;
  cart_total: number;
  cart_items: CartItem[];
}

interface BrowserHost {
  name: string;
  type: 'local' | 'ssh';
  description?: string;
  host?: string;
  user?: string;
}

const BANNERS = [
  { id: 'superstore', name: 'Real Canadian Superstore' },
  { id: 'nofrills', name: 'No Frills' },
  { id: 'loblaws', name: 'Loblaws' },
  { id: 'zehrs', name: 'Zehrs' },
  { id: 'saveon', name: 'SaveOn Foods' },
];

export function GroceryTab({
  sendMessage,
  sessionId,
  subscribeToDomainEvents,
  requestDomainState,
  isLLMResponding,
  callDomainMethod,
}: PluginContext) {
  // State
  const [state, setState] = useState<GroceryState | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [storeId, setStoreId] = useState('1511');
  const [banner, setBanner] = useState('superstore');
  const [browserStatus, setBrowserStatus] = useState<'stopped' | 'running' | 'starting'>('stopped');
  const [browserHosts, setBrowserHosts] = useState<BrowserHost[]>([]);
  const [selectedHost, setSelectedHost] = useState('local');
  const initializedRef = useRef(false);

  // Request initial state AND load browser hosts on mount
  // The domain must be loaded (via requestDomainState) before calling domain methods
  useEffect(() => {
    // Only run once
    if (initializedRef.current) return;
    if (!sessionId || !callDomainMethod) return;

    initializedRef.current = true;

    const initDomain = async () => {
      // First, trigger domain loading via state request
      if (requestDomainState) {
        console.log('[GroceryTab] Requesting domain state to trigger domain loading...');
        await requestDomainState('grocery');
      }

      // Then load browser hosts via @ws_expose method
      try {
        console.log('[GroceryTab] Calling getBrowserHosts...');
        const result = await callDomainMethod('getBrowserHosts', {});
        console.log('[GroceryTab] getBrowserHosts result:', result);

        if (result && Array.isArray(result)) {
          const hosts: BrowserHost[] = result.map((h: any) => ({
            name: h.name,
            type: h.type,
            host: h.host,
            user: h.user,
            description: h.description,
          }));
          console.log('[GroceryTab] Parsed hosts:', hosts);
          setBrowserHosts(hosts);
          // Set initial selection to current host
          const current = result.find((h: any) => h.is_current);
          if (current) {
            setSelectedHost(current.name);
          }
        } else if (result && typeof result === 'object' && 'error' in result) {
          console.error('[GroceryTab] getBrowserHosts error:', result.error);
        } else {
          console.log('[GroceryTab] Result is not an array:', typeof result, result);
        }
      } catch (e) {
        console.error('[GroceryTab] Failed to load hosts:', e);
      }
    };
    initDomain();
  }, [requestDomainState, sessionId, callDomainMethod]);

  // Subscribe to domain events
  useEffect(() => {
    if (!subscribeToDomainEvents || !sessionId) return;

    return subscribeToDomainEvents('grocery', (event) => {
      if (event.sessionId !== sessionId) return;

      console.log('[GroceryTab] Event:', event.eventType, event.data);

      switch (event.eventType) {
        case 'grocery_state_sync':
        case 'state_sync':
          const newState = event.data as unknown as GroceryState;
          setState(newState);
          // Sync host selection from state
          if (newState.browser_host) {
            setSelectedHost(newState.browser_host);
          }
          break;
        // Add more event handlers as needed
      }
    });
  }, [subscribeToDomainEvents, sessionId]);

  // Set store - call directly via @ws_expose
  const handleSetStore = async () => {
    if (!callDomainMethod) {
      setError('Domain method not available');
      return;
    }

    try {
      const result = await callDomainMethod('grocerySetStore', {
        store_id: storeId,
        banner: banner,
      });
      console.log('[GroceryTab] grocerySetStore result:', result);
      // Refresh state after setting store
      if (requestDomainState) {
        await requestDomainState('grocery');
      }
    } catch (e) {
      console.error('[GroceryTab] Failed to set store:', e);
      setError(`Failed to set store: ${e}`);
    }
  };

  // Search products - call directly via @ws_expose
  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    if (!callDomainMethod) {
      setError('Domain method not available');
      return;
    }

    if (browserStatus !== 'running') {
      setError('Start the browser first to search products');
      return;
    }

    setIsSearching(true);
    setError(null);

    try {
      const result = await callDomainMethod('groceryBrowserSearch', {
        query: searchQuery,
      });
      console.log('[GroceryTab] groceryBrowserSearch result:', result);
      // Result contains URL and title after search
    } catch (e) {
      console.error('[GroceryTab] Failed to search:', e);
      setError(`Failed to search: ${e}`);
    } finally {
      setIsSearching(false);
    }
  };

  // Set browser host via @ws_expose method
  const handleSetHost = async (hostName: string) => {
    setSelectedHost(hostName);
    if (!callDomainMethod) return;

    try {
      const result = await callDomainMethod('setBrowserHost', { host: hostName });
      if (result && result.error) {
        setError(result.error as string);
      }
    } catch (e) {
      setError(`Failed to set host: ${e}`);
    }
  };

  // Start browser - call @ws_expose method directly
  const handleStartBrowser = async () => {
    if (!callDomainMethod) {
      setError('Domain method not available');
      return;
    }

    setBrowserStatus('starting');
    setError(null);

    try {
      const result = await callDomainMethod('groceryBrowserStart', {});
      console.log('[GroceryTab] groceryBrowserStart result:', result);

      // Check for ToolResult format (has 'result' key) or error
      if (result && typeof result === 'object') {
        if ('error' in result) {
          setError(result.error as string);
          setBrowserStatus('stopped');
        } else {
          // Success
          setBrowserStatus('running');
        }
      }
    } catch (e) {
      console.error('[GroceryTab] Failed to start browser:', e);
      setError(`Failed to start browser: ${e}`);
      setBrowserStatus('stopped');
    }
  };

  // Stop browser - call @ws_expose method directly
  const handleStopBrowser = async () => {
    if (!callDomainMethod) return;

    try {
      const result = await callDomainMethod('groceryBrowserStop', {});
      console.log('[GroceryTab] groceryBrowserStop result:', result);
      setBrowserStatus('stopped');
    } catch (e) {
      console.error('[GroceryTab] Failed to stop browser:', e);
      // Still mark as stopped even on error
      setBrowserStatus('stopped');
    }
  };

  return (
    <div className="grocery-tab">
      {/* Header */}
      <div className="grocery-header">
        <h2>Grocery Shopping</h2>
        <div className="grocery-browser-controls">
          {/* Host selector */}
          <select
            value={selectedHost}
            onChange={(e) => handleSetHost(e.target.value)}
            disabled={browserStatus !== 'stopped'}
            className="host-selector"
            title="Select where the browser runs"
          >
            {browserHosts.length === 0 ? (
              <option value="local">local (headless)</option>
            ) : (
              browserHosts.map(host => (
                <option key={host.name} value={host.name}>
                  {host.name} {host.type === 'local' ? '(headless)' : ''}
                </option>
              ))
            )}
          </select>

          {/* Browser status/controls */}
          <div className="grocery-browser-status">
            {browserStatus === 'stopped' && (
              <button onClick={handleStartBrowser} className="browser-btn start">
                Start Browser
              </button>
            )}
            {browserStatus === 'starting' && (
              <span className="browser-status starting">Starting...</span>
            )}
            {browserStatus === 'running' && (
              <>
                <span className="browser-status running">
                  Running{selectedHost !== 'local' ? ` on ${selectedHost}` : ''}
                </span>
                <button onClick={handleStopBrowser} className="browser-btn stop">
                  Stop
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="grocery-error">
          {error}
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      {/* Store selector */}
      <div className="grocery-section">
        <h3>Store</h3>
        <div className="grocery-store-selector">
          <select
            value={banner}
            onChange={(e) => setBanner(e.target.value)}
          >
            {BANNERS.map(b => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </select>
          <input
            type="text"
            value={storeId}
            onChange={(e) => setStoreId(e.target.value)}
            placeholder="Store ID"
            className="store-id-input"
          />
          <button onClick={handleSetStore}>Set Store</button>
        </div>
        {state?.store_id && (
          <div className="current-store">
            Current: {state.banner} #{state.store_id}
          </div>
        )}
      </div>

      {/* Search */}
      <div className="grocery-section">
        <h3>Search Products</h3>
        <div className="grocery-search">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="Search for products..."
            disabled={isSearching}
          />
          <button onClick={handleSearch} disabled={isSearching || !searchQuery.trim()}>
            {isSearching ? 'Searching...' : 'Search'}
          </button>
        </div>
        {/* Search results would go here - for now, just show a placeholder */}
        <div className="grocery-search-results">
          <p className="placeholder">
            Search results will appear here. Use the LLM to search and the results will sync.
          </p>
        </div>
      </div>

      {/* Cart */}
      <div className="grocery-section">
        <h3>Cart ({state?.cart_count || 0} items)</h3>
        {state?.cart_items && state.cart_items.length > 0 ? (
          <>
            <div className="grocery-cart-items">
              {state.cart_items.map((item) => (
                <div key={item.product_code} className="cart-item">
                  <span className="item-name">
                    {item.brand && `${item.brand} `}
                    {item.name}
                    {item.size && ` (${item.size})`}
                  </span>
                  <span className="item-qty">×{item.quantity}</span>
                  <span className="item-price">${(item.price * item.quantity).toFixed(2)}</span>
                </div>
              ))}
            </div>
            <div className="grocery-cart-total">
              <strong>Total: ${state.cart_total?.toFixed(2) || '0.00'}</strong>
            </div>
          </>
        ) : (
          <p className="placeholder">Cart is empty</p>
        )}
      </div>

      {/* Quick actions */}
      <div className="grocery-section">
        <h3>Quick Actions</h3>
        <div className="grocery-quick-actions">
          <button
            onClick={async () => {
              if (!callDomainMethod) return;
              try {
                const result = await callDomainMethod('groceryCartShow', {});
                console.log('[GroceryTab] Cart:', result);
                // TODO: Display cart in UI rather than console
              } catch (e) {
                setError(`Failed to show cart: ${e}`);
              }
            }}
            disabled={!callDomainMethod}
          >
            Show Cart
          </button>
          <button
            onClick={async () => {
              if (!callDomainMethod) return;
              try {
                const result = await callDomainMethod('groceryCartExport', {});
                console.log('[GroceryTab] Export:', result);
                // TODO: Display export in a modal
              } catch (e) {
                setError(`Failed to export cart: ${e}`);
              }
            }}
            disabled={!callDomainMethod}
          >
            Export Cart
          </button>
          <button
            onClick={async () => {
              if (!callDomainMethod) return;
              try {
                const result = await callDomainMethod('groceryBrowserScreenshot', {});
                console.log('[GroceryTab] Screenshot:', result);
                // Result contains path to screenshot file
              } catch (e) {
                setError(`Failed to take screenshot: ${e}`);
              }
            }}
            disabled={!callDomainMethod || browserStatus !== 'running'}
          >
            Screenshot
          </button>
        </div>
      </div>
    </div>
  );
}

export default GroceryTab;
