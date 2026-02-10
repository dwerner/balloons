"""Tool definitions for OpenAI-compatible backends.

Defines tools in OpenAI function calling format for use with OpenRouter,
llamacpp, and other OpenAI-compatible APIs.

All tools are organized into categories:
- TOOLS: Standard file/shell tools (Read, Write, Bash, Glob, Grep, List)
- BALLOON_TOOLS: Balloons-specific tools including:
  - Workflow tools (propose_fork, propose_merge, create_slide)
  - Session/link tools (list_links, follow_link, search_linked_session, session_info)
  - UI tools (balloon)
- SUPERVISOR_TOOLS: Process supervisor tools for managing long-running commands
"""

# Standard file/shell tools in OpenAI function format
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read the contents of a file. Returns the file content as text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to read (absolute or relative to working directory)"
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line number to start reading from (1-indexed). Optional."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines to read. Optional."
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Write",
            "description": "Write content to a file. Creates the file if it doesn't exist, overwrites if it does.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to write"
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file"
                    }
                },
                "required": ["file_path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "Execute a bash command and return its output. Use for git, npm, running tests, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 120, max 600)"
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": "Find files matching a glob pattern. Returns list of matching file paths.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to match (e.g., '**/*.py', 'src/**/*.ts')"
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in. Defaults to working directory."
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "Search for a pattern in files. Returns matching lines with file paths and line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regular expression pattern to search for"
                    },
                    "path": {
                        "type": "string",
                        "description": "File or directory to search in. Defaults to working directory."
                    },
                    "glob": {
                        "type": "string",
                        "description": "Glob pattern to filter files (e.g., '*.py')"
                    },
                    "case_insensitive": {
                        "type": "boolean",
                        "description": "Whether to ignore case (default false)"
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "List",
            "description": "List files and directories in a path. Like 'ls -la'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list. Defaults to working directory."
                    }
                },
                "required": []
            }
        }
    },
]

# Balloons-specific tools - UI interaction, workflow, and session/link navigation
BALLOON_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "balloon",
            "description": "Send a message or notification to the user through the Balloons UI. Use this to provide status updates, ask questions, or display information that should be highlighted in the chat interface.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to display to the user"
                    },
                    "type": {
                        "type": "string",
                        "enum": ["info", "warning", "error", "success", "question"],
                        "description": "The type of message (affects styling). Defaults to 'info'."
                    }
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "propose_fork",
            "description": """Propose creating a fork with curated context. Use this when you've analyzed a task and want to suggest an implementation path with optimized starting context. This allows you to specify which exchanges should be fully included (copy), summarized (compress), or excluded (drop) in the new fork.

When you call this tool, the user will see a visual representation of your proposal showing:
- The fork name and what it will accomplish
- Which exchanges you've selected to keep, summarize, or drop
- Your reasoning for each context decision

The user can then accept the proposal (creating the fork), modify your suggestions, or reject it.

Use this instead of asking "Would you like me to implement this?" when you have a clear implementation plan and want to start with focused context.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short name for the fork (e.g., 'implement-cache-layer', 'fix-auth-bug')"
                    },
                    "description": {
                        "type": "string",
                        "description": "What this fork will accomplish - the implementation goal"
                    },
                    "context_plan": {
                        "type": "array",
                        "description": "List of context mode assignments for exchanges",
                        "items": {
                            "type": "object",
                            "properties": {
                                "exchange_range": {
                                    "type": "string",
                                    "description": "Exchange range: '0-2' (indices 0,1,2), '5' (single), 'last' (most recent), 'last-2' (last 3), '-3' (last 3), 'all'"
                                },
                                "mode": {
                                    "type": "string",
                                    "enum": ["copy", "compress", "drop"],
                                    "description": "copy=include verbatim, compress=LLM summarizes, drop=exclude"
                                },
                                "reason": {
                                    "type": "string",
                                    "description": "Why this mode for these exchanges (shown to user)"
                                }
                            },
                            "required": ["exchange_range", "mode"]
                        }
                    },
                    "initial_prompt": {
                        "type": "string",
                        "description": "Optional starting prompt for the fork (what to do first)"
                    }
                },
                "required": ["name", "description", "context_plan"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "propose_merge",
            "description": """Propose merging the current fork back to its parent session. Use this when you believe work in the fork is complete and ready to be merged.

When you call this tool, the user will see a modal showing:
- Your proposed summary of what was accomplished
- Why you think the merge is appropriate now
- Key files changed and accomplishments

The user can then accept (merge happens), edit the summary, or reject.

Use this when:
- The implementation task from the fork is complete
- Tests are passing (if applicable)
- The work is ready to be integrated back

