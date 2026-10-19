"""
SQL reward-model client for the BIRD-bench skill.

Connects to a local Unix-socket reward server (JSON line in, JSON line out)
when one is running. The AdaSkill original client used a private jump host and
kubectl; that path is not used here.

Set REWARD_SOCKET_PATH (default /tmp/reward.sock). Expected response keys:
  yes_prob, no_prob
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from typing import Optional

SOCKET_PATH = os.environ.get("REWARD_SOCKET_PATH", "/tmp/reward.sock")
INFERENCE_TIMEOUT = int(os.environ.get("REWARD_TIMEOUT", "60"))


@dataclass
class RewardScore:
    yes_prob: float
    no_prob: float


class RewardModelClient:
    """Relay one inference request to a local Unix-socket reward server."""

    def __init__(self, socket_path: str = SOCKET_PATH):
        self.socket_path = socket_path

    def score(
        self,
        db_schema: str,
        question: str,
        sql_candidate: str,
        evidence: str = "",
        execution_result: str = "",
        num_rows: int = 0,
    ) -> float:
        return self._call(
            db_schema, question, sql_candidate, evidence, execution_result, num_rows
        ).yes_prob

    def score_detailed(
        self,
        db_schema: str,
        question: str,
        sql_candidate: str,
        evidence: str = "",
        execution_result: str = "",
        num_rows: int = 0,
    ) -> RewardScore:
        return self._call(
            db_schema, question, sql_candidate, evidence, execution_result, num_rows
        )

    def rank(
        self,
        db_schema: str,
        question: str,
        sql_candidates: list[str],
        evidence: str = "",
        execution_results: Optional[list[str]] = None,
        num_rows_list: Optional[list[int]] = None,
    ) -> tuple[str, list[tuple[str, float]]]:
        if execution_results is None:
            execution_results = [""] * len(sql_candidates)
        if num_rows_list is None:
            num_rows_list = [0] * len(sql_candidates)

        scored = [
            (sql, self.score(db_schema, question, sql, evidence, ex, nr))
            for sql, ex, nr in zip(sql_candidates, execution_results, num_rows_list)
        ]
        ranked = sorted(scored, key=lambda x: x[1], reverse=True)
        return ranked[0][0], ranked

    def health(self) -> bool:
        try:
            self._call("test_schema", "test_question", "SELECT 1", "")
            return True
        except Exception:
            return False

    def close(self):
        """No-op — kept for API compatibility."""
        pass

    def _call(
        self,
        db_schema: str,
        question: str,
        sql_candidate: str,
        evidence: str,
        execution_result: str = "",
        num_rows: int = 0,
    ) -> RewardScore:
        if not os.path.exists(self.socket_path):
            raise RuntimeError(
                f"Reward server socket not found at {self.socket_path}. "
                "Start a local reward_server.py or unset ranking and choose "
                "with execute_sql plus select_tips."
            )

        payload = (
            json.dumps(
                {
                    "db_schema": db_schema,
                    "question": question,
                    "sql_candidate": sql_candidate,
                    "evidence": evidence,
                    "execution_result": execution_result,
                    "num_rows": num_rows,
                }
            )
            + "\n"
        )

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(INFERENCE_TIMEOUT)
        try:
            sock.connect(self.socket_path)
            sock.sendall(payload.encode("utf-8"))
            buf = b""
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
        finally:
            sock.close()

        raw = buf.decode("utf-8").strip()
        if not raw:
            raise RuntimeError("Empty response from reward server.")

        data = json.loads(raw)
        if "error" in data:
            raise RuntimeError(f"Server inference error: {data['error']}")

        return RewardScore(yes_prob=data["yes_prob"], no_prob=data["no_prob"])


if __name__ == "__main__":
    client = RewardModelClient()
    if not client.health():
        print("reward server unavailable (optional); skip ranking")
    else:
        print("reward server ok")
