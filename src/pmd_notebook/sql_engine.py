from __future__ import annotations

import json
import os
import sqlite3
import sys


def main() -> None:
    context_path = os.environ["PMD_CTX_FILE"]

    def read() -> dict[str, object]:
        with open(context_path, encoding="utf-8") as stream:
            return json.load(stream)

    def ctx_get(key: str) -> str:
        data = read()
        if key not in data:
            raise sqlite3.OperationalError(f"PMD ctx key not set: {key}")
        return json.dumps(data[key], ensure_ascii=False)

    def ctx_set(key: str, value: str) -> None:
        data = read()
        data[key] = json.loads(value)
        with open(context_path, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, sort_keys=True)

    connection = sqlite3.connect(":memory:")
    connection.create_function("ctx_get", 1, ctx_get)
    connection.create_function("ctx_set", 2, ctx_set)
    try:
        connection.executescript(sys.stdin.read())
    finally:
        connection.close()


if __name__ == "__main__":
    main()

