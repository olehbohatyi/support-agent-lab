from django.contrib import admin
from django.db import DatabaseError, connection
from django.http import HttpRequest, JsonResponse
from django.urls import path
from django.views.decorators.http import require_GET


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    """Liveness + database check. No auth: it exposes no data.

    Returns 503 (not 500) when the database is unreachable, so load balancers and
    orchestrators read it as "not ready" rather than as an application crash.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
]
