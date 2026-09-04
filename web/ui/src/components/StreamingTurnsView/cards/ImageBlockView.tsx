/**
 * ImageBlockView - renders an ImageBlock by fetching its bytes from the
 * auth-gated uploads route (GET /uploads/{filename}) and displaying them.
 *
 * Why fetch + blob instead of <img src="/uploads/...">: an <img> tag cannot
 * send an Authorization header, and we deliberately do NOT put the JWT in the
 * URL (it would leak into browser history / access logs). So we fetch with
 * authFetch (which attaches the Bearer token), turn the response into a blob
 * object URL, and point <img> at that. Fetched URLs are cached per file path
 * for the session; upload filenames are content-hashed and immutable, so the
 * cache never goes stale.
 */

import React, { useEffect, useState } from 'react';
import { authFetch, getAuthBaseUrl } from '../../../utils/auth';
import type { ImageBlock } from '../../../../../generated/types';

// filePath -> in-flight/resolved object URL. Object URLs are intentionally
// never revoked: they live for the page lifetime and uploads are immutable.
const objectUrlCache = new Map<string, Promise<string>>();

function loadObjectUrl(filePath: string): Promise<string> {
  const cached = objectUrlCache.get(filePath);
  if (cached) return cached;

  const filename = filePath.split(/[\\/]/).pop() || '';
  const url = `${getAuthBaseUrl()}/uploads/${encodeURIComponent(filename)}`;

  const promise = authFetch(url)
    .then(async (res) => {
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const blob = await res.blob();
      return URL.createObjectURL(blob);
    })
    .catch((err) => {
      // Don't cache failures (e.g. a transient 401 before re-login).
      objectUrlCache.delete(filePath);
      throw err;
    });

  objectUrlCache.set(filePath, promise);
  return promise;
}

interface ImageBlockViewProps {
  block: ImageBlock;
}

export const ImageBlockView = React.memo(function ImageBlockView({
  block,
}: ImageBlockViewProps): React.ReactElement {
  const filePath = block.filePath || '';
  const label = block.filename || 'Image';
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!filePath) {
      setError('No image path');
      return;
    }
    let active = true;
    setError(null);
    loadObjectUrl(filePath)
      .then((u) => {
        if (active) setObjectUrl(u);
      })
      .catch((e: unknown) => {
        if (active) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      active = false;
    };
  }, [filePath]);

  if (error) {
    return (
      <div className="image-block image-block--error">
        <span className="image-block__placeholder">🖼 {label}</span>
        <span className="image-block__error">Image unavailable ({error})</span>
      </div>
    );
  }

  if (!objectUrl) {
    return (
      <div className="image-block image-block--loading">
        <span className="image-block__placeholder">Loading {label}…</span>
      </div>
    );
  }

  return (
    <div className="image-block">
      <img
        src={objectUrl}
        alt={label}
        className="image-block__img"
        loading="lazy"
      />
      <div className="image-block__caption">
        {label}
        {block.width && block.height ? ` · ${block.width}×${block.height}` : ''}
      </div>
    </div>
  );
});