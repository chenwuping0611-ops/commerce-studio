import io
import hashlib
import json
import mimetypes
import os
import threading
import uuid
from types import SimpleNamespace
from urllib.parse import quote, unquote, urlparse, urlsplit, urlunsplit

import requests
from flask import current_app, has_app_context
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .provider_catalog import (
    KUAIPAO_IMAGE_EDIT_URL,
    KUAIPAO_IMAGE_GENERATION_URL,
    KUAIPAO_IMAGE_API_MODEL_CODES,
    KUAIPAO_IMAGE_MODEL_CODE,
    KUAIPAO_LEGACY_IMAGE_MODEL_CODES,
    KuaipaoCatalog,
    kuaipao_image_api_model_code,
    provider_catalog_key,
)


class ProviderRequestError(Exception):
    """Normalized upstream request error with an optional response payload."""

    def __init__(
        self,
        message,
        status_code=None,
        payload=None,
        request_id=None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.payload = redact_provider_payload(payload)
        self.request_id = request_id


BALANCE_FIELDS = (
    "remain_balance",
    "used_balance",
    "remain_credits",
    "used_credits",
    "credits_per_usd",
    "unlimited_quota",
)

GPT5_COMPLETION_MODEL_CODES = frozenset(
    {
        "gpt-5.4",
        "gpt-5.5",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    }
)

GPT56_MODEL_CODES = frozenset(
    {
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    }
)

# GPT-5.x supports up to 128000 output tokens. Responses uses the
# max_output_tokens field; Chat Completions uses max_completion_tokens.
GPT_MAX_OUTPUT_TOKENS = 128000

_SENSITIVE_PAYLOAD_KEYS = frozenset(
    {
        "password",
        "oldpassword",
        "newpassword",
        "confirmpassword",
        "apikey",
        "authkey",
        "accesstoken",
        "refreshtoken",
        "clientsecret",
        "privatekey",
        "token",
        "secret",
        "authorization",
    }
)

_LARGE_PAYLOAD_KEYS = frozenset(
    {
        "b64json",
        "base64",
        "basedata",
        "base64data",
        "datauri",
        "imagebytes",
        "videobytes",
        "binary",
        "contentbytes",
    }
)


def _payload_value_size(value):
    if isinstance(value, (bytes, bytearray)):
        return len(value)
    return len(str(value).encode("utf-8"))

# Responses only continues a prior model interaction when the caller supplies
# an explicit conversation/previous-response reference. Keep these aliases
# out of every application request so a provider configuration cannot
# accidentally turn a one-shot operation into a shared conversation.
_CONVERSATION_STATE_FIELDS = frozenset(
    {
        "conversation",
        "conversation_id",
        "previous_response_id",
        "response_id",
        "session_id",
        "thread_id",
        "chat_id",
    }
)


def redact_provider_payload(value):
    """Remove credentials and large binary fields from provider snapshots."""

    if isinstance(value, list):
        return [redact_provider_payload(item) for item in value]
    if not isinstance(value, dict):
        return value
    redacted = {}
    for key, item in value.items():
        normalized = str(key).replace("-", "").replace("_", "").lower()
        if normalized in _SENSITIVE_PAYLOAD_KEYS:
            redacted[key] = "[REDACTED]"
        elif normalized in _LARGE_PAYLOAD_KEYS:
            redacted[key] = (
                "[BINARY_PAYLOAD_OMITTED:%s_BYTES]"
                % _payload_value_size(item)
            )
        else:
            redacted[key] = redact_provider_payload(item)
    return redacted


def _find_balance_object(payload):
    """Find the first response object containing ToAPIs balance fields."""

    if isinstance(payload, dict):
        if any(field in payload for field in BALANCE_FIELDS):
            return payload
        for value in payload.values():
            found = _find_balance_object(value)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_balance_object(value)
            if found is not None:
                return found
    return None


def normalize_balance(payload):
    """Return a stable balance summary while retaining unknown relay fields."""

    payload = redact_provider_payload(payload)
    balance = _find_balance_object(payload)
    if balance is None:
        return {"available": False, "raw": payload}

    summary = {
        "available": True,
        "remain_balance": balance.get("remain_balance"),
        "used_balance": balance.get("used_balance"),
        "remain_credits": balance.get("remain_credits"),
        "used_credits": balance.get("used_credits"),
        "credits_per_usd": balance.get("credits_per_usd"),
        "unlimited_quota": bool(balance.get("unlimited_quota", False)),
    }
    return summary


def extract_chat_content(payload):
    """Extract assistant text from Chat Completions or Responses payloads."""

    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0] or {}
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text:
                        parts.append(str(text))
            return "\n".join(parts).strip()
        if choice.get("text"):
            return str(choice["text"]).strip()
    for key in ("output_text", "text", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    output = payload.get("output")
    if isinstance(output, list):
        parts = []
        for item in output:
            if not isinstance(item, dict):
                continue
            value = item.get("text")
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
            content = item.get("content")
            if isinstance(content, str) and content.strip():
                parts.append(content.strip())
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, str) and part.strip():
                        parts.append(part.strip())
                    elif isinstance(part, dict):
                        text = part.get("text") or part.get("value")
                        if isinstance(text, str) and text.strip():
                            parts.append(text.strip())
        if parts:
            return "\n".join(parts).strip()
    return ""


