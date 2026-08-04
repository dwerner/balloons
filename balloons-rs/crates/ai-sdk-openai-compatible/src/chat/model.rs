//! OpenAI-compatible chat language model.

use std::collections::HashMap;
use std::sync::Arc;
use async_trait::async_trait;
use futures::StreamExt;
use tokio::sync::Mutex;

use crate::chat::messages::convert_to_chat_messages;
use crate::chat::tools::{parse_tool_calls, prepare_tool_choice, prepare_tools};
use crate::chat::types::{
    ChatCompletionChunk, ChatCompletionRequest, ChatCompletionResponse,
};
use crate::error::Error;
use crate::http::HttpClient;
use crate::streaming::parse_sse_stream;
use crate::types::{
    CallOptions, FinishReason, GenerateResult, LanguageModel,
    LanguageModelStream, Prompt, StreamPart, Usage,
};

/// Check if a string is valid JSON (like TypeScript SDK's isParsableJson).
fn is_valid_json(s: &str) -> bool {
    s.parse::<serde_json::Value>().is_ok()
}

/// Tracks tool call state across streaming chunks.
#[derive(Default)]
struct ToolCallState {
    /// Tool IDs that have been started (ToolCallStart emitted)
    started_tools: std::collections::HashSet<String>,
    /// Tool IDs that are currently active (not yet ended)
    active_tools: std::collections::HashSet<String>,
    /// Maps tool call index to tool ID (for handling empty IDs in subsequent chunks)
    current_tool_ids: HashMap<u32, String>,
    /// Maps tool ID to accumulated arguments
    accumulated_args: HashMap<String, String>,
    /// Maps tool ID to tool name
    tool_names: HashMap<String, String>,
}

/// Configuration for the OpenAI-compatible chat model.
#[derive(Debug, Clone)]
pub struct ChatConfig {
    pub base_url: String,
    pub model_id: String,
    pub api_key: Option<String>,
    pub headers: reqwest::header::HeaderMap,
}

/// OpenAI-compatible chat language model.
pub struct OpenAICompatibleChatModel {
    config: ChatConfig,
    client: HttpClient,
}

impl OpenAICompatibleChatModel {
    pub fn new(config: ChatConfig) -> Result<Self, Error> {
        let mut client = HttpClient::new(&config.base_url)?;

        if let Some(ref api_key) = config.api_key {
            client = client.with_api_key(api_key);
        }

        if !config.headers.is_empty() {
            client = client.with_headers(config.headers.clone());
        }

        Ok(Self {
            config,
            client,
        })
    }

    /// Build the request body.
    fn build_request(&self, prompt: &Prompt, options: &CallOptions) -> Result<ChatCompletionRequest, Error> {
        let messages = convert_to_chat_messages(prompt)?;

        Ok(ChatCompletionRequest {
            model: self.config.model_id.clone(),
            messages,
            temperature: options.temperature,
            top_p: options.top_p,
            n: options.n,
            stream: Some(false),
            stop: options.stop.clone(),
            max_tokens: options.max_tokens,
            presence_penalty: options.presence_penalty,
            frequency_penalty: options.frequency_penalty,
            logit_bias: None,
            user: None,
            tools: options.tools.as_ref().map(|t| prepare_tools(t)),
            tool_choice: options.tool_choice.as_ref().and_then(prepare_tool_choice),
            response_format: None,
            seed: options.seed,
        })
    }

    /// Build the streaming request body.
    fn build_streaming_request(
        &self,
        prompt: &Prompt,
        options: &CallOptions,
    ) -> Result<ChatCompletionRequest, Error> {
        let mut request = self.build_request(prompt, options)?;
        request.stream = Some(true);
        Ok(request)
    }
}

#[async_trait]
impl LanguageModel for OpenAICompatibleChatModel {
    fn provider(&self) -> &str {
        "openai-compatible"
    }

    fn model_id(&self) -> &str {
        &self.config.model_id
    }

