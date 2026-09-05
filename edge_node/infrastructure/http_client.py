import json
import urllib.request


def request_json(
    url: str,
    method: str = "GET",
    payload: dict | None = None,
    timeout: float = 0.65
):
    """
    Gửi thông điệp JSON giữa các Edge Node.
    """

    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url=url,
        data=data,
        method=method
    )

    request.add_header(
        "Content-Type",
        "application/json"
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout
    ) as response:

        response_data = response.read()

        if not response_data:
            return response.status, {}

        return (
            response.status,
            json.loads(response_data)
        )