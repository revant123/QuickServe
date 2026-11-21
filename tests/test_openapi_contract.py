"""The API contract the customer app is built against must match the real API.

frontend/openapi.json is committed, and the app's TypeScript types are generated
from it. If someone changes an endpoint and forgets to re-export, the app would
compile against an API that no longer exists. This test catches that in CI.
"""

from pathlib import Path

from scripts.export_openapi import OUT, contract


def test_frontend_contract_is_up_to_date():
    assert OUT.exists(), "Run: python -m scripts.export_openapi"
    assert OUT.read_text(encoding="utf-8") == contract(), (
        "frontend/openapi.json is out of date. Run: python -m scripts.export_openapi, "
        "then in frontend/: npm run gen:api"
    )


def test_contract_has_the_endpoints_the_app_calls():
    text = Path(OUT).read_text(encoding="utf-8")
    for path in ['"/api/v1/restaurants/near"', '"/api/v1/orders/quote"', '"/api/v1/orders"', '"/api/v1/search"']:
        assert path in text
