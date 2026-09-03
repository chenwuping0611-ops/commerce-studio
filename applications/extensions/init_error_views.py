from flask import render_template, jsonify


def init_error_views(app):
    @app.errorhandler(403)
    def page_not_found(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(e):
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
