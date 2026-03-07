/**
 * SurveysTab - View parenting feedback survey responses
 *
 * Fetches responses from the local survey server (port 3001)
 * and displays them in a nice format.
 */

import React, { useState, useEffect, useCallback, memo } from 'react';
import './SurveysTab.css';

interface QuestionAnswer {
  questionId: string;
  type: 'rating' | 'text';
  value: number | string;
}

interface SurveyQuestion {
  id: string;
  type: 'rating' | 'text';
  label: string;
  required?: boolean;
  placeholder?: string;
  ratingLabels?: {
    low?: string;
    high?: string;
  };
}

interface SurveyResponse {
  surveyId: string;
  childName: string;
  incidentTitle: string;
  // Legacy simple format
  rating?: number;
  writtenResponse?: string;
  // New extended format
  answers?: QuestionAnswer[];
  submittedAt: string;
}

interface PendingSurvey {
  id: string;
  childName: string;
  incidentTitle: string;
  incidentDescription: string;
  feedbackPrompt: string;
  createdAt: string;
  createdBy: string;
  questions?: SurveyQuestion[];
}

// Get the survey server URL
// When running via TLS dev server, use relative URLs (proxied through dev server)
// When running directly, use the survey server port
function getSurveyServerUrl(): string {
  // Use relative URLs - the dev server proxies /api/survey* to port 3001
  return '';
}

