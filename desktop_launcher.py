"""Open AMT Quotation in a browser with the current Windows device identity."""
import argparse
import json
import os
import re
import socket
import subprocess
import urllib.parse
import webbrowser

from backend.security.mac import normalize_mac


def select_adapter(snapshot):
    """Prefer an up physical adapter with the lowest-cost default route."""
    routes = snapshot.get('routes') or []
    adapters = snapshot.get('adapters') or []
    if isinstance(routes, dict):
        routes = [routes]
    if isinstance(adapters, dict):
        adapters = [adapters]
    route_cost = {}
    for route in routes:
        try:
            index = int(route['InterfaceIndex'])
            cost = int(route['RouteMetric']) + int(route.get('InterfaceMetric') or 0)
        except (KeyError, TypeError, ValueError):
            continue
        route_cost[index] = min(cost, route_cost.get(index, cost))

    candidates = []
    for adapter in adapters:
        if adapter.get('Status') != 'Up' or adapter.get('HardwareInterface') is not True:
            continue
        description = (adapter.get('InterfaceDescription') or '').lower()
        if any(word in description for word in (
                'virtual', 'loopback', 'hyper-v', 'vmware', 'virtualbox',
                'docker', 'wsl', 'vpn', 'tunnel', 'tap-windows')):
            continue
        mac = normalize_mac(adapter.get('MacAddress'))
        if not mac:
            continue
        try:
            index = int(adapter['InterfaceIndex'])
        except (KeyError, TypeError, ValueError):
            continue
        name = (adapter.get('Name') or description or 'Network adapter').strip()
        candidates.append((index not in route_cost, route_cost.get(index, 10**9),
                           index, name, mac))
    if not candidates:
        return None
    _, _, _, name, mac = min(candidates)
    return name, mac


def adapter_from_ipconfig(output):
    """Fallback for Windows accounts denied access to Get-NetAdapter CIM data."""
    blocks = re.split(r'(?im)^\s*[^\r\n]*adapter\s+([^:\r\n]+):\s*$', output)
    adapters = []
    routes = []
    for position in range(1, len(blocks), 2):
        name, body = blocks[position].strip(), blocks[position + 1]
        def field(label):
            match = re.search(r'(?im)^\s*' + re.escape(label) + r'\s*\.[^:\r\n]*:\s*([^\r\n]*)', body)
            return match.group(1).strip() if match else ''
        description = field('Description')
        mac = field('Physical Address')
        if not mac:
            continue
        index = len(adapters) + 1
        disconnected = 'media disconnected' in body.lower()
        adapters.append({'InterfaceIndex': index, 'Name': name,
                         'InterfaceDescription': description, 'MacAddress': mac,
                         'Status': 'Disconnected' if disconnected else 'Up',
                         'HardwareInterface': True})
        if field('Default Gateway'):
            routes.append({'InterfaceIndex': index, 'RouteMetric': 0})
    return select_adapter({'adapters': adapters, 'routes': routes})


def physical_adapter():
    if os.name != 'nt':
        raise RuntimeError('The device launcher requires Windows.')
    command = (
        "$adapters = @(Get-NetAdapter -Physical -ErrorAction Stop | "
        "Select-Object Name,InterfaceDescription,InterfaceIndex,MacAddress,Status,HardwareInterface); "
        "$routes = @(Get-NetRoute -DestinationPrefix '0.0.0.0/0','::/0' "
        "-ErrorAction SilentlyContinue | Select-Object InterfaceIndex,RouteMetric,InterfaceMetric); "
        "@{adapters=$adapters;routes=$routes} | ConvertTo-Json -Compress -Depth 4"
    )
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
            capture_output=True, text=True, timeout=15, check=True)
        adapter = select_adapter(json.loads(result.stdout))
        if adapter:
            return adapter
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    result = subprocess.run(['ipconfig.exe', '/all'], capture_output=True,
                            text=True, timeout=15, check=True)
    return adapter_from_ipconfig(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:5062/login')
    args = parser.parse_args()
    try:
        adapter = physical_adapter()
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        raise SystemExit(f'Unable to read a physical network adapter: {exc}')
    if not adapter:
        raise SystemExit('No active physical adapter with a valid MAC address was found. Connect a physical network adapter and try again.')
    name = (os.environ.get('COMPUTERNAME') or socket.gethostname() or 'Windows device').strip()[:120]
    fragment = urllib.parse.urlencode({'mac': adapter[1], 'name': name})
    webbrowser.open(args.url.split('#', 1)[0] + '#' + fragment)


if __name__ == '__main__':
    main()
