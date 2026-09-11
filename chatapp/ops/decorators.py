from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.urls import reverse


def staff_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("ops:login"))
        if not request.user.is_staff:
            return HttpResponseForbidden("该账号无运营权限")
        return view(request, *args, **kwargs)
    return wrapper
