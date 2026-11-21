"""Write the API contract (OpenAPI) to frontend/openapi.json.

The customer app's TypeScript types are generated from this file
(`npm run gen:api` in frontend/). So:

    python -m scripts.export_openapi        # after changing an endpoint or schema
    cd frontend && npm run gen:api          # regenerate the TypeScript types

tests/test_openapi_contract.py fails if the file is out of date, so an API
change can't reach main without the app's types being updated with it.
"""

import json
from pathlib import Path

from app.main import app

OUT = Path(__file__).resolve().parent.parent / "frontend" / "openapi.json"


def contract() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUT.write_text(contract(), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT}")
