from flask import request

def _get_ip():
    return (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()


