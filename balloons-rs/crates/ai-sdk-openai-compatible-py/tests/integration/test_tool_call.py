"""Test tool calling with ai-sdk-openai-compatible."""

import asyncio
import json
from ai_sdk_openai_compatible_py import (
    create_chat_model_py as create_chat_model,
    Message,
    ToolDefinition,
)

BASE_URL = "http://192.168.0.196:8000"
MODEL_ID = "Qwen3.5-122B-A10B-Q6_K-00001-of-00004.gguf"

async def test_tool_call():
    """Test tool calling."""
    model = create_chat_model(BASE_URL, MODEL_ID, None)
    
    tools = [
        ToolDefinition(
            name="Bash",
            description="Run a bash command",
            parameters=json.dumps({
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command to run"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds"
                    }
                },
                "required": ["command"]
            })
        )
    ]
    
    print("Testing tool call...")
    result_str = await model.generate(
        messages=[
            Message("user", "What is the current directory? Run pwd.")
        ],
        tools=tools,
        max_tokens=1000,
        temperature=0.7,
    )
    
    result = result_str
    print(f"\n=== Result ===")
    print(f"Type: {type(result)}")
    print(f"Text: {result.text[:200] if result.text else 'None'}")
    print(f"Tool calls: {result.tool_calls}")
    print(f"Reasoning: {result.reasoning[:200] if result.reasoning else 'None'}")
    print(f"Usage: {result.usage}")
    print(f"Finish reason: {result.finish_reason}")
    
    if result.tool_calls:
        print(f"\n=== Tool Calls ===")
        for tc in result.tool_calls:
            print(f"  ID: {tc.id}")
            print(f"  Tool: {tc.name}")
            print(f"  Args: {tc.arguments}")
    else:
        print("\nNo tool calls in result")

if __name__ == "__main__":
    asyncio.run(test_tool_call())
