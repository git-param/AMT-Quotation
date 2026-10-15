let profileVersion=0;
let currentPage = 1;
let totalPages = 0;
let loadVersion = 0;
let editingId = null;
let readOnly = false;
const scalarFields = ['name', 'company', 'email', 'phone', 'notes', 'location'];
const byId = id => document.getElementById(id);
function clientActionButton(action, name, style = '') {
  const icons = {
    details: ['View details', 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z'],
    edit: ['Edit', 'm16 3 5 5-12 12-6 1 1-6L16 3Z M13 6l5 5'],
    deactivate: ['Deactivate', 'M12 3v9 M6 5a9 9 0 1 0 12 0'],
    activate: ['Reactivate', 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z m-14 0 3 3 7-7'],
    delete: ['Delete', 'M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7'],
  };
  const [label, path] = icons[action];
  const button = document.createElement('button');
  button.type = 'button';
  button.className = `btn-sm client-action-icon ${style}`;
  button.title = label;
  button.setAttribute('aria-label', `${label}: ${name}`);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.8');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const shape = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  shape.setAttribute('d', path);
  svg.append(shape);button.append(svg);
  return button;
}
function message(text, error = false) { byId('message').textContent = text; byId('message').className = error ? 'error' : ''; }
async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (response.status === 401) { byId('content').hidden = true; throw new Error('Session ended. Please sign in again.'); }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Unable to complete this action.');
  return data;
}
async function load() {
  const version = ++loadVersion;
  const params = new URLSearchParams({page: currentPage, page_size: byId('pageSize').value});
  const fields = {q:'search', active:'filterActive', ownership:'filterOwnership', creator:'filterCreator', access:'filterAccess', source:'filterSource', sort:'sort', direction:'direction'};
  Object.entries(fields).forEach(([key,id]) => params.set(key, byId(id).value));
  const data = await api('/api/leads?' + params);
  if (version !== loadVersion) return;
  totalPages = data.pages;
  if (currentPage > Math.max(1, totalPages)) { currentPage = Math.max(1,totalPages); return load(); }
  byId('pageInfo').textContent = `Page ${data.page} of ${Math.max(1,data.pages)}`;
  byId('previousPage').disabled = currentPage <= 1;
  byId('nextPage').disabled = currentPage >= totalPages;
  byId('hdrUser').textContent = data.username;
  byId('accessLink').style.display = data.can_manage_sharing ? 'inline-block' : 'none';
  byId('summary').textContent = `${data.total} matching clients`;
  byId('leads').replaceChildren();
  data.leads.forEach(lead => {
    const row = document.createElement('tr');
    [[lead.name,lead.company].filter(Boolean).join('\n'),[lead.email,lead.phone].filter(Boolean).join('\n'),lead.creator_name].forEach((value,index)=>{
      const cell=document.createElement('td');cell.textContent=value||'-';cell.dataset.label=['Client / company','Contact','Owner'][index];row.append(cell);
    });
    const ordersCell=document.createElement('td');ordersCell.dataset.label='Orders / pending';
    const ordersLink=document.createElement('button');ordersLink.type='button';ordersLink.className='btn-sm';
    ordersLink.textContent=`${lead.order_count} orders / ${lead.pending_order_count} pending`;
    ordersLink.onclick=()=>openDetails(lead.id).catch(error=>message(error.message,true));
    ordersCell.append(ordersLink);row.append(ordersCell);
    const status = document.createElement('td');status.dataset.label='Availability';
    status.textContent = lead.is_active ? 'Active' : 'Inactive'; row.append(status);
    const access = document.createElement('td');access.dataset.label='Access';
    const badge = document.createElement('span'); badge.className = 'badge ' + (lead.is_shared ? 'badge-ok' : 'badge-warn');
    badge.textContent = lead.is_shared ? `Shared / ${lead.shared_access_level}${lead.shared_access_level === 'VIEW' && lead.can_edit ? ' (independent edit)' : ''}` : (lead.can_edit ? 'Editable' : 'Read only');
    access.append(badge); row.append(access);
    const actions = document.createElement('td'); actions.className = 'client-actions';actions.dataset.label='Actions';
    const detailsButton = clientActionButton('details', lead.name);
    detailsButton.onclick = () => openDetails(lead.id).catch(error => message(error.message, true)); actions.append(detailsButton);
    if (lead.can_edit) {
      const button = clientActionButton('edit', lead.name);
      button.onclick = () => editClient(lead.id);
      actions.append(button);
    }
    if (lead.can_manage_client) {
      const toggle = clientActionButton(lead.is_active ? 'deactivate' : 'activate', lead.name, lead.is_active ? 'btn-del' : 'btn-activate');
      toggle.onclick = async () => {
        toggle.disabled = true;
        try { await api(`/api/leads/${lead.id}/${lead.is_active ? 'deactivate' : 'activate'}`, {method: 'POST'}); await load(); message('Client availability updated. Shares and history retained.'); }
        catch (error) { message(error.message, true); }
        finally { toggle.disabled = false; }
      }; actions.append(toggle);
    }
    if (lead.can_delete) {
      const remove = clientActionButton('delete', lead.name, 'btn-del');
      remove.onclick=()=>deleteClient(lead).catch(error=>message(error.message,true));
      actions.append(remove);
    }
    row.append(actions);
    byId('leads').append(row);
  });
  if (!data.leads.length) {
    const row = document.createElement('tr'); const cell = document.createElement('td');
    cell.colSpan = 7; cell.className = 'source-empty'; cell.textContent = 'No clients match these filters. Add a client or adjust your search.';
    row.append(cell); byId('leads').append(row);
  }
}
async function editClient(id) {
        try {
          const current = (await api(`/api/leads/${id}`)).lead;
          resetForm(); readOnly = !current.can_edit;
          editingId = current.id;
          scalarFields.forEach(field => { byId(field).value = current[field]; });
          setSource(current);
          byId('emails').value = current.emails.join('\n');
          byId('phones').value = current.phones.join('\n');
          current.contact_persons.forEach(addContact);
          byId('leadForm').querySelectorAll('input, select, textarea, #addContact, .remove-contact').forEach(control => { control.disabled = readOnly; });
          openForm();
          byId('save').hidden = readOnly;
          byId('formTitle').textContent = readOnly ? 'Client details' : 'Edit client';
          byId('save').textContent = 'Save changes';
          byId('cancelEdit').hidden = false;
          byId('name').focus();
          byId('leadForm').scrollIntoView({behavior: 'smooth', block: 'center'});
        } catch (error) { message(error.message, true); }
}
async function deleteClient(client) {
  if (!window.confirm(`Delete client ${client.name}? Its orders and invoices will be hidden; all history will be retained.`)) return;
  await api(`/api/leads/${client.id}`, {method:'DELETE'});
  resetForm();closeForm();byId('clientDetail').hidden=true;byId('directoryPanel').hidden=false;
  await loadOptions();await load();message('Client deleted. History retained.');
}
byId('refresh').onclick = () => load().catch(error => message(error.message, true));
byId('leadForm').onsubmit = async event => {
  event.preventDefault(); byId('save').disabled = true;
  try {
    const wasEditing = editingId !== null;
    const saved = await api(wasEditing ? `/api/leads/${editingId}` : '/api/leads', {method: wasEditing ? 'PUT' : 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(formDetails())});
    resetForm(); closeForm(); byId('clientDetail').hidden = true; await loadOptions(); await load(); message(wasEditing ? 'Client updated.' : 'Client created.');await openDetails(saved.lead.id);
  } catch (error) { message(error.message, true); }
  finally { byId('save').disabled = false; }
};
(async () => {
  try { await loadOptions(); await load(); byId('content').hidden = false; const id = new URLSearchParams(location.search).get('client_id'); if (id) await openDetails(id); }
  catch (error) { message(error.message, true); }
})();

function resetForm() {
  editingId = null; readOnly = false; byId('leadForm').reset();
  byId('contacts').replaceChildren();
  byId('leadForm').querySelectorAll('input, select, textarea, button').forEach(control => { control.disabled = false; });
  byId('save').hidden = false;
  byId('formTitle').textContent = 'Add a client';
  byId('save').textContent = 'Create client'; byId('cancelEdit').hidden = true;
}
byId('cancelEdit').onclick = () => { resetForm(); closeForm(); };
byId('addLead').onclick = () => { resetForm(); openForm(); byId('name').focus(); };

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
  details.enquiry_source_id = byId('enquiry_source_id').value ? Number(byId('enquiry_source_id').value) : null;
  return details;
}

