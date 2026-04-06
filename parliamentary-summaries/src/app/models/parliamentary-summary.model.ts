// src/app/models/parliamentary-summary.model.ts

// Base interfaces
export interface ParliamentarySummary {
  executive_summary: string;
  main_topics: EnhancedTopic[];
  key_decisions: string[];
  political_dynamics: string;
  next_steps: string[];
  meeting_info: MeetingInfo;
  processing_info: ProcessingInfo;
}

export interface EnhancedTopic {
  topic: string;
  context?: TopicContext;
  summary: string;
  party_positions: { [party: string]: EnhancedPartyPosition | string };
  outcome: string;
}

export interface TopicContext {
  why_discussed?: string;
  background?: string;
  stakes?: string;
  trigger?: string;
}

export interface EnhancedPartyPosition {
  position: string;
  specific_proposals?: string[];
  reasoning?: string;
  key_evidence?: string;
}

export interface MeetingInfo {
  vergadering_titel: string;
  vergadering_datum: string;
  verslag_id: string;
  status: string;
}

export interface ProcessingInfo {
  chunks_processed: number;
  total_topics_found: number;
  processing_date: string;
  enhancement_level?: string;
  ai_model?: string;
}

export interface ParliamentaryDocument {
  id: string;
  title: string;
  date: Date;
  summary: ParliamentarySummary;
}

// Helper interfaces for filtering and display
export interface TopicFilter {
  name: string;
  selected: boolean;
  count?: number; // Number of meetings discussing this topic
}

export interface PartyFilter {
  name: string;
  selected: boolean;
  color?: string; // For party colors in UI
  positions?: number; // Number of positions taken
}

export interface SearchFilter {
  query: string;
  includeTopics: boolean;
  includePositions: boolean;
  includeDecisions: boolean;
  includeContext: boolean; // New: search in context
  includeReasoning: boolean; // New: search in party reasoning
  includeProposals?: boolean; // Added for search options
}

// New interfaces for enhanced display
export interface TopicDisplayMode {
  showContext: boolean;
  showSpecificProposals: boolean;
  showReasoning: boolean;
  showEvidence: boolean;
}

export interface SummaryDisplayOptions {
  topicMode: TopicDisplayMode;
  expandedTopics: Set<string>;
  showAllParties: boolean;
  groupByTopic: boolean;
}

// New interfaces for preprocessed/optimized data
export interface ProcessedDocument extends ParliamentaryDocument {
  formattedDate: string;
  preview: string;
  topicCount: number;
  decisionCount: number;
  hasNextSteps: boolean;
  nextStepsCount: number;
  hasDecisions: boolean;
  processingDate: string;
  summary: ProcessedSummary;
}

export interface ProcessedSummary extends ParliamentarySummary {
  main_topics: ProcessedTopic[];
}

export interface ProcessedTopic extends EnhancedTopic {
  hasContext: boolean;
  partyPositionsArray: ProcessedPartyPosition[];
}

export interface ProcessedPartyPosition {
  party: string;
  color: string;
  mainPosition: string;
  proposals: string[] | null;
  hasProposals: boolean;
  reasoning: string | null;
  evidence: string | null;
}

// Search options interface
export interface SearchOptions {
  includeContext: boolean;
  includeReasoning: boolean;
  includeProposals: boolean;
}

// Additional utility types
export type FilterType = 'topic' | 'party' | 'search';

export interface FilterState {
  topics: TopicFilter[];
  parties: PartyFilter[];
  search: SearchFilter;
}

// Virtual scrolling configuration
export interface VirtualScrollConfig {
  itemSize: number;
  minBufferPx: number;
  maxBufferPx: number;
}

// Performance monitoring
export interface PerformanceMetrics {
  documentLoadTime: number;
  preprocessingTime: number;
  renderTime: number;
  lastUpdate: Date;
}