    async fn do_generate(
        &self,
        prompt: Prompt,
        options: CallOptions,
    ) -> Result<GenerateResult, Error> {
        let request = self.build_request(&prompt, &options)?;

        let response: ChatCompletionResponse = self
            .client
            .post_json("/v1/chat/completions", &request)
            .await?;

        let choice = &response.choices[0];
        let usage = response.usage.as_ref().map(|u| Usage {
            input_tokens: u.prompt_tokens,
            output_tokens: u.completion_tokens,
            total_tokens: u.total_tokens,
        });

        let finish_reason = match choice.finish_reason.as_deref() {
            Some("stop") => FinishReason::Stop,
            Some("length") => FinishReason::Length,
            Some("tool_calls") => FinishReason::ToolCalls,
            Some("content_filter") => FinishReason::ContentFilter,
            _ => FinishReason::Other,
        };

        let mut text = None;
        let mut reasoning = None;
        let mut tool_calls = Vec::new();

        if let Some(ref reasoning_content) = choice.message.reasoning_content {
            if !reasoning_content.is_empty() {
                reasoning = Some(reasoning_content.clone());
            }
        }

        if let Some(ref content) = choice.message.content {
            if !content.is_empty() {
                text = Some(content.clone());
            }
        }

        if let Some(ref calls) = choice.message.tool_calls {
            tool_calls = parse_tool_calls(calls);
        }

        Ok(GenerateResult {
            response_id: response.id,
            text,
            reasoning,
            tool_calls,
            usage: usage.unwrap_or_default(),
            finish_reason,
            provider_metadata: serde_json::Value::Null,
        })
    }

