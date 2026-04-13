# Serve Qwen3.5-35B-A3B VLM with SGLang on Modal
#
# Qwen3.5-35B-A3B is a native vision-language model with 35B total parameters
# and only 3B activated per token (MoE: 256 experts, 8 routed + 1 shared).
# Uses Gated Delta Networks + full attention hybrid architecture.
#
# Usage:
#   modal run sglang_qwen35_vlm.py          # test
#   modal deploy sglang_qwen35_vlm.py       # deploy

import asyncio
import json
import subprocess
import time

import aiohttp
import modal
import modal.experimental

MINUTES = 60  # seconds

# --- Container Image ---
# SGLang v0.5.9 supports Qwen3.5 (GDN, MoE routing, mRoPE for vision)
sglang_image = (
    modal.Image.from_registry("lmsysorg/sglang:v0.5.9-cu129-amd64-runtime")
    .entrypoint([])
    .uv_pip_install("huggingface-hub==0.36.0")
)

# --- Model Configuration ---
# BF16 weights (~72GB). For FP8 (~35GB, single H100), use:
#   MODEL_NAME = "Qwen/Qwen3.5-35B-A3B-FP8"
#   MODEL_REVISION = "0b2752837483aa34b3db6e83e151b150c0e00e49"
#   GPU = "H100!:1", N_GPUS = 1
MODEL_NAME = "Qwen/Qwen3.5-35B-A3B"
MODEL_REVISION = "ec2d4ec"  # latest verified commit as of 2026-02-27

# --- GPU Configuration ---
# BF16 ~72GB: 2x H100 with TP=2
# FP8 ~35GB: 1x H100
GPU_TYPE = "H100!"
N_GPUS = 2
GPU = f"{GPU_TYPE}:{N_GPUS}"

# --- Volume Caching ---
HF_CACHE_VOL = modal.Volume.from_name("huggingface-cache", create_if_missing=True)
HF_CACHE_PATH = "/root/.cache/huggingface"

DG_CACHE_VOL = modal.Volume.from_name("deepgemm-cache", create_if_missing=True)
DG_CACHE_PATH = "/root/.cache/deepgemm"

sglang_image = sglang_image.env(
    {
        "HF_HUB_CACHE": HF_CACHE_PATH,
        "HF_XET_HIGH_PERFORMANCE": "1",
        "SGLANG_ENABLE_JIT_DEEPGEMM": "1",
    }
)


# --- DeepGEMM Compilation ---
def compile_deep_gemm():
    import os
    import subprocess

    if int(os.environ.get("SGLANG_ENABLE_JIT_DEEPGEMM", "1")):
        subprocess.run(
            f"python3 -m sglang.compile_deep_gemm "
            f"--model-path {MODEL_NAME} "
            f"--revision {MODEL_REVISION} "
            f"--tp {N_GPUS}",
            shell=True,
            check=True,
        )


sglang_image = sglang_image.run_function(
    compile_deep_gemm,
    volumes={DG_CACHE_PATH: DG_CACHE_VOL, HF_CACHE_PATH: HF_CACHE_VOL},
    gpu=GPU,
)

# --- Inference Server ---
REGION = "us"
PROXY_REGION = "us-east"
PORT = 8000
TARGET_INPUTS = 10
MIN_CONTAINERS = 0  # set to 1+ for always-warm replicas

app = modal.App(name="qwen35-35b-a3b-vlm")


@app.cls(
    image=sglang_image,
    gpu=GPU,
    volumes={HF_CACHE_PATH: HF_CACHE_VOL, DG_CACHE_PATH: DG_CACHE_VOL},
    region=REGION,
    min_containers=MIN_CONTAINERS,
    timeout=15 * MINUTES,
)
@modal.experimental.http_server(port=PORT, proxy_regions=[PROXY_REGION])
@modal.concurrent(target_inputs=TARGET_INPUTS)
class Qwen35VLM:
    @modal.enter()
    def startup(self):
        """Start SGLang server, wait for health, send warmup requests."""
        self.process = _start_server()
        wait_ready(self.process)
        warmup()

    @modal.exit()
    def stop(self):
        self.process.terminate()
        self.process.wait()


