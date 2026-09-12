from rest_framework.exceptions import APIException


class SingleDeviceSessionConflict(APIException):
    """账号已在其他设备登录(单设备登录策略)。"""

    status_code = 401
    default_detail = "账号已在其他设备登录,请重新登录"
    default_code = "single_device"
    detail_code = 40101
