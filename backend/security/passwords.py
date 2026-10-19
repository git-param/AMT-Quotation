"""Account password policy."""


def error(password):
    if not isinstance(password, str) or len(password) < 12:
        return 'Password must be at least 12 characters'
    if len(password) > 128:
        return 'Password must be 128 characters or fewer'
    if password.strip() != password:
        return 'Password cannot begin or end with spaces'
    return None
