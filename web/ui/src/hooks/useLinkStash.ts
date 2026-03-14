/**
 * useLinkStash - Hook for managing link stash state with localStorage persistence
 *
 * The link stash allows users to collect references to turns/exchanges from any session,
 * then create links to them when composing messages.
 *
 * Features:
 * - Persists to localStorage across browser sessions
 * - Supports adding, removing, toggling selection
 * - Navigate to source session/turn
 * - Batch operations (link selected, clear all)
 */

import { useState, useCallback, useEffect, useMemo, useRef } from 'react';

const STORAGE_KEY = 'balloons-link-stash';

export interface LinkStashItem {
  /** Local UUID for this stash item */
  id: string;
  /** Source session ID */
  sourceSessionId: string;
  /** Source session name (for display) */
  sourceSessionName: string;
  /** Turn indices included in this reference */
  turnIndices: number[];
  /** First ~100 chars of content for preview */
  excerpt: string;
  /** When this was added to stash */
  addedAt: string;
  /** Whether this item is selected for batch operations */
  checked: boolean;
}

export interface UseLinkStashReturn {
  /** All items in the stash */
  items: LinkStashItem[];
  /** Number of checked items */
  checkedCount: number;
  /** Add a new item to the stash */
  addItem: (item: Omit<LinkStashItem, 'id' | 'addedAt' | 'checked'>) => void;
  /** Remove an item from the stash */
  removeItem: (id: string) => void;
  /** Toggle the checked state of an item */
  toggleItem: (id: string) => void;
  /** Check/uncheck all items */
  toggleAll: (checked: boolean) => void;
  /** Get all checked items */
  getCheckedItems: () => LinkStashItem[];
  /** Remove all checked items (after linking) */
  popChecked: () => LinkStashItem[];
  /** Clear all items from the stash */
  clearAll: () => void;
  /** Check if a turn is already in the stash */
  isInStash: (sessionId: string, turnIndex: number) => boolean;
}

/**
 * Generate a simple UUID v4
 */
function generateId(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Load stash from localStorage
 */
function loadFromStorage(): LinkStashItem[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const items = JSON.parse(stored);
      // Validate structure
      if (Array.isArray(items)) {
        return items.filter(
          (item) =>
            typeof item.id === 'string' &&
            typeof item.sourceSessionId === 'string' &&
            Array.isArray(item.turnIndices)
        );
      }
    }
  } catch (e) {
    console.warn('Failed to load link stash from localStorage:', e);
  }
  return [];
}

/**
 * Save stash to localStorage
 */
function saveToStorage(items: LinkStashItem[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  } catch (e) {
    console.warn('Failed to save link stash to localStorage:', e);
  }
}

/**
 * Hook for managing link stash state
 */
export function useLinkStash(): UseLinkStashReturn {
  const [items, setItems] = useState<LinkStashItem[]>(() => loadFromStorage());

  // Keep a ref to current items so callbacks can access latest state
  const itemsRef = useRef(items);
  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  // Sync to localStorage when items change
  useEffect(() => {
    saveToStorage(items);
  }, [items]);

  const addItem = useCallback(
    (item: Omit<LinkStashItem, 'id' | 'addedAt' | 'checked'>) => {
      const newItem: LinkStashItem = {
        ...item,
        id: generateId(),
        addedAt: new Date().toISOString(),
        checked: false,
      };
      setItems((prev) => [...prev, newItem]);
    },
    []
  );

  const removeItem = useCallback((id: string) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const toggleItem = useCallback((id: string) => {
    setItems((prev) =>
      prev.map((item) =>
        item.id === id ? { ...item, checked: !item.checked } : item
      )
    );
  }, []);

  const toggleAll = useCallback((checked: boolean) => {
    setItems((prev) => prev.map((item) => ({ ...item, checked })));
  }, []);

  // Use ref to always get current items - stable function reference
  const getCheckedItems = useCallback(() => {
    return itemsRef.current.filter((item) => item.checked);
  }, []);

  const popChecked = useCallback(() => {
    const checked = itemsRef.current.filter((item) => item.checked);
    setItems((prev) => prev.filter((item) => !item.checked));
    return checked;
  }, []);

  const clearAll = useCallback(() => {
    setItems([]);
  }, []);

  // Use ref for stable function reference
  const isInStash = useCallback(
    (sessionId: string, turnIndex: number) => {
      return itemsRef.current.some(
        (item) =>
          item.sourceSessionId === sessionId &&
          item.turnIndices.includes(turnIndex)
      );
    },
    []
  );

  const checkedCount = items.filter((item) => item.checked).length;

  // Memoize the return object to maintain stable reference
  // The callback functions are stable (empty deps), only items/checkedCount change
  return useMemo(() => ({
    items,
    checkedCount,
    addItem,
    removeItem,
    toggleItem,
    toggleAll,
    getCheckedItems,
    popChecked,
    clearAll,
    isInStash,
  }), [items, checkedCount, addItem, removeItem, toggleItem, toggleAll, getCheckedItems, popChecked, clearAll, isInStash]);
}

export default useLinkStash;
