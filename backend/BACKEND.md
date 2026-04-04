# Backend Architecture (v0.1) — Modal GPU Integration

This document details the backend architecture for the Emulation Agent, focusing on Modal as the GPU container service for hosting vision-language models.

---

## Table of Contents

1. [High-Level Architecture](#high-level-architecture)
2. [Agent Loop Flow](#agent-loop-flow)
3. [File Structure](#file-structure)
4. [Component Deep Dive](#component-deep-dive)
5. [Modal Integration](#modal-integration)
6. [API Contracts](#api-contracts)
7. [Data Flow Diagrams](#data-flow-diagrams)
8. [Configuration](#configuration)

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER MACHINE                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                     Electron Frontend (main.js)                      │   │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐   │   │
│  │  │  Chat UI    │◄──►│  IPC Bridge │◄──►│  Shell Process          │   │   │
│  │  │  (renderer) │    │  (actions/) │    │  (psProcess.js)         │   │   │
│  │  └─────────────┘    └──────┬──────┘    └─────────────────────────┘   │   │
│  │                            │                                          │   │
│  │                            │ HTTP                                     │   │
│  │                            ▼                                          │   │
│  │  ┌───────────────────────────────────────────────────────────────┐   │   │
│  │  │              Local FastAPI Backend (backend/main.py)          │   │   │
│  │  │  • Session management                                          │   │   │
│  │  │  • Screenshot storage                                          │   │   │
│  │  │  • Action logging                                              │   │   │
│  │  │  • Modal orchestration                                         │   │   │
│  │  └────────────────────────────┬──────────────────────────────────┘   │   │
│  └───────────────────────────────┼──────────────────────────────────────┘   │
│                                  │                                          │
└──────────────────────────────────┼──────────────────────────────────────────┘
                                   │ HTTPS
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MODAL GPU CLOUD                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Vision-Language Model Container                    │   │
│  │  ┌─────────────────┐    ┌──────────────────────────────────────────┐ │   │
│  │  │  Model Server   │◄──►│  Inference Engine (GPU-accelerated)     │ │   │
│  │  │  (modal_app.py) │    │  • Image understanding                   │ │   │
│  │  │                 │    │  • Reasoning generation                  │ │   │
│  │  │                 │    │  • Action prediction                     │ │   │
│  │  └─────────────────┘    └──────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Agent Loop Flow

The agent operates in a **closed-loop** fashion, where each iteration consists of:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           AGENT EXECUTION LOOP                               │
└──────────────────────────────────────────────────────────────────────────────┘

Step 1: USER INPUT
    User types message in chat UI
           │
           ▼
Step 2: CAPTURE STATE
    Electron captures full desktop screenshot via desktopCapturer
           │
           ▼
Step 3: BUILD REQUEST
    Backend constructs AgentRequest:
    {
        user_message:      "Open Notepad and type hello world"
        base64_screenshot: <current screen state>
        previous_messages: [prior reasoning + actions]
        step_index:        N
        ...
    }
           │
           ▼
Step 4: MODAL INFERENCE
    Request sent to Modal-hosted VLM
    Model processes: image + text context
           │
           ▼
Step 5: MODEL RESPONSE
    Modal returns AgentResponse:
    {
        reasoning: "I see the Windows desktop. I need to click Start menu..."
        action: {
            type: "left_click",
            coordinates: { x: 24, y: 1056 }
        }
        done: false
    }
           │
           ▼
Step 6: EXECUTE ACTION
    Backend sends action to Electron
    Shell executes: mouse move, click, type, scroll, etc via PowerShell Win32 API
           │
           ▼
Step 7: CAPTURE NEW STATE
    After action settles (~100-500ms delay), capture new screenshot
           │
           ▼
Step 8: LOOP OR TERMINATE
    If action.done == false:
        Append {reasoning, action, screenshot} to context
        Go to Step 3 with updated state
    Else:
        Return final response to user
```

### Detailed Sequence Diagram

```
User          Electron        Backend         Modal           Shell
 │               │               │               │               │
 │──"open calc"──►               │               │               │
 │               │               │               │               │
 │               │──screenshot───►               │               │
 │               │               │               │               │
 │               │               │───AgentReq────►               │
 │               │               │               │               │
 │               │               │◄──AgentRes────│               │
 │               │               │  (reasoning   │               │
 │               │               │   + action)   │               │
 │               │               │               │               │
 │               │◄──action──────│               │               │
 │               │               │               │               │
 │               │───────────────┼───────────────┼───ps.run()───►
 │               │               │               │               │
 │               │◄──────────────┼───────────────┼───done────────│
 │               │               │               │               │
 │               │──screenshot───►               │               │
 │               │               │               │               │
 │               │               │───AgentReq────►               │
 │               │               │  (+ prev ctx) │               │
 │               │               │               │               │
 │               │  ... loop continues ...       │               │
 │               │               │               │               │
 │◄──"Done!"─────│◄──────────────│◄──done:true───│               │
 │               │               │               │               │
```

---

## File Structure

```
emulation-agent/
│
├── backend/
│   ├── main.py                    # FastAPI server — local orchestrator
│   ├── modal_app.py               # Modal function definitions (GPU inference)
│   ├── modal_client.py            # Client for calling Modal endpoints
│   ├── models/
│   │   ├── __init__.py
│   │   ├── request.py             # AgentRequest Pydantic model
│   │   ├── response.py            # AgentResponse Pydantic model
│   │   └── actions.py             # Action type definitions
│   ├── services/
│   │   ├── __init__.py
│   │   ├── session.py             # Session state management
│   │   ├── context.py             # Conversation context builder
│   │   └── action_router.py       # Maps model output to frontend actions
│   ├── prompts/
│   │   ├── system.txt             # Base system prompt for the VLM
│   │   └── templates/             # Action-specific prompt templates
│   ├── emulation_screen_shots/    # Screenshot storage (gitignored)
│   └── requirements.txt
│
├── frontend/
│   ├── index.html                 # Main UI
│   ├── app.js                     # Renderer process entry
│   ├── components/
│   │   ├── index.js
│   │   ├── Button.js
│   │   ├── Message.js
│   │   ├── ChatInput.js
│   │   └── Sidebar.js
│   ├── actions/                   # IPC action handlers
│   │   ├── index.js               # Barrel export + registerAll
│   │   ├── screenshot.js          # Default screenshot (includes panel)
│   │   ├── fullCapture.js         # Full desktop capture (hides panel)
│   │   ├── navigate.js            # Mouse move
│   │   ├── leftClick.js           # Left click
│   │   ├── rightClick.js          # Right click
│   │   ├── leftClickOpen.js       # Double-click / open
│   │   ├── scroll.js              # Scroll up/down
│   │   └── window.js              # Window minimize/restore
│   └── process/
│       └── psProcess.js           # Persistent Shell subprocess
│
├── main.js                        # Electron main process
├── package.json
├── BACKEND.MD                     # This file
├── DOCUMENTATION.md
├── AGENTS.MD
└── README.md
```

---

## Component Deep Dive

### 1. Local FastAPI Backend (`backend/main.py`)

The local backend serves as the **orchestration layer** between the Electron frontend and Modal GPU service.

**Responsibilities:**
- Receive user messages from Electron UI
- Trigger screenshot capture
- Build `AgentRequest` payloads with full context
- Call Modal inference endpoint
- Parse `AgentResponse` and route actions back to frontend
- Maintain session state (conversation history, step count)
- Store screenshots for debugging/replay

**Key Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/agent/step` | POST | Main agent loop entry — accepts user message, orchestrates Modal call |
| `/agent/session` | POST | Create new session |
| `/agent/session/{id}` | GET | Retrieve session state |
| `/screenshot` | POST | Receive and store screenshot from Electron |
| `/action/complete` | POST | Electron notifies backend that action finished |

### 2. Modal GPU Service (`backend/modal_app.py`)

Runs on Modal's infrastructure with GPU acceleration.

**Responsibilities:**
- Load and serve the vision-language model
- Accept `AgentRequest` with image + text
- Run inference to produce reasoning + action
- Return structured `AgentResponse`

**Modal App Structure:**

```python
# backend/modal_app.py

import modal

app = modal.App("emulation-agent")

# Define the container image with model dependencies
image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "torch",
    "transformers",
    "accelerate",
    "pillow",
    "pydantic"
)

# GPU container class
@app.cls(
    image=image,
    gpu="A10G",  # or "A100" for larger models
    timeout=300,
    container_idle_timeout=120,
    secrets=[modal.Secret.from_name("hf-token")]  # HuggingFace token if needed
)
class AgentModel:
    @modal.enter()
    def load_model(self):
        """Load model weights on container startup (cached across invocations)."""
        from transformers import AutoModelForCausalLM, AutoProcessor

        self.processor = AutoProcessor.from_pretrained("model-name")
        self.model = AutoModelForCausalLM.from_pretrained(
            "model-name",
            torch_dtype=torch.float16,
            device_map="auto"
        )

    @modal.method()
    def infer(self, request: dict) -> dict:
        """Run single inference step."""
        # 1. Decode base64 screenshot
        # 2. Build prompt with context
        # 3. Run model forward pass
        # 4. Parse output into AgentResponse
        return response
```

### 3. Modal Client (`backend/modal_client.py`)

Local client for invoking Modal functions.

```python
# backend/modal_client.py

import modal
from .modal_app import AgentModel

async def call_agent_model(request: AgentRequest) -> AgentResponse:
    """Invoke Modal GPU function and return parsed response."""

    # Get reference to deployed Modal function
    model = modal.Cls.lookup("emulation-agent", "AgentModel")

    # Call the inference method
    result = await model.infer.remote.aio(request.model_dump())

    return AgentResponse(**result)
```

### 4. Session Management (`backend/services/session.py`)

Tracks conversation state across the agent loop.

```python
# backend/services/session.py

from dataclasses import dataclass, field
from typing import List
from datetime import datetime

@dataclass
class AgentSession:
    session_id: str
    user_message: str
    created_at: datetime = field(default_factory=datetime.utcnow)

    # Conversation history
    messages: List[dict] = field(default_factory=list)

    # Step tracking
    step_index: int = 0
    max_steps: int = 50

    # Screenshots for this session
    screenshots: List[str] = field(default_factory=list)  # file paths

    # Current state
    is_complete: bool = False
    final_response: str = None

class SessionManager:
    def __init__(self):
        self._sessions: dict[str, AgentSession] = {}

    def create(self, user_message: str) -> AgentSession:
        ...

    def get(self, session_id: str) -> AgentSession:
        ...

    def append_step(self, session_id: str, reasoning: str, action: dict, screenshot: str):
        ...

    def mark_complete(self, session_id: str, final_response: str):
        ...
```

### 5. Context Builder (`backend/services/context.py`)

Constructs the prompt context for each agent step.

```python
# backend/services/context.py

def build_agent_context(session: AgentSession, current_screenshot: str) -> AgentRequest:
    """
    Build the full context for a single agent step.

    Context structure (sent to Modal):
    - System prompt (static)
    - User's original message
    - For each previous step:
        - [IMAGE] Previous screenshot
        - [REASONING] Model's reasoning
        - [ACTION] Action taken
    - [IMAGE] Current screenshot (latest state)
    """

    previous_messages = []

    # System prompt
    previous_messages.append({
        "role": "system",
        "content": load_system_prompt()
    })

    # User's original instruction
    previous_messages.append({
        "role": "user",
        "content": session.user_message
    })

    # Previous steps (reasoning + actions)
    for step in session.messages:
        previous_messages.append({
            "role": "assistant",
            "content": f"[REASONING]\n{step['reasoning']}\n\n[ACTION]\n{step['action']}"
        })

    return AgentRequest(
        session_id=session.session_id,
        user_message=session.user_message,
        base64_screenshot=current_screenshot,
        previous_messages=previous_messages,
        step_index=session.step_index,
        max_steps=session.max_steps
    )
```

### 6. Action Router (`backend/services/action_router.py`)

Maps model output to frontend actions.

```python
# backend/services/action_router.py

from enum import Enum

class ActionType(str, Enum):
    LEFT_CLICK = "left_click"
    RIGHT_CLICK = "right_click"
    DOUBLE_CLICK = "double_click"
    MOUSE_MOVE = "mouse_move"
    SCROLL = "scroll"
    TYPE_TEXT = "type_text"
    KEY_PRESS = "key_press"
    WAIT = "wait"
    DONE = "done"

def route_action(action: dict) -> dict:
    """
    Convert model's action output to frontend-executable format.

    Model output example:
    {
        "type": "left_click",
        "coordinates": {"x": 100, "y": 200}
    }

    Frontend format:
    {
        "ipc_channel": "mouse:left-click",
        "params": {"x": 100, "y": 200}
    }
    """

    action_type = ActionType(action["type"])

    routing_table = {
        ActionType.LEFT_CLICK:   ("mouse:left-click",  ["x", "y"]),
        ActionType.RIGHT_CLICK:  ("mouse:right-click", ["x", "y"]),
        ActionType.DOUBLE_CLICK: ("mouse:double-click", ["x", "y"]),
        ActionType.MOUSE_MOVE:   ("mouse:move",        ["x", "y"]),
        ActionType.SCROLL:       ("mouse:scroll",      ["x", "y", "direction", "amount"]),
        ActionType.TYPE_TEXT:    ("keyboard:type",     ["text"]),
        ActionType.KEY_PRESS:    ("keyboard:key",      ["key", "modifiers"]),
        ActionType.WAIT:         ("system:wait",       ["ms"]),
        ActionType.DONE:         ("agent:done",        ["message"]),
    }

    channel, param_keys = routing_table[action_type]
    params = {k: action.get(k) or action.get("coordinates", {}).get(k) for k in param_keys}

    return {"ipc_channel": channel, "params": params}
```

---

## Modal Integration

### Setup Steps

1. **Install Modal CLI:**
   ```bash
   pip install modal
   modal token new
   ```

2. **Create Secrets (HuggingFace token if using gated models):**
   ```bash
   modal secret create hf-token HF_TOKEN=hf_xxx...
   ```

3. **Deploy the Modal App:**
   ```bash
   cd backend
   modal deploy modal_app.py
   ```

4. **Test Locally with Modal:**
   ```bash
   modal run modal_app.py::AgentModel.infer --request '{"user_message": "test"}'
   ```

### Modal App Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Modal Container Lifecycle                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. COLD START (first request or after idle timeout)                        │
│     ├── Container provisioned with GPU                                      │
│     ├── Image pulled (cached on Modal infra)                                │
│     ├── @modal.enter() runs: load model weights → GPU VRAM                  │
│     └── Ready for inference (~30-60s for large models)                      │
│                                                                             │
│  2. WARM INVOCATION (subsequent requests within idle window)                │
│     ├── Model already loaded in GPU memory                                  │
│     ├── Direct inference call                                               │
│     └── ~100-500ms latency depending on model size                          │
│                                                                             │
│  3. IDLE TIMEOUT (container_idle_timeout=120s by default)                   │
│     └── Container shut down, GPU released                                   │
│                                                                             │
│  4. SCALE TO ZERO                                                           │
│     └── No cost when not in use                                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### GPU Selection Guide

| Model Size | Recommended GPU | Modal Config | Approx. Cost |
|------------|-----------------|--------------|--------------|
| <7B params | T4 | `gpu="T4"` | $0.000164/sec |
| 7-13B params | A10G | `gpu="A10G"` | $0.000306/sec |
| 13-30B params | A100-40GB | `gpu="A100"` | $0.001036/sec |
| 30B+ params | A100-80GB | `gpu="A100-80GB"` | $0.001377/sec |

---

## API Contracts

### AgentRequest (Backend → Modal)

```python
class AgentRequest(BaseModel):
    # Core fields
    session_id:        str
    user_message:      str
    base64_screenshot: str            # PNG encoded as base64
    timestamp:         datetime

    # Conversation context
    previous_messages: list[PreviousMessage]

    # Task metadata
    task_id:    Optional[str]
    step_index: int                   # Current step (0-indexed)
    max_steps:  int                   # Hard limit

    # Screen metadata
    screen_dimensions: ScreenDimensions
    display_scale:     float          # DPI scaling factor

    # Environment
    os_platform: Literal["windows", "macos", "linux"]
```

### AgentResponse (Modal → Backend)

```python
class AgentResponse(BaseModel):
    # Reasoning (shown to user, used for context)
    reasoning: str

    # Action to execute
    action: Action

    # Completion flag
    done: bool

    # Optional final message when done=True
    final_message: Optional[str] = None

    # Confidence score (0-1) for action
    confidence: float = 1.0

    # Processing metadata
    inference_time_ms: int
    model_name: str

class Action(BaseModel):
    type: ActionType

    # For click/move actions
    coordinates: Optional[Coordinates] = None

    # For type actions
    text: Optional[str] = None

    # For key press actions
    key: Optional[str] = None
    modifiers: Optional[list[str]] = None

    # For scroll actions
    direction: Optional[Literal["up", "down"]] = None
    amount: Optional[int] = None

    # For wait actions
    ms: Optional[int] = None
```

### Frontend ↔ Backend (Electron IPC → FastAPI)

**Screenshot Capture:**
```json
POST /screenshot
{
    "image": "<base64-png>",
    "width": 1920,
    "height": 1080
}
```

**Agent Step Request:**
```json
POST /agent/step
{
    "session_id": "uuid-or-null-for-new",
    "user_message": "Open calculator"
}
```

**Agent Step Response (streamed or polled):**
```json
{
    "session_id": "abc-123",
    "step_index": 3,
    "reasoning": "I can see the Start menu is now open. I'll search for Calculator...",
    "action": {
        "ipc_channel": "keyboard:type",
        "params": {"text": "Calculator"}
    },
    "done": false
}
```

---

## Data Flow Diagrams

### Single Agent Step

```
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
│ Electron│    │ Backend │    │  Modal  │    │ Backend │    │ Electron│
│   UI    │    │ FastAPI │    │   GPU   │    │ FastAPI │    │   PS    │
└────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘
     │              │              │              │              │
     │──user msg───►│              │              │              │
     │              │              │              │              │
     │◄─screenshot──│              │              │              │
     │──req────────►│              │              │              │
     │              │              │              │              │
     │              │──AgentReq───►│              │              │
     │              │              │──inference──►│              │
     │              │              │◄─response────│              │
     │              │◄─AgentRes────│              │              │
     │              │              │              │              │
     │              │──────────────┼──route action┼─────────────►│
     │              │              │              │              │
     │              │◄─────────────┼──────────────┼──action done─│
     │              │              │              │              │
     │◄─reasoning───│              │              │              │
     │              │              │              │              │
```

### Complete Task Flow

```
                    ┌────────────────────────────────────────┐
                    │         TASK: "Open Calculator"        │
                    └────────────────────────────────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                      │
            ┌───────────────┐                              │
            │   STEP 0      │                              │
            │ screenshot_0  │                              │
            │ → click Start │                              │
            └───────┬───────┘                              │
                    │                                      │
                    ▼                                      │
            ┌───────────────┐                              │
            │   STEP 1      │                              │
            │ screenshot_1  │                              │
            │ → type "calc" │                              │
            └───────┬───────┘                              │
                    │                                context
                    ▼                               accumulates
            ┌───────────────┐                              │
            │   STEP 2      │                              │
            │ screenshot_2  │                              │
            │ → press Enter │                              │
            └───────┬───────┘                              │
                    │                                      │
                    ▼                                      │
            ┌───────────────┐                              │
            │   STEP 3      │◄─────────────────────────────┘
            │ screenshot_3  │  Context includes:
            │ → done: true  │  • Original user message
            └───────────────┘  • All prior screenshots
                               • All reasoning + actions
```

---

## Configuration

### Environment Variables

```bash
# backend/.env

# Modal
MODAL_TOKEN_ID=xxx
MODAL_TOKEN_SECRET=xxx
MODAL_APP_NAME=emulation-agent

# Model
MODEL_NAME=llava-hf/llava-1.5-13b-hf  # or your preferred VLM
MODEL_GPU=A10G
MODEL_TIMEOUT=300

# Local server
BACKEND_PORT=8000
SCREENSHOTS_DIR=./emulation_screen_shots

# Agent limits
MAX_STEPS_PER_TASK=50
STEP_TIMEOUT_MS=30000
ACTION_SETTLE_DELAY_MS=500
```

### Modal Configuration (`modal.toml`)

```toml
[settings]
environment = "main"

[secrets]
hf-token = "hf-token"  # Reference to Modal secret

[app.emulation-agent]
gpu = "A10G"
memory = 16384
timeout = 300
container_idle_timeout = 120
```

---

## Error Handling

### Retry Strategy

```python
# backend/services/modal_client.py

import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10)
)
async def call_modal_with_retry(request: AgentRequest) -> AgentResponse:
    try:
        return await call_agent_model(request)
    except modal.exception.TimeoutError:
        # Container cold start taking too long
        raise
    except Exception as e:
        logger.error(f"Modal call failed: {e}")
        raise
```

### Fallback Actions

If the model returns an invalid action or the confidence is too low:

```python
def handle_low_confidence_action(response: AgentResponse, threshold: float = 0.5):
    if response.confidence < threshold:
        return AgentResponse(
            reasoning="I'm not confident about the next action. Please provide more guidance.",
            action=Action(type=ActionType.DONE),
            done=True,
            confidence=1.0
        )
    return response
```

---

## Next Steps

1. **Implement `modal_app.py`** with your chosen vision-language model
2. **Add keyboard actions** (`type_text`, `key_press`) to `psProcess.js`
3. **Implement WebSocket** for real-time step updates to UI
4. **Add screenshot diffing** to detect when actions complete (vs. fixed delay)
5. **Implement action validation** (bounds checking, safety limits)
