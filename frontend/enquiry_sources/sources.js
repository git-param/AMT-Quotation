let sources = [];
let editingId = null;
const byId = id => document.getElementById(id);
function message(text, error = false) {
  byId('message').textContent = text;
  byId('message').className = error ? 'error' : '';
}
async function api(path, options = {}) {
  const response = await fetch(path, options);
  if ([401, 403].includes(response.status)) {
    byId('content').hidden = true;
    throw new Error(response.status === 401 ? 'Session ended. Please sign in again.' : 'Access denied. Your role cannot manage sources.');
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Unable to complete this action.');
  return data;
}
function channelChanged() {
  const email = byId('kind').value === 'email';
  byId('contactLabel').textContent = email ? 'Email address' : 'WhatsApp number';
  byId('contact').type = email ? 'email' : 'tel';
  byId('contact').placeholder = email ? 'sales@example.com' : '+919876543210';
  byId('contactHint').textContent = email ? 'Enter the email address used for enquiries.' : 'Include + and the country code.';
}
function resetForm() {
  editingId = null;
  byId('sourceForm').reset();
  byId('formTitle').textContent = 'Add an enquiry source';
  byId('save').textContent = 'Add source';
  byId('cancel').hidden = true;
  channelChanged();
}
function edit(source) {
  editingId = source.id;
  byId('name').value = source.name;
  byId('kind').value = source.source_type || 'email';
  byId('contact').value = source.contact_value || '';
  byId('formTitle').textContent = 'Edit enquiry source';
  byId('save').textContent = 'Save changes';
  byId('cancel').hidden = false;
  channelChanged();
  byId('name').focus();
  byId('sourceForm').scrollIntoView({behavior: 'smooth', block: 'center'});
}
function render() {
  const filter = byId('filter').value;
  const visible = sources.filter(s => filter === 'all' || Boolean(s.is_active) === (filter === 'active'));
  const active = sources.filter(s => s.is_active).length;
  byId('summary').textContent = `${sources.length} sources / ${active} active`;
  byId('sources').replaceChildren();
  visible.forEach(source => {
    const row = document.createElement('tr');
    [source.name, source.source_type === 'whatsapp' ? 'WhatsApp' : source.source_type === 'email' ? 'Email' : 'Unclassified', source.contact_value || 'Contact not yet set'].forEach(value => {
      const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
    });
    const status = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = `badge ${source.is_active ? 'badge-ok' : 'badge-warn'}`;
    badge.textContent = source.is_active ? 'Active' : 'Inactive'; status.append(badge); row.append(status);
    const actions = document.createElement('td');
    const controls = document.createElement('div'); controls.className = 'source-controls';
    const editButton = document.createElement('button'); editButton.className = 'btn-sm'; editButton.textContent = 'Edit';
    editButton.setAttribute('aria-label', `Edit ${source.name}`); editButton.onclick = () => edit(source);
    const toggle = document.createElement('button'); toggle.className = `btn-sm ${source.is_active ? 'btn-del' : 'btn-activate'}`;
    toggle.textContent = source.is_active ? 'Deactivate' : 'Activate';
    toggle.setAttribute('aria-label', `${toggle.textContent} ${source.name}`);
    toggle.onclick = async () => {
      toggle.disabled = true;
      try {
        await api(`/api/sources/${source.id}/${source.is_active ? 'deactivate' : 'activate'}`, {method: 'POST'});
        await load(); message('Source status updated.');
      } catch (error) { message(error.message, true); }
      finally { toggle.disabled = false; }
    };
    controls.append(editButton, toggle); actions.append(controls); row.append(actions); byId('sources').append(row);
  });
  if (!visible.length) {
    const row = document.createElement('tr'); const cell = document.createElement('td');
    cell.colSpan = 5; cell.className = 'source-empty';
    const icon = document.createElement('span'); icon.className = 'empty-icon'; icon.textContent = '@'; icon.setAttribute('aria-hidden', 'true');
    const title = document.createElement('strong'); title.className = 'empty-title';
    title.textContent = sources.length ? 'No matching sources' : 'Add your first enquiry source';
    const description = document.createElement('p'); description.className = 'empty-description';
    description.textContent = sources.length ? 'Choose another status filter to see your sources.' : 'Start with an email inbox or WhatsApp number using the form above.';
    cell.append(icon, title, description);
    row.append(cell); byId('sources').append(row);
  }
}
async function load() { sources = (await api('/api/sources')).sources; render(); }
byId('kind').onchange = channelChanged;
byId('cancel').onclick = resetForm;
byId('filter').onchange = render;
byId('sourceForm').onsubmit = async event => {
  event.preventDefault(); byId('save').disabled = true;
  try {
    await api(editingId === null ? '/api/sources' : `/api/sources/${editingId}`, {
      method: editingId === null ? 'POST' : 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: byId('name').value, source_type: byId('kind').value, contact_value: byId('contact').value})
    });
    resetForm(); await load(); message('Source saved.');
  } catch (error) { message(error.message, true); }
  finally { byId('save').disabled = false; }
};
(async () => {
  try {
    const user = await api('/api/me');
    byId('hdrUser').textContent = user.username;
    if (!user.permissions.includes('sources.manage')) throw new Error('Access denied. Your role cannot manage sources.');
    await load(); byId('content').hidden = false;
  } catch (error) { message(error.message, true); }
})();
