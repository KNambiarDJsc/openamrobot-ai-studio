"""Optional LLM phrasing: Ollama directly, or a Strands Agents loop on an Ollama model.

The model never decides the status and never sees a tool that can act. It gets the deterministic
answer and may only restate it. Its output is accepted only if
  * it names the same status word and the same trace id, and
  * every number in it also appears in the deterministic answer.
Otherwise it is dropped and the deterministic answer stands alone. With no provider configured,
or the provider unreachable, the copilot works the same, without phrasing.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

import httpx

SYSTEM = (
    "You restate a robot diagnostics answer for an engineer in two or three sentences. Use only the facts in "
    "the answer. Keep the status word (READY, BLOCKED, UNKNOWN or ERROR) and the trace id exactly. Do not add "
    "numbers, causes, advice or capabilities that are not in the answer. Never offer to move or command the robot."
)

_NUM = re.compile(r"\d+(?:\.\d+)?")
_STATUS = re.compile(r"\b(READY|BLOCKED|UNKNOWN|ERROR|REFUSED)\b")
_TRACE = re.compile(r"diag-\d{4}-\d{2}-\d{2}-[0-9a-f]+")


def validate(model_text: str, deterministic: str) -> bool:
    if not model_text or not model_text.strip():
        return False
    status = _STATUS.search(deterministic)
    trace = _TRACE.search(deterministic)
    if status and status.group(1) not in model_text:
        return False
    if trace and trace.group(0) not in model_text:
        return False
    allowed = set(_NUM.findall(deterministic))
    return all(n in allowed for n in _NUM.findall(model_text))


def ollama_phraser(url: str, model: str, timeout_s: float = 20.0,
                   client: Optional[httpx.Client] = None) -> Callable[[str, str], tuple[Optional[str], str]]:
    c = client or httpx.Client(timeout=timeout_s)

    def phrase(question: str, text: str):
        try:
            r = c.post(f"{url.rstrip('/')}/api/chat", json={
                "model": model, "stream": False, "options": {"temperature": 0},
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": f"Question: {question}\n\nAnswer:\n{text}"}]})
            r.raise_for_status()
            out = r.json().get("message", {}).get("content", "").strip()
        except Exception:  # noqa: BLE001 - provider down: deterministic answer stands
            return None, "deterministic"
        return (out, "ollama") if validate(out, text) else (None, "deterministic")

    return phrase


def strands_phraser(url: str, model: str) -> Callable[[str, str], tuple[Optional[str], str]]:
    """Strands Agents with an Ollama model and no tools. Import-guarded: strands is optional."""
    try:
        from strands import Agent  # type: ignore
        from strands.models.ollama import OllamaModel  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("LLM_PROVIDER=strands needs `pip install 'strands-agents[ollama]'`") from e

    agent_model = OllamaModel(host=url, model_id=model)

    def phrase(question: str, text: str):
        try:
            agent = Agent(model=agent_model, system_prompt=SYSTEM, tools=[], callback_handler=None)
            out = str(agent(f"Question: {question}\n\nAnswer:\n{text}")).strip()
        except Exception:  # noqa: BLE001
            return None, "deterministic"
        return (out, "strands") if validate(out, text) else (None, "deterministic")

    return phrase


def make_phraser(provider: str, url: str, model: str):
    if provider in ("", "none"):
        return None
    if not model:
        raise RuntimeError(f"LLM_PROVIDER={provider} needs OLLAMA_MODEL")
    if provider == "ollama":
        return ollama_phraser(url, model)
    if provider == "strands":
        return strands_phraser(url, model)
    raise RuntimeError(f"unknown LLM_PROVIDER {provider!r} (none | ollama | strands)")
