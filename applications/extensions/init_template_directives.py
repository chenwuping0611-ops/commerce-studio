from applications.common.scope import has_effective_permission


def init_template_directives(app):
    @app.template_global()
    def authorize(power):
        # Resolve the live role assignment so revoked permissions disappear
        # from rendered pages without requiring a new login session.
        return has_effective_permission(power)
