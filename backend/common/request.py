from backend.security.request import client_ip


def _get_ip():
    return client_ip()


