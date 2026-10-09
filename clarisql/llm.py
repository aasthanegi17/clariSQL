"""One thin client for Gemini, OpenAI and Groq with strict JSON + Pydantic parsing."""
from __future__ import annotations

import os
import re
import time
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from .config import MODELS

T = TypeVar("T", bound=BaseModel)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _extract_json(text: str) -> str:
    """Strip markdown fences / chatter and return the outermost JSON object."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in model reply")
    return text[start : end + 1]


class LLMClient:
    def __init__(self, provider: str, model: str | None = None):
        provider = provider.lower()
        if provider not in MODELS:
            raise ValueError(f"Unknown provider '{provider}'. Choose from {list(MODELS)}")
        self.provider = provider
        self.model = model or MODELS[provider]
        self.last_latency = 0.0

        if provider == "gemini":
            from google import genai

            self._client = genai.Client(api_key=self._key("GEMINI_API_KEY"))
        elif provider == "openai":
            from openai import OpenAI

            self._client = OpenAI(api_key=self._key("OPENAI_API_KEY"))
        else:  # groq speaks the OpenAI protocol
            from openai import OpenAI

            self._client = OpenAI(api_key=self._key("GROQ_API_KEY"), base_url=GROQ_BASE_URL)

    @staticmethod
    def _key(name: str) -> str:
        key = os.getenv(name)
        if not key:
            raise RuntimeError(f"{name} is not set. Add it to your .env file.")
        return key

    # ------------------------------------------------------------------ raw call
    def _raw(self, system: str, messages: list[dict]) -> str:
        if self.provider == "gemini":
            from google.genai import types

            contents = [
                types.Content(
                    role="user" if m["role"] == "user" else "model",
                    parts=[types.Part(text=m["content"])],
                )
                for m in messages
            ]
            resp = self._client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    temperature=0,
                ),
            )
            return resp.text or ""

        kwargs = {}
        if self.provider == "groq":
            kwargs["temperature"] = 0
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, *messages],
            response_format={"type": "json_object"},
            **kwargs,
        )
        return resp.choices[0].message.content or ""

    # ------------------------------------------------------------- structured call
    def generate(self, system: str, messages: list[dict], schema_model: Type[T], retries: int = 1) -> T:
        """Call the model and return a validated Pydantic object.

        If the reply is not valid JSON / does not satisfy the model, the error is
        sent back to the LLM once so it can correct itself.
        """
        msgs = list(messages)
        start = time.perf_counter()
        for attempt in range(retries + 1):
            text = self._raw(system, msgs)
            try:
                obj = schema_model.model_validate_json(_extract_json(text))
                self.last_latency = time.perf_counter() - start
                return obj
            except (ValidationError, ValueError) as err:
                if attempt == retries:
                    raise
                msgs += [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": f"Your reply was invalid ({err}). Reply again with valid JSON only."},
                ]
        raise RuntimeError("unreachable")
