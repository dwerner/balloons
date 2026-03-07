# Create Parenting Feedback Survey

Create surveys to gather feedback from family members about specific incidents or experiences.

## Quick Start (Simple Survey)

```bash
curl -X POST http://localhost:3001/api/survey \
  -H "Content-Type: application/json" \
  -d '{
    "childName": "NAME",
    "incidentTitle": "TITLE",
    "incidentDescription": "DESCRIPTION",
    "feedbackPrompt": "PROMPT",
    "createdBy": "Dad"
  }'
```

## Fields

| Field | Required | Description |
|-------|----------|-------------|
| `childName` | Yes | Who will fill out the survey |
| `incidentTitle` | Yes | Brief name for the event |
| `incidentDescription` | Yes | What happened (1-2 sentences) |
| `feedbackPrompt` | No | What feedback you're seeking (has default) |
| `createdBy` | No | Who is sending (defaults to "Dad") |
| `questions` | No | Array of custom questions (see below) |

## Simple Example

```bash
curl -X POST http://localhost:3001/api/survey \
  -H "Content-Type: application/json" \
  -d '{
    "childName": "Ruby",
    "incidentTitle": "Late pickup",
    "incidentDescription": "When I was late picking you up from school.",
    "feedbackPrompt": "I would love to hear how that felt and if there is anything I could do differently.",
    "createdBy": "Dad"
  }'
```

**Response:**
```json
{"id":"abc123","url":"http://192.168.0.133:3001/survey/abc123"}
```

Send the URL via Signal, text, or email.

---

## Extended Survey with Custom Questions

For deeper conversations, you can add multiple questions. Each question can be:
- **rating**: 1-5 scale with custom labels
- **text**: Open-ended written response

### Question Fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier for the question |
| `type` | Yes | `"rating"` or `"text"` |
| `label` | Yes | The question text shown to the user |
| `required` | No | If true, must be answered (default: false) |
| `placeholder` | No | Placeholder text (for text type) |
| `ratingLabels` | No | Custom labels for 1 and 5 (for rating type) |

### "Being Heard" Check-in Example

```bash
curl -X POST http://localhost:3001/api/survey \
  -H "Content-Type: application/json" \
  -d '{
    "childName": "Ruby",
    "incidentTitle": "Check-in: Am I hearing you?",
    "incidentDescription": "I want to make sure you feel heard and respected when we talk.",
    "feedbackPrompt": "Your honest answers help me be a better listener.",
    "createdBy": "Dad",
    "questions": [
      {
        "id": "listened",
        "type": "rating",
        "label": "When we talked recently, did you feel like I really listened?",
        "required": true,
        "ratingLabels": {
          "low": "Not at all",
          "high": "Completely"
        }
      },
      {
        "id": "interrupt",
        "type": "rating",
        "label": "Did I let you finish your thoughts, or did I interrupt?",
        "ratingLabels": {
          "low": "Interrupted a lot",
          "high": "Let me finish"
        }
      },
      {
        "id": "feelings",
        "type": "text",
        "label": "What feelings came up that you did not get to share?",
        "placeholder": "It is okay if you are not sure..."
      },
      {
        "id": "understand",
        "type": "text",
        "label": "What do you wish I understood better?",
        "required": true
      },
      {
        "id": "next_time",
        "type": "text",
        "label": "Next time we disagree, what would help you feel more heard?"
      }
    ]
  }'
```

### After a Conflict Example

```bash
curl -X POST http://localhost:3001/api/survey \
  -H "Content-Type: application/json" \
  -d '{
    "childName": "Ruby",
    "incidentTitle": "After our disagreement",
    "incidentDescription": "I want to understand how you experienced our argument earlier.",
    "feedbackPrompt": "Help me see it from your side.",
    "createdBy": "Dad",
    "questions": [
      {
        "id": "fair",
        "type": "rating",
        "label": "Did you feel the outcome was fair?",
        "required": true,
        "ratingLabels": {
          "low": "Very unfair",
          "high": "Very fair"
        }
      },
      {
        "id": "heard",
        "type": "rating",
        "label": "Did you feel your side was understood?",
        "ratingLabels": {
          "low": "Not at all",
          "high": "Yes, completely"
        }
      },
      {
        "id": "your_side",
        "type": "text",
        "label": "What was the most important thing you were trying to say?",
        "required": true
      },
      {
        "id": "wish",
        "type": "text",
        "label": "What do you wish had gone differently?"
      },
      {
        "id": "repair",
        "type": "text",
        "label": "Is there anything I can do to make it right?"
      }
    ]
  }'
```

---

## View Responses

- **UI**: Balloons → Global → Surveys tab
- **API**: `GET http://localhost:3001/api/surveys/responses`
- **Files**: `web/survey/data/responses/*.json`

### Response Format

**Simple survey response:**
```json
{
  "surveyId": "abc123",
  "childName": "Ruby",
  "incidentTitle": "Late pickup",
  "rating": 3,
  "writtenResponse": "I felt worried...",
  "submittedAt": "2024-01-15T10:30:00Z"
}
```

**Extended survey response:**
```json
{
  "surveyId": "def456",
  "childName": "Ruby",
  "incidentTitle": "Check-in: Am I hearing you?",
  "answers": [
    { "questionId": "listened", "type": "rating", "value": 4 },
    { "questionId": "interrupt", "type": "rating", "value": 3 },
    { "questionId": "feelings", "type": "text", "value": "Sometimes I feel rushed..." },
    { "questionId": "understand", "type": "text", "value": "That I need time to think..." }
  ],
  "submittedAt": "2024-01-15T10:30:00Z"
}
```

---

## Server

Make sure the survey server is running:

```bash
# Check status
pgrep -fa survey-server

# Start manually
cd web/survey && bun run survey-server.ts

# Or use supervisor (from Balloons)
```

The server runs on **port 3001** and is accessible on your local network.
