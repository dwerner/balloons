/**
 * Survey System Types
 */

/**
 * A survey question - either rating (1-5) or text
 */
export interface SurveyQuestion {
  id: string;
  type: 'rating' | 'text';
  label: string;
  required?: boolean;
  placeholder?: string;  // For text type
  // For rating type, optional custom labels (defaults provided)
  ratingLabels?: {
    low?: string;   // e.g., "Not at all"
    high?: string;  // e.g., "Completely"
  };
}

export interface PendingSurvey {
  id: string;
  childName: string;
  incidentTitle: string;
  incidentDescription: string;
  feedbackPrompt: string;
  createdAt: string;
  createdBy: string;  // e.g., "Dad"
  questions?: SurveyQuestion[];  // Custom questions (optional, for extended surveys)
}

/**
 * Answer to a single question
 */
export interface QuestionAnswer {
  questionId: string;
  type: 'rating' | 'text';
  value: number | string;  // number for rating, string for text
}

export interface SurveyResponse {
  surveyId: string;
  childName: string;
  incidentTitle: string;
  // Legacy fields (for backward compatibility with simple surveys)
  rating?: number;  // 1-5
  writtenResponse?: string;
  // New: answers to custom questions
  answers?: QuestionAnswer[];
  submittedAt: string;
}
