/**
 * EditorView - Monaco editor + Code Map split view
 */

export { EditorView } from './EditorView';
export { EditorTabs } from './EditorTabs';
export { MonacoWrapper } from './MonacoWrapper';
export { SplitHandle } from './SplitHandle';
export { CodeMapPane } from './CodeMapPane';
export { extractEntities, extractRelations } from './entityExtractor';
export { useLSPEntities } from './useLSPEntities';

export type {
  EditorFile,
  EditorViewState,
  CodeEntity,
  CodeRelation,
} from './types';

export {
  detectLanguage,
  getLanguageColor,
  getMonacoLanguage,
  LANGUAGE_COLORS,
} from './types';

// Import CSS
import './EditorView.css';