function openForm() {
  byId('leadEditor').hidden = false;
  byId('addLead').setAttribute('aria-expanded', 'true');
  byId('cancelEdit').hidden = false;
  byId('leadEditor').scrollIntoView({behavior: 'smooth', block: 'start'});
}
function closeForm() {
  byId('leadEditor').hidden = true;
  byId('addLead').setAttribute('aria-expanded', 'false');
  byId('addLead').focus();
}
async function loadOptions() {
  const data = await api('/api/leads/options');
  const creator = byId('filterCreator').value;
  byId('filterCreator').replaceChildren(new Option('All accessible creators',''), ...data.creators.map(u => new Option(u.username,u.id)));
  if ([...byId('filterCreator').options].some(o => o.value === creator)) byId('filterCreator').value = creator;
  const oldSource = byId('filterSource').value;
  byId('filterSource').replaceChildren(new Option('All sources',''), ...data.filter_sources.map(s => new Option(`${s.name}${s.is_active === 0 ? ' (inactive)' : ''}`,s.id)));
  if ([...byId('filterSource').options].some(o => o.value === oldSource)) byId('filterSource').value = oldSource;
  byId('enquiry_source_id').replaceChildren(new Option('Not specified',''), ...data.sources.map(s => new Option(s.name,s.id)));
}
function setSource(client) {
  const select = byId('enquiry_source_id');
  if (client.enquiry_source_id && ![...select.options].some(o => Number(o.value) === client.enquiry_source_id)) {
    select.add(new Option(`${client.enquiry_source_name} (inactive)`,client.enquiry_source_id));
  }
  select.value = client.enquiry_source_id || '';
}
async function openDetails(id) {
  const version=++profileVersion;
  const data = await api(`/api/leads/${id}`);if(version!==profileVersion)return; const client = data.lead;
  history.replaceState(null,'',`/clients-orders?client_id=${id}`);
  byId('detailTitle').textContent = client.name;
  byId('detailAvatar').textContent = client.name.trim().split(/\s+/).slice(0,2).map(part=>part[0]).join('').toUpperCase();
  byId('detailSubtitle').textContent = client.company || 'Client profile';
  byId('detailBadges').replaceChildren();
  const accessLabel = client.is_shared ? `Shared ${client.shared_access_level} / ${client.can_edit ? 'Editable' : 'Read only'}` : client.can_edit ? 'Editable' : 'Read only';
  for (const [label, style] of [[client.is_active ? 'Active' : 'Inactive', client.is_active ? 'client-active' : 'client-inactive'], [accessLabel, 'client-access']]) {
    const badge=document.createElement('span');badge.className=style;badge.textContent=label;byId('detailBadges').append(badge);
  }
  byId('detailActions').replaceChildren();
  if(client.can_edit){const edit=clientActionButton('edit',client.name);edit.onclick=()=>editClient(client.id);byId('detailActions').append(edit);}
  if(client.can_delete){const remove=clientActionButton('delete',client.name,'btn-del');remove.onclick=()=>deleteClient(client).catch(error=>message(error.message,true));byId('detailActions').append(remove);}
  byId('detailBody').replaceChildren();
  const section = (label, value) => {
    const block = document.createElement('section'); const heading = document.createElement('h3'); heading.textContent = label;
    const text = document.createElement('p'); text.textContent = value || 'Not provided';
    if (!value) block.classList.add('detail-empty');
    if (label === 'Notes') block.classList.add('detail-notes');
    block.append(heading,text); byId('detailBody').append(block);
  };
  section('Company information', client.company);
  section('Contacts', [...new Set([client.email,client.phone,...client.emails,...client.phones,...client.contact_persons.map(c => [c.name,c.email,c.phone].filter(Boolean).join(' / '))].filter(Boolean))].join('\n'));
  section('Location',client.location);
  section('Notes',client.notes);
  section('Owner and creation',`${client.creator_name}\nCreated ${new Date(client.created_at).toLocaleString('en-GB',{dateStyle:'medium',timeStyle:'short'})}`);
  section('Enquiry source',client.enquiry_source_name ? `${client.enquiry_source_name}${client.enquiry_source_active ? '' : ' (inactive)'}` : 'Not specified');
  await window.renderRelatedOrders(byId('detailBody'),{client_id:id},client.can_edit&&client.is_active);
  if(version!==profileVersion)return;
  byId('directoryPanel').hidden=true;
  byId('clientDetail').hidden = false; byId('clientDetail').scrollIntoView({behavior:'smooth',block:'start'});
}
byId('closeDetail').onclick = byId('backDirectory').onclick = () => { profileVersion++;byId('clientDetail').hidden = true;byId('directoryPanel').hidden=false;history.replaceState(null,'','/clients-orders'); };
byId('discoveryForm').onsubmit = event => { event.preventDefault(); currentPage = 1; load().catch(error => message(error.message,true)); };
byId('clearFilters').onclick = () => { byId('discoveryForm').reset(); currentPage = 1; load().catch(error => message(error.message,true)); };
byId('previousPage').onclick = () => { if (currentPage > 1) { currentPage--; load().catch(error => message(error.message,true)); } };
byId('nextPage').onclick = () => { if (currentPage < totalPages) { currentPage++; load().catch(error => message(error.message,true)); } };
byId('pageSize').onchange = () => { currentPage = 1; load().catch(error => message(error.message,true)); };
