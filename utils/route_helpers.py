from flask import flash


def flash_service_response(response, default_success="success", default_error="danger"):
    if not response:
        return

    level = response.get("level")
    if not level:
        level = default_success if response.get("success") else default_error

    flash(response.get("message", ""), level)
