/**
 * Hook to extract code entities using LSP.
 *
 * Falls back to regex extraction when LSP is not available.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import type { LSPServiceClient, LSPDocumentSymbol } from '../../../../../generated/balloons-client';
import type { CodeEntity, CodeRelation } from './types';
import { extractEntities, extractRelations } from './entityExtractor';

// Map LSP SymbolKind to our CodeEntity types
const SYMBOL_KIND_MAP: Record<number, CodeEntity['type']> = {
  5: 'class',      // Class
  6: 'method',     // Method
  9: 'method',     // Constructor
  11: 'interface', // Interface
  12: 'function',  // Function
  13: 'variable',  // Variable
  14: 'constant',  // Constant
  2: 'module',     // Module
  23: 'class',     // Struct
  10: 'type',      // Enum
};

/**
 * Convert LSP document symbols to our CodeEntity format.
 */
function convertLSPSymbols(
  symbols: LSPDocumentSymbol[],
  filePath: string,
  language: string,
  parentId?: string,
): CodeEntity[] {
  const entities: CodeEntity[] = [];

  for (const sym of symbols) {
    const entityType = SYMBOL_KIND_MAP[sym.kind] || 'variable';
    const entityId = `${filePath}:${sym.lineStart}:${sym.name}`;

    entities.push({
      id: entityId,
      name: sym.name,
      type: entityType,
      filePath,
      lineStart: sym.lineStart + 1, // LSP is 0-indexed, we use 1-indexed
      lineEnd: sym.lineEnd + 1,
      language,
      parentId,
      isAsync: sym.detail?.includes('async') || false,
      isExported: sym.detail?.includes('export') || false,
    });

    // Process children recursively
    if (sym.children && sym.children.length > 0) {
      entities.push(...convertLSPSymbols(sym.children, filePath, language, entityId));
    }
  }

  return entities;
}

export interface UseLSPEntitiesOptions {
  /** LSP service client */
  lspClient?: LSPServiceClient;
  /** Files to extract entities from */
  files: Array<{
    path: string;
    content?: string;
    language: string;
    includedInMap: boolean;
  }>;
}

export interface UseLSPEntitiesResult {
  /** Extracted entities */
  entities: CodeEntity[];
  /** Relations between entities */
  relations: CodeRelation[];
  /** Whether currently loading */
  isLoading: boolean;
  /** Last error */
  error: string | null;
  /** Force refresh */
  refresh: () => void;
}

/**
 * Hook to extract code entities from files.
 *
 * Tries LSP first, falls back to regex extraction.
 */
export function useLSPEntities({
  lspClient,
  files,
}: UseLSPEntitiesOptions): UseLSPEntitiesResult {
  const [entities, setEntities] = useState<CodeEntity[]>([]);
  const [relations, setRelations] = useState<CodeRelation[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Track which files we've already processed
  const processedRef = useRef<Map<string, { hash: number; entities: CodeEntity[] }>>(new Map());

  // Simple hash of file content for change detection
  const hashContent = (content: string): number => {
    let hash = 0;
    for (let i = 0; i < Math.min(content.length, 1000); i++) {
      hash = ((hash << 5) - hash) + content.charCodeAt(i);
      hash = hash & hash;
    }
    return hash;
  };

  const extractFromFile = useCallback(async (
    path: string,
    content: string | undefined,
    language: string,
  ): Promise<CodeEntity[]> => {
    // Try LSP first
    if (lspClient) {
      try {
        const result = await lspClient.getDocumentSymbols(path);
        if (result.success && result.symbols && result.symbols.length > 0) {
          return convertLSPSymbols(result.symbols, path, language);
        }
      } catch (e) {
        // LSP failed, fall back to regex
        console.debug('LSP extraction failed, falling back to regex:', e);
      }
    }

    // Fall back to regex extraction
    if (content) {
      return extractEntities(content, path, language);
    }

    return [];
  }, [lspClient]);

  const refresh = useCallback(async () => {
    const mappedFiles = files.filter(f => f.includedInMap);

    if (mappedFiles.length === 0) {
      setEntities([]);
      setRelations([]);
      processedRef.current.clear();
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const allEntities: CodeEntity[] = [];
      const allRelations: CodeRelation[] = [];

      for (const file of mappedFiles) {
        const contentHash = file.content ? hashContent(file.content) : 0;
        const cached = processedRef.current.get(file.path);

        // Use cached if content hasn't changed
        if (cached && cached.hash === contentHash) {
          allEntities.push(...cached.entities);
          continue;
        }

        // Extract entities
        const fileEntities = await extractFromFile(file.path, file.content, file.language);
        allEntities.push(...fileEntities);

        // Cache the result
        processedRef.current.set(file.path, {
          hash: contentHash,
          entities: fileEntities,
        });

        // Extract relations for this file
        if (file.content) {
          allRelations.push(...extractRelations(fileEntities, file.content));
        }
      }

      // Clean up cache for files no longer in map
      const mappedPaths = new Set(mappedFiles.map(f => f.path));
      for (const path of processedRef.current.keys()) {
        if (!mappedPaths.has(path)) {
          processedRef.current.delete(path);
        }
      }

      setEntities(allEntities);
      setRelations(allRelations);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to extract entities');
    } finally {
      setIsLoading(false);
    }
  }, [files, extractFromFile]);

  // Refresh when files change
  useEffect(() => {
    refresh();
  }, [refresh]);

  return {
    entities,
    relations,
    isLoading,
    error,
    refresh,
  };
}

export default useLSPEntities;
