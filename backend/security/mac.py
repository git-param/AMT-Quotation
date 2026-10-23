"""Dependency-free MAC normalization shared by the launcher and Flask app."""
import re


MAC_PATTERN = re.compile(r'^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$')


def normalize_mac(value):
    if not isinstance(value, str):
        return None
    value = value.strip().lower().replace('-', ':')
    if not MAC_PATTERN.fullmatch(value):
        return None
    octets = bytes.fromhex(value.replace(':', ''))
    if octets == b'\x00' * 6 or octets == b'\xff' * 6 or octets[0] & 1:
        return None
    return value
