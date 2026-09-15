"""Model backends.

One interface (:class:`LLMBackend`) with three implementations:

``openai``    OpenAI Responses/Chat API **and** every OpenAI-compatible gateway
              (DeepSeek, Moonshot, self-hosted proxies...). Selected when the
              model name looks like GPT/OSS or when ``OPENAI_BASE_URL`` is set.
``codebuddy`` Local CodeBuddy CLI gateway. This is the only reliable route to
              ``hy4-preview``: the same model id on a shared MaaS endpoint is a
              text-only deployment and the key-based CLI path 504s.
``offline``   Deterministic fallback so the pipeline can be tested without any
              credentials. Never pretend this is real analysis.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any

JSON_RETRY_SYSTEM = (
    "You repair JSON. Return ONLY the corrected JSON object, no prose, no Markdown fences. "
    "Keep the same keys and language; never invent values that you cannot recover from the broken text."
)


def extract_json(text: str) -> Any:
    """Best-effort JSON recovery from a model reply."""
    if not text:
        raise ValueError("empty model output")
    cleaned = text.strip()
    fence = re.search(r"```(?:json|JSON)?\s*(.*?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"model output is not JSON: {cleaned[:200]!r}")


class LLMBackendError(RuntimeError):
    pass


@dataclass
class GenOptions:
    max_output_tokens: int = 2400
    temperature: float = 0.2
    json_mode: bool = False


class LLMBackend:
    name = "base"

    def complete(self, system: str, user: str, options: GenOptions | None = None) -> str:
        raise NotImplementedError

    def complete_json(self, system: str, user: str, options: GenOptions | None = None) -> Any:
        options = options or GenOptions()
        options.json_mode = True
        raw = self.complete(system, user, options)
        try:
            return extract_json(raw)
        except ValueError:
            # One repair attempt is cheaper than losing a whole paper's analysis.
            repaired = self.complete(JSON_RETRY_SYSTEM, f"Broken output:\n{raw}\n\nReturn the corrected JSON only.", GenOptions(max_output_tokens=options.max_output_tokens, temperature=0.0))
            return extract_json(repaired)


class OpenAICompatBackend(LLMBackend):
    """Works with OpenAI, DeepSeek and any OpenAI-compatible gateway."""

    name = "openai"

    def __init__(self, model: str, base_url: str | None = None, api_key: str | None = None, timeout: float = 180.0, retries: int = 2, prefer_chat: bool = True):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise LLMBackendError("缺少 openai 依赖：pip install -e '.[openai]'") from exc
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise LLMBackendError(
                "未设置 OPENAI_API_KEY（DeepSeek 请设 OPENAI_BASE_URL=https://api.deepseek.com + DEEPSEEK_API_KEY）；"
                "也可改用其它后端，例如 --model hy4-preview --provider codebuddy"
            )
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.timeout = timeout
        self.retries = retries
        self.prefer_chat = prefer_chat
        kwargs: dict[str, Any] = {"api_key": self.api_key, "timeout": timeout}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self.client = OpenAI(**kwargs)

    def complete(self, system: str, user: str, options: GenOptions | None = None) -> str:
        options = options or GenOptions()
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                if self.prefer_chat:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                        temperature=options.temperature,
                        max_tokens=options.max_output_tokens,
                        response_format={"type": "json_object"} if options.json_mode else None,
                    )
                    return response.choices[0].message.content or ""
                response = self.client.responses.create(
                    model=self.model,
                    input=[{"role": "system", "content": [{"type": "input_text", "text": system}]}, {"role": "user", "content": [{"type": "input_text", "text": user}]}],
                    max_output_tokens=options.max_output_tokens,
                    temperature=options.temperature,
                )
                return getattr(response, "output_text", "") or ""
            except Exception as exc:  # transient gateway errors
                last_error = exc
                if attempt < self.retries:
                    time.sleep(2.0 * (attempt + 1))
                    continue
        raise LLMBackendError(f"OpenAI-compatible request failed: {last_error}")


class CodeBuddyBackend(LLMBackend):
    """Hy4-preview and friends through the locally authenticated CodeBuddy CLI."""

    name = "codebuddy"

    def __init__(self, model: str = "hy4-preview", timeout: int = 600, extra_args: list[str] | None = None):
        self.model = model
        self.timeout = timeout
        self.default_timeout = timeout  # the caller may shrink the live value
        self.extra_args = extra_args or []
        self.executable = shutil.which("codebuddy") or shutil.which("codebuddy.cmd")
        if not self.executable:
            raise LLMBackendError("未找到 codebuddy CLI；请先安装并通过 codebuddy 登录，或改用 openai provider")

    def complete(self, system: str, user: str, options: GenOptions | None = None) -> str:
        options = options or GenOptions()
        prompt = f"<system>\n{system}\n</system>\n\n<task>\n{user}\n</task>"
        if options.json_mode:
            prompt += "\n\n输出要求：只返回一个合法 JSON 对象，不要包裹 Markdown 代码块，不要输出解释文字。"
        cmd = [self.executable, "-p", "--model", self.model, *self.extra_args]
        try:
            completed = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise LLMBackendError(f"codebuddy CLI 超时（{self.timeout}s）") from exc
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()[-400:]
            raise LLMBackendError(f"codebuddy CLI 失败 code={completed.returncode}: {stderr}")
        text = completed.stdout or ""
        text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
        return text.strip()


class OfflineBackend(LLMBackend):
    """No-network backend used by tests and ``--offline`` runs."""

    name = "offline"

    def complete(self, system: str, user: str, options: GenOptions | None = None) -> str:
        return ""

    def complete_json(self, system: str, user: str, options: GenOptions | None = None) -> Any:
        # Minimal shape so downstream code paths stay type-correct.
        if "triage" in system:
            return {"results": []}
        return {}


def resolve_provider(model: str, explicit: str = "") -> str:
    if explicit and explicit != "auto":
        return explicit
    lowered = model.lower()
    if lowered.startswith("hy") or "codebuddy" in lowered:
        return "codebuddy"
    if "deepseek" in lowered or os.getenv("DEEPSEEK_API_KEY"):
        return "openai"
    if lowered.startswith(("gpt", "o1", "o3", "o4", "gpt-oss", "oss")):
        return "openai"
    if os.getenv("OPENAI_BASE_URL"):
        return "openai"
    return "codebuddy"


def build_backend(model: str, provider: str = "", offline: bool = False) -> LLMBackend:
    if offline:
        return OfflineBackend()
    kind = resolve_provider(model, provider)
    if kind == "codebuddy":
        return CodeBuddyBackend(model=model)
    if kind == "openai":
        return OpenAICompatBackend(model=model)
    raise LLMBackendError(f"未知的 provider: {kind}")
