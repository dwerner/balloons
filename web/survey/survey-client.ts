/**
 * Survey Client - Handles form rendering and submission
 * Supports both simple surveys (single rating + text) and
 * extended surveys with custom questions (rating 1-5 or text)
 */

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

interface QuestionAnswer {
  questionId: string;
  type: 'rating' | 'text';
  value: number | string;
}

// Get survey ID from URL
const pathParts = window.location.pathname.split('/');
const surveyId = pathParts[pathParts.length - 1];

const container = document.querySelector('.survey-container')!;

// Track the current survey for submission
let currentSurvey: PendingSurvey | null = null;

async function loadSurvey() {
  try {
    const response = await fetch(`/api/survey/${surveyId}`);

    if (response.status === 404) {
      showError("This survey doesn't exist or has already been completed.");
      return;
    }

    if (!response.ok) {
      throw new Error('Failed to load survey');
    }

    const survey: PendingSurvey = await response.json();
    currentSurvey = survey;
    renderSurvey(survey);
  } catch (error) {
    console.error('Error loading survey:', error);
    showError("Something went wrong loading this survey. Please try again.");
  }
}

function showError(message: string) {
  container.innerHTML = `
    <div class="survey-error">
      <h2>Oops!</h2>
      <p>${message}</p>
    </div>
  `;
}

function showCompleted() {
  container.innerHTML = `
    <div class="survey-completed">
      <h2>Thanks!</h2>
      <p>Your feedback has been sent.</p>
    </div>
  `;
}

function renderRatingQuestion(question: SurveyQuestion, index: number): string {
  const lowLabel = question.ratingLabels?.low || "Not at all";
  const highLabel = question.ratingLabels?.high || "Completely";
  const requiredAttr = question.required ? 'required' : '';
  const nameAttr = `q_${question.id}`;

  return `
    <div class="rating-section question-block" data-question-id="${question.id}" data-question-type="rating">
      <label class="rating-label">${escapeHtml(question.label)}${question.required ? ' *' : ''}</label>
      <div class="rating-options">
        <div class="rating-option">
          <input type="radio" name="${nameAttr}" value="1" id="${nameAttr}_1" ${requiredAttr}>
          <label for="${nameAttr}_1">
            <span class="rating-number">1</span>
            <span class="rating-desc">${escapeHtml(lowLabel)}</span>
          </label>
        </div>
        <div class="rating-option">
          <input type="radio" name="${nameAttr}" value="2" id="${nameAttr}_2">
          <label for="${nameAttr}_2">
            <span class="rating-number">2</span>
          </label>
        </div>
        <div class="rating-option">
          <input type="radio" name="${nameAttr}" value="3" id="${nameAttr}_3">
          <label for="${nameAttr}_3">
            <span class="rating-number">3</span>
          </label>
        </div>
        <div class="rating-option">
          <input type="radio" name="${nameAttr}" value="4" id="${nameAttr}_4">
          <label for="${nameAttr}_4">
            <span class="rating-number">4</span>
          </label>
        </div>
        <div class="rating-option">
          <input type="radio" name="${nameAttr}" value="5" id="${nameAttr}_5">
          <label for="${nameAttr}_5">
            <span class="rating-number">5</span>
            <span class="rating-desc">${escapeHtml(highLabel)}</span>
          </label>
        </div>
      </div>
    </div>
  `;
}

function renderTextQuestion(question: SurveyQuestion, index: number): string {
  const placeholder = question.placeholder || "Share your thoughts...";
  const requiredAttr = question.required ? 'required' : '';
  const nameAttr = `q_${question.id}`;

  return `
    <div class="response-section question-block" data-question-id="${question.id}" data-question-type="text">
      <label class="response-label" for="${nameAttr}">${escapeHtml(question.label)}${question.required ? ' *' : ''}</label>
      <textarea
        id="${nameAttr}"
        name="${nameAttr}"
        class="response-textarea"
        placeholder="${escapeHtml(placeholder)}"
        ${requiredAttr}
      ></textarea>
    </div>
  `;
}

function renderQuestion(question: SurveyQuestion, index: number): string {
  if (question.type === 'rating') {
    return renderRatingQuestion(question, index);
  } else {
    return renderTextQuestion(question, index);
  }
}