The merge summary becomes the record of what this fork accomplished, visible in the parent session.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "1-3 sentence summary of what was accomplished in this fork. Focus on outcomes, not process."
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why merge now? What indicates the work is complete?"
                    },
                    "files_changed": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of key files that were created or modified"
                    },
                    "key_accomplishments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Bullet points of what was done (e.g., 'Added caching layer', 'Fixed auth bug')"
                    }
                },
                "required": ["summary"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_slide",
            "description": """Create a presentation slide. Slides appear in the Slides tab and can be viewed in presentation mode.

Use this tool to:
- Build a presentation from conversation content
- Create step-by-step slide decks
- Visualize summaries or key concepts

Content constraints for 1080p display:
- Title: max ~50 characters
- Content: max ~10 lines of body text
- Bullets: 5-7 items, each under 60 chars
- Code blocks: max ~15 lines
- One concept per slide""",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Slide title (max ~50 characters for 1080p)"
                    },
                    "content": {
                        "type": "string",
                        "description": "Markdown body content (max ~10 lines for 1080p)"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional speaker notes (not shown in presentation)"
                    }
                },
                "required": []
            }
        }
    },
    # Session/link navigation tools
    {
        "type": "function",
        "function": {
            "name": "list_links",
            "description": "List all links from the current session. Returns link IDs, summaries, and linked session names. Use this to discover what other conversations are linked to this one.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "follow_link",
            "description": "Load context from a linked session. Returns the session metadata and recent conversation history. Use after list_links to explore a specific linked conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "link_id": {
                        "type": "string",
                        "description": "The link ID to follow (from list_links)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of turns to return (default 10)"
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Turn index to start from. If omitted, returns the last N turns."
                    },
                    "full_content": {
                        "type": "boolean",
                        "description": "If true, returns full turn content. Default returns truncated content."
                    }
                },
                "required": ["link_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_linked_session",
            "description": "Search for content within a linked session's conversation history. Use to find specific information in a linked conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "link_id": {
                        "type": "string",
                        "description": "The link ID of the session to search"
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query (case-insensitive substring match)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 20)"
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Skip first N matches for pagination (default 0)"
                    },
                    "full_content": {
                        "type": "boolean",
                        "description": "If true, returns full turn content. Default returns a preview."
                    }
                },
                "required": ["link_id", "query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "session_info",
            "description": "Get information about the current session including context usage, token counts, and fork status. Use this to understand the state of the conversation and make informed decisions about forking or merging.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "speak",
            "description": """Speak text aloud using text-to-speech. Use this to provide audio feedback or read content to the user.

Use this tool when:
- The user asks you to read something aloud
- You want to announce important information
- During presentations or demos
- When the user has indicated they prefer audio output

The speech will be queued and played sequentially. The user can stop speech at any time.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to speak aloud"
                    },
                    "voice": {
                        "type": "string",
                        "description": "Optional voice to use (overrides default). Backend-specific."
                    }
                },
                "required": ["text"]
            }
        }
    },
]

# Names of balloon tools for easy checking (includes all non-standard tools)
BALLOON_TOOL_NAMES = {
    "balloon", "propose_fork", "propose_merge", "create_slide",
    "list_links", "follow_link", "search_linked_session", "session_info",
    "speak",
}

# Process supervisor tools for managing long-running background processes
SUPERVISOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "supervisor_start",
            "description": """Start a new supervised background process.

Use this tool to run long-running commands (servers, watchers, builds, etc.) that
should continue running while you work on other tasks. The process output is captured
and can be queried later with supervisor_output.

Examples of good use cases:
- Starting a development server: `npm run dev`
- Running a file watcher: `cargo watch -x test`
- Long builds: `make all`
- Database processes: `docker-compose up`

The process is scoped to the current session and will be tracked until stopped
or the session is closed.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute"
                    },
                    "name": {
                        "type": "string",
                        "description": "Optional friendly name for the process (e.g., 'dev-server', 'test-watcher')"
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory for the process. Defaults to session working directory."
                    },
                    "env": {
                        "type": "object",
                        "description": "Optional environment variables to set (in addition to inherited env)",
                        "additionalProperties": {"type": "string"}
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "supervisor_list",
            "description": """List all supervised processes.

Shows all processes managed by the supervisor, including their status (running/exited),
command, and basic info. By default only shows processes for the current session.

Use this to check what background processes are running before starting new ones,
or to get process IDs for supervisor_output or supervisor_stop.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "all_sessions": {
                        "type": "boolean",
                        "description": "If true, list processes from all sessions. Default: only current session."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "supervisor_output",
            "description": """Get output from a supervised process.

Returns recent log entries (stdout, stderr, system messages) from a process.
Use this to check on the status of a background process, see build output,
or diagnose issues.

The output includes timestamps and source (stdout/stderr/system) for each entry.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {
                        "type": "string",
                        "description": "The process ID (from supervisor_start or supervisor_list)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of log entries to return. Default: 50"
                    }
                },
                "required": ["process_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "supervisor_stop",
            "description": """Stop a supervised process.

Sends SIGTERM to stop a running process. Use this when you're done with a
background process (e.g., shutting down a dev server, stopping a watcher).

The process and its logs are retained after stopping, so you can still
query its output with supervisor_output.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {
                        "type": "string",
                        "description": "The process ID to stop"
                    }
                },
                "required": ["process_id"]
            }
        }
    },
]

# Names of supervisor tools
SUPERVISOR_TOOL_NAMES = {
    "supervisor_start", "supervisor_list", "supervisor_output", "supervisor_stop",
}

# Session review tools for quality evaluation
REVIEW_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "save_review",
            "description": """Save a completed session quality review.

Call this tool after collecting all review data from the user:
- Rubric scores (1-5) for each dimension
- User's summary of their experience
- Your task classification and analysis

This saves the review data persistently for later analysis and reporting.
The review will be associated with the session being reviewed.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "ID of the session being reviewed (from the context provided)"
                    },
                    "model_under_review": {
                        "type": "string",
                        "description": "Backend/model name that was used in the session being reviewed"
                    },
                    "scores": {
                        "type": "object",
                        "description": "Rubric scores (1-5 each, or 0 if skipped)",
                        "properties": {
                            "correctness": {"type": "integer", "minimum": 0, "maximum": 5},
                            "efficiency": {"type": "integer", "minimum": 0, "maximum": 5},
                            "instruction_following": {"type": "integer", "minimum": 0, "maximum": 5},
                            "recovery": {"type": "integer", "minimum": 0, "maximum": 5},
                            "autonomy": {"type": "integer", "minimum": 0, "maximum": 5},
                            "judgment": {"type": "integer", "minimum": 0, "maximum": 5},
                            "communication": {"type": "integer", "minimum": 0, "maximum": 5}
                        },
                        "required": ["correctness", "efficiency", "instruction_following", "recovery", "autonomy", "judgment", "communication"]
                    },
                    "task_category": {
                        "type": "string",
                        "enum": ["debugging", "feature", "refactor", "exploration", "documentation", "review", "learning", "ops", "other"],
                        "description": "Category of the task performed in the session"
                    },
                    "task_description": {
                        "type": "string",
                        "description": "One sentence description of what the session was about"
                    },
                    "user_summary": {
                        "type": "string",
                        "description": "User's freeform comments about the session"
                    },
                    "llm_commentary": {
                        "type": "string",
                        "description": "Your analysis of the session including patterns from sentiment markers and suggestions"
                    }
                },
                "required": ["session_id", "model_under_review", "scores", "task_category", "task_description", "user_summary", "llm_commentary"]
            }
        }
    },
]

