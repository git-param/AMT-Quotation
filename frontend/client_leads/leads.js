let editingId = null;
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
    const actions = document.createElement('td');
    if (lead.can_edit) {
      const button = document.createElement('button');
      button.className = 'btn-sm'; button.textContent = 'Edit';
      button.setAttribute('aria-label', `Edit ${lead.name}`);
      button.onclick = async () => {
        try {
          const current = (await api(`/api/leads/${lead.id}`)).lead;
          if (!current.can_edit) throw new Error('Edit access is no longer available.');
          editingId = current.id;
          ['name', 'company', 'email', 'phone', 'notes'].forEach(field => { byId(field).value = current[field]; });
          byId('formTitle').textContent = 'Edit client lead';
          byId('save').textContent = 'Save changes';
          byId('cancelEdit').hidden = false;
          byId('name').focus();
          byId('leadForm').scrollIntoView({behavior: 'smooth', block: 'center'});
        } catch (error) { message(error.message, true); }
      };
      actions.append(button);
    } else { actions.textContent = 'Read only'; }
    row.append(actions);
    byId('leads').append(row);
  });
  if (!data.leads.length) {
    const row = document.createElement('tr'); const cell = document.createElement('td');
    cell.colSpan = 8; cell.className = 'source-empty'; cell.textContent = 'No leads yet. Create your first lead above.';
    row.append(cell); byId('leads').append(row);
  }
}
byId('refresh').onclick = () => load().catch(error => message(error.message, true));
byId('leadForm').onsubmit = async event => {
  event.preventDefault(); byId('save').disabled = true;
  try {
    const wasEditing = editingId !== null;
    await api(wasEditing ? `/api/leads/${editingId}` : '/api/leads', {method: wasEditing ? 'PUT' : 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(Object.fromEntries(new FormData(event.target)))});
    resetForm(); await load(); message(wasEditing ? 'Client lead updated.' : 'Client lead created.');
  } catch (error) { message(error.message, true); }
  finally { byId('save').disabled = false; }
};
(async () => {
  try { await load(); byId('content').hidden = false; }
  catch (error) { message(error.message, true); }
})();

function resetForm() {
  editingId = null; byId('leadForm').reset();
  byId('formTitle').textContent = 'Add a client lead';
  byId('save').textContent = 'Create lead'; byId('cancelEdit').hidden = true;
}
byId('cancelEdit').onclick = resetForm;
