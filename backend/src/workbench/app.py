"""Provide the application address used by the server's launch command.

Keeping this small entry file lets existing start commands continue to work while
the browser pages and request handlers are maintained in separate files. Importing
it prepares the web application; it does not begin analysing a manual."""

from workbench.http_endpoints.serve_application import app

__all__ = ["app"]