def _start_server() -> subprocess.Popen:
    """Launch SGLang server with Qwen3.5-optimized configuration."""
    cmd = [
        "python", "-m", "sglang.launch_server",
        "--model-path", MODEL_NAME,
        "--revision", MODEL_REVISION,
        "--served-model-name", MODEL_NAME,
        "--host", "0.0.0.0",
        "--port", f"{PORT}",
        "--tp", f"{N_GPUS}",
        "--cuda-graph-max-bs", f"{TARGET_INPUTS * 2}",
        "--enable-metrics",
        "--mem-fraction-static", "0.8",
        # 131K context is a good VRAM balance; Qwen3.5 supports 262K natively
        "--context-length", "131072",
        # Reasoning: enables <think> tag parsing for CoT
        "--reasoning-parser", "qwen3",
        # Tool calling
        "--tool-call-parser", "qwen3_coder",
        # MTP speculative decoding (native to Qwen3.5, no draft model needed)
        "--speculative-algo", "NEXTN",
        "--speculative-num-steps", "3",
        "--speculative-eagle-topk", "1",
        "--speculative-num-draft-tokens", "4",
    ]

    print("Starting SGLang server with command:")
    print(*cmd)
    return subprocess.Popen(" ".join(cmd), shell=True, start_new_session=True)


# --- Health Check & Warmup ---
def wait_ready(process: subprocess.Popen, timeout: int = 10 * MINUTES):
    import requests

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            check_running(process)
            requests.get(f"http://127.0.0.1:{PORT}/health").raise_for_status()
            return
        except (
            subprocess.CalledProcessError,
            requests.exceptions.ConnectionError,
            requests.exceptions.HTTPError,
        ):
            time.sleep(5)
    raise TimeoutError(f"SGLang server not ready within {timeout} seconds")


def check_running(p: subprocess.Popen):
    if (rc := p.poll()) is not None:
        raise subprocess.CalledProcessError(rc, cmd=p.args)


# Warmup payloads — exercise both text and vision pipelines
SAMPLE_IMAGE_PAYLOAD = {
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0c/GoldenGateBridge-001.jpg/1280px-GoldenGateBridge-001.jpg"
                    },
                },
                {"type": "text", "text": "Describe this image briefly."},
            ],
        }
    ],
    "max_tokens": 64,
}

SAMPLE_TEXT_PAYLOAD = {
    "messages": [{"role": "user", "content": "Hello, how are you?"}],
    "max_tokens": 16,
}


def warmup():
    import requests

    for payload in [SAMPLE_TEXT_PAYLOAD, SAMPLE_IMAGE_PAYLOAD]:
        for _ in range(2):
            requests.post(
                f"http://127.0.0.1:{PORT}/v1/chat/completions",
                json=payload,
                timeout=120,
            ).raise_for_status()


# --- Local Test Entrypoint ---
@app.local_entrypoint()
async def main(
    prompt: str = "Describe this image in detail. What do you see?",
    image_url: str = "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0c/GoldenGateBridge-001.jpg/1280px-GoldenGateBridge-001.jpg",
    text_only: bool = False,
):
    url = (await Qwen35VLM._experimental_get_flash_urls.aio())[0]

    if text_only:
        messages = [{"role": "user", "content": prompt}]
    else:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

    print(f"Sending request to {url}")
    if not text_only:
        print(f"  Image: {image_url}")
    print(f"  Prompt: {prompt}")
    print("---")

    response = await probe(url, messages, timeout=10 * MINUTES)
    print("\n---")
    print(f"Full response:\n{response}")


# --- Client Helpers ---
async def probe(url: str, messages: list, timeout: int = 5 * MINUTES) -> str:
    headers = {"Modal-Session-Id": "test-session"}
    deadline = time.time() + timeout
    async with aiohttp.ClientSession(base_url=url, headers=headers) as session:
        while time.time() < deadline:
            try:
                return await _send_request_streaming(session, messages)
            except asyncio.TimeoutError:
                await asyncio.sleep(1)
            except aiohttp.client_exceptions.ClientResponseError as e:
                if e.status == 503:
                    await asyncio.sleep(1)
                    continue
                raise
    raise TimeoutError(f"No response from server within {timeout} seconds")


async def _send_request_streaming(
    session: aiohttp.ClientSession, messages: list, timeout: int | None = None
) -> str:
    payload = {
        "messages": messages,
        "stream": True,
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 20,
        "presence_penalty": 1.5,
    }
    headers = {"Accept": "text/event-stream"}

    async with session.post(
        "/v1/chat/completions", json=payload, headers=headers, timeout=timeout
    ) as resp:
        resp.raise_for_status()
        full_text = ""
        chunk = ""

        async for raw in resp.content:
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            if not line.startswith("data:"):
                continue

            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break

            try:
                evt = json.loads(data)
            except json.JSONDecodeError:
                continue

            delta = (evt.get("choices") or [{}])[0].get("delta") or {}
            # Handle both regular content and reasoning_content (thinking mode)
            chunk += delta.get("content") or delta.get("reasoning_content") or ""

            if chunk and ("." in chunk or "\n" in chunk):
                print(chunk, end="", flush=True)
                full_text += chunk
                chunk = ""

        if chunk:
            print(chunk, end="", flush=True)
            full_text += chunk

        print()
        return full_text