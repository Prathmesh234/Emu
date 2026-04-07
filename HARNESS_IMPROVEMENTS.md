# HARNESS_IMPROVEMENTS.md

## Diff-Style Comparative Analysis: Emu Harness vs Claude Code Harness

### Executive Summary

The Emu harness is a **runtime evaluation framework** centered on the `/agent/step` endpoint with inline action validation and session-based logging. The Claude Code harness is a **production-grade agent execution engine** built around `QueryEngine`, a typed `Tool` interface with Zod schemas, a VCR fixture system for deterministic replay, granular cost tracking, and a rich analytics pipeline. The Emu harness lacks formal test case definitions, deterministic replay, per-model cost tracking, typed tool schemas, and structured result reporting — all of which Claude Code treats as first-class primitives.

---

## 1. Test Case Structure

| Dimension | Emu Harness | Claude Code Harness |
|---|---|---|
| **Test definition** | No DSL, no test cases. `test.py` is a one-off VLM probe script — single request, no session, no assertions | `QueryEngine` accepts structured `QueryEngineConfig` with `maxTurns`, `maxBudgetUsd`, `jsonSchema` for structured output enforcement, and yields typed `SDKMessage` results |
| **Fixtures** | System prompt dynamically built from workspace at runtime; no caching | `vcr.ts`: SHA1-hash-keyed fixture files, dehydration/hydration of paths and timestamps, auto-record on first run, fail-in-CI-if-missing guard |
| **Reproducibility** | Non-deterministic — relies on live model calls every time | VCR replay with `withVCR()` / `withStreamingVCR()` / `withFixture()` ensures byte-identical replay in CI |
| **Schema** | Implicit — Pydantic `AgentResponse` validates at parse-time but no per-tool input schema | Zod schemas per tool (`inputSchema: Input`), `validateInput()` method, and `outputSchema` for type-safe tool results |

### Gap: No fixture/replay system

**`backend/test.py`** fires a live request every invocation:
```python
def send_request(image_uri: str, task: str) -> None:
    payload = {
        "model": "Qwen/Qwen3.5-35B-A3B",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": image_uri}},
                {"type": "text", "text": task},
            ]},
        ],
    }
```

Claude Code's `vcr.ts` wraps all API calls with deterministic fixture management:
```typescript
// services/vcr.ts
export async function withVCR(
  messages: Message[],
  f: () => Promise<(AssistantMessage | StreamEvent | SystemAPIErrorMessage)[]>,
): Promise<(AssistantMessage | StreamEvent | SystemAPIErrorMessage)[]> {
  if (!shouldUseVCR()) return await f();
  
  const dehydratedInput = mapMessages(
    messagesForAPI.map(_ => _.message.content),
    dehydrateValue,  // Replaces CWD, timestamps, UUIDs with placeholders
  );
  const filename = `fixtures/${hash}.json`;
  
  // Read from cache or record + write
  try {
    const cached = jsonParse(await readFile(filename));
    return cached.output.map((message, index) =>
      mapMessage(message, hydrateValue, index, randomUUID())
    );
  } catch { /* ENOENT: record new fixture */ }
  
  if (env.isCI && !isEnvTruthy(process.env.VCR_RECORD)) {
    throw new Error(`Fixture missing: ${filename}. Re-run with VCR_RECORD=1`);
  }
  // ...records fixture to disk
}
```

---

## 2. Agent Invocation

| Dimension | Emu Harness | Claude Code Harness |
|---|---|---|
| **Entry point** | `POST /agent/step` in `main.py` — flat `for loop_i in range(MAX_TOOL_LOOPS + 1)` | `QueryEngine.submitMessage()` — async generator yielding typed `SDKMessage` events |
| **Provider abstraction** | `load_provider()` returns `(call_model, is_ready, ensure_ready, name)` tuple | Typed `Tool` interface with `call()`, `validateInput()`, `checkPermissions()`, `isReadOnly()`, `isConcurrencySafe()`, `isDestructive()` — built via `buildTool()` with safe defaults |
| **Budget control** | `MAX_TOOL_LOOPS = 10` counter only | `maxTurns`, `maxBudgetUsd`, `taskBudget` with real-time USD tracking; yields `error_max_turns` and `error_max_budget_usd` result types |
| **Abort support** | None — loop runs to completion or error | `AbortController` per query, `this.abortController.abort()` for clean interruption |
| **Multi-agent** | Single agent loop | Task hierarchy: `LocalAgentTask`, `RemoteAgentTask`, `InProcessTeammateTask`, `DreamTask` — each with typed state (`TaskState`), `kill()` cleanup, and `isTerminalTaskStatus()` guards |

