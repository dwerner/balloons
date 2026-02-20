/**
 * ClientContext - Provides BalloonsClient access to card components
 *
 * Used by interactive cards (like ForkProposalCard) that need to
 * call API methods.
 */

import { createContext, useContext } from 'react';
import type { BalloonsClient } from '../../../../../generated/balloons-client';

// Context with null default (must be provided by parent)
export const ClientContext = createContext<BalloonsClient | null>(null);

// Hook for accessing the client
export function useClient(): BalloonsClient | null {
  return useContext(ClientContext);
}

// Hook that throws if client is not available
export function useRequiredClient(): BalloonsClient {
  const client = useContext(ClientContext);
  if (!client) {
    throw new Error('useRequiredClient must be used within a ClientContext.Provider');
  }
  return client;
}
