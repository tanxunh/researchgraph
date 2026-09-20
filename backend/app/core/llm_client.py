from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings


class LLMClientError(Exception):
    """Raised when the LLM provider cannot return a valid answer."""

    def __init__(self, message: str, error_type: str = "llm_provider_error"):
        super().__init__(message)
        self.error_type = error_type


class LLMClient:
    """OpenAI-compatible chat completions client used by ResearchGraph."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        self._ensure_key()
        payload = self._payload(prompt, system_prompt)
        try:
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
                response = await client.post(self._chat_completions_url(), headers=self._headers(), json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMClientError(f"LLM request failed: HTTP {exc.response.status_code}.", "llm_provider_error") from exc
        except httpx.TimeoutException as exc:
            raise LLMClientError("LLM request timed out. Check network/model service or increase LLM_TIMEOUT_SECONDS.", "llm_timeout") from exc
        except httpx.RequestError as exc:
            raise LLMClientError("LLM network request failed.", "llm_network_error") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMClientError("LLM response is not valid JSON.", "invalid_model_response") from exc
        return self._extract_content(data)

    def generate_sync(self, prompt: str, system_prompt: str | None = None) -> str:
        self._ensure_key()
        payload = self._payload(prompt, system_prompt)
        try:
            with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                response = client.post(self._chat_completions_url(), headers=self._headers(), json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMClientError(f"LLM request failed: HTTP {exc.response.status_code}.", "llm_provider_error") from exc
        except httpx.TimeoutException as exc:
            raise LLMClientError("LLM request timed out. Check network/model service or increase LLM_TIMEOUT_SECONDS.", "llm_timeout") from exc
        except httpx.RequestError as exc:
            raise LLMClientError("LLM network request failed.", "llm_network_error") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMClientError("LLM response is not valid JSON.", "invalid_model_response") from exc
        return self._extract_content(data)

    def _ensure_key(self) -> None:
        if not self.settings.llm_api_key.strip():
            raise LLMClientError("LLM_API_KEY is not configured.", "llm_configuration_error")

    def _payload(self, prompt: str, system_prompt: str | None) -> dict[str, Any]:
        return {"model": self.settings.llm_model_id, "messages": self._build_messages(prompt, system_prompt), "temperature": 0.1}

    def _build_messages(self, prompt: str, system_prompt: str | None) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _chat_completions_url(self) -> str:
        base_url = self.settings.llm_base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.llm_api_key}", "Content-Type": "application/json"}

    def _extract_content(self, data: dict[str, Any]) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError("LLM response shape is invalid.", "invalid_model_response") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMClientError("LLM returned empty content.", "invalid_model_response")
        return content.strip()

    def _extract_error_detail(self, response: httpx.Response) -> str:
        try:
            body: Any = response.json()
        except ValueError:
            return response.text
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error)
            if error:
                return str(error)
            return str(body)
        return str(body)