### Gap: No abort/cancellation mechanism

The Emu harness loop in `main.py` has no way to interrupt a running step:
```python
for loop_i in range(MAX_TOOL_LOOPS + 1):
    response = call_model(agent_req)  # Blocks until complete — no abort signal
    # ...no cancellation check between iterations
```

Claude Code threads an `AbortController` through the entire query lifecycle:
```typescript
// QueryEngine.ts
export class QueryEngine {
  private abortController: AbortController
  
  interrupt(): void {
    this.abortController.abort()
  }
}
```

---

## 3. Output Validation

| Dimension | Emu Harness | Claude Code Harness |
|---|---|---|
| **Runtime validation** | 6 heuristic rules in `action_validator.py` (no consecutive mouse_moves, micro-movement, 5-strike, minimum scroll, unknown action, absolute coords) | Per-tool `validateInput()` returning `ValidationResult = { result: true } \| { result: false, message, errorCode }`, plus permission system with `checkPermissions()` |
| **Schema enforcement** | Pydantic `AgentResponse` — catches malformed JSON after model response | Zod schemas at tool definition (`inputSchema`), validated before execution; `SyntheticOutputTool` enforces structured JSON output matching caller-supplied `jsonSchema` |
| **Structured output** | No support — responses are parsed from JSON in model output text | `jsonSchema` parameter triggers `registerStructuredOutputEnforcement()` hook; `SyntheticOutputTool` catches schema violations with retries up to `MAX_STRUCTURED_OUTPUT_RETRIES` |
| **Result typing** | `AgentResponse(action, tool_calls, done, confidence, inference_time_ms)` — flat | `SDKMessage` union: `result`, `user`, `assistant`, `system`, `stream_event`, `progress` — each with subtypes (`success`, `error_max_turns`, `error_max_budget_usd`, `error_during_execution`, `error_max_structured_output_retries`) |

### Gap: No structured output enforcement / typed tool results

Emu's validation is purely reactive (post-parse):
```python
# context_manager/action_validator.py
def validate(self, session_id: str, action: dict) -> tuple[bool, str]:
    history = self._history.setdefault(session_id, [])
    # ...6 heuristic rules on raw dict
```

Claude Code validates at the schema level with Zod:
```typescript
// Tool.ts
export type Tool<Input extends AnyObject = AnyObject, Output = unknown> = {
  readonly inputSchema: Input  // Zod schema
  
  validateInput?(
    input: z.infer<Input>,
    context: ToolUseContext,
  ): Promise<ValidationResult>
  
  checkPermissions(
    input: z.infer<Input>,
    context: ToolUseContext,
  ): Promise<PermissionResult>
  
  call(
    args: z.infer<Input>,
    context: ToolUseContext,
    canUseTool: CanUseToolFn,
    parentMessage: AssistantMessage,
    onProgress?: ToolCallProgress<P>,
  ): Promise<ToolResult<Output>>
}
```

---

## 4. Error Handling

| Dimension | Emu Harness | Claude Code Harness |
|---|---|---|
| **Strategy** | 4-layer catch-and-retry: Provider → Schema → Tool → Action, with error text injected back into context | Typed error propagation via `SDKMessage` union results; retryable API errors categorized in `services/api/errors.ts`; structured error diagnostics |
| **Error classification** | `interpret_action_error()` in `utilities/action_errors.py` — string-matching ("permission", "not found", "timed out") | `categorizeRetryableAPIError()` returns structured error types; `error_during_execution` results include diagnostic `[ede_diagnostic] result_type=... last_content_type=... stop_reason=...` |
| **Budget exhaustion** | `MAX_TOOL_LOOPS` only — returns `"action_rejected"` status | Separate result subtypes: `error_max_turns`, `error_max_budget_usd`, `error_max_structured_output_retries` — each yields a typed SDKMessage with cost metadata |
| **In-memory error log** | `conversation.log` flat file | `getInMemoryErrors()` ring buffer (100 entries), watermarked per-turn for scoped error reporting in results |

