"""登录并读取检判首页。密码只放在请求里，不写进日志。"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from typing import Any, Optional

from scrap_alert.models import Station, parse_homepage

logger = logging.getLogger(__name__)

_AUTH_HINTS = ("登录", "token", "Token", "认证", "过期", "未授权", "无权")


class ApiError(Exception):
    def __init__(self, message: str, *, auth: bool = False, code: Optional[int] = None) -> None:
        super().__init__(message)
        self.auth = auth
        self.code = code


class ScrapClient:
    def __init__(self, base_url: str, employee_id: str, password: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.employee_id = employee_id
        self.password = password
        self.timeout = timeout
        self._logged_in = False
        self._cookies = CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._cookies))

    def ensure_login(self) -> None:
        if not self._logged_in:
            self.login()

    def mark_logged_out(self) -> None:
        self._logged_in = False

    @property
    def logged_in(self) -> bool:
        return self._logged_in

    def login(self) -> str:
        """登录并记住 satoken Cookie。返回登录人姓名，供状态栏显示。"""
        query = urllib.parse.urlencode(
            {"employeeId": self.employee_id, "password": self.password}
        )
        payload = self._request("POST", f"/api/auth/login?{query}", data=b"", allow_relogin=False)
        token_info = ((payload.get("data") or {}).get("tokenInfo") or {})
        token = token_info.get("tokenValue")
        if not token:
            raise ApiError("登录成功但没有返回 token")
        self._logged_in = True
        name = (payload.get("data") or {}).get("userFullName") or self.employee_id
        logger.info("登录成功：%s", name)
        return str(name)

    def homepage_stations(self) -> list[Station]:
        payload = self._request("GET", "/api/intelligence/intelliTaskInfo/getIntelliHomePageInfo")
        return parse_homepage(payload)

    def check_detail(self, flow_code: str) -> dict[str, Any]:
        query = urllib.parse.urlencode({"flowCode": flow_code})
        payload = self._request(
            "GET",
            f"/api/intelligence/intelliTaskInfo/getCheckDetail?{query}",
        )
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            return {}
        return data

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: Optional[bytes] = None,
        allow_relogin: bool = True,
    ) -> dict[str, Any]:
        url = self.base_url + path
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/json",
                "User-Agent": "yongfeng-scrap-alert/1.0",
            },
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            payload = _parse_json(body)
            if payload is not None:
                return self._unwrap(payload, allow_relogin=allow_relogin, retry_path=path, method=method, data=data)
            if exc.code in (401, 403):
                self._logged_in = False
                if allow_relogin:
                    self.login()
                    return self._request(method, path, data=data, allow_relogin=False)
                raise ApiError(f"登录已失效（HTTP {exc.code}）", auth=True, code=exc.code) from exc
            raise ApiError(f"接口 HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ApiError(f"连不上检判系统：{exc.reason}") from exc
        except (TimeoutError, ConnectionError) as exc:
            raise ApiError(f"连不上检判系统：{exc}") from exc

        payload = _parse_json(body)
        if payload is None:
            raise ApiError("检判系统返回的不是 JSON")
        return self._unwrap(payload, allow_relogin=allow_relogin, retry_path=path, method=method, data=data)

    def _unwrap(
        self,
        payload: dict[str, Any],
        *,
        allow_relogin: bool,
        retry_path: str,
        method: str,
        data: Optional[bytes],
    ) -> dict[str, Any]:
        meta = payload.get("meta") or {}
        success = bool(meta.get("success"))
        code = meta.get("code")
        if success and code in (200, "200", None):
            return payload
        message = str(meta.get("message") or "接口返回失败")
        auth = code in (401, 403, "401", "403") or any(hint in message for hint in _AUTH_HINTS)
        if auth and allow_relogin:
            logger.info("登录态失效，重新登录")
            self._logged_in = False
            self.login()
            return self._request(method, retry_path, data=data, allow_relogin=False)
        raise ApiError(message, auth=auth, code=code if isinstance(code, int) else None)


def _parse_json(body: str) -> Optional[dict[str, Any]]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload
