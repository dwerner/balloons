/**
 * GroceryTab - Main UI for the grocery shopping plugin
 *
 * Features:
 * - Store selection
 * - Product search
 * - Cart management
 * - Browser automation status
 */

import React, { useState, useEffect } from 'react';
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

  // Request initial state on mount
  useEffect(() => {
    if (requestDomainState && sessionId) {
      requestDomainState('grocery').catch(console.error);
    }
  }, [requestDomainState, sessionId]);

  // Load browser hosts on mount using @ws_expose method
  useEffect(() => {
    const loadHosts = async () => {
      console.log('[GroceryTab] loadHosts called, callDomainMethod:', !!callDomainMethod);
      if (!callDomainMethod) return;
      try {
        // Call the @ws_expose method which returns JSON directly
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
        } else {
          console.log('[GroceryTab] Result is not an array:', typeof result);
        }
      } catch (e) {
        console.error('[GroceryTab] Failed to load hosts:', e);
      }
    };
    loadHosts();
  }, [callDomainMethod]);

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

  // Set store - ask LLM to call the tool
  const handleSetStore = () => {
    if (!sendMessage) return;
    sendMessage(`grocery_set_store(store_id="${storeId}", banner="${banner}")`);
  };

  // Search products - ask LLM to use browser search
  const handleSearch = () => {
    if (!searchQuery.trim()) return;
    if (!sendMessage) return;

    if (browserStatus !== 'running') {
      setError('Start the browser first to search products');
      return;
    }

    setIsSearching(true);
    setError(null);
    sendMessage(`grocery_browser_search(query="${searchQuery}")`);
    // Note: isSearching will be cleared when we get a response
    setTimeout(() => setIsSearching(false), 5000);
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

  // Start browser - ask LLM to call the tool
  const handleStartBrowser = () => {
    if (!sendMessage) return;
    setBrowserStatus('starting');
    setError(null);
    sendMessage('grocery_browser_start()');
    // Status will be updated via domain events or we timeout
    setTimeout(() => {
      if (browserStatus === 'starting') {
        setBrowserStatus('running');
      }
    }, 10000);
  };

  // Stop browser - ask LLM to call the tool
  const handleStopBrowser = () => {
    if (!sendMessage) return;
    sendMessage('grocery_browser_stop()');
    setBrowserStatus('stopped');
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
            onClick={() => sendMessage?.('grocery_cart_show')}
            disabled={isLLMResponding}
          >
            Show Cart
          </button>
          <button
            onClick={() => sendMessage?.('grocery_cart_export')}
            disabled={isLLMResponding}
          >
            Export Cart
          </button>
          <button
            onClick={() => sendMessage?.('grocery_browser_screenshot')}
            disabled={isLLMResponding || browserStatus !== 'running'}
          >
            Screenshot
          </button>
        </div>
      </div>
    </div>
  );
}

export default GroceryTab;