### Gap: No error classification taxonomy

Emu's error interpretation is brittle string-matching:
```python
# utilities/action_errors.py
def interpret_action_error(error: str, action_label: str) -> str:
    if "permission" in error.lower():
        return "[ACTION FAILED: left_click] Permission denied..."
    if "not found" in error.lower():
        return "[ACTION FAILED: left_click] Target not found..."
    if "timed out" in error.lower():
        return "[ACTION FAILED: left_click] Timed out after 30s..."
```

Claude Code returns structured, typed error results:
```typescript
// QueryEngine.ts
yield {
  type: 'result',
  subtype: 'error_during_execution',
  duration_ms: Date.now() - startTime,
  duration_api_ms: getTotalAPIDuration(),
  is_error: true,
  num_turns: turnCount,
  stop_reason: lastStopReason,
  session_id: getSessionId(),
  total_cost_usd: getTotalCost(),
  usage: this.totalUsage,
  errors: [
    `[ede_diagnostic] result_type=${edeResultType} last_content_type=${edeLastContentType}`,
    ...getInMemoryErrors().slice(watermark).map(_ => _.error),
  ],
}
```

---

## 5. Observability / Logging

| Dimension | Emu Harness | Claude Code Harness |
|---|---|---|
| **Logging** | `log_entry()` → flat text in `.emu/sessions/<id>/logs/conversation.log`; WebSocket broadcast via `ConnectionManager.send()` | Analytics pipeline with `logEvent()` / `logEventAsync()` using typed metadata (no strings to prevent code/filepath leaks); Datadog sink; session transcript persistence via `recordTranscript()` |
| **Cost tracking** | `inference_time_ms` field in `AgentResponse`; no cost tracking | Full `cost-tracker.ts`: per-model USD costs, cache read/write tokens, web search requests, tool duration, lines changed; `getModelUsage()` returns per-model breakdown |
| **Token accounting** | `estimate_token_count()` — rough `len(content) // 4` heuristic | `accumulateUsage()` uses real API usage objects (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`); VCR fixtures replay costs via `addCachedCostToTotalSessionCost()` |
| **Session persistence** | Log file only | `recordTranscript()` / `flushSessionStorage()` with fire-and-forget for assistant messages, awaited for user messages; resumable sessions via `--resume` |

### Gap: No cost tracking at all

Emu records only `inference_time_ms`:
```python
# models/response.py
class AgentResponse(BaseModel):
    inference_time_ms: int = Field(ge=0)
    # No cost tracking fields
```

Claude Code tracks every dimension of cost:
```typescript
// cost-tracker.ts
export function addToTotalSessionCost(cost: number, usage: Usage, model: string): number {
  const modelUsage = addToTotalModelUsage(cost, usage, model);
  addToTotalCostState(cost, modelUsage, model);
  getCostCounter()?.add(cost, attrs);
  getTokenCounter()?.add(usage.input_tokens, { ...attrs, type: 'input' });
  getTokenCounter()?.add(usage.output_tokens, { ...attrs, type: 'output' });
  getTokenCounter()?.add(usage.cache_read_input_tokens ?? 0, { ...attrs, type: 'cacheRead' });
  // ...
}
```

---

## 6. Extensibility

| Dimension | Emu Harness | Claude Code Harness |
|---|---|---|
| **Tool registration** | Add OpenAI-format dict to `AGENT_TOOLS_OPENAI` list, implement handler function, add `if name == "..."` branch in dispatcher | `buildTool()` factory with typed defaults; tools are standalone modules (`tools/BashTool/`, `tools/FileEditTool/`); `getAllBaseTools()` assembles the registry with feature flags |
| **Provider system** | `_PROVIDER_MAP` dict + env var auto-detection; each provider implements `call_model()`, `is_ready()`, `ensure_ready()` | `Tool` interface is provider-agnostic; framework handles tool format conversion internally; MCP protocol support via `MCPTool` |
| **Feature gating** | None — all features always active | `feature()` macro (compile-time dead code elimination via `bun:bundle`); runtime `isEnvTruthy()` toggles; `isEnabled()` per tool |
| **Permission system** | Only action validator rules | Multi-layer: `validateInput()` → `checkPermissions()` → `canUseTool` hook → `ToolPermissionContext` with `alwaysAllowRules`, `alwaysDenyRules`, `alwaysAskRules` per source |

### Gap: No feature flag system

Emu has no way to toggle features for A/B testing or gradual rollout. Claude Code uses compile-time feature flags:
```typescript
// tools.ts
const SleepTool = feature('PROACTIVE') || feature('KAIROS')
  ? require('./tools/SleepTool/SleepTool.js').SleepTool
  : null;

// getAllBaseTools()
...(SleepTool ? [SleepTool] : []),
```

---

## Prioritized Improvements

### P0 — Critical (Blocks Evaluation Fidelity)

#### 1. VCR Fixture/Replay System for Deterministic Testing

**Why**: Without replay, every test run hits live APIs — non-deterministic, expensive, rate-limited, and impossible to CI.

**Implementation**: Add a `vcr.py` module wrapping model calls:

```python
# backend/tools/vcr.py
import hashlib, json, os
from pathlib import Path

FIXTURES_DIR = Path(".emu/fixtures")
VCR_ENABLED = os.environ.get("EMU_VCR", "0") == "1"
VCR_RECORD = os.environ.get("EMU_VCR_RECORD", "0") == "1"

def _dehydrate(s: str, cwd: str) -> str:
    """Replace environment-specific values with placeholders."""
    return s.replace(cwd, "[CWD]").replace(os.path.expanduser("~"), "[HOME]")

def _hydrate(s: str, cwd: str) -> str:
    return s.replace("[CWD]", cwd).replace("[HOME]", os.path.expanduser("~"))

def _fixture_path(messages: list[dict]) -> Path:
    dehydrated = json.dumps(messages, sort_keys=True)
    h = hashlib.sha1(dehydrated.encode()).hexdigest()[:12]
    return FIXTURES_DIR / f"vcr-{h}.json"

def with_vcr(messages: list[dict], call_fn):
    """Wrap a model call with fixture caching."""
    if not VCR_ENABLED:
        return call_fn()
    
    fixture = _fixture_path(messages)
    if fixture.exists():
        return json.loads(fixture.read_text())
    
    if os.environ.get("CI") and not VCR_RECORD:
        raise RuntimeError(f"Fixture missing: {fixture}. Re-run with EMU_VCR_RECORD=1")
    
    result = call_fn()
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    fixture.write_text(json.dumps(result, indent=2))
    return result
```

Integrate in each provider's `call_model()`:
```python
# providers/claude/client.py
def call_model(agent_req: AgentRequest) -> AgentResponse:
    messages = build_messages(agent_req)
    raw = with_vcr(messages, lambda: _call_anthropic_api(messages))
    return parse_response(raw)
```

#### 2. Formal Test Case Definitions with pytest

**Why**: `test.py` is a one-off script — no suite, no assertions, no pass/fail criteria.

```python
# backend/tests/test_harness.py
import pytest
from pathlib import Path

class EvalCase:
    """A single evaluation test case."""
    def __init__(self, name: str, task: str, screenshot: str,
                 expected_action: str, expected_target: dict | None = None,
                 max_steps: int = 5, timeout_s: float = 30.0):
        self.name = name
        self.task = task
        self.screenshot = screenshot
        self.expected_action = expected_action
        self.expected_target = expected_target
        self.max_steps = max_steps
        self.timeout_s = timeout_s

EVAL_CASES = [
    EvalCase(
        name="open_notepad",
        task="Open Notepad",
        screenshot="fixtures/desktop_home.png",
        expected_action="left_click",
        expected_target={"element_contains": "Notepad"},
    ),
    EvalCase(
        name="type_in_editor",
        task="Type 'Hello World' in the currently open text editor",
        screenshot="fixtures/notepad_open.png",
        expected_action="type_text",
        expected_target={"text": "Hello World"},
    ),
]

@pytest.fixture
def session_id():
    import uuid
    return str(uuid.uuid4())

@pytest.mark.parametrize("case", EVAL_CASES, ids=lambda c: c.name)
def test_eval_case(case: EvalCase, session_id):
    """Run an evaluation case and validate output."""
    from backend.main import agent_step_sync  # hypothetical sync wrapper
    
    response = agent_step_sync(
        session_id=session_id,
        task=case.task,
        screenshot_path=case.screenshot,
    )
    
    assert response.action is not None, f"No action returned for {case.name}"
    assert response.action.type == case.expected_action
    assert response.confidence >= 0.5, f"Low confidence: {response.confidence}"
    
    if case.expected_target:
        for key, val in case.expected_target.items():
            assert key in response.action.dict() or val in str(response.action.dict())
```

#### 3. Structured Result Reporting

**Why**: The harness returns raw dicts with string statuses. No way to aggregate accuracy, cost, or latency across runs.

```python
# backend/models/eval_result.py
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

class EvalResultStatus(str, Enum):
    SUCCESS = "success"
    ERROR_INFERENCE = "error_inference"
    ERROR_VALIDATION = "error_validation"
    ERROR_MAX_LOOPS = "error_max_loops"
    ERROR_TIMEOUT = "error_timeout"
    ERROR_BUDGET = "error_budget"

class EvalResult(BaseModel):
    session_id: str
    case_name: str
    status: EvalResultStatus
    action_type: Optional[str] = None
    confidence: float = 0.0
    inference_time_ms: int = 0
    total_cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls_count: int = 0
    loop_iterations: int = 0
    errors: list[str] = Field(default_factory=list)
    chain_length: int = 0
```

---

### P1 — High Priority (Improves Evaluation Quality)

#### 4. Per-Model Cost Tracking

**Why**: Running evals across providers (Claude, OpenAI, Gemini, Modal) without cost tracking makes optimization blind.

```python
# backend/utilities/cost_tracker.py
from dataclasses import dataclass, field
from threading import Lock

@dataclass
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    requests: int = 0
    total_latency_ms: int = 0

# Pricing per 1M tokens (input, output)
MODEL_PRICING = {
    "claude-3-5-sonnet": (3.0, 15.0),
    "gpt-4o": (2.5, 10.0),
    "gemini-1.5-pro": (3.5, 10.5),
    "Qwen/Qwen3.5-35B-A3B": (0.0, 0.0),  # Self-hosted
}

class CostTracker:
    def __init__(self):
        self._usage: dict[str, ModelUsage] = {}
        self._lock = Lock()
    
    def record(self, model: str, input_tokens: int, output_tokens: int, latency_ms: int):
        with self._lock:
            u = self._usage.setdefault(model, ModelUsage())
            u.input_tokens += input_tokens
            u.output_tokens += output_tokens
            u.requests += 1
            u.total_latency_ms += latency_ms
            pricing = MODEL_PRICING.get(model, (0.0, 0.0))
            u.cost_usd += (input_tokens * pricing[0] + output_tokens * pricing[1]) / 1_000_000
    
    def get_total_cost(self) -> float:
        return sum(u.cost_usd for u in self._usage.values())
    
    def get_summary(self) -> dict[str, ModelUsage]:
        return dict(self._usage)

# Singleton
cost_tracker = CostTracker()
```

#### 5. AbortController Pattern for Step Cancellation

**Why**: A hung model call or infinite loop currently blocks the entire session with no way to cancel.

```python
# backend/utilities/abort.py
import asyncio
from typing import Optional

class AbortController:
    def __init__(self):
        self._event = asyncio.Event()
    
    def abort(self):
        self._event.set()
    
    @property
    def is_aborted(self) -> bool:
        return self._event.is_set()
    
    async def check(self):
        """Raise if aborted. Call between iterations."""
        if self._event.is_set():
            raise AbortedError("Step was cancelled")

class AbortedError(Exception):
    pass
```

Usage in `main.py`:
```python
abort = AbortController()
sessions_abort[session_id] = abort

for loop_i in range(MAX_TOOL_LOOPS + 1):
    await abort.check()  # Clean exit point
    response = call_model(agent_req)
    await abort.check()
    # ...process response
```

#### 6. Typed Tool Interface with Input Validation

**Why**: Tools are currently dicts in `AGENT_TOOLS_OPENAI` and dispatched via string matching. No schema validation on tool inputs.

```python
# backend/tools/base.py
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import TypeVar, Generic, Optional

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT")

class ToolResult(BaseModel):
    data: str
    error: Optional[str] = None

class BaseTool(ABC, Generic[InputT]):
    name: str
    description: str
    input_model: type[InputT]
    
    @abstractmethod
    async def execute(self, input: InputT, context: dict) -> ToolResult:
        ...
    
    def validate_input(self, raw_args: dict) -> InputT:
        """Parse and validate tool input against the schema."""
        return self.input_model(**raw_args)
    
    @property
    def is_read_only(self) -> bool:
        return False
    
    @property
    def is_enabled(self) -> bool:
        return True
    
    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_model.model_json_schema(),
            },
        }
