from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView


class _ProbeView(APIView):
    """A view with no explicit auth or permissions: it uses the project defaults."""

    def get(self, request: Request) -> Response:
        return Response({"reached": True})


def test_api_denies_anonymous_requests_by_default() -> None:
    """Until tenant auth lands (B-06), any DRF view must reject anonymous calls."""
    request = APIRequestFactory().get("/probe/")

    response = _ProbeView.as_view()(request)

    assert response.status_code in {401, 403}
    assert "reached" not in response.data
