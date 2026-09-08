"""Command-line entry for the grokbot dispatcher client."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

from grokbot import SCHEMA, __version__
from grokbot.dispatch import (
    DEFAULT_TIMEOUT,
    load_key,
    load_url,
    loopback_http_allowed,
    post_json,
    validate_url,
)
from grokbot.errors import (
    ConfigError,
    GrokbotError,
    HttpStatusError,
    InputError,
    RedirectRejected,
    UnknownOutcome,
)
from grokbot.redact import scrub, secret_fragments
from grokbot.targets import known_target_rows, resolve_target

HELP = """向已有云端 webhook dispatcher 发送一次已认证 POST。

本命令不创建云端 bot、不调用 xAI API、不伪造 SendToAgent、不等待异步完成。
HTTP 2xx 只证明对端收票（receipt），即使响应正文声称 done/completed 也不表示任务完成。
POST 失败、超时或断连时远端效果未知：不自动重试，不宣称已投递或已完成。
密钥只来自环境变量 GROK_DISPATCH_WEBHOOK_KEY，禁止放进 argv、日志或本命令输出。

环境变量:
  GROK_DISPATCH_WEBHOOK_URL   已有 dispatcher 的 URL（生产必须 HTTPS）
  GROK_DISPATCH_WEBHOOK_KEY   Bearer 令牌（切勿写入仓库或命令行）
  GROK_DISPATCH_ALLOW_LOOPBACK_HTTP  合成环回 HTTP 测试才需要

退出码:
  0  2xx 收票或 --dry-run
  2  命令行用法错误
  3  配置错误（缺 URL/密钥、非 HTTPS 等）
  4  输入错误（空 task、未知 target）
  5  HTTP 非 2xx
  6  拒绝重定向（不会发第二次请求）
  7  超时/断连/传输失败（远端未知、无重试）
