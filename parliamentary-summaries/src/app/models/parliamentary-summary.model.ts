// src/app/models/parliamentary-summary.model.ts

// Base interfaces
export interface ParliamentarySummary {
  executive_summary: string;
  main_topics: EnhancedTopic[];
  key_decisions: string[];
  political_dynamics: string;
  next_steps: string[];
  fact_checks?: FactCheck[];
  meeting_info: MeetingInfo;
  processing_info: ProcessingInfo;
}

/**
 * A verifiable claim the summarizer checked against official sources.
 * Only produced by summaries generated from 2026-08 onwards.
 */
export interface FactCheck {
  claim: string;
  speaker: string;
  assessment: FactCheckAssessment;
  explanation: string;
  correction: string;
  sources: string[];
}

export type FactCheckAssessment =
  | 'onjuist'
  | 'misleidend'
  | 'grotendeels_juist'
  | 'onverifieerbaar';

/**
 * Positions are an array of {party, position} in current summaries. Summaries
 * generated before the single-pass rewrite used a party-keyed object, and those
 * files are still served, so both shapes must be readable.
 */
export type PartyPositions =
  | PartyPositionEntry[]
  | { [party: string]: EnhancedPartyPosition | string };

export interface PartyPositionEntry {
  party: string;
  position: string;
}

export interface EnhancedTopic {
  topic: string;
  context?: TopicContext;
  summary: string;
  party_positions: PartyPositions;
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
  processing_date: string;
  ai_model?: string;
  input_tokens?: number;
  output_tokens?: number;
  web_searches?: number;
  transcript_chars?: number;
  note?: string;
  /** Only present on summaries produced by the old chunked pipeline. */
  chunks_processed?: number;
  total_topics_found?: number;
  enhancement_level?: string;
}

/**
 * One meeting as described by assets/summaries/manifest.json.
 *
 * The index holds everything the list, the filters and the search box need, so
 * the app renders from a single request. Full summaries are ~9.5 KB each and
 * are fetched only when a meeting is opened.
 */
export interface SummaryIndexEntry {
  file: string;
  id: string;
  title: string;
  date: string;
  model: string;
  /** Executive summary: shown as the preview and used as the search body. */
  summaryText: string;
  topics: string[];
  parties: string[];
  topicCount: number;
  decisionCount: number;
  factCheckCount: number;
}

export interface ParliamentaryDocument {
  id: string;
  title: string;
  date: Date;
  index: SummaryIndexEntry;
  /** Null until the full summary has been fetched. */
  summary: ParliamentarySummary | null;
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
  factCheckCount: number;
  hasFactChecks: boolean;
  processingDate: string;
  /** Null while the full summary is still loading. */
  summary: ProcessedSummary | null;
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

// Constants
export const DEFAULT_PARTY_COLORS: { [party: string]: string } = {
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

function hasTopicContext(topic: EnhancedTopic): boolean {
  return !!(topic.context?.why_discussed ||
            topic.context?.background ||
            topic.context?.stakes ||
            topic.context?.trigger);
}

function isEnhancedPartyPosition(
  position: EnhancedPartyPosition | string
): position is EnhancedPartyPosition {
  return typeof position === 'object' && 'position' in position;
}

function createProcessedTopic(topic: EnhancedTopic): ProcessedTopic {
  return {
    ...topic,
    hasContext: hasTopicContext(topic),
    partyPositionsArray: normalizePartyPositions(topic.party_positions)
  };
}

// Utility functions for data transformation
/**
 * Counts and the preview come from the index, so a meeting renders in the list
 * identically whether or not its full summary has been fetched yet.
 */
export function createProcessedDocument(
  doc: ParliamentaryDocument,
  formatDate: (date: Date) => string
): ProcessedDocument {
  const index = doc.index;
  const summary = doc.summary;

  return {
    ...doc,
    formattedDate: formatDate(doc.date),
    preview: index.summaryText.slice(0, 200),
    topicCount: index.topicCount,
    decisionCount: index.decisionCount,
    hasDecisions: index.decisionCount > 0,
    factCheckCount: index.factCheckCount,
    hasFactChecks: index.factCheckCount > 0,
    nextStepsCount: summary?.next_steps?.length ?? 0,
    hasNextSteps: (summary?.next_steps?.length ?? 0) > 0,
    processingDate: summary
      ? formatDate(new Date(summary.processing_info.processing_date))
      : '',
    summary: summary
      ? {
          ...summary,
          main_topics: summary.main_topics.map(topic => createProcessedTopic(topic))
        }
      : null
  };
}

/**
 * Flatten either party-position shape into one array the template can iterate.
 */
export function normalizePartyPositions(positions: PartyPositions | null | undefined): ProcessedPartyPosition[] {
  if (!positions) {
    return [];
  }

  if (Array.isArray(positions)) {
    return positions.map(entry =>
      createProcessedPartyPosition(entry.party, entry.position)
    );
  }

  return Object.keys(positions).map(party =>
    createProcessedPartyPosition(party, positions[party])
  );
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