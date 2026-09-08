from flask import current_app, jsonify, render_template, request


def _is_api_request():
    """Keep browser-facing error pages separate from JSON API failures."""

    path = str(request.path or "")
    return (
        path.startswith("/amazon-ai/api/")
        or path.startswith("/studio/api/")
        or request.is_json
        or request.accept_mimetypes.best == "application/json"
    )


def _json_error(message, status_code, code):
    return (
        jsonify(
            success=False,
            msg=message,
            code=code,
        ),
        status_code,
    )


def init_error_views(app):
    @app.errorhandler(403)
    def page_not_found(e):
        if _is_api_request():
            return _json_error("没有权限访问该接口", 403, "FORBIDDEN")
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def page_not_found(e):
        if _is_api_request():
            return _json_error("接口不存在", 404, "NOT_FOUND")
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        original = getattr(e, "original_exception", None)
        current_app.logger.error(
            "unhandled server error path=%s method=%s",
            request.path,
            request.method,
            exc_info=original or e,
        )
        if _is_api_request():
            return _json_error(
                "服务器内部错误，请查看服务器日志",
                500,
                "INTERNAL_SERVER_ERROR",
            )
        return render_template('errors/500.html'), 500

    # Return validation errors as JSON
    @app.errorhandler(422)
    @app.errorhandler(400)
    def handle_error(err):
        error_data = getattr(err, "data", {}) or {}
        headers = error_data.get("headers")
        message_data = error_data.get("messages") or {}
        messages = (
            message_data.get("json")
            if isinstance(message_data, dict)
            else None
        )
        msg = "请求参数无效"

        if isinstance(messages, dict):
            for field, field_messages in messages.items():
                if field_messages:
                    msg = str(field) + str(field_messages[0])
                    break

        if headers:
            return jsonify({"success": False, "msg": msg})
        else:
            return jsonify({"success": False, "msg": msg})