    async fn do_stream(
        &self,
        prompt: Prompt,
        options: CallOptions,
    ) -> Result<LanguageModelStream, Error> {
        let request = self.build_streaming_request(&prompt, &options)?;

        // Need to make blocking call to get response for streaming
        let response = self
            .client
            .post_json_stream("/v1/chat/completions", &request)
            .await?;

      let stream = parse_sse_stream(response).await?;
        
        // Track tool call state across chunks
        let tool_state = Arc::new(Mutex::new(ToolCallState::default()));
        // Event buffer for emitting multiple events per chunk
        let event_buffer: Arc<Mutex<Vec<Result<StreamPart, Error>>>> = Arc::new(Mutex::new(Vec::new()));
        
        let parsed = stream
            .filter_map(move |result| {
                let tool_state = tool_state.clone();
                let event_buffer = event_buffer.clone();
                async move {
                    match result {
                        Ok(event) => {
                            if event.data == "[DONE]" {
                                // Emit ToolCallEnd + ToolCall for any remaining active tools
                                let mut state = tool_state.lock().await;
                                let ended_tools: Vec<_> = state.active_tools.drain().collect();
                                // Release state borrow before processing
                                drop(state);
                                
                                let mut buffer = event_buffer.lock().await;
                                for tool_id in ended_tools {
                                    let mut state = tool_state.lock().await;
                                    let arguments = state.accumulated_args.remove(&tool_id).unwrap_or_default();
                                    let tool_name = state.tool_names.remove(&tool_id);
                                    drop(state);
                                    
                                    buffer.push(Ok(StreamPart::ToolCallEnd { id: tool_id.clone() }));
                                    if let Some(name) = tool_name {
                                        buffer.push(Ok(StreamPart::ToolCall {
                                            id: tool_id,
                                            tool_name: name,
                                            arguments,
                                        }));
                                    }
                                }
                                // Return first buffered event
                                let mut buffer = event_buffer.lock().await;
                                return buffer.pop();
                            }

                            match serde_json::from_str::<ChatCompletionChunk>(&event.data) {
                                Ok(chunk) => {
                                    let choice = &chunk.choices[0];
                                    let mut new_events = Vec::new();

                                    // Extract text delta
                                    if let Some(ref content) = choice.delta.content {
                                        if !content.is_empty() {
                                            new_events.push(Ok(StreamPart::TextDelta {
                                                delta: content.clone(),
                                            }));
                                        }
                                    }

                                    // Extract reasoning delta
                                    if let Some(ref reasoning) = choice.delta.reasoning_content {
                                        if !reasoning.is_empty() {
                                            new_events.push(Ok(StreamPart::ReasoningDelta {
                                                delta: reasoning.clone(),
                                            }));
                                        }
                                    }

                                     // Extract tool call deltas
                                     if let Some(ref calls) = choice.delta.tool_calls {
                                         for call in calls {
                                            if let Some(ref function) = call.function {
                                                let tool_id = call.id.clone().unwrap_or_default();
                                                let _tool_id_for_debug = tool_id.clone();
                                                let actual_tool_id = if tool_id.is_empty() {
                                                    let state = tool_state.lock().await;
                                                    state.current_tool_ids.get(&call.index).cloned().unwrap_or_default()
                                                } else {
                                                    tool_id
                                                };
                                                
                                                // Update current tool ID tracking
                                                {
                                                    let mut state = tool_state.lock().await;
                                                    if !actual_tool_id.is_empty() {
                                                        state.current_tool_ids.insert(call.index, actual_tool_id.clone());
                                                    }
                                                }
                                                
                                              let mut state = tool_state.lock().await;
                                                   
                                                  // Check if this is a new tool call
                                                   if !state.started_tools.contains(&actual_tool_id) {
                                                       state.started_tools.insert(actual_tool_id.clone());
                                                       state.active_tools.insert(actual_tool_id.clone());
                                                       let tool_name = function.name.clone().unwrap_or_default();
                                                       state.tool_names.insert(actual_tool_id.clone(), tool_name.clone());
                                                       new_events.push(Ok(StreamPart::ToolCallStart {
                                                           id: actual_tool_id.clone(),
                                                           tool_name,
                                                       }));
                                                   }
                                                 
                                                 // Accumulate arguments and emit ToolCallDelta
                                                  if let Some(ref args) = function.arguments {
                                                      // Accumulate arguments
                                                      let accumulated = state.accumulated_args.entry(actual_tool_id.clone())
                                                          .or_insert_with(String::new);
                                                      accumulated.push_str(args);
                                                      
                                                      // Clone accumulated value before releasing borrow
                                                      let accumulated_clone = accumulated.clone();
                                                      
                                                      new_events.push(Ok(StreamPart::ToolCallDelta {
                                                          id: actual_tool_id.clone(),
                                                          delta: accumulated_clone.clone(),
                                                      }));
                                                      
// Check if accumulated arguments are complete JSON (like TS SDK)
                                                       if is_valid_json(&accumulated_clone) && state.active_tools.contains(&actual_tool_id) {
                                                           state.active_tools.remove(&actual_tool_id);
                                                           new_events.push(Ok(StreamPart::ToolCallEnd {
                                                               id: actual_tool_id.clone(),
                                                           }));
                                                           let tool_name = state.tool_names.get(&actual_tool_id).cloned().unwrap_or_default();
                                                           new_events.push(Ok(StreamPart::ToolCall {
                                                               id: actual_tool_id.clone(),
                                                               tool_name: tool_name.clone(),
                                                               arguments: accumulated_clone.clone(),
                                                           }));
                                                           eprintln!("[M] Emitting ToolCall: id={}, tool_name={}, arguments={}", actual_tool_id, tool_name, accumulated_clone);
                                                       }
                                                  }
                                            }
                                        }
                                    }

                                    // Check for finish - emit ToolCallEnd + ToolCall for all active tools
                                    if let Some(ref reason) = choice.finish_reason {
                                        let mut state = tool_state.lock().await;
                                        let ended_tools: Vec<_> = state.active_tools.drain().collect();
                                        for tool_id in ended_tools {
                                            let arguments = state.accumulated_args.remove(&tool_id).unwrap_or_default();
                                            let tool_name = state.tool_names.remove(&tool_id);
                                            new_events.push(Ok(StreamPart::ToolCallEnd { id: tool_id.clone() }));
                                            if let Some(name) = tool_name {
                                                new_events.push(Ok(StreamPart::ToolCall {
                                                    id: tool_id,
                                                    tool_name: name,
                                                    arguments,
                                                }));
                                            }
                                        }
                                        
                                        let finish_reason = match reason.as_str() {
                                            "stop" => FinishReason::Stop,
                                            "length" => FinishReason::Length,
                                            "tool_calls" => FinishReason::ToolCalls,
                                            "content_filter" => FinishReason::ContentFilter,
                                            _ => FinishReason::Other,
                                        };

                                        new_events.push(Ok(StreamPart::Finish {
                                            reason: finish_reason,
                                            usage: chunk.usage.map(|u| Usage {
                                                input_tokens: u.prompt_tokens,
                                                output_tokens: u.completion_tokens,
                                                total_tokens: u.total_tokens,
                                            }),
                                        }));
                                    }

                                    // Buffer new events and return first one
                                    let mut buffer = event_buffer.lock().await;
                                    buffer.extend(new_events);
                                    buffer.pop()
                                }
                                Err(e) => Some(Err(Error::InvalidJson(e))),
                            }
                        }
                        Err(e) => Some(Err(e)),
                    }
                }
            });

        Ok(Box::pin(parsed))
    }
}
