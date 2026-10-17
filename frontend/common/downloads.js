/* Fetch files first so API validation failures can be shown as notifications. */
window.downloadPiFile = async function(url, filename) {
  const response = await fetch(url);
  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.error || 'Unable to download the PI.');
  }
  if (!filename) {
    const disposition = response.headers?.get('Content-Disposition') || '';
    const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const plain = disposition.match(/filename="?([^";]+)/i);
    filename = encoded ? decodeURIComponent(encoded[1]) : plain ? plain[1].trim() : '';
  }
  const objectUrl = URL.createObjectURL(await response.blob());
  const link = document.createElement('a'); link.href = objectUrl; link.download = filename || '';
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
};
