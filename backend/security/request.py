"""Client metadata after optional trusted-proxy normalization."""
from flask import request


def client_ip():
    return (request.remote_addr or '').strip()[:64]


def user_agent():
    return (request.user_agent.string or '')[:500]
