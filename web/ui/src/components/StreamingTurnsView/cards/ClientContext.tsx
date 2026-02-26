/**
 * ClientContext - Provides BalloonsClient access to card components
 *
 * Used by interactive cards (like ForkProposalCard) that need to
 * call API methods.
 */

import { createContext, useContext, type RefObject } from 'react';
import type { BalloonsClient } from '../../../../../generated/balloons-client';

// Combined context value
interface ClientContextValue {
  client: BalloonsClient | null;
  onSelectSession?: (sessionId: string) => void;
  /** Scroll container ref for IntersectionObserver root */
  scrollContainerRef?: RefObject<HTMLElement | null>;
}

// Context with null default (must be provided by parent)
export const ClientContext = createContext<ClientContextValue>({ client: null });

// Hook for accessing the client
export function useClient(): BalloonsClient | null {
  return useContext(ClientContext).client;
}

// Hook for accessing the session selection callback
export function useSelectSession(): ((sessionId: string) => void) | undefined {
  return useContext(ClientContext).onSelectSession;
}

// Hook that throws if client is not available
export function useRequiredClient(): BalloonsClient {
  const { client } = useContext(ClientContext);
  if (!client) {
    throw new Error('useRequiredClient must be used within a ClientContext.Provider');
  }
  return client;
}

// Hook for accessing the scroll container ref (for IntersectionObserver)
export function useScrollContainer(): RefObject<HTMLElement | null> | undefined {
  return useContext(ClientContext).scrollContainerRef;
}
