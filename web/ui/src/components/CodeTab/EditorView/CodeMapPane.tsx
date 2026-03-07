/**
 * CodeMapPane - Visual code map using React Flow.
 *
 * Features:
 * - Nodes for code entities (classes, functions, etc.)
 * - Edges for relationships (calls, extends, imports)
 * - Color-coded by language
 * - Click node to navigate to code
 * - Auto-layout with elkjs
 * - Mobile-friendly zoom controls
 */

import React, { useCallback, useMemo, memo, useRef } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  useReactFlow,
  ReactFlowProvider,
  Position,
  MarkerType,
} from 'reactflow';
import type { Node, Edge, NodeTypes } from 'reactflow';
import 'reactflow/dist/style.css';

import type { CodeEntity, CodeRelation } from './types';
import { getLanguageColor } from './types';

export interface CodeMapPaneProps {
  /** Entities to display */
  entities: CodeEntity[];
  /** Relations between entities */
  relations: CodeRelation[];
  /** Currently selected entity ID */
  selectedEntityId: string | null;
  /** Dark mode */
  isDarkMode: boolean;
  /** Whether on mobile */
  isMobile?: boolean;
  /** Callback when an entity is selected */
  onSelectEntity: (entityId: string) => void;
  /** Callback when requesting fullscreen toggle */
  onToggleFullscreen?: () => void;
  /** Whether currently fullscreen */
  isFullscreen?: boolean;
}

/** Custom node component for code entities */
const CodeNode = memo(function CodeNode({ data }: { data: CodeEntity & { selected: boolean } }) {
  const bgColor = getLanguageColor(data.language);
  const typeIcons: Record<string, string> = {
    class: 'C',
    function: 'ƒ',
    method: 'm',
    interface: 'I',
    type: 'T',
    constant: '▪',
    variable: 'v',
    module: '◫',
  };

  return (
    <div
      className={`code-node code-node--${data.type} ${data.selected ? 'code-node--selected' : ''}`}
      style={{ borderColor: bgColor }}
    >
      <div className="code-node__header" style={{ backgroundColor: bgColor }}>
        <span className="code-node__type-icon">{typeIcons[data.type] || '?'}</span>
        <span className="code-node__language">{data.language}</span>
      </div>
      <div className="code-node__body">
        <span className="code-node__name">{data.name}</span>
        {data.isAsync && <span className="code-node__badge code-node__badge--async">async</span>}
        {data.isExported && <span className="code-node__badge code-node__badge--export">exp</span>}
      </div>
    </div>
  );
});

const nodeTypes: NodeTypes = {
  codeNode: CodeNode,
};

/** Mobile zoom control bar */
const MobileZoomControls = memo(function MobileZoomControls({
  onZoomIn,
  onZoomOut,
  onFitView,
  onReset,
  zoomLevel,
}: {
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFitView: () => void;
  onReset: () => void;
  zoomLevel: number;
}) {
  return (
    <div className="code-map-controls">
      <button onClick={onZoomOut} title="Zoom out" className="code-map-controls__btn">
        −
      </button>
      <span className="code-map-controls__level">{Math.round(zoomLevel * 100)}%</span>
      <button onClick={onZoomIn} title="Zoom in" className="code-map-controls__btn">
        +
      </button>
      <button onClick={onFitView} title="Fit all" className="code-map-controls__btn">
        ⊡
      </button>
      <button onClick={onReset} title="Reset" className="code-map-controls__btn">
        ↺
      </button>
    </div>
  );
});