```

---

### P2 — Medium Priority (Robustness & Observability)

#### 7. Error Taxonomy with Structured Classification

Replace string-matching in `action_errors.py` with typed error categories:

```python
# backend/utilities/error_taxonomy.py
from enum import Enum

class ErrorCategory(str, Enum):
    PERMISSION_DENIED = "permission_denied"
    TARGET_NOT_FOUND = "target_not_found"
    TIMEOUT = "timeout"
    SCHEMA_VALIDATION = "schema_validation"
    ACTION_REJECTED = "action_rejected"
    INFERENCE_FAILURE = "inference_failure"
    TOOL_EXECUTION = "tool_execution"
    BUDGET_EXCEEDED = "budget_exceeded"
    MAX_LOOPS = "max_loops"

class ClassifiedError:
    def __init__(self, category: ErrorCategory, message: str, 
                 recoverable: bool = True, original: str = ""):
        self.category = category
        self.message = message
        self.recoverable = recoverable
        self.original = original

def classify_error(error: str, action_label: str) -> ClassifiedError:
    e = error.lower()
    if "permission" in e or "access denied" in e:
        return ClassifiedError(ErrorCategory.PERMISSION_DENIED, 
            f"Permission denied for {action_label}", recoverable=True, original=error)
    if "not found" in e or "no such" in e:
        return ClassifiedError(ErrorCategory.TARGET_NOT_FOUND,
            f"Target not found for {action_label}", recoverable=True, original=error)
    if "timed out" in e or "timeout" in e:
        return ClassifiedError(ErrorCategory.TIMEOUT,
            f"Timed out during {action_label}", recoverable=True, original=error)
    return ClassifiedError(ErrorCategory.TOOL_EXECUTION,
        f"Unknown error during {action_label}: {error}", recoverable=False, original=error)