def is_responses_path(path):
    """Return whether an endpoint is an OpenAI Responses-compatible path."""

    return str(path or "").rstrip("/").lower().endswith("/responses")


class ProviderClient:
    """Compatibility entry point for provider-specific HTTP clients.

    Existing callers can keep constructing ``ProviderClient(provider)``.
    The entry point selects the code-owned client for known providers, while
    direct subclasses remain available for tests and explicit integrations.
    """

    def __new__(cls, provider, *args, **kwargs):
        if cls is ProviderClient:
            client_class = provider_client_class(provider)
            if client_class is not ProviderClient:
                return object.__new__(client_class)
        return object.__new__(cls)

    _session_local = threading.local()

    @classmethod
    def _shared_session(cls, provider):
        config = current_app.config if has_app_context() else {}
        pool_size = max(
            1,
            int(
                config.get("STUDIO_HTTP_POOL_SIZE")
                or os.getenv("STUDIO_HTTP_POOL_SIZE")
                or 10
            ),
        )
        retry_total = max(
            0,
            int(
                config.get("STUDIO_HTTP_MAX_RETRIES")
                or os.getenv("STUDIO_HTTP_MAX_RETRIES")
                or 2
            ),
        )
        api_key_digest = hashlib.sha256(
            str(provider.api_key or "").encode("utf-8")
        ).hexdigest()
        key = (
            str(provider.base_url or "").rstrip("/"),
            api_key_digest,
            pool_size,
            retry_total,
        )
        cache = getattr(cls._session_local, "sessions", None)
        if cache is None:
            cache = {}
            cls._session_local.sessions = cache
        session = cache.get(key)
        if session is not None:
            return session

        session = requests.Session()
        retry = Retry(
            total=retry_total,
            connect=retry_total,
            read=retry_total,
            backoff_factor=0.6,
            status_forcelist=(408, 425, 429, 500, 502, 503, 504),
            # Model submission is POST and may charge or enqueue work.
            allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            pool_connections=pool_size,
            pool_maxsize=pool_size,
            pool_block=True,
            max_retries=retry,
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        # Bound the per-thread cache so rotating department keys cannot grow
        # without limit in a long-lived worker.
        if len(cache) >= 16:
            cache.pop(next(iter(cache)))
        cache[key] = session
        return session

    def __init__(self, provider):
        # Materialize settings immediately so a long HTTP request never
        # triggers lazy SQLAlchemy reads or keeps a DB connection checked out.
        self.provider = SimpleNamespace(
            base_url=provider.base_url,
            api_key=provider.api_key,
            generation_path=provider.generation_path,
            result_path=provider.result_path,
            balance_path=provider.balance_path,
            token_balance_path=getattr(provider, "token_balance_path", None),
            auth_header=getattr(provider, "auth_header", None),
            auth_prefix=getattr(provider, "auth_prefix", None),
            timeout=provider.timeout,
        )
        self.session = self._shared_session(self.provider)

    def _url(self, path):
        base = (self.provider.base_url or "").rstrip("/")
        path = path or ""
        if str(path).lower().startswith(("http://", "https://")):
            return str(path)
        if not path.startswith("/"):
            path = "/" + path
        base_path = urlsplit(base).path.rstrip("/")
        parsed_path = urlsplit(path)
        if base_path and (
            parsed_path.path == base_path
            or parsed_path.path.startswith(base_path + "/")
        ):
            path = urlunsplit(
                (
                    "",
                    "",
                    parsed_path.path[len(base_path) :] or "/",
                    parsed_path.query,
                    parsed_path.fragment,
                )
            )
        return base + path

    def _headers(self):
        headers = {
            "Accept": "application/json",
            "User-Agent": "commerce-studio/0.1",
        }
        api_key = (self.provider.api_key or "").strip()
        if api_key:
            header_name = (getattr(self.provider, "auth_header", None) or "Authorization").strip()
            prefix = (getattr(self.provider, "auth_prefix", None) or "").strip()
            # Users sometimes paste the complete "Bearer <token>" value.
            # Avoid sending "Bearer Bearer <token>" to the upstream API.
            if prefix and api_key.lower().startswith(prefix.lower() + " "):
                api_key = api_key[len(prefix):].strip()
            headers[header_name] = f"{prefix} {api_key}".strip() if prefix else api_key
        return headers

    @staticmethod
    def _fresh_chat_body(body):
        """Return a stateless Chat Completions request without mutating input."""

        request_body = dict(body or {})
        for field in _CONVERSATION_STATE_FIELDS:
            request_body.pop(field, None)
        # ``store`` is not needed for Chat Completions and some compatible
        # relays reject it as an unknown field. The messages supplied by the
        # application are built for one operation only.
        request_body.pop("store", None)
        return request_body

    @staticmethod
    def _fresh_responses_body(body):
        """Return a new, non-persistent Responses request."""

        request_body = dict(body or {})
        for field in _CONVERSATION_STATE_FIELDS:
            request_body.pop(field, None)
        # Do not retain the response on the provider side. More importantly,
        # no previous_response_id or conversation reference is sent, so this
        # request cannot continue an earlier model conversation.
        request_body["store"] = False
        return request_body

    def _request(self, method, path, body=None):
        url = self._url(path)
        headers = self._headers()
        request_id = "commerce-studio-" + uuid.uuid4().hex
        headers["X-Client-Request-Id"] = request_id
        if body is not None:
            headers["Content-Type"] = "application/json"
        timeout = (10, max(int(self.provider.timeout or 120), 30))
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                json=body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise ProviderRequestError(
                f"供应商网络请求失败：{exc}",
                request_id=request_id,
            ) from exc

        try:
            payload = response.json()
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {"raw": response.text[:4000]}
        response.close()

        if not 200 <= response.status_code < 300:
            message = self._error_message(payload, response.status_code)
            raise ProviderRequestError(
                message,
                response.status_code,
                payload,
                request_id=request_id,
            )
        return payload

    def _multipart_request(self, method, path, data=None, files=None):
        """Send multipart form data without overriding requests' boundary."""

        url = self._url(path)
        headers = self._headers()
        request_id = "commerce-studio-" + uuid.uuid4().hex
        headers["X-Client-Request-Id"] = request_id
        timeout = (10, max(int(self.provider.timeout or 120), 30))
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                data=data,
                files=files,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise ProviderRequestError(
                f"供应商网络请求失败：{exc}",
                request_id=request_id,
            ) from exc

        status_code = response.status_code
        try:
            payload = response.json()
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {"raw": response.text[:4000]}
        response.close()

        if not 200 <= status_code < 300:
            message = self._error_message(payload, status_code)
            raise ProviderRequestError(
                message,
                status_code,
                payload,
                request_id=request_id,
            )
        return payload

    def _download_reference_image(self, url, index):
        """Download one public reference image without provider credentials."""

        target = str(url or "").strip()
        parsed = urlparse(target)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ProviderRequestError(
                f"参考图 {index} 必须是公开的 http(s) 图片地址"
            )

        timeout = (10, max(int(self.provider.timeout or 120), 60))
        response = None
        try:
            # This request intentionally uses no Authorization header. The
            # provider key belongs only on the Kuaipao image request.
            response = requests.get(
                target,
                headers={"Accept": "image/*"},
                timeout=timeout,
            )
            response.raise_for_status()
            image_bytes = response.content
            content_type = (
                response.headers.get("Content-Type") or ""
            ).split(";", 1)[0].strip().lower()
        except requests.RequestException as exc:
            raise ProviderRequestError(
                f"参考图 {index} 下载失败：{exc}"
            ) from exc
        finally:
            if response is not None:
                response.close()

        filename = unquote(os.path.basename(parsed.path)) or (
            f"reference_{index}.jpg"
        )
        filename = filename.replace("\x00", "") or f"reference_{index}.jpg"
        guessed_type, guessed_encoding = mimetypes.guess_type(filename)
        if guessed_encoding:
            guessed_type = None
        if not content_type or content_type == "application/octet-stream":
            content_type = guessed_type or "image/jpeg"
        if not content_type.startswith("image/"):
            raise ProviderRequestError(
                f"参考图 {index} 不是受支持的图片文件"
            )
        if "." not in filename:
            extension = mimetypes.guess_extension(content_type) or ".jpg"
            filename += extension
        return image_bytes, filename, content_type

    @staticmethod
    def _error_message(payload, status_code):
        payload = redact_provider_payload(payload)
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return error.get("message") or error.get("code") or str(error)
            return payload.get("message") or payload.get("msg") or str(payload)
        return f"供应商返回 HTTP {status_code}"

    def submit_generation(self, model, body):
        path = model.generation_path or self.provider.generation_path
        return self._request("POST", path, body)

    def chat_completion(self, model, body):
        """Call a configured OpenAI-compatible chat/vision model."""

        path = model.generation_path or "/v1/chat/completions"
        request_body = self._fresh_chat_body(body)
        model_code = str(getattr(model, "model_code", "") or "").strip().lower()
        if model_code in GPT5_COMPLETION_MODEL_CODES:
            if (
                request_body.get("max_completion_tokens") is None
                and request_body.get("max_tokens") is not None
            ):
                request_body["max_completion_tokens"] = request_body["max_tokens"]
            request_body.pop("max_tokens", None)
            request_body.pop("max_output_tokens", None)
            max_completion_tokens = request_body.get("max_completion_tokens")
            if max_completion_tokens not in (None, ""):
                try:
                    request_body["max_completion_tokens"] = min(
                        max(int(max_completion_tokens), 1),
                        GPT_MAX_OUTPUT_TOKENS,
                    )
                except (TypeError, ValueError):
                    request_body.pop("max_completion_tokens", None)
        if model_code in GPT56_MODEL_CODES:
            request_body.pop("temperature", None)
            request_body.pop("top_p", None)
            request_body.setdefault("reasoning_effort", "medium")
        return self._request("POST", path, request_body)

    @staticmethod
    def _responses_content_part(part):
        if isinstance(part, str):
            return {"type": "input_text", "text": part}
        if not isinstance(part, dict):
            return None

        part_type = str(part.get("type") or "").strip()
        if part_type in ("input_text", "input_file", "input_image"):
            return part
        if part_type == "text":
            return {
                "type": "input_text",
                "text": str(part.get("text") or ""),
            }
        if part_type == "image_url":
            image = part.get("image_url")
            image_url = (
                image.get("url")
                if isinstance(image, dict)
                else image
            )
            if image_url:
                return {
                    "type": "input_image",
                    "image_url": image_url,
                }
        if part_type == "video_url":
            video = part.get("video_url")
            video_url = (
                video.get("url")
                if isinstance(video, dict)
                else video
            )
            if video_url:
                return {
                    "type": "input_text",
                    "text": "视频参考地址：" + str(video_url),
                }
        if part.get("text") not in (None, ""):
            return {
                "type": "input_text",
                "text": str(part.get("text")),
            }
        return None

    @classmethod
    def _chat_body_to_responses(cls, body):
        """Translate the existing chat payload into Responses input syntax."""

        body = dict(body or {})
        messages = body.get("messages") or []
        instructions = body.get("instructions") or ""
        input_messages = []

        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "user").strip().lower()
            content = message.get("content")
            if role in ("system", "developer"):
                if isinstance(content, list):
                    content = "\n".join(
                        str(item.get("text") or item)
                        if isinstance(item, dict)
                        else str(item)
                        for item in content
                    )
                if content:
                    instructions = "\n\n".join(
                        item for item in (instructions, str(content)) if item
                    )
                continue

            parts = content if isinstance(content, list) else [content]
            converted = [
                converted
                for part in parts
                if (converted := cls._responses_content_part(part))
            ]
            if converted:
                input_messages.append(
                    {
                        "role": role if role in ("user", "assistant") else "user",
                        "content": converted,
                    }
                )

        response_body = {
            "model": body.get("model"),
            "input": input_messages,
        }
        if instructions:
            response_body["instructions"] = instructions
        if body.get("tools") is not None:
            response_body["tools"] = body["tools"]
        if body.get("max_output_tokens") is not None:
            response_body["max_output_tokens"] = body["max_output_tokens"]
        elif body.get("max_completion_tokens") is not None:
            response_body["max_output_tokens"] = body["max_completion_tokens"]
        elif body.get("max_tokens") is not None:
            response_body["max_output_tokens"] = body["max_tokens"]
        # Responses models such as GPT-5 may reject Chat Completions-only
        # sampling fields. Keep the relay request close to the native
        # Responses shape and only carry provider-neutral metadata controls.
        for key in ("metadata", "store"):
            if body.get(key) is not None:
                response_body[key] = body[key]
        return {
            key: value
            for key, value in response_body.items()
            if value not in (None, "", [])
        }

    def responses_create(self, model, body):
        """Call a configured OpenAI-compatible Responses API model."""

        path = model.generation_path or self.provider.generation_path or "/v1/responses"
        request_body = (
            body
            if "input" in (body or {})
            else self._chat_body_to_responses(body)
        )
        request_body = self._fresh_responses_body(request_body)
        return self._request("POST", path, request_body)

    def complete(self, model, body):
        """Dispatch Chat Completions or Responses by the model endpoint."""

        path = (
            getattr(model, "generation_path", None)
            or self.provider.generation_path
            or "/v1/chat/completions"
        )
        if is_responses_path(path):
            return self.responses_create(model, body)
        return self.chat_completion(model, body)

    def fetch_generation_result(self, model, task_id, media_type):
        path = model.result_path or self.provider.result_path
        if not path:
            path = (
                "/v1/videos/generations/{task_id}"
                if media_type == "VIDEO"
                else "/v1/images/generations/{task_id}"
            )
        if "{task_id}" in path:
            path = path.replace("{task_id}", quote(str(task_id), safe=""))
        else:
            path = path.rstrip("/") + "/" + quote(str(task_id), safe="")
        return self._request("GET", path)

    def get_balance(self, scope="user"):
        if scope == "token":
            path = getattr(self.provider, "token_balance_path", None) or "/v1/balance"
        else:
            path = self.provider.balance_path or "/v1/user/balance"
        payload = self._request("GET", path)
        if isinstance(payload, dict) and payload.get("success") is False:
            message = payload.get("message") or payload.get("msg") or "余额查询失败"
            raise ProviderRequestError(str(message), payload=payload)
        return payload