/** Inner component that uses useReactFlow hook */
const CodeMapInner = memo(function CodeMapInner({
  entities,
  relations,
  selectedEntityId,
  isDarkMode,
  isMobile = false,
  onSelectEntity,
  onToggleFullscreen,
  isFullscreen = false,
}: CodeMapPaneProps) {
  const reactFlowInstance = useReactFlow();
  const [zoomLevel, setZoomLevel] = React.useState(1);
  // Convert entities to React Flow nodes
  const initialNodes = useMemo((): Node[] => {
    // Simple grid layout (elkjs auto-layout will come later)
    const COLS = 3;
    const NODE_WIDTH = 180;
    const NODE_HEIGHT = 80;
    const GAP_X = 40;
    const GAP_Y = 40;

    return entities.map((entity, index) => ({
      id: entity.id,
      type: 'codeNode',
      position: {
        x: (index % COLS) * (NODE_WIDTH + GAP_X),
        y: Math.floor(index / COLS) * (NODE_HEIGHT + GAP_Y),
      },
      data: { ...entity, selected: entity.id === selectedEntityId },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    }));
  }, [entities, selectedEntityId]);

  // Convert relations to React Flow edges
  const initialEdges = useMemo((): Edge[] => {
    const edgeColors: Record<string, string> = {
      calls: '#58a6ff',
      extends: '#a371f7',
      implements: '#3fb950',
      imports: '#8b949e',
      contains: '#6e7681',
    };

    return relations.map((rel, index) => ({
      id: `edge-${index}`,
      source: rel.sourceId,
      target: rel.targetId,
      label: rel.label,
      type: 'smoothstep',
      animated: rel.type === 'calls',
      style: { stroke: edgeColors[rel.type] || '#6e7681' },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: edgeColors[rel.type] || '#6e7681',
      },
    }));
  }, [relations]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Update nodes when entities change
  React.useEffect(() => {
    setNodes(initialNodes);
  }, [initialNodes, setNodes]);

  // Update edges when relations change
  React.useEffect(() => {
    setEdges(initialEdges);
  }, [initialEdges, setEdges]);

  // Handle node click
  const handleNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    onSelectEntity(node.id);
  }, [onSelectEntity]);

  // Zoom controls
  const handleZoomIn = useCallback(() => {
    reactFlowInstance.zoomIn({ duration: 200 });
  }, [reactFlowInstance]);

  const handleZoomOut = useCallback(() => {
    reactFlowInstance.zoomOut({ duration: 200 });
  }, [reactFlowInstance]);

  const handleFitView = useCallback(() => {
    reactFlowInstance.fitView({ padding: 0.2, duration: 300 });
  }, [reactFlowInstance]);

  const handleReset = useCallback(() => {
    reactFlowInstance.setViewport({ x: 0, y: 0, zoom: 1 }, { duration: 300 });
    setZoomLevel(1);
  }, [reactFlowInstance]);

  // Track zoom level changes
  const handleMoveEnd = useCallback(() => {
    const zoom = reactFlowInstance.getZoom();
    setZoomLevel(zoom);
  }, [reactFlowInstance]);

  // Empty state
  if (entities.length === 0) {
    return (
      <div className="code-map-pane code-map-pane--empty">
        <div className="code-map-pane__empty-state">
          <span className="code-map-pane__empty-icon">◉</span>
          <p>No files mapped</p>
          <p className="code-map-pane__empty-hint">
            Check the ◉ checkbox on file tabs to add them to the map
          </p>
        </div>
        {onToggleFullscreen && (
          <button
            className="code-map-pane__fullscreen-btn"
            onClick={onToggleFullscreen}
            title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
          >
            {isFullscreen ? '⊗' : '⛶'}
          </button>
        )}
      </div>
    );
  }

  return (
    <div
      className={`code-map-pane ${isFullscreen ? 'code-map-pane--fullscreen' : ''}`}
      style={{ touchAction: 'none' }}  /* Prevent viewport zoom on pinch */
    >
      {/* Fullscreen toggle */}
      {onToggleFullscreen && (
        <button
          className="code-map-pane__fullscreen-btn"
          onClick={onToggleFullscreen}
          title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
        >
          {isFullscreen ? '⊗' : '⛶'}
        </button>
      )}

      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        onMoveEnd={handleMoveEnd}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.1}
        maxZoom={4}
        zoomOnScroll={!isMobile}
        zoomOnPinch={true}
        panOnScroll={false}
        panOnDrag={true}
        preventScrolling={true}
        className={isDarkMode ? 'code-map--dark' : 'code-map--light'}
      >
        <Background
          color={isDarkMode ? '#30363d' : '#d0d7de'}
          gap={20}
          size={1}
        />
        {/* Desktop: use built-in controls; Mobile: hide them, use our bar */}
        {!isMobile && (
          <Controls
            showZoom
            showFitView
            showInteractive={false}
            position="bottom-left"
          />
        )}
        {/* MiniMap - hide on mobile to save space */}
        {!isMobile && (
          <MiniMap
            nodeColor={(node) => getLanguageColor((node.data as CodeEntity).language)}
            maskColor={isDarkMode ? 'rgba(0,0,0,0.7)' : 'rgba(255,255,255,0.7)'}
            position="bottom-right"
          />
        )}
      </ReactFlow>

      {/* Mobile zoom controls */}
      {isMobile && (
        <MobileZoomControls
          onZoomIn={handleZoomIn}
          onZoomOut={handleZoomOut}
          onFitView={handleFitView}
          onReset={handleReset}
          zoomLevel={zoomLevel}
        />
      )}
    </div>
  );
});

/** Wrapper that provides ReactFlow context */
export const CodeMapPane = memo(function CodeMapPane(props: CodeMapPaneProps) {
  return (
    <ReactFlowProvider>
      <CodeMapInner {...props} />
    </ReactFlowProvider>
  );
});

export default CodeMapPane;
