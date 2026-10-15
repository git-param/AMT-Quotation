(() => {
  const form = document.getElementById('settingsForm');
  const input = document.getElementById('hsnCode');
  const save = document.getElementById('save');
  const message = document.getElementById('message');
  async function request(options) {
    const response = await fetch('/api/settings', options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to load configuration.');
    return data;
  }
  form.onsubmit = async event => {
    event.preventDefault(); save.disabled = true;
    try {
      const data = await request({method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({hsn_code: input.value.trim()})});
      input.value = data.hsn_code; message.className = ''; message.textContent = 'Shared HSN code saved for all SKUs.';
    } catch (error) { message.className = 'error'; message.textContent = error.message; }
    finally { save.disabled = false; }
  };
  request().then(data => { input.value = data.hsn_code; save.disabled = false; })
    .catch(error => { message.className = 'error'; message.textContent = error.message; input.disabled = true; });
})();
