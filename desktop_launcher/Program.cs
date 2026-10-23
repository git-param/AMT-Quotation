using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net.NetworkInformation;
using System.Windows.Forms;

namespace AMTQuotationLauncher
{
    internal static class Program
    {
        private static readonly string SettingsPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "AMT Quotation", "server-url.txt");

        [STAThread]
        private static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            string savedUrl = "http://127.0.0.1:5062/login";
            try
            {
                if (File.Exists(SettingsPath)) savedUrl = File.ReadAllText(SettingsPath).Trim();
            }
            catch (IOException) { }
            if (args.Length == 1) savedUrl = args[0];

            using (var form = new Form())
            using (var label = new Label())
            using (var address = new TextBox())
            using (var open = new Button())
            {
                form.Text = "AMT Quotation";
                form.Width = 510;
                form.Height = 170;
                form.FormBorderStyle = FormBorderStyle.FixedDialog;
                form.MaximizeBox = false;
                form.StartPosition = FormStartPosition.CenterScreen;
                label.Text = "Server address provided by your Admin:";
                label.SetBounds(20, 17, 450, 22);
                address.Text = savedUrl;
                address.SetBounds(20, 44, 450, 23);
                open.Text = "Open login";
                open.SetBounds(355, 82, 115, 30);
                form.AcceptButton = open;
                form.Controls.AddRange(new Control[] { label, address, open });
                open.Click += (sender, eventArgs) =>
                {
                    try
                    {
                        Uri loginUrl = ValidateUrl(address.Text);
                        string mac = PhysicalMac();
                        if (mac == null)
                            throw new InvalidOperationException("No active physical network adapter was found. Connect Wi-Fi or Ethernet and try again.");
                        string deviceName = Environment.MachineName;
                        if (deviceName.Length > 120) deviceName = deviceName.Substring(0, 120);
                        var builder = new UriBuilder(loginUrl) {
                            Fragment = "mac=" + Uri.EscapeDataString(mac) +
                                       "&name=" + Uri.EscapeDataString(deviceName)
                        };
                        var process = new ProcessStartInfo(builder.Uri.AbsoluteUri) { UseShellExecute = true };
                        Process.Start(process);
                        Directory.CreateDirectory(Path.GetDirectoryName(SettingsPath));
                        File.WriteAllText(SettingsPath, loginUrl.AbsoluteUri);
                        form.Close();
                    }
                    catch (Exception error)
                    {
                        MessageBox.Show(form, error.Message, "AMT Quotation", MessageBoxButtons.OK,
                            MessageBoxIcon.Warning);
                    }
                };
                Application.Run(form);
            }
        }

        private static Uri ValidateUrl(string value)
        {
            Uri url;
            if (!Uri.TryCreate(value.Trim(), UriKind.Absolute, out url) ||
                (url.Scheme != Uri.UriSchemeHttps &&
                 !(url.Scheme == Uri.UriSchemeHttp &&
                   (url.Host == "127.0.0.1" || url.Host == "localhost"))))
                throw new ArgumentException("Enter your HTTPS server address, or the local http://127.0.0.1:5062/login address.");
            if (url.UserInfo.Length != 0)
                throw new ArgumentException("Do not put a username or password in the server address.");
            return new UriBuilder(url) { Path = "/login", Query = "", Fragment = "" }.Uri;
        }

        private static string PhysicalMac()
        {
            var adapters = NetworkInterface.GetAllNetworkInterfaces()
                .Where(adapter => adapter.OperationalStatus == OperationalStatus.Up &&
                    (adapter.NetworkInterfaceType == NetworkInterfaceType.Wireless80211 ||
                     adapter.NetworkInterfaceType == NetworkInterfaceType.Ethernet ||
                     adapter.NetworkInterfaceType == NetworkInterfaceType.GigabitEthernet ||
                     adapter.NetworkInterfaceType == NetworkInterfaceType.FastEthernetT ||
                     adapter.NetworkInterfaceType == NetworkInterfaceType.FastEthernetFx))
                .Where(adapter => {
                    string name = (adapter.Name + " " + adapter.Description).ToLowerInvariant();
                    return !new[] { "virtual", "loopback", "hyper-v", "vmware", "virtualbox",
                        "docker", "wsl", "vpn", "tunnel", "tap-windows" }.Any(name.Contains);
                })
                .Select(adapter => new {
                    Adapter = adapter,
                    Bytes = adapter.GetPhysicalAddress().GetAddressBytes(),
                    HasGateway = adapter.GetIPProperties().GatewayAddresses.Any()
                })
                .Where(item => item.Bytes.Length == 6 && item.Bytes.Any(value => value != 0))
                .OrderByDescending(item => item.HasGateway)
                .ThenBy(item => item.Adapter.Id)
                .FirstOrDefault();
            if (adapters == null) return null;
            return string.Join(":", adapters.Bytes.Select(value => value.ToString("x2")));
        }
    }
}
