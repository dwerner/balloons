# AI SDK Runner Gap Analysis

## Overview
Comparing `ai_sdk_runner.py` against `openai_runner.py` and `claude_runner.py` to identify missing features.

---

## 1. Message Building & Context Handling

### ✅ Implemented in AI SDK Runner
- System prompt support (`user_prompt` parameter)
- Conversation history passing
- Tool result messages with `role="tool"`
- Image support (basic)
- Text content blocks

### ❌ Missing in AI SDK Runner

#### 1.1 Context Building
**OpenAI Runner**: Uses `ContextBuilder` class for sophisticated context construction
- Handles complex message block types (TextBlock, ImageBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock, ErrorBlock, LinkBlock, ArchiveBlock)
- Proper alternation normalization (`_normalize_strict_alternation`)
- Tool message reordering (`_reorder_tool_messages`)
- Merging consecutive same-role messages (`_merge_consecutive_messages`)

**Claude Runner**: Uses `ContextBuilder` with `OutputFormat.STRUCTURED`
- Fresh domain prompts per turn via `_get_system_prompt()`
- Pending images support (`_pending_images`)
- Context token counting via tiktoken

**AI SDK Runner**: Simple manual conversion
- No `ContextBuilder` integration
- No token counting
- No message normalization/reordering
- Limited block type support

#### 1.2 Message Validation
**OpenAI Runner**: 
- `_is_placeholder_assistant_error()` - filters placeholder error messages
- Strict alternation enforcement
- Tool result ordering validation

**AI SDK Runner**: 
- ❌ No validation
- ❌ No error message filtering
- ❌ No alternation enforcement

---

## 2. Tool Handling

### ✅ Implemented in AI SDK Runner
- Tool execution via `execute_tool()`
- Client-only tools handling (`propose_fork`, `propose_merge`, `play_midi`)
- Tool result emission (`ToolResultEvent`)
- Tool result message building
- Domain tools change detection (`domains_changed`)

### ❌ Missing in AI SDK Runner

#### 2.1 Tool Call Parsing/Repair
**Claude Runner**:
- `<balloons-tool>` XML block parsing (`_parse_balloons_tools`)
- `<tool_use>` XML block parsing (`_handle_text_tool_uses`)
- Malformed tool use repair (`_handle_malformed_tool_uses`)
- Regex-based extraction with code fence detection
- JSON repair integration

**AI SDK Runner**: 
- ❌ No XML tool parsing
- ❌ No malformed tool repair
- ❌ No example filtering (code fences)

#### 2.2 Tool Result Bundling
**Claude Runner**:
- Hybrid turns: tool_result + steering in single message (`_send_tool_result`)
- Batch result sending for multiple tools
- Continuation message handling

**OpenAI Runner**:
- Synthetic tool results for client-only tools
- Proper tool_call_id tracking
- Tool result reordering

**AI SDK Runner**:
- ❌ No hybrid turns
- ❌ No batch result sending
- Individual tool result messages only

---

## 3. Steering / Mid-stream Struction

### ✅ Implemented in AI SDK Runner
- Basic steering injection (`_injection_callback`)
- `SteeringInjectedEvent` emission
- Steering breaks tool loop

### ❌ Missing in AI SDK Runner

#### 3.1 Steering Integration
**Claude Runner**:
- Hybrid steering: bundles with tool results (`_send_tool_result`)
- Standalone steering messages (`_send_tool_result_standalone_steering`)
- Immediate steering after EACH tool (soft interrupt)
- Boundary-aware injection (checks after every tool)
- Accumulated steering for multiple tools

**OpenAI Runner**:
- Steering after tool execution
- Proper message insertion

**AI SDK Runner**:
- ❌ No hybrid steering
- ❌ No immediate/soft interrupt steering
- ❌ No boundary-aware injection
- ❌ No steering accumulation

---

## 4. Streaming & Event Handling

### ✅ Implemented in AI SDK Runner
- Text delta streaming
- Reasoning delta streaming
- Tool call streaming (start, delta, end, complete)
- Usage tracking
- Finish reason handling
- Error handling

### ❌ Missing in AI SDK Runner

#### 4.1 Additional Event Types
**Claude Runner**:
- `RawEvent` - passthrough of raw JSON
- `ContextTokensEvent` - tiktoken-based token counting
- `RepairedToolEvent` - tool JSON repair notifications
- `HallucinatedUserEvent` - detects `<user>` blocks

**OpenAI Runner**:
- Similar event coverage to AI SDK

**AI SDK Runner**:
- ❌ No raw event passthrough
- ❌ No context token counting
- ❌ No repair events
- ❌ No hallucination detection

#### 4.2 Streaming Robustness
**Claude Runner**:
- `readline_unlimited()` with soft/hard timeout
- Soft timeout for tool execution (warns, keeps waiting)
- Hard timeout for stream reading (3 min)
- Incomplete read handling
- Limit overrun handling

**AI SDK Runner**:
- ❌ No timeout management
- ❌ No error recovery
- Basic exception handling only

