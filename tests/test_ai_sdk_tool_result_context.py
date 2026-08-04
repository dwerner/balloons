"""Test that LLM can respond based on tool results in context."""

import pytest
from unittest.mock import patch

from core.ai_sdk_runner import AISDKRunner
from models import (
    ToolResultEvent, ResultEvent, Message as CoreMessage, ToolResultBlock
)


class TestToolResultContext:
    """Test that LLM can use tool results to generate responses."""

    @pytest.mark.asyncio
    async def test_llm_responds_to_tool_result(self):
        """Test that LLM receives tool result and responds based on it."""
        runner = AISDKRunner(
            base_url='http://localhost:8000',
            model='test-model'
        )
        
        call_count = 0
        
        # First call: model asks to read file
        # Second call: model should respond based on tool result
        async def mock_stream_resp(messages, prompt, tools, working_dir):
            nonlocal call_count
            call_count += 1
            
            if call_count == 1:
                # First turn: model wants to read file
                return ({
                    'text': '',
                    'reasoning': '',
                    'tool_calls': [{
                        'id': 'call_1',
                        'name': 'Read',
                        'arguments': {'file_path': 'test.txt'},
                    }],
                    'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
                    'finish_reason': 'tool_calls',
                }, [])
            else:
                # Second turn: model should respond based on tool result
                # Verify that tool result is in messages
                tool_result_found = False
                for msg in messages:
                    if msg.role == "tool":
                        tool_result_found = True
                        break
                
                assert tool_result_found, "Tool result should be in messages"
                
                # Model responds based on tool result
                return ({
                    'text': 'The file contains: Hello World!',
                    'reasoning': '',
                    'tool_calls': [],
                    'usage': {'input_tokens': 20, 'output_tokens': 10, 'total_tokens': 30},
                    'finish_reason': 'stop',
                }, [])
        
        async def mock_execute(name, args, working_dir, run_id, session=None, output_callback=None):
            # Return specific content that LLM should use
            return ('Hello World!', False)
        
        with patch('core.ai_sdk_runner.get_tools_for_request', return_value=[]):
            with patch.object(runner, '_stream_one_response', mock_stream_resp):
                with patch('core.ai_sdk_runner.execute_tool', mock_execute):
                    events = []
                    async for event in runner.stream_response([], 'What is in test.txt?'):
                        events.append(event)
                    
                    # Verify we got tool result
                    tool_result_events = [e for e in events if isinstance(e, ToolResultEvent)]
                    assert len(tool_result_events) == 1
                    assert tool_result_events[0].result == 'Hello World!'
                    
                    # Verify we got final response
                    result_events = [e for e in events if isinstance(e, ResultEvent)]
                    assert len(result_events) == 1
                    
                    # Verify model made 2 calls (one for tool, one for response)
                    assert call_count == 2

    @pytest.mark.asyncio
    async def test_llm_uses_multiple_tool_results(self):
        """Test that LLM can use multiple tool results to respond."""
        runner = AISDKRunner(
            base_url='http://localhost:8000',
            model='test-model'
        )
        
        call_count = 0
        
        async def mock_stream_resp(messages, prompt, tools, working_dir):
            nonlocal call_count
            call_count += 1
            
            if call_count == 1:
                # First turn: model wants to read multiple files
                return ({
                    'text': '',
                    'reasoning': '',
                    'tool_calls': [
                        {'id': 'call_1', 'name': 'Read', 'arguments': {'file_path': 'file1.txt'}},
                        {'id': 'call_2', 'name': 'Read', 'arguments': {'file_path': 'file2.txt'}},
                    ],
                    'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
                    'finish_reason': 'tool_calls',
                }, [])
            else:
                # Second turn: verify both tool results are in context
                tool_results = []
                for msg in messages:
                    if msg.role == "tool":
                        if msg.content_blocks:
                            for block in msg.content_blocks:
                                if hasattr(block, 'tool_use_id'):
                                    tool_results.append(block.tool_use_id)
                
                assert 'call_1' in tool_results, "First tool result should be in context"
                assert 'call_2' in tool_results, "Second tool result should be in context"
                
                return ({
                    'text': 'I have read both files. file1.txt contains: A, file2.txt contains: B',
                    'reasoning': '',
                    'tool_calls': [],
                    'usage': {'input_tokens': 25, 'output_tokens': 15, 'total_tokens': 40},
                    'finish_reason': 'stop',
                }, [])
        
        async def mock_execute(name, args, working_dir, run_id, session=None, output_callback=None):
            if args['file_path'] == 'file1.txt':
                return ('A', False)
            else:
                return ('B', False)
        
        with patch('core.ai_sdk_runner.get_tools_for_request', return_value=[]):
            with patch.object(runner, '_stream_one_response', mock_stream_resp):
                with patch('core.ai_sdk_runner.execute_tool', mock_execute):
                    events = []
                    async for event in runner.stream_response([], 'Read file1.txt and file2.txt'):
                        events.append(event)
                    
                    # Verify we got 2 tool results
                    tool_result_events = [e for e in events if isinstance(e, ToolResultEvent)]
                    assert len(tool_result_events) == 2
                    
                    # Verify model made 2 calls
                    assert call_count == 2

    @pytest.mark.asyncio
    async def test_llm_handles_tool_error(self):
        """Test that LLM can handle tool execution errors."""
        runner = AISDKRunner(
            base_url='http://localhost:8000',
            model='test-model'
        )
        
        call_count = 0
        
        async def mock_stream_resp(messages, prompt, tools, working_dir):
            nonlocal call_count
            call_count += 1
            
            if call_count == 1:
                return ({
                    'text': '',
                    'reasoning': '',
                    'tool_calls': [{
                        'id': 'call_1',
                        'name': 'Read',
                        'arguments': {'file_path': 'nonexistent.txt'},
                    }],
                    'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
                    'finish_reason': 'tool_calls',
                }, [])
            else:
                # Second turn: verify error is in context
                error_found = False
                for msg in messages:
                    if msg.role == "tool" and msg.content_blocks:
                        for block in msg.content_blocks:
                            if hasattr(block, 'is_error') and block.is_error:
                                error_found = True
                                break
                
                assert error_found, "Error should be in tool result"
                
                return ({
                    'text': 'The file does not exist.',
                    'reasoning': '',
                    'tool_calls': [],
                    'usage': {'input_tokens': 20, 'output_tokens': 10, 'total_tokens': 30},
                    'finish_reason': 'stop',
                }, [])
        
        async def mock_execute(name, args, working_dir, run_id, session=None, output_callback=None):
            return ('File not found', True)  # is_error=True
        
        with patch('core.ai_sdk_runner.get_tools_for_request', return_value=[]):
            with patch.object(runner, '_stream_one_response', mock_stream_resp):
                with patch('core.ai_sdk_runner.execute_tool', mock_execute):
                    events = []
                    async for event in runner.stream_response([], 'Read nonexistent.txt'):
                        events.append(event)
                    
                    # Verify we got tool result with error
                    tool_result_events = [e for e in events if isinstance(e, ToolResultEvent)]
                    assert len(tool_result_events) == 1
                    
                    # Verify model made 2 calls
                    assert call_count == 2