class ToApisClient(ProviderClient):
    """Client for the code-owned ToAPIs image, video, and chat contracts."""

    provider_key = "toapis"

    def complete(self, model, body):
        path = (
            getattr(model, "generation_path", None)
            or self.provider.generation_path
            or "/v1/chat/completions"
        )
        if is_responses_path(path):
            raise ProviderRequestError(
                "ToAPIs 语言模型必须使用 Chat Completions 接口"
            )
        return self.chat_completion(model, body)


class KuaipaoClient(ProviderClient):
    """Client for Kuaipao Responses text and multipart image models."""

    provider_key = "kuaipao"
    model_codes = frozenset(KuaipaoCatalog.MODEL_CODES)
    image_model_codes = frozenset(KuaipaoCatalog.IMAGE_MODEL_CODES)
    legacy_image_model_codes = frozenset(KUAIPAO_LEGACY_IMAGE_MODEL_CODES)
    all_image_model_codes = image_model_codes | legacy_image_model_codes
    default_model_code = "gpt-5.4"
    responses_path = "/responses"

    def submit_generation(self, model, body):
        media_type = str(
            getattr(model, "media_type", "") or ""
        ).strip().upper()
        model_code = str(
            getattr(model, "model_code", "") or ""
        ).strip()
        if media_type == "IMAGE" or model_code in self.image_model_codes:
            if model_code not in self.all_image_model_codes:
                raise ProviderRequestError(
                    "快跑AI图片模型不在系统模型目录中"
                )
            return self._submit_image_generation(model, body)
        raise ProviderRequestError(
            "快跑AI当前只支持图片模型和文本 Responses 模型"
        )

    @staticmethod
    def _reference_urls(body):
        references = body.get("reference_images")
        if references in (None, "", []):
            references = body.get("image_urls")
        if references in (None, "", []):
            return []
        if isinstance(references, str):
            try:
                parsed = json.loads(references)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = [
                    item.strip()
                    for item in references.replace(",", "\n").splitlines()
                    if item.strip()
                ]
            references = parsed
        if not isinstance(references, (list, tuple)):
            references = [references]
        result = []
        for item in references:
            value = (
                item.get("url")
                if isinstance(item, dict)
                else item
            )
            value = str(value or "").strip()
            if value:
                result.append(value)
        return list(dict.fromkeys(result))

    @staticmethod
    def _multipart_value(value):
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _submit_image_generation(self, model, body):
        request_body = dict(body or {})
        model_code = str(
            getattr(model, "model_code", "") or ""
        ).strip().lower()
        request_code = str(request_body.get("model") or "").strip().lower()
        api_model_codes = {
            str(code).strip().lower()
            for code in KUAIPAO_IMAGE_API_MODEL_CODES.values()
        }
        if model_code == KUAIPAO_IMAGE_MODEL_CODE:
            requested_resolution = request_body.get("resolution")
            expected_api_code = (
                kuaipao_image_api_model_code(requested_resolution)
                if requested_resolution not in (None, "")
                else None
            )
            if request_code in api_model_codes:
                if expected_api_code and request_code != expected_api_code:
                    raise ProviderRequestError(
                        "快跑AI图片分辨率与请求模型不一致"
                    )
                request_body["model"] = request_code
            elif request_code in ("", KUAIPAO_IMAGE_MODEL_CODE):
                request_body["model"] = (
                    expected_api_code
                    or kuaipao_image_api_model_code("1k")
                )
            else:
                raise ProviderRequestError(
                    "快跑AI请求模型与已选择的图片模型不一致"
                )
        elif model_code in self.legacy_image_model_codes:
            if request_code and request_code != model_code:
                raise ProviderRequestError(
                    "快跑AI请求模型与已选择的模型不一致"
                )
            request_body["model"] = model_code
        else:
            raise ProviderRequestError("快跑AI图片模型不在系统模型目录中")
        references = self._reference_urls(request_body)
        request_body.pop("reference_images", None)
        request_body.pop("image_urls", None)
        request_body.pop("resolution", None)
        request_body.pop("response_format", None)

        if not references:
            # Keep the no-reference path JSON based so a prompt-only image
            # request does not need to construct an empty multipart body.
            return self._request(
                "POST",
                KUAIPAO_IMAGE_GENERATION_URL,
                {
                    key: value
                    for key, value in request_body.items()
                    if value not in (None, "", [], {})
                },
            )

        files = []
        handles = []
        try:
            for index, reference_url in enumerate(references, start=1):
                image_bytes, filename, content_type = (
                    self._download_reference_image(
                        reference_url,
                        index,
                    )
                )
                handle = io.BytesIO(image_bytes)
                handles.append(handle)
                # Repeating the same multipart field is required by the
                # Kuaipao image edit endpoint for multiple references.
                files.append(
                    (
                        "image",
                        (filename, handle, content_type),
                    )
                )
            data = {
                key: self._multipart_value(value)
                for key, value in request_body.items()
                if value not in (None, "", [], {})
            }
            path = (
                getattr(model, "generation_path", None)
                or KUAIPAO_IMAGE_EDIT_URL
            )
            return self._multipart_request(
                "POST",
                path,
                data=data,
                files=files,
            )
        finally:
            for handle in handles:
                handle.close()

    def responses_create(self, model, body):
        # Always use the native Responses contract. The model row is not
        # allowed to redirect this provider to ToAPIs Chat Completions.
        request_body = dict(body or {})
        if "input" not in request_body:
            request_body = self._chat_body_to_responses(request_body)
        request_body = self._fresh_responses_body(request_body)
        if (
            getattr(model, "media_type", "CHAT")
            and str(getattr(model, "media_type", "CHAT")).upper() != "CHAT"
        ):
            raise ProviderRequestError(
                "快跑AI当前只支持文本 Responses 模型"
            )
        if (
            request_body.get("max_output_tokens") in (None, "")
            and request_body.get("max_completion_tokens") not in (None, "")
        ):
            request_body["max_output_tokens"] = request_body.pop(
                "max_completion_tokens"
            )
        elif request_body.get("max_output_tokens") in (None, ""):
            request_body.pop("max_tokens", None)
        request_body.pop("max_completion_tokens", None)
        request_body.pop("max_tokens", None)
        max_output_tokens = request_body.get("max_output_tokens")
        if max_output_tokens not in (None, ""):
            try:
                request_body["max_output_tokens"] = min(
                    max(int(max_output_tokens), 1),
                    GPT_MAX_OUTPUT_TOKENS,
                )
            except (TypeError, ValueError):
                request_body.pop("max_output_tokens", None)
        model_code = str(getattr(model, "model_code", "") or "").strip()
        if model_code.lower() in GPT56_MODEL_CODES:
            # GPT-5.6 reasoning models reject legacy sampling controls even
            # when the relay accepts the rest of the Responses payload.
            request_body.pop("temperature", None)
            request_body.pop("top_p", None)
            request_body.setdefault("reasoning_effort", "medium")
        request_code = str(request_body.get("model") or "").strip()
        for code in (model_code, request_code):
            if code and code not in self.model_codes:
                raise ProviderRequestError(
                    "快跑AI当前支持的模型为："
                    + "、".join(KuaipaoCatalog.MODEL_CODES)
                )
        if model_code and request_code and model_code != request_code:
            raise ProviderRequestError(
                "快跑AI请求模型与已选择的模型不一致"
            )
        request_body["model"] = (
            model_code
            or request_code
            or self.default_model_code
        )
        return self._request(
            "POST",
            self.responses_path,
            request_body,
        )

    def chat_completion(self, model, body):
        """Accept legacy callers but translate them to native Responses JSON."""

        return self.responses_create(model, body)

    def complete(self, model, body):
        if str(getattr(model, "media_type", "") or "").upper() == "IMAGE":
            return self.submit_generation(model, body)
        return self.responses_create(model, body)


def provider_client_class(provider):
    """Return the protocol client selected by a provider's stable identity."""

    key = provider_catalog_key(provider)
    if key == ToApisClient.provider_key:
        return ToApisClient
    if key == KuaipaoClient.provider_key:
        return KuaipaoClient
    return ProviderClient
