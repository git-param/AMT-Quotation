let editingId = null;
let readOnly = false;
const scalarFields = ['name', 'company', 'email', 'phone', 'notes', 'business_details', 'status'];
const addressFields = ['line1', 'line2', 'city', 'state', 'postal_code', 'country'];
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
  byId('accessLink').style.display = data.can_manage_sharing ? 'inline-block' : 'none';
  byId('summary').textContent = `${data.leads.length} leads`;
  byId('leads').replaceChildren();
  data.leads.forEach(lead => {
    const row = document.createElement('tr');
    const date = new Date(lead.created_at);
    [lead.name, lead.company, lead.email, lead.phone, lead.creator_name, date.toLocaleString(), lead.notes].forEach(value => {
      const cell = document.createElement('td'); cell.textContent = value || '?'; row.append(cell);
    });
    const status = document.createElement('td');
    status.textContent = `${lead.status} / ${lead.is_active ? 'Active' : 'Inactive'}`; row.append(status);
    const access = document.createElement('td');
    const badge = document.createElement('span'); badge.className = 'badge ' + (lead.is_shared ? 'badge-ok' : 'badge-warn');
    badge.textContent = lead.is_shared ? `Shared / ${lead.shared_access_level}${lead.shared_access_level === 'VIEW' && lead.can_edit ? ' (independent edit)' : ''}` : (lead.can_edit ? 'Editable' : 'Read only');
    access.append(badge); row.append(access);
    const actions = document.createElement('td');
    {
      const button = document.createElement('button');
      button.className = 'btn-sm'; button.textContent = lead.can_edit ? 'Edit' : 'Details';
      button.setAttribute('aria-label', `Edit ${lead.name}`);
      button.onclick = async () => {
        try {
          const current = (await api(`/api/leads/${lead.id}`)).lead;
          readOnly = !current.can_edit;
          resetForm(); readOnly = !current.can_edit;
          editingId = current.id;
          scalarFields.forEach(field => { byId(field).value = current[field]; });
          byId('emails').value = current.emails.join('\n');
          byId('phones').value = current.phones.join('\n');
          current.contact_persons.forEach(addContact);
          ['billing', 'shipping'].forEach(kind => addressFields.forEach(field => { byId(`${kind}_${field}`).value = current[`${kind}_address`][field] || ''; }));
          byId('leadForm').querySelectorAll('input, select, textarea, #addContact, .remove-contact').forEach(control => { control.disabled = readOnly; });
          byId('save').hidden = readOnly;
          byId('formTitle').textContent = readOnly ? 'Client details' : 'Edit client lead';
          byId('save').textContent = 'Save changes';
          byId('cancelEdit').hidden = false;
          byId('name').focus();
          byId('leadForm').scrollIntoView({behavior: 'smooth', block: 'center'});
        } catch (error) { message(error.message, true); }
      };
      actions.append(button);
    }
    if (lead.can_manage_client) {
      const toggle = document.createElement('button'); toggle.className = 'btn-sm ' + (lead.is_active ? 'btn-del' : 'btn-activate');
      toggle.textContent = lead.is_active ? 'Deactivate' : 'Reactivate';
      toggle.onclick = async () => {
        toggle.disabled = true;
        try { await api(`/api/leads/${lead.id}/${lead.is_active ? 'deactivate' : 'activate'}`, {method: 'POST'}); await load(); message('Client availability updated. Shares and history retained.'); }
        catch (error) { message(error.message, true); }
        finally { toggle.disabled = false; }
      }; actions.append(toggle);
    }
    row.append(actions);
    byId('leads').append(row);
  });
  if (!data.leads.length) {
    const row = document.createElement('tr'); const cell = document.createElement('td');
    cell.colSpan = 10; cell.className = 'source-empty'; cell.textContent = 'No leads yet. Create your first lead above.';
    row.append(cell); byId('leads').append(row);
  }
}
byId('refresh').onclick = () => load().catch(error => message(error.message, true));
byId('leadForm').onsubmit = async event => {
  event.preventDefault(); byId('save').disabled = true;
  try {
    const wasEditing = editingId !== null;
    await api(wasEditing ? `/api/leads/${editingId}` : '/api/leads', {method: wasEditing ? 'PUT' : 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(formDetails())});
    resetForm(); await load(); message(wasEditing ? 'Client lead updated.' : 'Client lead created.');
  } catch (error) { message(error.message, true); }
  finally { byId('save').disabled = false; }
};
(async () => {
  try { await load(); byId('content').hidden = false; }
  catch (error) { message(error.message, true); }
})();

function resetForm() {
  editingId = null; readOnly = false; byId('leadForm').reset();
  byId('contacts').replaceChildren();
  byId('leadForm').querySelectorAll('input, select, textarea, button').forEach(control => { control.disabled = false; });
  byId('save').hidden = false;
  byId('formTitle').textContent = 'Add a client lead';
  byId('save').textContent = 'Create lead'; byId('cancelEdit').hidden = true;
}
byId('cancelEdit').onclick = resetForm;

function addContact(person = {}) {
  const row = document.createElement('div'); row.className = 'contact-row';
  ['name', 'email', 'phone'].forEach(field => {
    const input = document.createElement('input'); input.dataset.field = field;
    input.placeholder = field === 'name' ? 'Contact name' : field === 'email' ? 'Email' : 'Phone';
    input.setAttribute('aria-label', `Contact ${field}`);
    input.type = field === 'email' ? 'email' : field === 'phone' ? 'tel' : 'text';
    input.maxLength = field === 'name' ? 150 : field === 'email' ? 254 : 40;
    input.required = field === 'name'; input.value = person[field] || ''; row.append(input);
  });
  const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'btn-sm remove-contact'; remove.textContent = 'Remove'; remove.onclick = () => row.remove(); row.append(remove);
  byId('contacts').append(row);
}
byId('addContact').onclick = () => addContact();
function formDetails() {
  const details = Object.fromEntries(scalarFields.map(field => [field, byId(field).value]));
  ['emails', 'phones'].forEach(field => { details[field] = byId(field).value.split(/\n/).map(value => value.trim()).filter(Boolean); });
  details.contact_persons = [...byId('contacts').children].map(row => Object.fromEntries([...row.querySelectorAll('input')].map(input => [input.dataset.field, input.value])));
  ['billing', 'shipping'].forEach(kind => { details[`${kind}_address`] = Object.fromEntries(addressFields.map(field => [field, byId(`${kind}_${field}`).value.trim()]).filter(([,value]) => value)); });
  return details;
}
