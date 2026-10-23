"""The launcher selects a connected physical adapter without user input."""
import unittest
import subprocess
from unittest.mock import patch

import desktop_launcher


class LauncherTests(unittest.TestCase):
    def test_prefers_default_route_on_physical_adapter(self):
        snapshot = {'routes': [
            {'InterfaceIndex': 5, 'RouteMetric': 10, 'InterfaceMetric': 10},
            {'InterfaceIndex': 8, 'RouteMetric': 1, 'InterfaceMetric': 1},
        ], 'adapters': [
            {'InterfaceIndex': 8, 'Name': 'VPN', 'InterfaceDescription': 'Virtual VPN adapter',
             'Status': 'Up', 'HardwareInterface': True, 'MacAddress': '02-11-22-33-44-08'},
            {'InterfaceIndex': 5, 'Name': 'Wi-Fi', 'InterfaceDescription': 'Intel Wireless',
             'Status': 'Up', 'HardwareInterface': True, 'MacAddress': '02-11-22-33-44-05'},
            {'InterfaceIndex': 3, 'Name': 'Ethernet', 'InterfaceDescription': 'Intel Ethernet',
             'Status': 'Up', 'HardwareInterface': True, 'MacAddress': '02-11-22-33-44-03'},
        ]}
        self.assertEqual(desktop_launcher.select_adapter(snapshot),
                         ('Wi-Fi', '02:11:22:33:44:05'))

    def test_ignores_disconnected_virtual_and_invalid_adapters(self):
        adapters = [
            {'InterfaceIndex': 1, 'Name': 'Disconnected', 'InterfaceDescription': 'Intel',
             'Status': 'Disconnected', 'HardwareInterface': True, 'MacAddress': '02-11-22-33-44-01'},
            {'InterfaceIndex': 2, 'Name': 'Virtual', 'InterfaceDescription': 'Hyper-V Virtual Ethernet',
             'Status': 'Up', 'HardwareInterface': True, 'MacAddress': '02-11-22-33-44-02'},
            {'InterfaceIndex': 3, 'Name': 'Invalid', 'InterfaceDescription': 'Intel',
             'Status': 'Up', 'HardwareInterface': True, 'MacAddress': '00-00-00-00-00-00'},
        ]
        self.assertIsNone(desktop_launcher.select_adapter({'routes': [], 'adapters': adapters}))

    def test_launches_browser_with_computer_name_and_detected_mac(self):
        with patch('desktop_launcher.physical_adapter', return_value=('Wi-Fi', '02:11:22:33:44:05')), \
                patch('desktop_launcher.webbrowser.open') as open_browser, \
                patch('desktop_launcher.os.environ', {'COMPUTERNAME': 'SALES-PC'}), \
                patch('sys.argv', ['desktop_launcher.py', '--url', 'https://example.invalid/login']), \
                patch('builtins.input', side_effect=AssertionError('No prompt allowed')):
            desktop_launcher.main()
        open_browser.assert_called_once_with(
            'https://example.invalid/login#mac=02%3A11%3A22%3A33%3A44%3A05&name=SALES-PC')

    def test_missing_adapter_stops_without_opening_browser(self):
        with patch('desktop_launcher.physical_adapter', return_value=None), \
                patch('desktop_launcher.webbrowser.open') as open_browser, \
                patch('sys.argv', ['desktop_launcher.py']):
            with self.assertRaisesRegex(SystemExit, 'No active physical adapter'):
                desktop_launcher.main()
        open_browser.assert_not_called()

    def test_ipconfig_fallback_ignores_virtual_and_disconnected(self):
        output = '''Ethernet adapter Ethernet:
   Media State . . . . . . . . . . . : Media disconnected
   Description . . . . . . . . . . . : Intel Ethernet
   Physical Address. . . . . . . . . : 02-11-22-33-44-01

Wireless LAN adapter Virtual:
   Description . . . . . . . . . . . : Microsoft Wi-Fi Direct Virtual Adapter
   Physical Address. . . . . . . . . : 02-11-22-33-44-02
   Default Gateway . . . . . . . . . : 192.168.1.1

Wireless LAN adapter Wi-Fi:
   Description . . . . . . . . . . . : Intel Wireless
   Physical Address. . . . . . . . . : 02-11-22-33-44-03
   Default Gateway . . . . . . . . . : 192.168.1.1
'''
        self.assertEqual(desktop_launcher.adapter_from_ipconfig(output),
                         ('Wi-Fi', '02:11:22:33:44:03'))
        denied = subprocess.CalledProcessError(1, 'powershell.exe')
        with patch('desktop_launcher.subprocess.run', side_effect=[
                denied, subprocess.CompletedProcess(['ipconfig.exe'], 0, stdout=output)]) as run:
            self.assertEqual(desktop_launcher.physical_adapter(),
                             ('Wi-Fi', '02:11:22:33:44:03'))
        self.assertEqual(run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
