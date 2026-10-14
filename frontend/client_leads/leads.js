let currentPage = 1;
let totalPages = 0;
let loadVersion = 0;
let editingId = null;
let readOnly = false;
let separateShipping = null;
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
  const version = ++loadVersion;
  const params = new URLSearchParams({page: currentPage, page_size: byId('pageSize').value});
  const fields = {q:'search', status:'filterStatus', active:'filterActive', ownership:'filterOwnership', creator:'filterCreator', access:'filterAccess', source:'filterSource', sort:'sort', direction:'direction'};
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
    const date = new Date(lead.created_at);
    [lead.name, lead.company, lead.email, lead.phone, lead.creator_name, date.toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'}), lead.notes].forEach(value => {
      const cell = document.createElement('td'); cell.textContent = value || '-'; cell.title = value || ''; row.append(cell);
    });
    const enquiryCell = document.createElement('td');
    const enquiryLink = document.createElement('a'); enquiryLink.className = 'enquiry-count';
    enquiryLink.href = `/enquiries?client_id=${lead.id}`; enquiryLink.textContent = `${lead.enquiry_count} ${lead.enquiry_count === 1 ? 'enquiry' : 'enquiries'}`;
    enquiryCell.append(enquiryLink); row.append(enquiryCell);
    const status = document.createElement('td');
    status.textContent = `${lead.status} / ${lead.is_active ? 'Active' : 'Inactive'}`; row.append(status);
    const access = document.createElement('td');
    const badge = document.createElement('span'); badge.className = 'badge ' + (lead.is_shared ? 'badge-ok' : 'badge-warn');
    badge.textContent = lead.is_shared ? `Shared / ${lead.shared_access_level}${lead.shared_access_level === 'VIEW' && lead.can_edit ? ' (independent edit)' : ''}` : (lead.can_edit ? 'Editable' : 'Read only');
    access.append(badge); row.append(access);
    const actions = document.createElement('td'); actions.className = 'client-actions';
    const detailsButton = document.createElement('button'); detailsButton.className = 'btn-sm'; detailsButton.textContent = 'Details';
    detailsButton.onclick = () => openDetails(lead.id).catch(error => message(error.message, true)); actions.append(detailsButton);
    if (lead.can_edit) {
      const button = document.createElement('button');
      button.className = 'btn-sm'; button.textContent = lead.can_edit ? 'Edit' : 'Details';
      button.setAttribute('aria-label', `Edit ${lead.name}`);
      button.onclick = async () => {
        try {
          const current = (await api(`/api/leads/${lead.id}`)).lead;
          resetForm(); readOnly = !current.can_edit;
          editingId = current.id;
          scalarFields.forEach(field => { byId(field).value = current[field]; });
          setSource(current);
          byId('emails').value = current.emails.join('\n');
          byId('phones').value = current.phones.join('\n');
          current.contact_persons.forEach(addContact);
          ['billing', 'shipping'].forEach(kind => addressFields.forEach(field => { byId(`${kind}_${field}`).value = current[`${kind}_address`][field] || ''; }));
          byId('leadForm').querySelectorAll('input, select, textarea, #addContact, .remove-contact').forEach(control => { control.disabled = readOnly; });
          byId('sameAsBilling').checked = Boolean(current.billing_address.line1) && addressFields.every(field => (current.billing_address[field] || '') === (current.shipping_address[field] || ''));
          syncShipping();
          openForm();
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
    cell.colSpan = 11; cell.className = 'source-empty'; cell.textContent = 'No leads yet. Click Add Lead to create your first client.';
    row.append(cell); byId('leads').append(row);
  }
}
byId('refresh').onclick = () => load().catch(error => message(error.message, true));
byId('leadForm').onsubmit = async event => {
  event.preventDefault(); byId('save').disabled = true;
  try {
    const wasEditing = editingId !== null;
    await api(wasEditing ? `/api/leads/${editingId}` : '/api/leads', {method: wasEditing ? 'PUT' : 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(formDetails())});
    resetForm(); closeForm(); byId('clientDetail').hidden = true; await loadOptions(); await load(); message(wasEditing ? 'Client lead updated.' : 'Client lead created.');
  } catch (error) { message(error.message, true); }
  finally { byId('save').disabled = false; }
};
(async () => {
  try { await loadOptions(); await load(); byId('content').hidden = false; const id = new URLSearchParams(location.search).get('client_id'); if (id) await openDetails(id); }
  catch (error) { message(error.message, true); }
})();

function resetForm() {
  editingId = null; readOnly = false; separateShipping = null; byId('leadForm').reset();
  byId('contacts').replaceChildren();
  byId('leadForm').querySelectorAll('input, select, textarea, button').forEach(control => { control.disabled = false; });
  byId('save').hidden = false;
  byId('formTitle').textContent = 'Add a client lead';
  byId('save').textContent = 'Create lead'; byId('cancelEdit').hidden = true;
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
  syncShipping();
  const details = Object.fromEntries(scalarFields.map(field => [field, byId(field).value]));
  ['emails', 'phones'].forEach(field => { details[field] = byId(field).value.split(/\n/).map(value => value.trim()).filter(Boolean); });
  details.contact_persons = [...byId('contacts').children].map(row => Object.fromEntries([...row.querySelectorAll('input')].map(input => [input.dataset.field, input.value])));
  ['billing', 'shipping'].forEach(kind => { details[`${kind}_address`] = Object.fromEntries(addressFields.map(field => [field, byId(`${kind}_${field}`).value.trim()]).filter(([,value]) => value)); });
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
function syncShipping() {
  const same = byId('sameAsBilling').checked;
  addressFields.forEach(field => {
    const shipping = byId(`shipping_${field}`);
    if (same) shipping.value = byId(`billing_${field}`).value;
    shipping.disabled = readOnly || same;
  });
}
byId('sameAsBilling').onchange = () => {
  if (byId('sameAsBilling').checked) {
    separateShipping = Object.fromEntries(addressFields.map(field => [field, byId(`shipping_${field}`).value]));
  } else if (separateShipping) {
    addressFields.forEach(field => { byId(`shipping_${field}`).value = separateShipping[field]; });
    separateShipping = null;
  }
  syncShipping();
};
addressFields.forEach(field => { byId(`billing_${field}`).addEventListener('input', syncShipping); });

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
  const data = await api(`/api/leads/${id}`); const client = data.lead;
  byId('detailTitle').textContent = client.name;
  byId('detailBody').replaceChildren();
  const section = (label, value) => {
    const block = document.createElement('section'); const heading = document.createElement('h3'); heading.textContent = label;
    const text = document.createElement('p'); text.textContent = value || 'Not provided'; block.append(heading,text); byId('detailBody').append(block);
  };
  const formatAddress = address => ['line1','line2','city','state','postal_code','country'].map(k => address[k]).filter(Boolean).join(', ');
  section('Company information', [client.company,client.business_details].filter(Boolean).join('\n'));
  section('Contacts', [client.email,client.phone,...client.emails,...client.phones,...client.contact_persons.map(c => [c.name,c.email,c.phone].filter(Boolean).join(' / '))].filter(Boolean).join('\n'));
  section('Reusable billing address',formatAddress(client.billing_address));
  section('Default shipping address',formatAddress(client.shipping_address));
  section('Notes',client.notes);
  section('Status and availability',`${client.status} / ${client.is_active ? 'Active' : 'Inactive'}`);
  section('Ownership and creation',`${client.creator_name} (owner and creator) / ${new Date(client.created_at).toLocaleString()}`);
  section('Access',client.is_shared ? `Shared ${client.shared_access_level} / ${client.can_edit ? 'Editable' : 'Read only'}` : client.can_edit ? 'Editable' : 'Read only');
  section('Enquiry source',client.enquiry_source_name ? `${client.enquiry_source_name}${client.enquiry_source_active ? '' : ' (inactive)'}` : 'Not specified');
  byId('addressHistory').replaceChildren();
  data.address_history.forEach(snapshot => {
    const line = document.createElement('p'); line.textContent = `${new Date(snapshot.recorded_at).toLocaleString()} / ${snapshot.actor_name || 'Migration baseline'}\nBilling: ${formatAddress(snapshot.billing_address) || '-'}\nDefault shipping: ${formatAddress(snapshot.default_shipping_address) || '-'}`; byId('addressHistory').append(line);
  });
  const enquiries = await api('/api/enquiries?' + new URLSearchParams({client_id:id,page_size:10}));
  const enquirySection = document.createElement('section'); enquirySection.className = 'client-enquiries';
  const enquiryHeader = document.createElement('div'); enquiryHeader.className = 'enquiry-header';
  const heading = document.createElement('h3'); heading.textContent = `Enquiries (${enquiries.total})`; enquiryHeader.append(heading);
  const all = document.createElement('a'); all.className = 'btn-sm enquiry-link'; all.href = `/enquiries?client_id=${id}`; all.textContent = 'View all enquiries'; enquiryHeader.append(all);
  if (client.can_edit && client.is_active) { const add = document.createElement('a'); add.className = 'btn-sm btn-add'; add.href = `/enquiries?client_id=${id}&new=1`; add.textContent = 'Add Enquiry'; enquiryHeader.append(add); }
  enquirySection.append(enquiryHeader);
  enquiries.enquiries.forEach(e => {
    const card = document.createElement('a'); card.className = 'enquiry-card';
    card.href = `/enquiries?client_id=${id}&enquiry_id=${e.id}`;
    const title = document.createElement('strong'); title.textContent = e.subject;
    const meta = document.createElement('span'); meta.textContent = `#${e.reference} / ${e.enquiry_date} / ${e.status.replaceAll('_', ' ')}`;
    const arrow = document.createElement('span'); arrow.className = 'enquiry-card-action'; arrow.textContent = 'View details';
    card.append(title,meta,arrow); enquirySection.append(card);
  });
  if (!enquiries.total) { const empty = document.createElement('p'); empty.textContent = 'No enquiries for this client yet.'; enquirySection.append(empty); }
  byId('detailBody').append(enquirySection);
  byId('clientDetail').hidden = false; byId('clientDetail').scrollIntoView({behavior:'smooth',block:'start'});
}
byId('closeDetail').onclick = () => { byId('clientDetail').hidden = true; };
byId('discoveryForm').onsubmit = event => { event.preventDefault(); currentPage = 1; load().catch(error => message(error.message,true)); };
byId('clearFilters').onclick = () => { byId('discoveryForm').reset(); currentPage = 1; load().catch(error => message(error.message,true)); };
byId('previousPage').onclick = () => { if (currentPage > 1) { currentPage--; load().catch(error => message(error.message,true)); } };
byId('nextPage').onclick = () => { if (currentPage < totalPages) { currentPage++; load().catch(error => message(error.message,true)); } };
byId('pageSize').onchange = () => { currentPage = 1; load().catch(error => message(error.message,true)); };