```

#### 8. In-Memory Error Ring Buffer

Adopt Claude Code's pattern of a fixed-size ring buffer with per-turn watermarks:

```python
# backend/utilities/error_buffer.py
from collections import deque
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ErrorEntry:
    timestamp: datetime
    session_id: str
    error: str
    category: str

class ErrorBuffer:
    def __init__(self, maxlen: int = 100):
        self._buffer: deque[ErrorEntry] = deque(maxlen=maxlen)
    
    def record(self, session_id: str, error: str, category: str = "unknown"):
        self._buffer.append(ErrorEntry(
            timestamp=datetime.now(), session_id=session_id,
            error=error, category=category
        ))
    
    def get_watermark(self) -> ErrorEntry | None:
        return self._buffer[-1] if self._buffer else None
    
    def errors_since(self, watermark: ErrorEntry | None) -> list[str]:
        if watermark is None:
            return [e.error for e in self._buffer]
        all_errors = list(self._buffer)
        try:
            idx = all_errors.index(watermark)
            return [e.error for e in all_errors[idx + 1:]]
        except ValueError:
            return [e.error for e in all_errors]  # Watermark evicted, return all

error_buffer = ErrorBuffer()
```

#### 9. Structured Analytics Events

Replace `print()` / `log_entry()` with typed analytics events:

```python
# backend/utilities/analytics.py
from enum import Enum
from typing import Any

