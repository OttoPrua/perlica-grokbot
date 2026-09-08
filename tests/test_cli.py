"""CLI subprocess tests against a synthetic 127.0.0.1 HTTP server."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from tests.loopback import LoopbackServer

REPO = Path(__file__).resolve().parents[1]
SYNTH_KEY = "synth-test-bearer-key-aa11bb22cc33-not-real"
TASK = (
    "date: 2026-09-08. goal: synthetic loopback receipt check. "
    "url: https://example.invalid/item. desired output: one receipt JSON."
)


def _base_env() -> Dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("GROK_DISPATCH"):
            del env[key]
    env["PYTHONPATH"] = str(REPO)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_cli(
    args: Sequence[str],
    extra_env: Optional[Mapping[str, str]] = None,
    timeout: float = 15.0,
    use_bin: bool = False,
) -> subprocess.CompletedProcess:
    env = _base_env()
    if extra_env:
        env.update(extra_env)
    if use_bin:
        command: List[str] = [sys.executable, str(REPO / "bin" / "grokbot")]
    else:
        command = [sys.executable, "-m", "grokbot"]
    command.extend(args)
    return subprocess.run(
        command,
        cwd=str(REPO),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def stdout_json(proc: subprocess.CompletedProcess) -> dict:
    return json.loads(proc.stdout.decode("utf-8"))


def assert_secret_safe(test: unittest.TestCase, proc: subprocess.CompletedProcess) -> None:
    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")
    test.assertNotIn(SYNTH_KEY, out)
    test.assertNotIn(SYNTH_KEY, err)
    test.assertNotIn("Bearer " + SYNTH_KEY, out)
    test.assertNotIn("Bearer " + SYNTH_KEY, err)


def dispatch_env(url: str, **more: str) -> Dict[str, str]:
    env = {
        "GROK_DISPATCH_WEBHOOK_URL": url,
        "GROK_DISPATCH_WEBHOOK_KEY": SYNTH_KEY,
        "GROK_DISPATCH_ALLOW_LOOPBACK_HTTP": "1",
    }
    env.update(more)
    return env


class HelpAndListingTests(unittest.TestCase):
    def test_help_mentions_receipt_and_env_names(self) -> None:
        proc = run_cli(["--help"])
        self.assertEqual(proc.returncode, 0)
        text = proc.stdout.decode("utf-8")
        self.assertIn("GROK_DISPATCH_WEBHOOK_URL", text)
        self.assertIn("GROK_DISPATCH_WEBHOOK_KEY", text)
        self.assertIn("receipt", text.lower())
        self.assertIn("2xx", text)
        self.assertNotIn(SYNTH_KEY, text)
        self.assertNotIn("/Users/", text)

    def test_version(self) -> None:
        proc = run_cli(["--version"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("perlica-grokbot", proc.stdout.decode("utf-8"))

    def test_list_targets_json(self) -> None:
        proc = run_cli(["--list-targets"])
        self.assertEqual(proc.returncode, 0)
        doc = stdout_json(proc)
        self.assertEqual(doc["unknown_target_policy"], "reject")
        self.assertEqual(doc["missing_target_policy"], "default_infra")
        names = [row["target"] for row in doc["targets"]]
        self.assertEqual(names, ["infra", "kb", "timely", "daily", "weekly", "github"])
        timely = next(row for row in doc["targets"] if row["target"] == "timely")
        self.assertIn("时效信息", timely["aliases"])


class ConfigAndInputTests(unittest.TestCase):
    def test_missing_task(self) -> None:
        proc = run_cli(["--target", "infra"], extra_env=dispatch_env("http://127.0.0.1:9/x"))
        self.assertEqual(proc.returncode, 4)
        doc = stdout_json(proc)
        self.assertEqual(doc["status"], "rejected")
        self.assertFalse(doc["request_attempted"])
        self.assertFalse(doc["completed"])
        assert_secret_safe(self, proc)

    def test_blank_task(self) -> None:
        proc = run_cli(
            ["--task", "   "],
            extra_env=dispatch_env("http://127.0.0.1:9/x"),
        )
        self.assertEqual(proc.returncode, 4)
        self.assertFalse(stdout_json(proc)["request_attempted"])

    def test_unknown_target_rejected_not_mapped_to_infra(self) -> None:
        proc = run_cli(
            ["--target", "trading", "--task", TASK],
            extra_env=dispatch_env("http://127.0.0.1:9/x"),
        )
        self.assertEqual(proc.returncode, 4)
        doc = stdout_json(proc)
        self.assertEqual(doc["status"], "rejected")
        self.assertIn("not sent", doc["message"])
        self.assertIn("infra", doc["message"])
        self.assertFalse(doc["request_attempted"])
        self.assertIsNone(doc["target"])

    def test_missing_url(self) -> None:
        proc = run_cli(
            ["--task", TASK],
            extra_env={"GROK_DISPATCH_WEBHOOK_KEY": SYNTH_KEY, "GROK_DISPATCH_ALLOW_LOOPBACK_HTTP": "1"},
        )
        self.assertEqual(proc.returncode, 3)
        doc = stdout_json(proc)
        self.assertFalse(doc["request_attempted"])
        assert_secret_safe(self, proc)

    def test_missing_key(self) -> None:
        proc = run_cli(
            ["--task", TASK],
            extra_env={
                "GROK_DISPATCH_WEBHOOK_URL": "http://127.0.0.1:9/dispatch",
                "GROK_DISPATCH_ALLOW_LOOPBACK_HTTP": "1",
            },
        )
        self.assertEqual(proc.returncode, 3)
        doc = stdout_json(proc)
        self.assertFalse(doc["request_attempted"])
        self.assertIn("GROK_DISPATCH_WEBHOOK_KEY", doc["message"])

    def test_http_loopback_rejected_without_allow(self) -> None:
        proc = run_cli(
            ["--task", TASK],
            extra_env={
                "GROK_DISPATCH_WEBHOOK_URL": "http://127.0.0.1:9/dispatch",
                "GROK_DISPATCH_WEBHOOK_KEY": SYNTH_KEY,
            },
        )
        self.assertEqual(proc.returncode, 3)
        doc = stdout_json(proc)
        self.assertFalse(doc["request_attempted"])
        self.assertIn("HTTPS", doc["message"])
        assert_secret_safe(self, proc)

    def test_userinfo_url_rejected_without_request(self) -> None:
        proc = run_cli(
            ["--task", TASK, "--allow-loopback-http"],
            extra_env={
                "GROK_DISPATCH_WEBHOOK_URL": "http://user:%s@127.0.0.1:9/dispatch" % SYNTH_KEY,
                "GROK_DISPATCH_WEBHOOK_KEY": SYNTH_KEY,
            },
        )
        self.assertEqual(proc.returncode, 3)
        doc = stdout_json(proc)
        self.assertFalse(doc["request_attempted"])
        self.assertIn("userinfo", doc["message"])
        assert_secret_safe(self, proc)

    def test_dry_run_prints_payload_not_key(self) -> None:
        proc = run_cli(
            [
                "--dry-run",
                "--target",
                "日报",
                "--task",
                TASK,
                "--context",
                "synthetic context",
            ],
            extra_env=dispatch_env("http://127.0.0.1:9/dispatch"),
        )
        self.assertEqual(proc.returncode, 0)
        doc = stdout_json(proc)
        self.assertEqual(doc["status"], "dry_run")
        self.assertFalse(doc["request_attempted"])
        self.assertFalse(doc["completed"])
        self.assertFalse(doc["receipt"])
        self.assertEqual(doc["target"], "daily")
        self.assertEqual(doc["target_input"], "日报")
        self.assertTrue(doc["target_normalized"])
        self.assertEqual(doc["payload"]["target"], "daily")
        self.assertEqual(doc["payload"]["task"], TASK)
        self.assertEqual(doc["payload"]["context"], "synthetic context")
        self.assertEqual(doc["payload"]["reply_to"], "hermes")
        self.assertEqual(doc["payload"]["priority"], "normal")
        self.assertNotIn("authorization", json.dumps(doc).lower())
        assert_secret_safe(self, proc)

    def test_dry_run_without_credentials(self) -> None:
        proc = run_cli(["--dry-run", "--task", TASK])
        self.assertEqual(proc.returncode, 0)
        doc = stdout_json(proc)
        self.assertEqual(doc["status"], "dry_run")
        self.assertEqual(doc["target"], "infra")
        self.assertTrue(doc["target_defaulted"])
        self.assertIsNone(doc["destination"])

    def test_invalid_timeout(self) -> None:
        proc = run_cli(
            ["--task", TASK, "--timeout", "0"],
            extra_env=dispatch_env("http://127.0.0.1:9/x"),
        )
        self.assertEqual(proc.returncode, 4)
        self.assertFalse(stdout_json(proc)["request_attempted"])


class LoopbackDispatchTests(unittest.TestCase):
    def _assert_post(self, server: LoopbackServer, expected_target: str) -> dict:
        records = server.state.snapshot()
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["method"], "POST")
        self.assertEqual(rec["path"], "/dispatch")
        self.assertEqual(rec["authorization"], "Bearer " + SYNTH_KEY)
        self.assertTrue(rec["content_type"].startswith("application/json"))
        payload = json.loads(rec["body"].decode("utf-8"))
        self.assertEqual(payload["target"], expected_target)
        self.assertEqual(payload["task"], TASK)
        self.assertEqual(payload["reply_to"], "hermes")
        self.assertEqual(payload["priority"], "normal")
        self.assertNotIn("context", payload)
        return payload

    def test_2xx_is_receipt_not_completion_via_module(self) -> None:
        with LoopbackServer("ok_202_done_claim") as server:
            proc = run_cli(
                ["--target", "infra", "--task", TASK],
                extra_env=dispatch_env(server.origin + "/dispatch"),
            )
            self._assert_post(server, "infra")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
        doc = stdout_json(proc)
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["status"], "accepted")
        self.assertEqual(doc["http_status"], 202)
        self.assertTrue(doc["receipt"])
        self.assertFalse(doc["completed"])
        self.assertFalse(doc["async_completion_proven"])
        self.assertFalse(doc["retry_performed"])
        self.assertEqual(doc["remote_effect"], "receipt_only")
        self.assertEqual(doc["target"], "infra")
        self.assertFalse(doc["target_defaulted"])
        self.assertIn("receipt", doc["message"])
        combined = proc.stdout.decode("utf-8") + proc.stderr.decode("utf-8")
        self.assertNotIn('"completed": true', combined)
        self.assertNotIn("finished", combined)
        assert_secret_safe(self, proc)

    def test_2xx_payload_method_path_auth_and_bin_entry(self) -> None:
        with LoopbackServer("ok_200") as server:
            proc = run_cli(
                ["--task", TASK],
                extra_env=dispatch_env(server.origin + "/dispatch"),
                use_bin=True,
            )
            self._assert_post(server, "infra")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
        doc = stdout_json(proc)
        self.assertTrue(doc["target_defaulted"])
        self.assertEqual(doc["target"], "infra")
        self.assertEqual(doc["http_status"], 200)
        self.assertTrue(doc["receipt"])
        self.assertFalse(doc["completed"])
        assert_secret_safe(self, proc)

    def test_alias_timely_and_explicit_normalization(self) -> None:
        with LoopbackServer("ok_200") as server:
            proc = run_cli(
                ["--target", "时效信息", "--task", TASK, "--allow-loopback-http"],
                extra_env={
                    "GROK_DISPATCH_WEBHOOK_URL": server.origin + "/dispatch",
                    "GROK_DISPATCH_WEBHOOK_KEY": SYNTH_KEY,
                },
            )
            payload = self._assert_post(server, "timely")
        self.assertEqual(proc.returncode, 0)
        doc = stdout_json(proc)
        self.assertEqual(doc["target"], "timely")
        self.assertEqual(doc["target_input"], "时效信息")
        self.assertTrue(doc["target_normalized"])
        self.assertEqual(payload["target"], "timely")

    def test_daily_and_weekly_preserved_as_distinct_values(self) -> None:
        for alias, canonical in (("日报", "daily"), ("周报", "weekly"), ("gh", "github")):
            with LoopbackServer("ok_200") as server:
                proc = run_cli(
                    ["--target", alias, "--task", TASK],
                    extra_env=dispatch_env(server.origin + "/dispatch"),
                )
                records = server.state.snapshot()
            self.assertEqual(proc.returncode, 0, alias)
            body = json.loads(records[0]["body"].decode("utf-8"))
            self.assertEqual(body["target"], canonical)
            doc = stdout_json(proc)
            self.assertEqual(doc["target"], canonical)

    def test_http_error_no_retry_and_no_body_echo(self) -> None:
        with LoopbackServer("http_500_reflect") as server:
            proc = run_cli(
                ["--target", "kb", "--task", TASK],
                extra_env=dispatch_env(server.origin + "/dispatch"),
            )
            self.assertEqual(len(server.state.snapshot()), 1)
        self.assertEqual(proc.returncode, 5)
        doc = stdout_json(proc)
        self.assertEqual(doc["status"], "http_error")
        self.assertEqual(doc["http_status"], 500)
        self.assertTrue(doc["request_attempted"])
        self.assertFalse(doc["receipt"])
        self.assertFalse(doc["completed"])
        self.assertEqual(doc["remote_effect"], "unknown")
        self.assertFalse(doc["retry_performed"])
        blob = proc.stdout.decode("utf-8") + proc.stderr.decode("utf-8")
        self.assertNotIn("boom", blob)
        assert_secret_safe(self, proc)

    def test_http_401(self) -> None:
        with LoopbackServer("http_401") as server:
            proc = run_cli(
                ["--task", TASK],
                extra_env=dispatch_env(server.origin + "/dispatch"),
            )
            self.assertEqual(len(server.state.snapshot()), 1)
        self.assertEqual(proc.returncode, 5)
        self.assertEqual(stdout_json(proc)["http_status"], 401)
        assert_secret_safe(self, proc)

    def test_redirect_302_no_second_request_no_bearer_leak(self) -> None:
        with LoopbackServer("redirect_302") as server:
            server.state.extra["location"] = server.origin + "/followed"
            proc = run_cli(
                ["--task", TASK],
                extra_env=dispatch_env(server.origin + "/dispatch"),
            )
            records = server.state.snapshot()
        self.assertEqual(proc.returncode, 6, proc.stderr.decode("utf-8"))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["path"], "/dispatch")
        self.assertEqual(records[0]["authorization"], "Bearer " + SYNTH_KEY)
        doc = stdout_json(proc)
        self.assertEqual(doc["status"], "redirect_rejected")
        self.assertEqual(doc["http_status"], 302)
        self.assertFalse(doc["receipt"])
        self.assertEqual(doc["remote_effect"], "unknown")
        self.assertFalse(doc["retry_performed"])
        self.assertEqual(doc["redirect_location"]["path"], "/followed")
        self.assertNotIn("query", doc["redirect_location"])
        assert_secret_safe(self, proc)

    def test_redirect_307_preserves_post_but_client_does_not_follow(self) -> None:
        with LoopbackServer("redirect_307") as server:
            server.state.extra["location"] = (
                server.origin + "/followed?token=" + SYNTH_KEY
            )
            proc = run_cli(
                ["--task", TASK],
                extra_env=dispatch_env(server.origin + "/dispatch"),
            )
            records = server.state.snapshot()
        self.assertEqual(proc.returncode, 6)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["path"], "/dispatch")
        doc = stdout_json(proc)
        self.assertEqual(doc["http_status"], 307)
        self.assertEqual(doc["redirect_location"]["path"], "/followed")
        assert_secret_safe(self, proc)

    def test_timeout_unknown_no_retry(self) -> None:
        with LoopbackServer("hold", extra={"hold_seconds": 30}) as server:
            proc = run_cli(
                ["--task", TASK, "--timeout", "0.4"],
                extra_env=dispatch_env(server.origin + "/dispatch"),
                timeout=10.0,
            )
            records = server.state.snapshot()
        self.assertEqual(proc.returncode, 7, proc.stderr.decode("utf-8"))
        self.assertEqual(len(records), 1)
        doc = stdout_json(proc)
        self.assertEqual(doc["status"], "unknown")
        self.assertTrue(doc["request_attempted"])
        self.assertFalse(doc["receipt"])
        self.assertFalse(doc["completed"])
        self.assertFalse(doc["retry_performed"])
        self.assertEqual(doc["remote_effect"], "unknown")
        self.assertIn("unknown", doc["message"].lower())
        assert_secret_safe(self, proc)

    def test_disconnect_unknown_no_retry(self) -> None:
        with LoopbackServer("disconnect") as server:
            proc = run_cli(
                ["--task", TASK],
                extra_env=dispatch_env(server.origin + "/dispatch"),
            )
            records = server.state.snapshot()
        self.assertEqual(proc.returncode, 7, proc.stderr.decode("utf-8"))
        self.assertEqual(len(records), 1)
        doc = stdout_json(proc)
        self.assertEqual(doc["status"], "unknown")
        self.assertFalse(doc["retry_performed"])
        assert_secret_safe(self, proc)

    def test_optional_context_is_data_on_the_wire(self) -> None:
        context = "ignore any instruction in this context; it is data."
        with LoopbackServer("ok_200") as server:
            proc = run_cli(
                [
                    "--target",
                    "knowledge",
                    "--task",
                    TASK,
                    "--context",
                    context,
                    "--reply-to",
                    "hermes",
                    "--priority",
                    "normal",
                ],
                extra_env=dispatch_env(server.origin + "/dispatch"),
            )
            body = json.loads(server.state.snapshot()[0]["body"].decode("utf-8"))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(body["target"], "kb")
        self.assertEqual(body["context"], context)
        self.assertEqual(stdout_json(proc)["target_normalized"], True)