export const SurveysTab = memo(function SurveysTab() {
  const [responses, setResponses] = useState<SurveyResponse[]>([]);
  const [pendingSurveys, setPendingSurveys] = useState<PendingSurvey[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedResponses, setExpandedResponses] = useState<Set<string>>(new Set());
  const [autoRefresh, setAutoRefresh] = useState(false);

  const surveyServerUrl = getSurveyServerUrl();

  // Fetch responses
  const fetchResponses = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`${surveyServerUrl}/api/surveys/responses`);
      if (!res.ok) throw new Error('Failed to fetch responses');
      const data = await res.json();
      setResponses(data);
    } catch (err) {
      setError(`Could not connect to survey server at ${surveyServerUrl}`);
      console.error('Failed to fetch survey responses:', err);
    } finally {
      setIsLoading(false);
    }
  }, [surveyServerUrl]);

  // Fetch pending surveys
  const fetchPending = useCallback(async () => {
    try {
      const res = await fetch(`${surveyServerUrl}/api/surveys/pending`);
      if (!res.ok) return; // Endpoint might not exist yet
      const data = await res.json();
      setPendingSurveys(data);
    } catch (err) {
      // Ignore - pending endpoint might not be implemented
    }
  }, [surveyServerUrl]);

  // Initial load
  useEffect(() => {
    fetchResponses();
    fetchPending();
  }, [fetchResponses, fetchPending]);

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      fetchResponses();
      fetchPending();
    }, 5000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchResponses, fetchPending]);

  // Toggle response expansion
  const toggleResponse = useCallback((id: string) => {
    setExpandedResponses(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  // Copy survey link - use the actual survey server URL (port 3001), not the proxy
  const copyLink = useCallback((id: string) => {
    const host = window.location.hostname;
    const link = `http://${host}:3001/survey/${id}`;
    navigator.clipboard.writeText(link).then(() => {
      // Could show a toast, but for now just log
      console.log('Link copied:', link);
    });
  }, []);

  // Rating display
  const getRatingDisplay = (rating: number) => {
    const labels = ['', 'Really bad', 'Not great', 'Okay', 'Pretty good', 'Really good'];
    const emojis = ['', '😢', '😕', '😐', '🙂', '😊'];
    return {
      label: labels[rating] || '',
      emoji: emojis[rating] || '',
    };
  };

  // Get average rating from answers (for extended surveys)
  const getAverageRating = (answers: QuestionAnswer[]): number | null => {
    const ratings = answers.filter(a => a.type === 'rating').map(a => a.value as number);
    if (ratings.length === 0) return null;
    return Math.round(ratings.reduce((a, b) => a + b, 0) / ratings.length * 10) / 10;
  };

  // Find the pending survey to get question labels
  const getQuestionLabel = (response: SurveyResponse, questionId: string): string => {
    // Try to find from pending surveys (if still available)
    const pending = pendingSurveys.find(p => p.id === response.surveyId);
    if (pending?.questions) {
      const q = pending.questions.find(q => q.id === questionId);
      if (q) return q.label;
    }
    // Fallback: make question ID human-readable
    return questionId.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  };

  // Format date
  const formatDate = (isoString: string) => {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  return (
    <div className="surveys-tab">
      {/* Header */}
      <div className="surveys-tab__header">
        <h2 className="surveys-tab__title">Feedback Surveys</h2>
        <div className="surveys-tab__controls">
          <label className="surveys-tab__auto-refresh">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            Auto
          </label>
          <button
            className="surveys-tab__refresh-btn"
            onClick={() => { fetchResponses(); fetchPending(); }}
            disabled={isLoading}
          >
            {isLoading ? '...' : '↻'}
          </button>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="surveys-tab__error">
          <p>{error}</p>
          <p className="surveys-tab__error-hint">
            Make sure the survey server is running: <code>bun run web/survey/survey-server.ts</code>
          </p>
        </div>
      )}

      {/* Pending surveys */}
      {pendingSurveys.length > 0 && (
        <div className="surveys-tab__section">
          <h3 className="surveys-tab__section-title">Pending ({pendingSurveys.length})</h3>
          <div className="surveys-tab__pending-list">
            {pendingSurveys.map(survey => (
              <div key={survey.id} className="surveys-tab__pending-item">
                <div className="surveys-tab__pending-info">
                  <span className="surveys-tab__pending-name">{survey.childName}</span>
                  <span className="surveys-tab__pending-incident">{survey.incidentTitle}</span>
                  <span className="surveys-tab__pending-date">{formatDate(survey.createdAt)}</span>
                </div>
                <button
                  className="surveys-tab__copy-btn"
                  onClick={() => copyLink(survey.id)}
                  title="Copy survey link"
                >
                  📋
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Responses */}
      <div className="surveys-tab__section">
        <h3 className="surveys-tab__section-title">
          Responses ({responses.length})
        </h3>

        {responses.length === 0 && !error && !isLoading && (
          <div className="surveys-tab__empty">
            No responses yet. Create a survey and share the link!
          </div>
        )}

        <div className="surveys-tab__responses">
          {responses.map(response => {
            const isExpanded = expandedResponses.has(response.surveyId);
            const hasAnswers = response.answers && response.answers.length > 0;

            // For extended surveys, show average rating; for simple, show the single rating
            const displayRating = hasAnswers
              ? getAverageRating(response.answers!)
              : response.rating;
            const { label, emoji } = displayRating ? getRatingDisplay(Math.round(displayRating)) : { label: '', emoji: '' };

            return (
              <div
                key={response.surveyId}
                className={`surveys-tab__response ${isExpanded ? 'surveys-tab__response--expanded' : ''}`}
                onClick={() => toggleResponse(response.surveyId)}
              >
                <div className="surveys-tab__response-header">
                  <span className="surveys-tab__response-name">{response.childName}</span>
                  <span className="surveys-tab__response-incident">{response.incidentTitle}</span>
                  {displayRating !== null && displayRating !== undefined && (
                    <span className="surveys-tab__response-rating">
                      <span className="surveys-tab__rating-number">{displayRating}/5</span>
                      <span className="surveys-tab__rating-emoji">{emoji}</span>
                    </span>
                  )}
                  <span className="surveys-tab__response-date">{formatDate(response.submittedAt)}</span>
                  <span className="surveys-tab__expand-hint">
                    {isExpanded ? '▼' : '▶'}
                  </span>
                </div>

                {isExpanded && (
                  <div className="surveys-tab__response-details">
                    {hasAnswers ? (
                      // Extended survey with multiple answers
                      <div className="surveys-tab__answers">
                        {response.answers!.map((answer, idx) => (
                          <div key={answer.questionId} className="surveys-tab__answer">
                            <div className="surveys-tab__answer-label">
                              {getQuestionLabel(response, answer.questionId)}
                            </div>
                            {answer.type === 'rating' ? (
                              <div className="surveys-tab__answer-rating">
                                <span className="surveys-tab__rating-number">{answer.value}/5</span>
                                <span className="surveys-tab__rating-emoji">
                                  {getRatingDisplay(answer.value as number).emoji}
                                </span>
                              </div>
                            ) : (
                              <div className="surveys-tab__answer-text">
                                {answer.value || <em>(No response)</em>}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      // Legacy simple survey
                      <>
                        <div className="surveys-tab__rating-label">{label}</div>
                        {response.writtenResponse ? (
                          <div className="surveys-tab__written-response">
                            <p className="surveys-tab__response-text">{response.writtenResponse}</p>
                          </div>
                        ) : (
                          <p className="surveys-tab__no-response">(No written response)</p>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
});

export default SurveysTab;
