(() => {
  const form = document.getElementById('settingsForm');
  const input = document.getElementById('hsnCode');
  const save = document.getElementById('save');
  const message = document.getElementById('message');
  const ratesMessage = document.getElementById('currencyRatesMessage');
  const ratesButton = document.getElementById('saveCurrencyRates');
  const refreshButton = document.getElementById('refreshCurrencyRates');
  function showRates(data) {
    for (const code of ['INR','AED','GBP','EUR']) {
      document.getElementById('rate'+code).textContent = data.rates?.[code] || 'Unavailable';
      const providers = data.providers?.[code] || [];
      document.getElementById('rateDate'+code).textContent = data.dates?.[code]
        ? 'Rate date: '+data.dates[code]+(providers.length?' · Providers: '+providers.join(', '):'')
        : 'No live rate yet';
    }
    document.getElementById('rateRefreshHours').value = data.refresh_hours;
    const source = document.getElementById('currencyRateSource');
    source.href = data.source_url; source.textContent = data.source;
    document.getElementById('currencyRateUpdated').textContent = data.fetched_at
      ? 'Last fetched: '+new Date(data.fetched_at).toLocaleString()+(data.stale?' — Rates are too old for new conversions.':'')
      : 'Waiting for the first live refresh.';
    if (data.last_error) { ratesMessage.className = 'error'; ratesMessage.textContent = 'Last refresh failed: '+data.last_error; }
  }
  async function ratesRequest(options) {
    const response = await fetch('/api/currency-rates', options); const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to load currency rates.');
    showRates(data);
    return data;
  }
  document.getElementById('currencyRatesForm').onsubmit = async event => {
    event.preventDefault(); ratesButton.disabled = true;
    try {
      const response = await fetch('/api/currency-rates/schedule', {method:'PUT',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({refresh_hours:Number(document.getElementById('rateRefreshHours').value)})});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Unable to save refresh interval.');
      showRates(data);ratesMessage.className = '';ratesMessage.textContent = 'Refresh interval saved.';
    } catch (error) { ratesMessage.className = 'error'; ratesMessage.textContent = error.message; }
    finally { ratesButton.disabled = false; }
  };
  refreshButton.onclick = async () => {
    refreshButton.disabled = true; ratesMessage.textContent = 'Fetching current published rates…';
    try {
      const response = await fetch('/api/currency-rates/refresh',{method:'POST'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Unable to refresh rates.');
      showRates(data);ratesMessage.className = '';ratesMessage.textContent = 'Rates refreshed.';
    } catch (error) { ratesMessage.className = 'error'; ratesMessage.textContent = error.message; }
    finally { refreshButton.disabled = false; }
  };
  ratesRequest().catch(error => { ratesMessage.className = 'error'; ratesMessage.textContent = error.message; });
  setInterval(() => ratesRequest().catch(error => {
    ratesMessage.className = 'error'; ratesMessage.textContent = error.message;
  }), 60000);
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

  const departmentForm = document.getElementById('departmentForm');
  const departmentName = document.getElementById('departmentName');
  const addDepartment = document.getElementById('addDepartment');
  const departmentMessage = document.getElementById('departmentMessage');
  let departmentSettings = [];
  const prefixForm = document.getElementById('departmentPrefixForm');
  const prefixDepartment = document.getElementById('prefixDepartment');
  const piPrefix = document.getElementById('piPrefix');
  const prefixMessage = document.getElementById('prefixMessage');
  const savePrefix = document.getElementById('saveDepartmentPrefix');
  function renderDepartments(names, settings = []) {
    departmentSettings = settings;
    const list = document.getElementById('departmentsList');
    list.replaceChildren();
    names.forEach(name => {
      const prefix = settings.find(row => row.name === name)?.pi_prefix;
      const item = document.createElement('li'); item.textContent = name + (prefix ? ` · ${prefix}/` : ''); list.append(item);
    });
    const selected = prefixDepartment.value;
    prefixDepartment.replaceChildren();
    settings.forEach(department => {
      const option = document.createElement('option'); option.value = String(department.id); option.textContent = department.name;
      prefixDepartment.append(option);
    });
    prefixDepartment.value = settings.some(row => String(row.id) === selected) ? selected : String(settings[0]?.id || '');
    piPrefix.value = settings.find(row => String(row.id) === prefixDepartment.value)?.pi_prefix || '';
    savePrefix.disabled = !settings.length;
    if (!names.length) departmentMessage.textContent = 'No departments configured yet.';
  }
  prefixDepartment.onchange = () => {
    piPrefix.value = departmentSettings.find(row => String(row.id) === prefixDepartment.value)?.pi_prefix || '';
    prefixMessage.textContent = '';
  };
  prefixForm.onsubmit = async event => {
    event.preventDefault(); savePrefix.disabled = true;
    try {
      const response = await fetch(`/api/departments/${prefixDepartment.value}/pi-prefix`, {
        method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({pi_prefix: piPrefix.value.trim()}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Unable to save PI prefix.');
      renderDepartments(data.departments, data.department_settings);
      prefixMessage.className = ''; prefixMessage.textContent = 'PI prefix saved.';
    } catch (error) { prefixMessage.className = 'error'; prefixMessage.textContent = error.message; }
    finally { savePrefix.disabled = !departmentSettings.length; }
  };
  async function departments(options) {
    const response = await fetch('/api/departments', options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to load departments.');
    return data;
  }
  departmentForm.onsubmit = async event => {
    event.preventDefault(); addDepartment.disabled = true;
    try {
      const data = await departments({method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: departmentName.value.trim(), pi_prefix: document.getElementById('departmentPrefix').value.trim()})});
      renderDepartments(data.departments, data.department_settings);
      document.getElementById('departmentPrefix').value = '';
      departmentName.value = ''; departmentMessage.className = ''; departmentMessage.textContent = 'Department added.';
    } catch (error) { departmentMessage.className = 'error'; departmentMessage.textContent = error.message; }
    finally { addDepartment.disabled = false; }
  };
  Promise.all([
    fetch('/api/me').then(async response => { if (!response.ok) throw new Error('Unable to load permissions.'); return response.json(); }),
    departments(),
  ]).then(([user, data]) => {
    departmentForm.hidden = !user.permissions.includes('users.manage');
    prefixForm.hidden = !user.permissions.includes('users.manage');
    document.getElementById('currencyRatesSection').hidden = !user.permissions.includes('users.manage');
    renderDepartments(data.departments, data.department_settings);
  }).catch(error => { departmentMessage.className = 'error'; departmentMessage.textContent = error.message; });
})();
