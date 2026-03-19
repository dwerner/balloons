/**
 * BackgroundPatterns - SVG pattern definitions for pane backgrounds
 *
 * These patterns are inspired by svgbackgrounds.com and adapted to work
 * with our theme colors. They use CSS custom properties for theming.
 */

import React, { memo } from 'react';
import { useTheme } from './ThemeContext';

/**
 * SVG pattern definitions that can be referenced by CSS url(#pattern-id)
 * Rendered once at the root level, patterns adapt to current theme.
 */
export const BackgroundPatternDefs = memo(function BackgroundPatternDefs() {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme !== 'light';

  // Theme-aware colors
  const strokeColor = isDark ? 'rgba(255, 255, 255, 0.15)' : 'rgba(0, 0, 0, 0.08)';
  const fillColor = isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.05)';
  const accentColor = isDark ? 'rgba(74, 222, 128, 0.15)' : 'rgba(22, 163, 74, 0.1)';

  return (
    <svg
      style={{ position: 'absolute', width: 0, height: 0, overflow: 'hidden' }}
      aria-hidden="true"
    >
      <defs>
        {/* Subtle Prism - Triangular tessellation */}
        <pattern
          id="bg-pattern-subtle-prism"
          x="0"
          y="0"
          width="40"
          height="70"
          patternUnits="userSpaceOnUse"
        >
          <polygon
            points="20,0 40,35 0,35"
            fill="none"
            stroke={strokeColor}
            strokeWidth="0.5"
          />
          <polygon
            points="20,70 40,35 0,35"
            fill="none"
            stroke={strokeColor}
            strokeWidth="0.5"
          />
        </pattern>

        {/* Endless Constellation - Connected nodes */}
        <pattern
          id="bg-pattern-endless-constellation"
          x="0"
          y="0"
          width="60"
          height="60"
          patternUnits="userSpaceOnUse"
        >
          <circle cx="10" cy="10" r="1.5" fill={fillColor} />
          <circle cx="50" cy="10" r="1" fill={fillColor} />
          <circle cx="30" cy="30" r="2" fill={accentColor} />
          <circle cx="10" cy="50" r="1" fill={fillColor} />
          <circle cx="50" cy="50" r="1.5" fill={fillColor} />
          <line x1="10" y1="10" x2="30" y2="30" stroke={strokeColor} strokeWidth="0.5" />
          <line x1="50" y1="10" x2="30" y2="30" stroke={strokeColor} strokeWidth="0.5" />
          <line x1="10" y1="50" x2="30" y2="30" stroke={strokeColor} strokeWidth="0.5" />
          <line x1="50" y1="50" x2="30" y2="30" stroke={strokeColor} strokeWidth="0.5" />
        </pattern>

        {/* Wavey Fingerprint - Curved lines */}
        <pattern
          id="bg-pattern-wavey-fingerprint"
          x="0"
          y="0"
          width="50"
          height="100"
          patternUnits="userSpaceOnUse"
        >
          <path
            d="M25 0 Q50 25 25 50 Q0 75 25 100"
            fill="none"
            stroke={strokeColor}
            strokeWidth="0.8"
          />
          <path
            d="M0 0 Q25 25 0 50 Q-25 75 0 100"
            fill="none"
            stroke={strokeColor}
            strokeWidth="0.8"
          />
          <path
            d="M50 0 Q75 25 50 50 Q25 75 50 100"
            fill="none"
            stroke={strokeColor}
            strokeWidth="0.8"
          />
        </pattern>

        {/* Large Triangles - Overlapping triangles */}
        <pattern
          id="bg-pattern-large-triangles"
          x="0"
          y="0"
          width="80"
          height="140"
          patternUnits="userSpaceOnUse"
        >
          <polygon
            points="40,0 80,70 0,70"
            fill={fillColor}
            stroke={strokeColor}
            strokeWidth="0.5"
          />
          <polygon
            points="40,140 80,70 0,70"
            fill="none"
            stroke={strokeColor}
            strokeWidth="0.5"
          />
        </pattern>

        {/* Circuit Board - Tech-inspired lines and nodes */}
        <pattern
          id="bg-pattern-circuit-board"
          x="0"
          y="0"
          width="50"
          height="50"
          patternUnits="userSpaceOnUse"
        >
          <rect x="0" y="0" width="50" height="50" fill="none" />
          <path
            d="M0 25 H15 M25 0 V15 M35 25 H50 M25 35 V50"
            stroke={strokeColor}
            strokeWidth="1"
            fill="none"
          />
          <circle cx="25" cy="25" r="3" fill="none" stroke={accentColor} strokeWidth="1" />
          <circle cx="15" cy="25" r="1.5" fill={fillColor} />
          <circle cx="35" cy="25" r="1.5" fill={fillColor} />
          <circle cx="25" cy="15" r="1.5" fill={fillColor} />
          <circle cx="25" cy="35" r="1.5" fill={fillColor} />
        </pattern>

        {/* Topography - Contour lines */}
        <pattern
          id="bg-pattern-topography"
          x="0"
          y="0"
          width="100"
          height="100"
          patternUnits="userSpaceOnUse"
        >
          <circle cx="50" cy="50" r="10" fill="none" stroke={strokeColor} strokeWidth="0.5" />
          <circle cx="50" cy="50" r="20" fill="none" stroke={strokeColor} strokeWidth="0.5" />
          <circle cx="50" cy="50" r="30" fill="none" stroke={strokeColor} strokeWidth="0.5" />
          <circle cx="50" cy="50" r="40" fill="none" stroke={strokeColor} strokeWidth="0.5" />
          <circle cx="0" cy="0" r="15" fill="none" stroke={strokeColor} strokeWidth="0.5" />
          <circle cx="100" cy="0" r="15" fill="none" stroke={strokeColor} strokeWidth="0.5" />
          <circle cx="0" cy="100" r="15" fill="none" stroke={strokeColor} strokeWidth="0.5" />
          <circle cx="100" cy="100" r="15" fill="none" stroke={strokeColor} strokeWidth="0.5" />
        </pattern>

        {/* Hexagons - Honeycomb pattern */}
        <pattern
          id="bg-pattern-hexagons"
          x="0"
          y="0"
          width="56"
          height="100"
          patternUnits="userSpaceOnUse"
        >
          <polygon
            points="28,0 56,15 56,45 28,60 0,45 0,15"
            fill="none"
            stroke={strokeColor}
            strokeWidth="0.5"
          />
          <polygon
            points="28,60 56,75 56,105 28,120 0,105 0,75"
            fill="none"
            stroke={strokeColor}
            strokeWidth="0.5"
          />
        </pattern>

        {/* Diagonal Lines */}
        <pattern
          id="bg-pattern-diagonal-lines"
          x="0"
          y="0"
          width="10"
          height="10"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)"
        >
          <line
            x1="0"
            y1="0"
            x2="0"
            y2="10"
            stroke={strokeColor}
            strokeWidth="1"
          />
        </pattern>

        {/* Plus Signs */}
        <pattern
          id="bg-pattern-plus-signs"
          x="0"
          y="0"
          width="30"
          height="30"
          patternUnits="userSpaceOnUse"
        >
          <path
            d="M15 8 V22 M8 15 H22"
            stroke={strokeColor}
            strokeWidth="1.5"
            strokeLinecap="round"
            fill="none"
          />
        </pattern>

        {/* Dots */}
        <pattern
          id="bg-pattern-dots"
          x="0"
          y="0"
          width="20"
          height="20"
          patternUnits="userSpaceOnUse"
        >
          <circle cx="10" cy="10" r="1.5" fill={fillColor} />
        </pattern>

        {/* Protruding Squares - from SVGBackgrounds.com */}
        {/* Gradient definitions for the 3D effect */}
        <linearGradient id="protruding-grad-a" gradientUnits="userSpaceOnUse" x1="100" y1="33" x2="100" y2="-3">
          <stop offset="0" stopColor="#000" stopOpacity="0" />
          <stop offset="1" stopColor="#000" stopOpacity="0.15" />
        </linearGradient>
        <linearGradient id="protruding-grad-b" gradientUnits="userSpaceOnUse" x1="100" y1="135" x2="100" y2="97">
          <stop offset="0" stopColor="#000" stopOpacity="0" />
          <stop offset="1" stopColor="#000" stopOpacity="0.15" />
        </linearGradient>

        <pattern
          id="bg-pattern-protruding-squares"
          x="0"
          y="0"
          width="70"
          height="70"
          patternUnits="userSpaceOnUse"
        >
          {/* Scale down from 200x200 viewBox to 70x70 */}
          <g transform="scale(0.35)">
            <rect fill={isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)'} width="200" height="200" />
            <g fill={fillColor} fillOpacity="0.6">
              <rect x="100" width="100" height="100" />
              <rect y="100" width="100" height="100" />
            </g>
            <g fillOpacity="0.5">
              <polygon fill="url(#protruding-grad-a)" points="100 30 0 0 200 0" />
              <polygon fill="url(#protruding-grad-b)" points="100 100 0 130 0 100 200 100 200 130" />
            </g>
          </g>
        </pattern>
      </defs>
    </svg>
  );
});

/**
 * Get the CSS background value for a pattern ID
 */
export function getPatternBackground(patternId: string, opacity: number): string {
  if (patternId === 'none' || !patternId) {
    return 'none';
  }
  // The opacity is applied via a semi-transparent overlay
  return `url(#bg-pattern-${patternId})`;
}

/**
 * Get CSS styles for a pane with a background pattern
 */
export function getPatternStyles(
  patternId: string,
  opacity: number
): React.CSSProperties {
  if (patternId === 'none' || !patternId) {
    return {};
  }

  return {
    position: 'relative' as const,
  };
}

export default BackgroundPatternDefs;
