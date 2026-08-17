import json
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class ProviderRequestError(Exception):
    """Normalized upstream request error with an optional response payload."""

    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class ProviderClient:
    """Small requests-based client for official and relay API providers."""

    def __init__(self, provider):
        self.provider = provider
        self.session = requests.Session()
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.6,
            status_forcelist=(408, 425, 429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))

    def _url(self, path):
        base = (self.provider.base_url or "").rstrip("/")
        path = path or ""
        if not path.startswith("/"):
            path = "/" + path
        return base + path

    def _headers(self):
        headers = {
            "Accept": "application/json",
            "User-Agent": "commerce-studio/0.1",
        }
        api_key = (self.provider.api_key or "").strip()
        if api_key:
            header_name = (getattr(self.provider, "auth_header", None) or "Authorization").strip()
            prefix = getattr(self.provider, "auth_prefix", None)
            headers[header_name] = f"{prefix.strip()} {api_key}".strip() if prefix else api_key
        return headers

    def _request(self, method, path, body=None):
        url = self._url(path)
        headers = self._headers()
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
            raise ProviderRequestError(f"供应商网络请求失败：{exc}") from exc

        try:
            payload = response.json()
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {"raw": response.text[:4000]}

        if not 200 <= response.status_code < 300:
            message = self._error_message(payload, response.status_code)
            raise ProviderRequestError(message, response.status_code, payload)
        return payload

    @staticmethod
    def _error_message(payload, status_code):
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return error.get("message") or error.get("code") or str(error)
            return payload.get("message") or payload.get("msg") or str(payload)
        return f"供应商返回 HTTP {status_code}"

    def submit_generation(self, model, body):
        path = model.generation_path or self.provider.generation_path
        return self._request("POST", path, body)

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
        return self._request("GET", path)