# Names of review tools
REVIEW_TOOL_NAMES = {"save_review"}

# Import goal tools
from .goal_tools import GOAL_TOOLS, GOAL_TOOL_NAMES


def get_tools_for_request(
    allowed_tools: list[str] | None = None,
    disable_tools: bool = False,
    include_balloon_tools: bool = True,
    include_supervisor_tools: bool = True,
    include_review_tools: bool = False,
    include_goal_tools: bool = True,
) -> list[dict] | None:
    """Get the list of tools to include in an API request.

    Includes standard file/shell tools and optionally Balloons-specific tools
    (workflow, UI, session/link navigation), supervisor tools, review tools,
    and goal management tools.

    Args:
        allowed_tools: List of tool names to allow, or None for all
        disable_tools: If True, return None (no tools)
        include_balloon_tools: If True, include balloon-specific tools
        include_supervisor_tools: If True, include process supervisor tools
        include_review_tools: If True, include session review tools (save_review)
        include_goal_tools: If True, include goal management tools (create_goal, etc.)

    Returns:
        List of tool definitions, or None if tools disabled
    """
    if disable_tools:
        return None

    # Combine tool categories
    all_tools = TOOLS
    if include_balloon_tools:
        all_tools = all_tools + BALLOON_TOOLS
    if include_supervisor_tools:
        all_tools = all_tools + SUPERVISOR_TOOLS
    if include_review_tools:
        all_tools = all_tools + REVIEW_TOOLS
    if include_goal_tools:
        all_tools = all_tools + GOAL_TOOLS

    if allowed_tools is None:
        return all_tools

    # Filter to only allowed tools
    return [
        tool for tool in all_tools
        if tool["function"]["name"] in allowed_tools
    ]


