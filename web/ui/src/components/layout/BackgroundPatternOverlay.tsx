/**
 * BackgroundPatternOverlay - Renders an SVG pattern overlay for a pane
 *
 * This component renders an absolutely positioned SVG that fills the pane
 * with the selected pattern. It uses the pattern definitions from BackgroundPatterns,
 * or renders custom user-provided SVGs.
 */

import React, { memo, useMemo } from 'react';
import type { BgPatternId, CustomBackground } from './PreferencesContext';
import './BackgroundPatternOverlay.css';

interface BackgroundPatternOverlayProps {
  /** The pattern ID to display */
  patternId: BgPatternId;
  /** Opacity of the pattern (0-1) */
  opacity: number;
  /** Scale of the pattern (0.5-3) */
  scale?: number;
  /** Custom background data (if patternId starts with 'custom-') */
  customBackground?: CustomBackground;
  /** Optional className for additional styling */
  className?: string;
}

/**
 * Overlay component that renders an SVG pattern background
 * Supports:
 * 1. Built-in patterns (referenced by url(#bg-pattern-{id}))
 * 2. Custom repeating patterns (user SVG tiled)
 * 3. Custom full backgrounds (user SVG stretched to fill)
 */
export const BackgroundPatternOverlay = memo(function BackgroundPatternOverlay({
  patternId,
  opacity,
  scale = 1,
  customBackground,
  className = '',
}: BackgroundPatternOverlayProps) {
  // Encode a custom full background as a data URL. Computed unconditionally
  // (as a hook) so hook order stays stable across renders; returns undefined
  // for non-custom-full backgrounds.
  const encodedSvg = useMemo(() => {
    if (!customBackground || customBackground.type !== 'custom-full') {
      return undefined;
    }
    const svg = customBackground.svg
      .replace(/[\r\n]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
    return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`;
  }, [customBackground?.svg]);

  // Don't render anything if no pattern selected
  if (patternId === 'none' || !patternId || opacity <= 0) {
    return null;
  }

  // Check if this is a custom background
  const isCustom = patternId.startsWith('custom-');

  // Apply scale via CSS transform
  const scaleStyle = scale !== 1 ? {
    transform: `scale(${scale})`,
    transformOrigin: 'top left',
    width: `${100 / scale}%`,
    height: `${100 / scale}%`,
  } : {};

  // For custom full backgrounds, render the SVG as a background-image with fit mode
  if (isCustom && customBackground?.type === 'custom-full') {
    const fitMode = customBackground.fitMode || 'cover';

    // Map fit modes to background-size/position
    const backgroundStyles: React.CSSProperties = {
      backgroundImage: encodedSvg,
      backgroundRepeat: 'no-repeat',
    };

    switch (fitMode) {
      case 'cover':
        backgroundStyles.backgroundSize = 'cover';
        backgroundStyles.backgroundPosition = 'center';
        break;
      case 'contain':
        backgroundStyles.backgroundSize = 'contain';
        backgroundStyles.backgroundPosition = 'center';
        break;
      case 'fill':
        backgroundStyles.backgroundSize = '100% 100%';
        break;
      case 'none':
      default:
        backgroundStyles.backgroundSize = 'auto';
        backgroundStyles.backgroundPosition = 'center';
        break;
    }

    return (
      <div className={`bg-pattern-container ${className}`} aria-hidden="true">
        <div
          className="bg-pattern-overlay bg-pattern-overlay--custom-full"
          style={{
            opacity,
            ...scaleStyle,
            ...backgroundStyles,
          }}
        />
      </div>
    );
  }

  // For custom images (pasted/uploaded images)
  if (isCustom && customBackground?.type === 'custom-image') {
    const fitMode = customBackground.fitMode || 'cover';

    // The svg field contains the image data URL (base64 or URL)
    const imageUrl = customBackground.svg;

    // Map fit modes to background-size/position
    const backgroundStyles: React.CSSProperties = {
      backgroundImage: `url("${imageUrl}")`,
      backgroundRepeat: 'no-repeat',
    };

    switch (fitMode) {
      case 'cover':
        backgroundStyles.backgroundSize = 'cover';
        backgroundStyles.backgroundPosition = 'center';
        break;
      case 'contain':
        backgroundStyles.backgroundSize = 'contain';
        backgroundStyles.backgroundPosition = 'center';
        break;
      case 'fill':
        backgroundStyles.backgroundSize = '100% 100%';
        break;
      case 'none':
      default:
        backgroundStyles.backgroundSize = 'auto';
        backgroundStyles.backgroundPosition = 'center';
        break;
    }

    return (
      <div className={`bg-pattern-container ${className}`} aria-hidden="true">
        <div
          className="bg-pattern-overlay bg-pattern-overlay--custom-image"
          style={{
            opacity,
            ...scaleStyle,
            ...backgroundStyles,
          }}
        />
      </div>
    );
  }

  // For custom patterns, we need to create an inline pattern definition
  if (isCustom && customBackground?.type === 'custom-pattern') {
    // Extract viewBox or default dimensions from SVG
    const widthMatch = customBackground.svg.match(/width=['"](\d+)/);
    const heightMatch = customBackground.svg.match(/height=['"](\d+)/);
    const patternWidth = widthMatch?.[1] ? parseInt(widthMatch[1]) : 100;
    const patternHeight = heightMatch?.[1] ? parseInt(heightMatch[1]) : 100;

    // Create a unique pattern ID for this custom background
    const customPatternId = `custom-pattern-${patternId}`;

    return (
      <div className={`bg-pattern-container ${className}`} aria-hidden="true">
        {/* Define the custom pattern inline */}
        <svg style={{ position: 'absolute', width: 0, height: 0, overflow: 'hidden' }}>
          <defs>
            <pattern
              id={customPatternId}
              x="0"
              y="0"
              width={patternWidth}
              height={patternHeight}
              patternUnits="userSpaceOnUse"
            >
              <g dangerouslySetInnerHTML={{ __html: customBackground.svg.replace(/<\/?svg[^>]*>/g, '') }} />
            </pattern>
          </defs>
        </svg>
        {/* Base pattern layer */}
        <svg
          className="bg-pattern-overlay bg-pattern-overlay--base"
          style={{ opacity: opacity * 0.5, ...scaleStyle }}
          preserveAspectRatio="none"
        >
          <rect
            width="100%"
            height="100%"
            fill={`url(#${customPatternId})`}
          />
        </svg>
        {/* Glow pattern layer */}
        <svg
          className="bg-pattern-overlay bg-pattern-overlay--glow"
          style={{ opacity: opacity * 2, ...scaleStyle }}
          preserveAspectRatio="none"
        >
          <rect
            width="100%"
            height="100%"
            fill={`url(#${customPatternId})`}
          />
        </svg>
      </div>
    );
  }

  // Built-in pattern - reference the global pattern definition
  return (
    <div className={`bg-pattern-container ${className}`} aria-hidden="true">
      {/* Base pattern layer - subtle background */}
      <svg
        className="bg-pattern-overlay bg-pattern-overlay--base"
        style={{ opacity: opacity * 0.5, ...scaleStyle }}
        preserveAspectRatio="none"
      >
        <rect
          width="100%"
          height="100%"
          fill={`url(#bg-pattern-${patternId})`}
        />
      </svg>
      {/* Glow pattern layer - brighter, uses screen blend mode */}
      <svg
        className="bg-pattern-overlay bg-pattern-overlay--glow"
        style={{ opacity: opacity * 2, ...scaleStyle }}
        preserveAspectRatio="none"
      >
        <rect
          width="100%"
          height="100%"
          fill={`url(#bg-pattern-${patternId})`}
        />
      </svg>
    </div>
  );
});

export default BackgroundPatternOverlay;