"""


def build_payload(
    *,
    target: str,
    task: str,
    context: Optional[str],
    reply_to: str,
    priority: str,
) -> Dict[str, str]:
    payload = {
        "target": target,
        "task": task,
        "reply_to": reply_to,
        "priority": priority,
    }
    if context is not None:
        payload["context"] = context
    return payload


def validate_task(raw: Optional[str]) -> str:
    if raw is None:
        raise InputError("task is required and must be a non-blank string")
    task = raw.strip()
    if not task:
        raise InputError("task is required and must be a non-blank string")
    return task


def validate_optional_text(name: str, raw: Optional[str], default: str) -> str:
    if raw is None:
        return default
    text = raw.strip()
    if not text:
        raise InputError(name + " is empty")
    return text


def validate_context(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        raise InputError("context is empty; omit the flag to skip it")
    return text


def parse_timeout(raw: Optional[str], env: Mapping[str, str]) -> float:
    text = raw
    if text is None:
        text = env.get("GROK_DISPATCH_TIMEOUT")
    if text is None or str(text).strip() == "":
        return DEFAULT_TIMEOUT
    try:
        value = float(str(text).strip())
    except ValueError:
        raise InputError("timeout must be a positive number of seconds")
    if value <= 0:
        raise InputError("timeout must be a positive number of seconds")
    return value


def encode_payload(payload: Mapping[str, str]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def result_document(
    *,
    status: str,
    ok: bool,
    exit_code: int,
    message: str,
    target: Optional[str] = None,
    target_input: Optional[str] = None,
    target_defaulted: bool = False,
    target_normalized: bool = False,
    http_status: Optional[int] = None,
    receipt: bool = False,
    request_attempted: bool = False,
    remote_effect: str = "none",
    destination: Optional[dict] = None,
    payload: Optional[Mapping[str, str]] = None,
    redirect_location: Optional[dict] = None,
) -> Dict[str, Any]:
    doc: Dict[str, Any] = {
        "schema": SCHEMA,
        "ok": ok,
        "status": status,
        "exit_code": exit_code,
        "target": target,
        "target_input": target_input,
        "target_defaulted": target_defaulted,
        "target_normalized": target_normalized,
        "http_status": http_status,
        "receipt": receipt,
        "completed": False,
        "async_completion_proven": False,
        "retry_performed": False,
        "request_attempted": request_attempted,
        "remote_effect": remote_effect,
        "destination": destination,
        "message": message,
    }
    if payload is not None:
        doc["payload"] = dict(payload)
    if redirect_location is not None:
        doc["redirect_location"] = redirect_location
    return doc


def emit(doc: Mapping[str, Any], secrets: Sequence[str], stderr_message: str) -> None:
    blob = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    sys.stdout.write(scrub(blob, secrets))
    sys.stderr.write(scrub(stderr_message, secrets) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grokbot",
        description=HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="store_true", help="print version and exit")
    parser.add_argument(
        "--list-targets",
        action="store_true",
        help="print canonical targets and aliases as JSON",
    )
    parser.add_argument(
        "--target",
        help="canonical name or alias; omitted defaults to infra",
    )
    parser.add_argument(
        "--task",
        help="required non-blank task text (dates, URLs, goal, desired output)",
    )
    parser.add_argument("--context", help="optional extra context string")
    parser.add_argument(
        "--reply-to",
        dest="reply_to",
        default=None,
        help="optional reply routing hint (default: hermes)",
    )
    parser.add_argument(
        "--priority",
        default=None,
        help="optional informational priority (default: normal)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the JSON payload and destination; do not POST",
    )
    parser.add_argument(
        "--timeout",
        default=None,
        help="POST timeout in seconds (default: 30, or GROK_DISPATCH_TIMEOUT)",
    )
    parser.add_argument(
        "--allow-loopback-http",
        action="store_true",
        help="allow http://127.0.0.1 (or localhost / ::1) for synthetic tests",
    )
    return parser


def _list_targets_document() -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "ok": True,
        "status": "targets",
        "exit_code": 0,
        "completed": False,
        "targets": known_target_rows(),
        "unknown_target_policy": "reject",
        "missing_target_policy": "default_infra",
        "message": "Unknown targets are rejected by this client; a missing target defaults to infra.",
    }


def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    environ = env if env is not None else os.environ
    secrets: List[str] = []
    # Collect the key if present so even usage-adjacent output can be scrubbed.
    raw_key = environ.get("GROK_DISPATCH_WEBHOOK_KEY")
    if isinstance(raw_key, str) and raw_key.strip():
        secrets.extend(secret_fragments(raw_key.strip()))

    if args.version:
        sys.stdout.write("perlica-grokbot " + __version__ + "\n")
        return 0
    if args.list_targets:
        emit(_list_targets_document(), secrets, "canonical targets listed")
        return 0

    try:
        return _dispatch(args, environ, secrets)
    except GrokbotError as exc:
        return _emit_error(exc, secrets)


def _emit_error(
    exc: GrokbotError,
    secrets: Sequence[str],
    extra: Optional[Dict[str, Any]] = None,
) -> int:
    http_status = getattr(exc, "http_status", None)
    location = getattr(exc, "location_safe", None)
    attempted = isinstance(exc, (HttpStatusError, RedirectRejected, UnknownOutcome))
    remote_effect = "unknown" if attempted else "none"
    fields: Dict[str, Any] = dict(extra or {})
    doc = result_document(
        status=exc.status,
        ok=False,
        exit_code=exc.exit_code,
        message=exc.message,
        target=fields.get("target"),
        target_input=fields.get("target_input"),
        target_defaulted=bool(fields.get("target_defaulted", False)),
        target_normalized=bool(fields.get("target_normalized", False)),
        http_status=http_status,
        request_attempted=attempted,
        remote_effect=remote_effect,
        destination=fields.get("destination"),
        redirect_location=location,
    )
    emit(doc, secrets, exc.message)
    return exc.exit_code


def _dispatch(args: argparse.Namespace, environ: Mapping[str, str], secrets: List[str]) -> int:
    target, target_input, defaulted, normalized = resolve_target(args.target)
    task = validate_task(args.task)
    context = validate_context(args.context)
    reply_to = validate_optional_text("reply-to", args.reply_to, "hermes")
    priority = validate_optional_text("priority", args.priority, "normal")
    payload = build_payload(
        target=target,
        task=task,
        context=context,
        reply_to=reply_to,
        priority=priority,
    )
    timeout = parse_timeout(args.timeout, environ)
    allow_http = loopback_http_allowed(bool(args.allow_loopback_http), environ)
    meta = {
        "target": target,
        "target_input": target_input,
        "target_defaulted": defaulted,
        "target_normalized": normalized,
    }

    destination = None
    url = None
    url_error = None
    try:
        url = load_url(environ)
        destination = validate_url(url, allow_loopback_http=allow_http)
    except ConfigError as exc:
        url_error = exc
    meta["destination"] = destination

    if args.dry_run:
        message = (
            "dry-run only; payload not sent; HTTP receipt and completion are both unproven"
        )
        if url_error is not None:
            message = message + "; destination not usable: " + url_error.message
        doc = result_document(
            status="dry_run",
            ok=True,
            exit_code=0,
            message=message,
            payload=payload,
            **meta
        )
        emit(doc, secrets, message)
        return 0

    if url_error is not None:
        return _emit_error(url_error, secrets, meta)
    try:
        key = load_key(environ)
    except ConfigError as exc:
        return _emit_error(exc, secrets, meta)
    secrets.extend(secret_fragments(key))
    body = encode_payload(payload)
    assert url is not None
    try:
        http_status = post_json(url=url, key=key, body=body, timeout=timeout)
    except GrokbotError as exc:
        return _emit_error(exc, secrets, meta)
    message = (
        "HTTP 2xx receipt only; asynchronous completion is not proven; no retry performed"
    )
    doc = result_document(
        status="accepted",
        ok=True,
        exit_code=0,
        message=message,
        http_status=http_status,
        receipt=True,
        request_attempted=True,
        remote_effect="receipt_only",
        **meta
    )
    emit(doc, secrets, message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
