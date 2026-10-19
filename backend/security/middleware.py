"""Application-wide CSRF, abuse controls, cookies and response headers."""
import hashlib
import hmac
import os

from flask import jsonify, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

from backend.security.events import record
from backend.security.limiter import hit
from backend.security.request import client_ip


UNSAFE = {'POST', 'PUT', 'PATCH', 'DELETE'}


def _limited(scope, identity, limit, seconds):
    allowed, retry, backend = hit(scope, identity, limit, seconds)
    if allowed:
        return None
    try:
        record('rate_limit_exceeded', 'warning', session.get('user_id'),
               session.get('username', ''), {'scope': scope, 'backend': backend})
    except Exception:
        pass
    response = jsonify(error='Too many requests. Try again later.')
    response.status_code = 429
    response.headers['Retry-After'] = str(retry)
    return response


def init_security(app):
    proxy_count = int(os.getenv('AMT_TRUSTED_PROXY_COUNT', '0'))
    if proxy_count:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_count, x_proto=proxy_count,
                                x_host=proxy_count)
    https = os.getenv('AMT_HTTPS', '').lower() in ('1', 'true', 'yes')
    app.config.update(
        SESSION_COOKIE_NAME='amt_session_v2', SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=https, SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=12 * 60 * 60,
        SESSION_REFRESH_EACH_REQUEST=False, MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )

    @app.before_request
    def protect_request():
        if app.testing:
            return None
        ip_hash = hashlib.sha256(client_ip().encode()).hexdigest()[:32]
        response = _limited('ip', ip_hash, 3000, 60)
        if response:
            return response
        if request.path.startswith('/api/') and session.get('user_id'):
            response = _limited('user', str(session['user_id']), 300, 60)
            if response:
                return response
            if ('sku-lookup' in request.path or request.path == '/api/lookup'):
                response = _limited('lookup', str(session['user_id']), 30, 60)
            elif '/invoices/' in request.path and request.method in UNSAFE:
                response = _limited('pi', str(session['user_id']), 10, 60)
            if response:
                return response
        if (request.method in UNSAFE and request.path != '/login'
                and session.get('user_id')):
            expected = session.get('csrf_token', '')
            supplied = request.headers.get('X-CSRF-Token', '')
            if not expected or not hmac.compare_digest(expected, supplied):
                try:
                    record('csrf_rejected', 'warning', session.get('user_id'),
                           session.get('username', ''), {'path': request.path})
                except Exception:
                    pass
                return jsonify(error='Security token is missing or invalid.'), 403
        return None

    @app.after_request
    def secure_response(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        response.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
        if https:
            response.headers.setdefault('Strict-Transport-Security',
                                        'max-age=31536000; includeSubDomains')
        csrf = session.get('csrf_token')
        if csrf:
            response.set_cookie('amt_csrf_v2', csrf, secure=https, httponly=False,
                                samesite='Strict', max_age=12 * 60 * 60, path='/')
        elif request.path == '/logout':
            response.delete_cookie('amt_csrf_v2', path='/')
        return response