class EventType(str, Enum):
    STEP_START = "step_start"
    STEP_COMPLETE = "step_complete"
    TOOL_CALL = "tool_call"
    ACTION_DISPATCHED = "action_dispatched"
    ACTION_REJECTED = "action_rejected"
    COMPACTION_TRIGGERED = "compaction_triggered"
    VALIDATION_ERROR = "validation_error"
    INFERENCE_ERROR = "inference_error"

_sink = None

def attach_sink(sink):
    global _sink
    _sink = sink

def log_event(event: EventType, metadata: dict[str, int | float | bool]):
    """Log structured event. Metadata must not contain strings (safety)."""
    if _sink:
        _sink.log(event.value, metadata)
    # Always log to conversation log as fallback
```

---

### P3 — Nice to Have (Operational Excellence)

#### 10. Feature Flag System

```python
# backend/utilities/features.py
import os

_FEATURE_FLAGS = {
    "VCR_REPLAY": False,
    "COST_TRACKING": False,
    "OMNI_PARSER": True,
    "PLAN_REVIEW": True,
    "AUTO_COMPACT": True,
}

def feature(name: str) -> bool:
    env_key = f"EMU_FEATURE_{name}"
    env_val = os.environ.get(env_key)
    if env_val is not None:
        return env_val.lower() in ("1", "true", "yes")
    return _FEATURE_FLAGS.get(name, False)
