from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Tuple


def _read_text_any_encoding(path: str | Path) -> str:
    data = Path(path).read_bytes()
    # Dumps are commonly encoded as cp1251 on Windows.
    # Important: try cp1251 first; utf-8 might not throw, but still decode to mojibake.
    for enc in ("cp1251", "utf-8", "latin1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    # If none worked, fall back (best-effort) so we at least can parse ASCII tokens.
    return data.decode("utf-8", errors="ignore")


def _strip_sql_comments(sql: str) -> str:
    # Remove MySQL-like block comments: /* ... */
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    # Remove line comments: -- ...
    sql = re.sub(r"(?m)^\s*--.*$", "", sql)
    return sql


def _split_sql_statements(sql: str) -> Iterable[str]:
    """
    Split SQL script into statements by ';', but keep ';' inside single quotes.
    """
    buf: list[str] = []
    in_str = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_str:
            in_str = True
            buf.append(ch)
            i += 1
            continue
        if ch == "'" and in_str:
            # MySQL escapes quotes by doubling them: '' inside a string.
            if i + 1 < len(sql) and sql[i + 1] == "'":
                buf.append("''")
                i += 2
                continue
            in_str = False
            buf.append(ch)
            i += 1
            continue
        if ch == ";" and not in_str:
            stmt = "".join(buf).strip()
            if stmt:
                yield stmt
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        yield tail


def _convert_mysql_ddl_to_sqlite(create_stmt: str) -> str:
    stmt = create_stmt.strip().rstrip(";")
    # Backticks are MySQL quoting; remove them for SQLite.
    stmt = stmt.replace("`", "")

    # Remove trailing table options (ENGINE=..., DEFAULT CHARSET=...)
    stmt = re.sub(r"\s+ENGINE\s*=\s*[^$]+$", "", stmt)
    stmt = re.sub(r"\s+DEFAULT\s+CHARSET\s*=\s*[^$]+$", "", stmt)

    # Remove COMMENT '...' fragments (present in column definitions)
    stmt = re.sub(r"\bCOMMENT\s+'[^']*'", "", stmt, flags=re.DOTALL)
    stmt = re.sub(r'\bCOMMENT\s+"[^"]*"', "", stmt, flags=re.DOTALL)

    # Convert common MySQL column types into SQLite-friendly affinities.
    replacements = [
        (r"\byear\s*\(\s*\d+\s*\)", "INTEGER"),
        (r"\btinyint\s*\(\s*\d+\s*\)", "INTEGER"),
        (r"\bint\s*\(\s*\d+\s*\)", "INTEGER"),
        (r"\bdecimal\s*\(\s*\d+\s*,\s*\d+\s*\)", "REAL"),
        (r"\bvarchar\s*\(\s*\d+\s*\)", "TEXT"),
        (r"\bchar\s*\(\s*\d+\s*\)", "TEXT"),
        (r"\btext\b", "TEXT"),
    ]
    for pattern, repl in replacements:
        stmt = re.sub(pattern, repl, stmt, flags=re.IGNORECASE)

    return stmt


def _convert_mysql_dml_to_sqlite(insert_stmt: str) -> str:
    stmt = insert_stmt.strip().rstrip(";")
    stmt = stmt.replace("`", "")
    return stmt


@dataclass(frozen=True)
class SQLLoadResult:
    ok: bool
    message: str = ""


class SQLProcessor:
    """
    Minimal SQL loader for MySQL-like dumps into an in-memory SQLite DB.

    Current goal: make `opop_data_extractor.py` functional for the bundled
    `math.sql` + `dump.sql` test data.

    Future extension: you can teach conversion rules for more MySQL features
    (or add more preprocessing), but the core structure stays the same.
    """

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        # FK constraints are not needed for SELECT-based extraction.
        self.conn.execute("PRAGMA foreign_keys = OFF")

    def close(self) -> None:
        self.conn.close()

    def load_sql_file(self, sql_path: str) -> Tuple[bool, str]:
        try:
            text = _read_text_any_encoding(sql_path)
            text = _strip_sql_comments(text)
            statements = list(_split_sql_statements(text))

            cur = self.conn.cursor()
            for stmt in statements:
                normalized = stmt.lstrip().upper()
                if normalized.startswith("CREATE TABLE"):
                    sqlite_stmt = _convert_mysql_ddl_to_sqlite(stmt)
                    cur.execute(sqlite_stmt)
                elif normalized.startswith("INSERT INTO"):
                    sqlite_stmt = _convert_mysql_dml_to_sqlite(stmt)
                    cur.execute(sqlite_stmt)
                else:
                    # Skip ALTER/COMMIT/etc. SQLite won't understand MySQL-specific syntax here.
                    continue

            self.conn.commit()
            return True, ""
        except Exception as e:  # pragma: no cover
            return False, str(e)