---

## 5. Error Handling & Recovery

### ✅ Implemented in AI SDK Runner
- Basic try/except blocks
- `ErrorBlock` emission
- Invalid JSON argument handling

### ❌ Missing in AI SDK Runner

#### 5.1 Advanced Error Recovery
**Claude Runner**:
- JSON repair for malformed tool uses
- Hallucination detection and reporting
- Placeholder error filtering
- Dump failed JSON to files
- JSON error tracking (`_json_errors`)

**OpenAI Runner**:
- Placeholder assistant error detection
- Message normalization on errors

**AI SDK Runner**:
- ❌ No JSON repair
- ❌ No hallucination detection
- ❌ No error dump files
- ❌ No error tracking

---

## 6. Session & Context Management

### ✅ Implemented in AI SDK Runner
- Session setting (`set_session()`)
- Session ID in events
- Enabled tools list from session

### ❌ Missing in AI SDK Runner

#### 6.1 Session Integration
**Claude Runner**:
- Fresh system prompt per turn (`_get_system_prompt()`)
- Context token counting and caching
- Session name in logging
- Pending images between requests

**OpenAI Runner**:
- Session-based enabled tools
- Context window tracking

**AI SDK Runner**:
- ❌ No per-turn system prompt refresh
- ❌ No token counting/caching
- ❌ No pending images support

---

## 7. Image Handling

### ✅ Implemented in AI SDK Runner
- Basic image block support
- Base64 encoding support

### ❌ Missing in AI SDK Runner

#### 7.1 Advanced Image Features
**Claude Runner**:
- `_load_image_as_base64()` with format detection
- Pending images between requests (`_pending_images`)
- Image token estimation (~1000 tokens/image)
- Multiple image support per message

**OpenAI Runner**:
- Image URL formatting
- Mixed text+image content

**AI SDK Runner**:
- ❌ No image file loading
- ❌ No pending images
- ❌ No token estimation

---

## 8. Client-Side Tools

### ✅ Implemented in AI SDK Runner
- `CLIENT_ONLY_TOOLS` set
- Synthetic results for UI-handled tools
- `propose_fork`, `propose_merge`, `play_midi`

### ❌ Missing in AI SDK Runner

#### 8.1 Client Tool Categories
**Claude Runner**:
- `CLIENT_ONLY_TOOLS` (same as AI SDK)
- `TERMINAL_TOOLS` differentiation
- Custom tool execution (link/review/watcher tools)
- CLI-handled vs custom tool separation

**OpenAI Runner**:
- `CLIENT_ONLY_TOOLS` handling
- Synthetic tool results

**AI SDK Runner**:
- ⚠️ Basic client-only tools support
- ❌ No terminal tools differentiation
- ❌ No custom tool categories

---

## 9. Debugging & Logging

### ✅ Implemented in AI SDK Runner
- `debug_log` usage
- Run ID tracking
- Category-based logging

### ❌ Missing in AI SDK Runner

#### 9.1 Enhanced Debugging
**Claude Runner**:
- Detailed tool parsing logs
- JSON error dumps to files
- Buffer state logging
- Position tracking for errors
- Match position logging

**AI SDK Runner**:
- ❌ No JSON dumps
- ❌ No detailed parsing logs
- Basic logging only

---

## Priority Recommendations

### High Priority
1. **Integrate ContextBuilder** - Replace manual message conversion with proper context building
2. **Add token counting** - Use tiktoken for accurate context tracking
3. **Implement message normalization** - Add alternation enforcement and tool reordering
4. **Add streaming robustness** - Implement timeout management and error recovery

### Medium Priority
5. **Add JSON repair** - Handle malformed tool uses from context/hallucinations
6. **Implement hybrid steering** - Bundle steering with tool results for soft interrupts
7. **Add pending images support** - Allow images to be queued between requests
8. **Add raw event passthrough** - Enable debugging with `RawEvent`

### Low Priority
9. **Add hallucination detection** - Detect and report `<user>` blocks
10. **Add error dump files** - Save failed JSON for debugging
11. **Add repair events** - Emit `RepairedToolEvent` for transparency
12. **Add context token events** - Emit `ContextTokensEvent` for UI display

---

## Implementation Complexity

| Feature | Complexity | Impact |
|---------|-----------|--------|
| ContextBuilder integration | Medium | High |
| Token counting | Low | High |
| Message normalization | Medium | High |
| Timeout management | Low | Medium |
| JSON repair | High | Medium |
| Hybrid steering | Medium | High |
| Pending images | Low | Medium |
| Raw event passthrough | Low | Low |
| Hallucination detection | Low | Low |
| Error dumps | Low | Low |

---

## Next Steps

1. Start with **ContextBuilder integration** - biggest impact, foundational
2. Add **token counting** - quick win, improves context management
3. Implement **message normalization** - ensures compatibility
4. Add **timeout management** - improves robustness
5. Consider **hybrid steering** - improves UX significantly