// State management helpers
export interface AppState {
  documents: ProcessedDocument[];
  selectedDocumentId: string | null;
  filters: FilterState;
  displayOptions: SummaryDisplayOptions;
  performance: PerformanceMetrics;
}

// Event interfaces for component communication
export interface DocumentSelectedEvent {
  documentId: string;
  document: ProcessedDocument;
}

export interface FilterChangedEvent {
  filterType: FilterType;
  filterName: string;
  value: boolean | string;
}

export interface DisplayOptionChangedEvent {
  option: keyof TopicDisplayMode;
  value: boolean;
}

// Utility type for party colors
export type PartyColorMap = { [party: string]: string };

// Constants
export const DEFAULT_PARTY_COLORS: PartyColorMap = {
  'VVD': '#0066CC',
  'PvdA': '#CC0000',
  'GroenLinks-PvdA': '#00AA00',
  'PVV': '#FFD700',
  'CDA': '#00AA55',
  'D66': '#FFAA00',
  'NSC': '#800080',
  'PvdD': '#006600',
  'ChristenUnie': '#0099CC',
  'SGP': '#FF6600',
  'SP': '#CC0000',
  'Minister': '#666666',
  'Voorzitter': '#999999'
};

export const DEFAULT_VIRTUAL_SCROLL_CONFIG: VirtualScrollConfig = {
  itemSize: 200,
  minBufferPx: 900,
  maxBufferPx: 1350
};

export const DEFAULT_DISPLAY_OPTIONS: SummaryDisplayOptions = {
  topicMode: {
    showContext: true,
    showSpecificProposals: true,
    showReasoning: true,
    showEvidence: true
  },
  expandedTopics: new Set<string>(),
  showAllParties: true,
  groupByTopic: true
};

// Type guards
export function isEnhancedPartyPosition(position: EnhancedPartyPosition | string): position is EnhancedPartyPosition {
  return typeof position === 'object' && 'position' in position;
}

export function hasTopicContext(topic: EnhancedTopic): boolean {
  return !!(topic.context?.why_discussed || 
           topic.context?.background || 
           topic.context?.stakes ||
           topic.context?.trigger);
}

// Utility functions for data transformation
export function createProcessedDocument(doc: ParliamentaryDocument, formatDate: (date: Date) => string): ProcessedDocument {
  return {
    ...doc,
    formattedDate: formatDate(doc.date),
    preview: doc.summary.executive_summary.slice(0, 200),
    topicCount: doc.summary.main_topics.length,
    decisionCount: doc.summary.key_decisions.length,
    hasNextSteps: doc.summary.next_steps?.length > 0,
    nextStepsCount: doc.summary.next_steps?.length || 0,
    hasDecisions: doc.summary.key_decisions.length > 0,
    processingDate: formatDate(new Date(doc.summary.processing_info.processing_date)),
    summary: {
      ...doc.summary,
      main_topics: doc.summary.main_topics.map(topic => createProcessedTopic(topic))
    }
  };
}

export function createProcessedTopic(topic: EnhancedTopic): ProcessedTopic {
  return {
    ...topic,
    hasContext: hasTopicContext(topic),
    partyPositionsArray: Object.keys(topic.party_positions).map(party => 
      createProcessedPartyPosition(party, topic.party_positions[party])
    )
  };
}

export function createProcessedPartyPosition(
  party: string, 
  position: EnhancedPartyPosition | string
): ProcessedPartyPosition {
  const isEnhanced = isEnhancedPartyPosition(position);
  
  return {
    party,
    color: DEFAULT_PARTY_COLORS[party] || '#666666',
    mainPosition: isEnhanced ? position.position : position,
    proposals: isEnhanced ? position.specific_proposals || null : null,
    hasProposals: isEnhanced ? (position.specific_proposals?.length || 0) > 0 : false,
    reasoning: isEnhanced ? position.reasoning || null : null,
    evidence: isEnhanced ? position.key_evidence || null : null
  };
}