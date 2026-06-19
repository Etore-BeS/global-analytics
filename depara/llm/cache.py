"""Cache SQLite para evitar re-chamadas LLM em produção."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from depara.llm.schemas import LLMMatchOutput


class MatchCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_matches (
                    cache_key TEXT PRIMARY KEY,
                    linha_produto TEXT NOT NULL,
                    model TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    @staticmethod
    def make_key(linha_produto: str, candidate_ids: list[int], model: str) -> str:
        payload = f"{linha_produto}|{','.join(map(str, sorted(candidate_ids)))}|{model}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, key: str) -> LLMMatchOutput | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT response_json FROM llm_matches WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None
        return LLMMatchOutput.model_validate_json(row[0])

    def set(self, key: str, linha_produto: str, model: str, output: LLMMatchOutput) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO llm_matches
                    (cache_key, linha_produto, model, response_json)
                VALUES (?, ?, ?, ?)
                """,
                (key, linha_produto, model, output.model_dump_json()),
            )