```

#### 11. Session Transcript Persistence with Resume Support

Mirror Claude Code's `recordTranscript()` / `--resume` pattern:
- Write full message history to `.emu/sessions/<id>/transcript.json` after each turn
- Support `POST /agent/resume` that reloads transcript and continues from last turn
- Fire-and-forget writes for assistant messages (non-blocking), awaited for user messages

#### 12. Tool `buildTool()` Factory Pattern

Adopt Claude Code's pattern of safe defaults:
```python
# backend/tools/builder.py
TOOL_DEFAULTS = {
    "is_enabled": lambda: True,
    "is_read_only": lambda _: False,
    "is_destructive": lambda _: False,
}

def build_tool(definition: dict) -> dict:
    """Apply safe defaults to a tool definition."""
    return {**TOOL_DEFAULTS, **definition}
```

---

## Patterns from Claude Code Worth Adopting Directly

| Pattern | Source File | What It Does | Priority |
|---|---|---|---|
| **VCR fixture system** | `services/vcr.ts` | Deterministic test replay with dehydration/hydration | P0 |
| **QueryEngine class** | `QueryEngine.ts` | Stateful async-generator query lifecycle with typed SDKMessage yields | P1 |
| **buildTool() factory** | `Tool.ts` | Safe defaults for tool properties (fail-closed for permissions/concurrency) | P2 |
| **Cost tracking singleton** | `cost-tracker.ts` | Per-model USD cost tracking with cache token accounting | P1 |
| **Analytics sink pattern** | `services/analytics/index.ts` | Event queue with deferred sink attachment; typed metadata (no string values) | P2 |
| **AbortController threading** | `QueryEngine.ts` | Clean cancellation through entire query lifecycle | P1 |
| **Structured result union** | `QueryEngine.ts` | Typed result subtypes (success, error_max_turns, error_max_budget_usd, etc.) | P0 |
| **Feature flag macros** | `tools.ts` | Compile-time dead code elimination via `feature()` | P3 |
| **Error ring buffer + watermark** | `QueryEngine.ts` + `utils/log.ts` | Turn-scoped error collection for diagnostics | P2 |
| **Task hierarchy** | `tasks/types.ts` + `Task.ts` | Typed task states (`TaskState` union), `isTerminalTaskStatus()` guards, `kill()` cleanup | P3 |
