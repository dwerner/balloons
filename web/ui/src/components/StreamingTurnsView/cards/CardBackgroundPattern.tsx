/**
 * CardBackgroundPattern - Renders an SVG pattern overlay for turn cards
 *
 * This component renders a pattern overlay that sits behind the card content.
 * It uses the same pattern definitions as the pane backgrounds.
 *
 * For repeating patterns, the pattern is offset based on the card's
 * vertical position so that consecutive cards show a continuous pattern.
 */

import React, { memo, useMemo, useRef, useEffect, useState, useId } from 'react';
import { usePreferences, BUILTIN_BG_PATTERNS } from '../../layout/PreferencesContext';

interface CardBackgroundPatternProps {
  /** If true, offset the pattern based on the card's position for seamless tiling */
  seamless?: boolean;
}

// Pattern sizes for built-in patterns (approximate, used for offset calculation)
const PATTERN_SIZES: Record<string, number> = {
  'subtle-prism': 60,
  'endless-constellation': 100,
  'wavey-fingerprint': 60,
  'large-triangles': 120,
  'circuit-board': 80,
  'topography': 100,
  'hexagons': 50,
  'diagonal-lines': 20,
  'plus-signs': 40,
  'dots': 30,
  'protruding-squares': 70,
};

/**
 * Overlay component that renders an SVG pattern background for cards
 */
export const CardBackgroundPattern = memo(function CardBackgroundPattern({
  seamless = true,
}: CardBackgroundPatternProps) {
  const {
    cardBgPattern,
    cardBgPatternOpacity,
    cardBgPatternScale,
    getCustomBackground,
  } = usePreferences();

  const overlayRef = useRef<HTMLDivElement>(null);
  const [yOffset, setYOffset] = useState(0);
  const uniqueId = useId().replace(/:/g, '-');

  // Calculate the Y offset relative to the scrollable parent
  useEffect(() => {
    if (!seamless || !overlayRef.current) return;

    const calculateOffset = () => {
      const el = overlayRef.current;
      if (!el) return;

      // Find the scrollable parent (the main pane content area)
      let scrollParent: HTMLElement | null = el.parentElement;
      while (scrollParent && scrollParent.scrollHeight <= scrollParent.clientHeight) {
        scrollParent = scrollParent.parentElement;
      }

      if (scrollParent) {
        // Get the element's position relative to the scroll container
        const scrollRect = scrollParent.getBoundingClientRect();
        const elRect = el.getBoundingClientRect();
        // Calculate offset from the top of the scroll container (accounting for scroll position)
        const offset = (elRect.top - scrollRect.top) + scrollParent.scrollTop;
        setYOffset(offset);
      }
    };

    // Calculate initially and after layout
    const rafId = requestAnimationFrame(calculateOffset);

    // Recalculate on resize (card positions may change)
    const resizeObserver = new ResizeObserver(() => {
      requestAnimationFrame(calculateOffset);
    });
    if (overlayRef.current.parentElement) {
      resizeObserver.observe(overlayRef.current.parentElement);
    }

    return () => {
      cancelAnimationFrame(rafId);
      resizeObserver.disconnect();
    };
  }, [seamless]);

  // Don't render anything if no pattern selected
  if (cardBgPattern === 'none' || !cardBgPattern || cardBgPatternOpacity <= 0) {
    return null;
  }

  // Check if this is a custom background
  const isCustom = cardBgPattern.startsWith('custom-');
  const customBackground = isCustom ? getCustomBackground(cardBgPattern) : undefined;

  // Apply scale via CSS transform
  const scaleStyle = cardBgPatternScale !== 1 ? {
    transform: `scale(${cardBgPatternScale})`,
    transformOrigin: 'top left',
    width: `${100 / cardBgPatternScale}%`,
    height: `${100 / cardBgPatternScale}%`,
  } : {};

  // For custom full backgrounds, render as background-image (no seamless for full bg)
  if (isCustom && customBackground?.type === 'custom-full') {
    const encodedSvg = useMemo(() => {
      const svg = customBackground.svg
        .replace(/[\r\n]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
      return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`;
    }, [customBackground.svg]);

    return (
      <div
        ref={overlayRef}
        className="card-pattern-overlay"
        style={{
          opacity: cardBgPatternOpacity,
          backgroundImage: encodedSvg,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
          ...scaleStyle,
        }}
        aria-hidden="true"
      />
    );
  }

  // For custom image backgrounds (no seamless for images)
  if (isCustom && customBackground?.type === 'custom-image') {
    return (
      <div
        ref={overlayRef}
        className="card-pattern-overlay"
        style={{
          opacity: cardBgPatternOpacity,
          backgroundImage: `url("${customBackground.svg}")`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
          ...scaleStyle,
        }}
        aria-hidden="true"
      />
    );
  }

  // For custom patterns, create an inline pattern definition with Y offset
  if (isCustom && customBackground?.type === 'custom-pattern') {
    const widthMatch = customBackground.svg.match(/width=['"](\d+)/);
    const heightMatch = customBackground.svg.match(/height=['"](\d+)/);
    const patternWidth = widthMatch?.[1] ? parseInt(widthMatch[1]) : 100;
    const patternHeight = heightMatch?.[1] ? parseInt(heightMatch[1]) : 100;
    const customPatternId = `card-pattern-${uniqueId}`;

    // Calculate Y offset for seamless tiling (negative to shift pattern up)
    const patternY = seamless ? -(yOffset % patternHeight) : 0;

    return (
      <div ref={overlayRef} className="card-pattern-overlay" aria-hidden="true">
        <svg
          className="card-pattern-svg"
          style={{ opacity: cardBgPatternOpacity, ...scaleStyle }}
          preserveAspectRatio="none"
        >
          <defs>
            <pattern
              id={customPatternId}
              x="0"
              y={patternY}
              width={patternWidth}
              height={patternHeight}
              patternUnits="userSpaceOnUse"
            >
              <g dangerouslySetInnerHTML={{ __html: customBackground.svg.replace(/<\/?svg[^>]*>/g, '') }} />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill={`url(#${customPatternId})`} />
        </svg>
      </div>
    );
  }

  // Built-in pattern - create a local <use> wrapper pattern with Y offset
  // This references the global pattern definition but applies a local Y offset
  const patternSize = PATTERN_SIZES[cardBgPattern] || 100;
  const localPatternId = `card-builtin-${uniqueId}`;
  const patternY = seamless ? -(yOffset % patternSize) : 0;

  return (
    <div ref={overlayRef} className="card-pattern-overlay" aria-hidden="true">
      <svg
        className="card-pattern-svg"
        style={{ opacity: cardBgPatternOpacity, ...scaleStyle }}
        preserveAspectRatio="none"
      >
        <defs>
          {/* Create a wrapper pattern that tiles the built-in pattern with Y offset */}
          <pattern
            id={localPatternId}
            x="0"
            y={patternY}
            width={patternSize}
            height={patternSize}
            patternUnits="userSpaceOnUse"
          >
            {/* Reference the built-in pattern by filling a rect with it */}
            <rect width={patternSize} height={patternSize} fill={`url(#bg-pattern-${cardBgPattern})`} />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill={`url(#${localPatternId})`} />
      </svg>
    </div>
  );
});

export default CardBackgroundPattern;
