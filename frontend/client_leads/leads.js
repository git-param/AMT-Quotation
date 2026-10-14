const byId = id => document.getElementById(id);
function message(text, error = false) { byId('message').textContent = text; byId('message').className = error ? 'error' : ''; }
async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (response.status === 401) { byId('content').hidden = true; throw new Error('Session ended. Please sign in again.'); }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Unable to complete this action.');
  return data;
}
async function load() {
  const data = await api('/api/leads');
  byId('hdrUser').textContent = data.username;
  byId('summary').textContent = `${data.leads.length} leads`;
  byId('leads').replaceChildren();
  data.leads.forEach(lead => {
    const row = document.createElement('tr');
    const date = new Date(lead.created_at);
    [lead.name, lead.company, lead.email, lead.phone, lead.creator_name, date.toLocaleString(), lead.notes].forEach(value => {
      const cell = document.createElement('td'); cell.textContent = value || '?'; row.append(cell);
    });
    byId('leads').append(row);
  });
  if (!data.leads.length) {
    const row = document.createElement('tr'); const cell = document.createElement('td');
    cell.colSpan = 7; cell.className = 'source-empty'; cell.textContent = 'No leads yet. Create your first lead above.';
    row.append(cell); byId('leads').append(row);
  }
}
byId('refresh').onclick = () => load().catch(error => message(error.message, true));
byId('leadForm').onsubmit = async event => {
  event.preventDefault(); byId('save').disabled = true;
  try {
    await api('/api/leads', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(Object.fromEntries(new FormData(event.target)))});
    event.target.reset(); await load(); message('Client lead created.');
  } catch (error) { message(error.message, true); }
  finally { byId('save').disabled = false; }
};
(async () => {
  try { await load(); byId('content').hidden = false; }
  catch (error) { message(error.message, true); }
})();