function renderSurvey(survey: PendingSurvey) {
  const hasCustomQuestions = survey.questions && survey.questions.length > 0;

  let questionsHtml: string;

  if (hasCustomQuestions) {
    // Render custom questions
    questionsHtml = survey.questions!.map((q, i) => renderQuestion(q, i)).join('\n');
  } else {
    // Render default simple survey (backward compatible)
    questionsHtml = `
      <div class="rating-section" data-legacy="true">
        <label class="rating-label">How was this experience?</label>
        <div class="rating-options">
          <div class="rating-option">
            <input type="radio" name="rating" value="1" id="r1" required>
            <label for="r1">
              <span class="rating-number">1</span>
              <span class="rating-desc">Really bad, felt unfair</span>
            </label>
          </div>
          <div class="rating-option">
            <input type="radio" name="rating" value="2" id="r2">
            <label for="r2">
              <span class="rating-number">2</span>
              <span class="rating-desc">Not great</span>
            </label>
          </div>
          <div class="rating-option">
            <input type="radio" name="rating" value="3" id="r3">
            <label for="r3">
              <span class="rating-number">3</span>
              <span class="rating-desc">Okay, I guess</span>
            </label>
          </div>
          <div class="rating-option">
            <input type="radio" name="rating" value="4" id="r4">
            <label for="r4">
              <span class="rating-number">4</span>
              <span class="rating-desc">Pretty good</span>
            </label>
          </div>
          <div class="rating-option">
            <input type="radio" name="rating" value="5" id="r5">
            <label for="r5">
              <span class="rating-number">5</span>
              <span class="rating-desc">Really good, felt fair</span>
            </label>
          </div>
        </div>
      </div>

      <div class="response-section" data-legacy="true">
        <label class="response-label" for="response">Tell me more (optional)</label>
        <textarea
          id="response"
          class="response-textarea"
          placeholder="What was going through your head? Anything I could have done differently?"
        ></textarea>
      </div>
    `;
  }

  container.innerHTML = `
    <form id="survey-form">
      <div class="survey-header">
        <h1 class="survey-greeting">Hey ${survey.childName}</h1>
        <p class="survey-from">From ${survey.createdBy}</p>
      </div>

      <div class="incident-box">
        <div class="incident-label">About this:</div>
        <div class="incident-title">${escapeHtml(survey.incidentTitle)}</div>
        <div class="incident-description">${escapeHtml(survey.incidentDescription)}</div>
      </div>

      <p class="feedback-prompt">${escapeHtml(survey.feedbackPrompt)}</p>

      ${questionsHtml}

      <button type="submit" class="submit-button">Send Feedback</button>
    </form>
  `;

  const form = document.getElementById('survey-form') as HTMLFormElement;
  form.addEventListener('submit', handleSubmit);
}

async function handleSubmit(event: Event) {
  event.preventDefault();

  const form = event.target as HTMLFormElement;
  const submitBtn = form.querySelector('.submit-button') as HTMLButtonElement;

  const hasCustomQuestions = currentSurvey?.questions && currentSurvey.questions.length > 0;

  let body: Record<string, unknown>;

  if (hasCustomQuestions) {
    // Collect answers from custom questions
    const answers: QuestionAnswer[] = [];
    const questionBlocks = form.querySelectorAll('.question-block');

    for (const block of questionBlocks) {
      const questionId = block.getAttribute('data-question-id');
      const questionType = block.getAttribute('data-question-type') as 'rating' | 'text';

      if (!questionId) continue;

      if (questionType === 'rating') {
        const checked = block.querySelector(`input[name="q_${questionId}"]:checked`) as HTMLInputElement | null;
        if (checked) {
          answers.push({
            questionId,
            type: 'rating',
            value: parseInt(checked.value, 10)
          });
        }
      } else {
        const textarea = block.querySelector(`textarea[name="q_${questionId}"]`) as HTMLTextAreaElement;
        if (textarea && textarea.value.trim()) {
          answers.push({
            questionId,
            type: 'text',
            value: textarea.value.trim()
          });
        }
      }
    }

    // Validate required questions
    for (const q of currentSurvey!.questions!) {
      if (q.required) {
        const answer = answers.find(a => a.questionId === q.id);
        if (!answer || (q.type === 'text' && !answer.value)) {
          alert(`Please answer: "${q.label}"`);
          return;
        }
      }
    }

    body = { answers };
  } else {
    // Legacy simple survey
    const ratingInput = form.querySelector('input[name="rating"]:checked') as HTMLInputElement;
    const responseTextarea = form.querySelector('#response') as HTMLTextAreaElement;

    if (!ratingInput) {
      alert('Please select a rating');
      return;
    }

    body = {
      rating: parseInt(ratingInput.value, 10),
      writtenResponse: responseTextarea.value.trim(),
    };
  }

  submitBtn.disabled = true;
  submitBtn.textContent = 'Sending...';

  try {
    const response = await fetch(`/api/survey/${surveyId}/respond`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error('Failed to submit response');
    }

    showCompleted();
  } catch (error) {
    console.error('Error submitting:', error);
    submitBtn.disabled = false;
    submitBtn.textContent = 'Send Feedback';
    alert('Something went wrong. Please try again.');
  }
}

function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Load the survey on page load
loadSurvey();
