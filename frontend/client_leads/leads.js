/* Clients & Orders — directory, client drawer and profile.
   Business rules are unchanged: every API call, permission flag and ownership
   rule below comes straight from the previous implementation. */
let profileVersion = 0;
let currentPage = 1;
let totalPages = 0;
let loadVersion = 0;
let editingId = null;
let readOnly = false;
let formDirty = false;
let restoreFocus = true;
let lastFocus = null;
let lastOpenedId = null;
let searchTimer = null;
let toastTimer = null;
const scalarFields = ['name', 'email', 'phone'];
const byId = id => document.getElementById(id);
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const scrollBehavior = () => (reduceMotion.matches ? 'auto' : 'smooth');
const baseTitle = document.title;

/* ───────────── small DOM helpers ───────────── */
function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value == null) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node[key] = value;
    else node.setAttribute(key, value === true ? '' : value);
  }
  node.append(...children.flat().filter(child => child != null && child !== false));
  return node;
}
const ICON_PATHS = {
  details: ['View details', 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z'],
  edit: ['Edit', 'm16 3 5 5-12 12-6 1 1-6L16 3Z M13 6l5 5'],
  deactivate: ['Deactivate', 'M12 3v9 M6 5a9 9 0 1 0 12 0'],
  activate: ['Reactivate', 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z m-14 0 3 3 7-7'],
  delete: ['Delete', 'M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7'],
};
function clientActionButton(action, name, style = '') {
  const [label, path] = ICON_PATHS[action];
  const button = h('button', {
    type: 'button',
    class: `cl-btn cl-icon-btn ${style}`.trim(),
    title: label,
    'aria-label': `${label}: ${name}`,
  });
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [key, value] of Object.entries({
    viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.8',
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', focusable: 'false',
  })) svg.setAttribute(key, value);
  const shape = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  shape.setAttribute('d', path);
  svg.append(shape);
  button.append(svg);
  return button;
}
function hueFor(text) {
  let hash = 0;
  for (const char of text || '') hash = (hash * 31 + char.codePointAt(0)) % 360;
  return hash;
}
function initials(name) {
  const letters = (name || '').trim().split(/\s+/).slice(0, 2).map(part => part[0] || '').join('').toUpperCase();
  return letters || '?';
}
function avatar(name, large = false) {
  const node = h('div', { class: large ? 'cl-avatar cl-avatar-lg' : 'cl-avatar', 'aria-hidden': 'true', text: initials(name) });
  node.style.setProperty('--h', hueFor(name));
  return node;
}

/* ───────────── feedback ───────────── */
function message(text, error = false) {
  const box = byId('message');
  clearTimeout(toastTimer);
  box.textContent = text;
  box.className = error ? 'error' : '';
  if (text && !error) toastTimer = setTimeout(() => { box.textContent = ''; box.className = ''; }, 6000);
}
byId('message').onclick = () => message('');
function setFormError(text) {
  const box = byId('formError');
  box.textContent = text || '';
  box.hidden = !text;
  if (text) box.scrollIntoView({ block: 'nearest' });
}
/* Promise-based replacement for window.confirm that matches the page. */
function confirmAction({ title, body, confirmLabel = 'Confirm', danger = false }) {
  const dialog = byId('confirmDialog');
  byId('confirmTitle').textContent = title;
  byId('confirmBody').textContent = body;
  byId('confirmOk').textContent = confirmLabel;
  byId('confirmOk').className = 'cl-btn ' + (danger ? 'cl-btn-danger' : 'cl-btn-primary');
  dialog.returnValue = '';
  return new Promise(resolve => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true });
    dialog.showModal();
  });
}
byId('confirmDialog').addEventListener('click', event => { if (event.target === event.currentTarget) event.currentTarget.close('cancel'); });

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (response.status === 401) { byId('content').hidden = true; throw new Error('Session ended. Please sign in again.'); }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Unable to complete this action.');
  return data;
}
const fail = error => message(error.message, true);

/* ───────────── filters ───────────── */
const radioValue = name => document.querySelector(`input[name="${name}"]:checked`).value;
const FILTERS = {
  q: () => byId('search').value,
  active: () => radioValue('availability'),
  ownership: () => radioValue('ownership'),
  creator: () => byId('filterCreator').value,
  access: () => byId('filterAccess').value,
  source: () => byId('filterSource').value,
  sort: () => byId('sort').value,
  direction: () => byId('direction').value,
};
const ADVANCED = [
  { id: 'filterCreator', label: 'Owner', empty: '' },
  { id: 'filterAccess', label: 'Access', empty: 'all' },
  { id: 'filterSource', label: 'Source', empty: '' },
];
function hasFilters() {
  return Boolean(byId('search').value.trim()) || radioValue('availability') !== 'all' || radioValue('ownership') !== 'all'
    || ADVANCED.some(item => byId(item.id).value !== item.empty);
}
function updateFilterUi() {
  const chips = byId('filterChips');
  chips.replaceChildren();
  let active = 0;
  for (const item of ADVANCED) {
    const select = byId(item.id);
    if (select.value === item.empty) continue;
    active++;
    chips.append(h('span', { class: 'cl-chip' },
      `${item.label}: ${select.selectedOptions[0]?.text || select.value}`,
      h('button', {
        type: 'button', 'aria-label': `Remove ${item.label} filter`,
        onclick: () => { select.value = item.empty; applyFilters(); },
      }, '×')));
  }
  if (byId('sort').value !== 'created' || byId('direction').value !== 'desc') {
    active++;
    chips.append(h('span', { class: 'cl-chip' },
      `Sorted by ${byId('sort').selectedOptions[0].text} (${byId('direction').value === 'asc' ? 'A→Z' : 'Z→A'})`,
      h('button', {
        type: 'button', 'aria-label': 'Reset sorting',
        onclick: () => { byId('sort').value = 'created'; byId('direction').value = 'desc'; applyFilters(); },
      }, '×')));
  }
  chips.hidden = !active;
  byId('moreCount').textContent = active;
  byId('moreCount').hidden = !active;
  byId('clearFilters').hidden = !hasFilters();
}
function applyFilters() {
  currentPage = 1;
  updateFilterUi();
  load().catch(fail);
}

/* ───────────── directory ───────────── */
function setBusy(busy) {
  byId('leads').setAttribute('aria-busy', String(busy));
  byId('directoryCard').classList.toggle('is-loading', busy);
  byId('refresh').disabled = busy;
}
function skeletonRows(count = 4) {
  return Array.from({ length: count }, () => h('li', { class: 'cl-skel-row', 'aria-hidden': 'true' },
    h('span', { class: 'cl-skel cl-skel-avatar' }), h('span', { class: 'cl-skel cl-skel-line' }), h('span', { class: 'cl-skel cl-skel-line short' })));
}
function emptyState() {
  const filtered = hasFilters();
  const li = h('li', { class: 'cl-empty' },
    h('div', { class: 'cl-empty-mark', 'aria-hidden': 'true' },
      (() => {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('viewBox', '0 0 24 24');
        const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        p.setAttribute('d', filtered ? 'M21 21l-4.3-4.3M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z' : 'M16 19v-1.5a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4V19M9.5 10a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM21 19v-1.5a4 4 0 0 0-3-3.9M15.5 3.1a3.5 3.5 0 0 1 0 6.8');
        svg.append(p);
        return svg;
      })()),
    h('h3', { text: filtered ? 'No clients match these filters' : 'No clients yet' }),
    h('p', { text: filtered ? 'Try a different search term or clear the filters to see everyone you can access.' : 'Add your first client to start tracking orders and proforma invoices.' }),
    filtered
      ? h('button', { type: 'button', class: 'cl-btn', onclick: () => byId('clearFilters').click() }, 'Clear filters')
      : h('button', { type: 'button', class: 'cl-btn cl-btn-primary', onclick: () => byId('addLead').click() }, 'Add a client'));
  return li;
}
function accessInfo(lead) {
  if (lead.is_shared) {
    return [`Shared · ${lead.shared_access_level}${lead.shared_access_level === 'VIEW' && lead.can_edit ? ' (independent edit)' : ''}`, 'is-shared'];
  }
  return lead.can_edit ? ['Editable', 'is-editable'] : ['Read only', 'is-readonly'];
}
function renderLead(lead) {
  const open = () => openDetails(lead.id).catch(fail);
  const [accessText, accessClass] = accessInfo(lead);
  const orders = lead.order_count, pending = lead.pending_order_count;
  const row = h('li', { class: 'cl-row' + (lead.is_active ? '' : ' is-inactive'), 'data-id': lead.id },
    h('div', { class: 'cl-cell cl-main' },
      avatar(lead.name),
      h('div', { class: 'cl-id' },
        h('button', { type: 'button', class: 'cl-name', onclick: open }, lead.name),
        lead.company ? h('span', { class: 'cl-company', text: lead.company }) : null)),
    h('div', { class: 'cl-cell cl-contact', 'data-label': 'Contact' },
      ...(lead.email || lead.phone
        ? [lead.email && h('span', { class: 'cl-line', text: lead.email }), lead.phone && h('span', { class: 'cl-line', text: lead.phone })]
        : [h('span', { class: 'cl-muted', text: 'No contact details' })])),
    h('div', { class: 'cl-cell cl-owner', 'data-label': 'Owner', text: lead.creator_name || '-' }),
    h('div', { class: 'cl-cell', 'data-label': 'Orders' },
      h('button', {
        type: 'button', class: 'cl-orders', onclick: open,
        'aria-label': `${orders} ${orders === 1 ? 'order' : 'orders'}, ${pending} pending. Open ${lead.name}`,
      },
      h('strong', { text: orders }), ` ${orders === 1 ? 'order' : 'orders'}`,
      pending ? h('span', { class: 'cl-pill', text: `${pending} pending` }) : null)),
    h('div', { class: 'cl-cell cl-state', 'data-label': 'Status' },
      h('span', { class: 'cl-badge ' + (lead.is_active ? 'is-active' : 'is-inactive'), text: lead.is_active ? 'Active' : 'Inactive' }),
      h('span', { class: `cl-badge ${accessClass}`, text: accessText })));

  const actions = h('div', { class: 'cl-cell client-actions cl-actions' });
  const details = clientActionButton('details', lead.name);
  details.onclick = open;
  actions.append(details);
  if (lead.can_edit) {
    const edit = clientActionButton('edit', lead.name);
    edit.onclick = () => editClient(lead.id);
    actions.append(edit);
  }
  if (lead.can_manage_client) {
    const toggle = clientActionButton(lead.is_active ? 'deactivate' : 'activate', lead.name, lead.is_active ? 'is-danger' : 'is-success');
    toggle.onclick = async () => {
      toggle.disabled = true;
      try {
        await api(`/api/leads/${lead.id}/${lead.is_active ? 'deactivate' : 'activate'}`, { method: 'POST' });
        await load();
        message('Client availability updated. Shares and history retained.');
      } catch (error) { message(error.message, true); }
      finally { toggle.disabled = false; }
    };
    actions.append(toggle);
  }
  if (lead.can_delete) {
    const remove = clientActionButton('delete', lead.name, 'is-danger');
    remove.onclick = () => deleteClient(lead).catch(fail);
    actions.append(remove);
  }
  row.append(actions);
  return row;
}
async function load() {
  const version = ++loadVersion;
  const list = byId('leads');
  const params = new URLSearchParams({ page: currentPage, page_size: byId('pageSize').value });
  Object.entries(FILTERS).forEach(([key, read]) => params.set(key, read()));
  setBusy(true);
  if (!list.querySelector('.cl-row')) list.replaceChildren(...skeletonRows());
  let data;
  try { data = await api('/api/leads?' + params); }
  catch (error) {
    if (version === loadVersion) { setBusy(false); if (!list.querySelector('.cl-row')) list.replaceChildren(); }
    throw error;
  }
  if (version !== loadVersion) return;
  totalPages = data.pages;
  if (currentPage > Math.max(1, totalPages)) { currentPage = Math.max(1, totalPages); return load(); }
  setBusy(false);
  byId('pageInfo').textContent = `Page ${data.page} of ${Math.max(1, data.pages)}`;
  byId('previousPage').disabled = currentPage <= 1;
  byId('nextPage').disabled = currentPage >= totalPages;
  byId('hdrUser').textContent = data.username;
  byId('accessLink').style.display = data.can_manage_sharing ? 'inline-block' : 'none';
  const first = (data.page - 1) * Number(byId('pageSize').value) + 1;
  byId('summary').textContent = data.leads.length
    ? `Showing ${first}–${first + data.leads.length - 1} of ${data.total} ${data.total === 1 ? 'client' : 'clients'}`
    : `${data.total} matching clients`;
  list.replaceChildren(...(data.leads.length ? data.leads.map(renderLead) : [emptyState()]));
  updateFilterUi();
}
/* A shorter placeholder keeps the search box readable on phones. */
const narrowScreen = window.matchMedia('(max-width: 650px)');
const syncPlaceholder = () => { byId('search').placeholder = narrowScreen.matches ? 'Search clients' : 'Search by company, contact, email or phone'; };
narrowScreen.addEventListener('change', syncPlaceholder);
syncPlaceholder();
byId('refresh').onclick = () => load().catch(fail);
byId('discoveryForm').addEventListener('change', event => { if (event.target.id !== 'search') applyFilters(); });
byId('search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(applyFilters, 300); });
byId('discoveryForm').onsubmit = event => { event.preventDefault(); clearTimeout(searchTimer); applyFilters(); };
byId('clearFilters').onclick = () => { clearTimeout(searchTimer); byId('discoveryForm').reset(); applyFilters(); };
byId('toggleFilters').onclick = () => {
  const panel = byId('morePanel');
  panel.hidden = !panel.hidden;
  byId('toggleFilters').setAttribute('aria-expanded', String(!panel.hidden));
};
byId('previousPage').onclick = () => { if (currentPage > 1) { currentPage--; load().catch(fail); } };
byId('nextPage').onclick = () => { if (currentPage < totalPages) { currentPage++; load().catch(fail); } };
byId('pageSize').onchange = () => { currentPage = 1; load().catch(fail); };

/* ───────────── create / edit drawer ───────────── */
const editor = byId('leadEditor');
let suggestionTimer = null;
let suggestionVersion = 0;
function clearSuggestions() {
  clearTimeout(suggestionTimer);
  suggestionVersion++;
  byId('clientSuggestions').replaceChildren();
  byId('clientSuggestions').hidden = true;
}
byId('name').addEventListener('input', () => {
  clearSuggestions();
  if (editingId !== null || readOnly || byId('name').value.trim().length < 3) return;
  const version = suggestionVersion;
  suggestionTimer = setTimeout(async () => {
    try {
      const {clients} = await api('/api/leads/suggestions?q=' + encodeURIComponent(byId('name').value.trim()));
      if (version !== suggestionVersion || editingId !== null) return;
      const panel = byId('clientSuggestions');
      panel.replaceChildren();
      if (!clients.length) return;
      panel.append(h('strong', {text: 'Similar clients already exist'}));
      for (const client of clients) {
        panel.append(h('button', {type: 'button', class: 'cl-suggestion',
          onclick: () => { closeForm({restore: false}); openDetails(client.id).catch(fail); }},
          client.name + (client.company ? ` · ${client.company}` : '')));
      }
      panel.hidden = false;
    } catch (error) { if (version === suggestionVersion) fail(error); }
  }, 250);
});
function syncContactsHint() { byId('contactsHint').hidden = byId('contacts').children.length > 0; }
function resetForm() {
  editingId = null; readOnly = false; formDirty = false;
  clearSuggestions();
  byId('leadForm').reset();
  byId('contacts').replaceChildren();
  byId('leadForm').querySelectorAll('input, select, textarea, button').forEach(control => { control.disabled = false; });
  byId('save').hidden = false;
  byId('formTitle').textContent = 'Add a client';
  byId('formHint').textContent = 'New clients are assigned to you automatically.';
  byId('save').textContent = 'Create client';
  byId('cancelEdit').textContent = 'Cancel';
  byId('moreContact').open = false;
  setFormError('');
  syncContactsHint();
}
function openForm() {
  lastFocus = document.activeElement;
  restoreFocus = true;
  if (!editor.open) editor.showModal();
  byId('addLead').setAttribute('aria-expanded', 'true');
  document.body.classList.add('cl-modal-open');
}
function closeForm({ restore = true } = {}) {
  restoreFocus = restore;
  if (editor.open) editor.close();
}
editor.addEventListener('close', () => {
  clearSuggestions();
  byId('addLead').setAttribute('aria-expanded', 'false');
  document.body.classList.remove('cl-modal-open');
  if (restoreFocus) (lastFocus && document.contains(lastFocus) ? lastFocus : byId('addLead')).focus();
});
async function requestCloseForm() {
  if (formDirty && !readOnly && !(await confirmAction({
    title: 'Discard your changes?', body: 'You have unsaved changes to this client. They will be lost if you close now.', confirmLabel: 'Discard changes', danger: true,
  }))) return;
  closeForm();
}
editor.addEventListener('cancel', event => { event.preventDefault(); requestCloseForm(); });
let downOnBackdrop = false;
editor.addEventListener('mousedown', event => { downOnBackdrop = event.target === editor; });
editor.addEventListener('click', event => { if (event.target === editor && downOnBackdrop) requestCloseForm(); });
byId('cancelEdit').onclick = byId('closeEditor').onclick = () => requestCloseForm();
byId('leadForm').addEventListener('input', () => { formDirty = true; });
byId('addLead').onclick = () => { resetForm(); openForm(); byId('name').focus(); };

function addContact(person = {}) {
  const row = h('div', { class: 'contact-row' });
  [['name', 'Contact name', 'text', 150], ['email', 'Email', 'email', 254], ['phone', 'Phone', 'tel', 40]].forEach(([field, placeholder, type, max]) => {
    const input = h('input', { class: 'cl-input', type, placeholder, maxlength: max, 'aria-label': `Contact ${field}`, required: field === 'name' });
    input.dataset.field = field;
    input.value = person[field] || '';
    row.append(input);
  });
  row.append(h('button', {
    type: 'button', class: 'cl-link-btn remove-contact', 'aria-label': 'Remove contact person',
    onclick: () => { row.remove(); formDirty = true; syncContactsHint(); byId('addContact').focus(); },
  }, 'Remove'));
  byId('contacts').append(row);
  syncContactsHint();
  return row;
}
byId('addContact').onclick = () => { formDirty = true; addContact().querySelector('input').focus(); };
function formDetails() {
  const details = Object.fromEntries(scalarFields.map(field => [field, byId(field).value]));
  ['emails', 'phones'].forEach(field => { details[field] = byId(field).value.split(/\n/).map(value => value.trim()).filter(Boolean); });
  details.contact_persons = [...byId('contacts').children].map(row => Object.fromEntries([...row.querySelectorAll('input')].map(input => [input.dataset.field, input.value])));
  details.enquiry_source_id = byId('enquiry_source_id').value ? Number(byId('enquiry_source_id').value) : null;
  return details;
}
async function loadOptions() {
  const data = await api('/api/leads/options');
  const creator = byId('filterCreator').value;
  byId('filterCreator').replaceChildren(new Option('All accessible creators', ''), ...data.creators.map(u => new Option(u.username, u.id)));
  if ([...byId('filterCreator').options].some(o => o.value === creator)) byId('filterCreator').value = creator;
  const oldSource = byId('filterSource').value;
  byId('filterSource').replaceChildren(new Option('All sources', ''), ...data.filter_sources.map(s => new Option(`${s.name}${s.is_active === 0 ? ' (inactive)' : ''}`, s.id)));
  if ([...byId('filterSource').options].some(o => o.value === oldSource)) byId('filterSource').value = oldSource;
  byId('enquiry_source_id').replaceChildren(new Option('Not specified', ''), ...data.sources.map(s => new Option(s.name, s.id)));
}
function setSource(client) {
  const select = byId('enquiry_source_id');
  if (client.enquiry_source_id && ![...select.options].some(o => Number(o.value) === client.enquiry_source_id)) {
    select.add(new Option(`${client.enquiry_source_name} (inactive)`, client.enquiry_source_id));
  }
  select.value = client.enquiry_source_id || '';
}
async function editClient(id) {
  try {
    const current = (await api(`/api/leads/${id}`)).lead;
    resetForm();
    readOnly = !current.can_edit;
    editingId = current.id;
    scalarFields.forEach(field => { byId(field).value = current[field]; });
    setSource(current);
    byId('emails').value = (current.emails || []).join('\n');
    byId('phones').value = (current.phones || []).join('\n');
    byId('moreContact').open = Boolean((current.emails || []).length || (current.phones || []).length);
    (current.contact_persons || []).forEach(person => addContact(person));
    byId('leadForm').querySelectorAll('input, select, textarea, #addContact, .remove-contact').forEach(control => { control.disabled = readOnly; });
    openForm();
    byId('save').hidden = readOnly;
    byId('formTitle').textContent = readOnly ? 'Client details' : 'Edit client';
    byId('formHint').textContent = readOnly ? 'You have read-only access to this client.' : current.name;
    byId('save').textContent = 'Save changes';
    byId('cancelEdit').textContent = readOnly ? 'Close' : 'Cancel';
    (readOnly ? byId('closeEditor') : byId('name')).focus();
  } catch (error) { message(error.message, true); }
}
byId('leadForm').onsubmit = async event => {
  event.preventDefault();
  if (readOnly) return;
  const wasEditing = editingId !== null;
  byId('save').disabled = true;
  setFormError('');
  let saved;
  try {
    saved = await api(wasEditing ? `/api/leads/${editingId}` : '/api/leads', {
      method: wasEditing ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(formDetails()),
    });
  } catch (error) { setFormError(error.message); return; }
  finally { byId('save').disabled = false; }
  resetForm();
  closeForm({ restore: false });
  try {
    await loadOptions();
    await load();
    message(wasEditing ? 'Client updated.' : 'Client created.');
    await openDetails(saved.lead.id);
  } catch (error) { message(error.message, true); }
};

async function deleteClient(client) {
  if (!(await confirmAction({
    title: 'Delete this client?',
    body: `${client.name} will be removed from your lists. Its orders and invoices will be hidden; all history will be retained.`,
    confirmLabel: 'Delete client', danger: true,
  }))) return;
  await api(`/api/leads/${client.id}`, { method: 'DELETE' });
  resetForm();
  closeForm({ restore: false });
  profileVersion++;
  byId('clientDetail').hidden = true;
  byId('directoryPanel').hidden = false;
  document.title = baseTitle;
  history.replaceState(null, '', '/clients-orders');
  await loadOptions();
  await load();
  message('Client deleted. History retained.');
}

/* ───────────── client profile ───────────── */
function contactLine(kind, value) {
  const digits = value.replace(/[^\d+]/g, '');
  const href = kind === 'Email' ? `mailto:${value}` : digits ? `tel:${digits}` : null;
  return h('div', { class: 'cl-contact-line' },
    h('span', { class: 'cl-line-label', text: kind }),
    href ? h('a', { href, text: value }) : h('span', { text: value }));
}
async function openDetails(id) {
  const version = ++profileVersion;
  const data = await api(`/api/leads/${id}`);
  if (version !== profileVersion) return;
  const client = data.lead;
  lastOpenedId = client.id;
  history.replaceState(null, '', `/clients-orders?client_id=${id}`);
  document.title = `${client.name} | ${baseTitle}`;
  byId('detailTitle').textContent = client.name;
  byId('detailAvatar').textContent = initials(client.name);
  byId('detailAvatar').style.setProperty('--h', hueFor(client.name));
  byId('detailSubtitle').textContent = client.company || '';
  byId('detailSubtitle').hidden = !client.company;
  byId('detailBadges').replaceChildren();
  const accessLabel = client.is_shared ? `Shared ${client.shared_access_level} / ${client.can_edit ? 'Editable' : 'Read only'}` : client.can_edit ? 'Editable' : 'Read only';
  for (const [label, style] of [[client.is_active ? 'Active' : 'Inactive', client.is_active ? 'client-active' : 'client-inactive'], [accessLabel, 'client-access']]) {
    byId('detailBadges').append(h('span', { class: `cl-badge ${style}`, text: label }));
  }
  byId('detailActions').replaceChildren();
  if (client.can_edit) {
    const edit = clientActionButton('edit', client.name);
    edit.onclick = () => editClient(client.id);
    byId('detailActions').append(edit);
  }
  if (client.can_delete) {
    const remove = clientActionButton('delete', client.name, 'is-danger');
    remove.onclick = () => deleteClient(client).catch(fail);
    byId('detailActions').append(remove);
  }

  const body = byId('detailBody');
  body.replaceChildren();
  const side = h('div', { class: 'cl-side' });
  body.append(side);
  const card = (label, ...content) => { const s = h('section', { class: 'cl-info' }, h('h3', { text: label }), ...content); side.append(s); return s; };

  const seenEmails = new Set(), seenPhones = new Set(), lines = [];
  const addEmail = value => { const k = (value || '').trim().toLowerCase(); if (k && !seenEmails.has(k)) { seenEmails.add(k); lines.push(contactLine('Email', value.trim())); } };
  const addPhone = value => { const k = (value || '').replace(/[^\d+]/g, '') || (value || '').trim(); if (k && !seenPhones.has(k)) { seenPhones.add(k); lines.push(contactLine('Phone', value.trim())); } };
  addEmail(client.email); addPhone(client.phone);
  (client.emails || []).forEach(addEmail);
  (client.phones || []).forEach(addPhone);
  const people = (client.contact_persons || []).map(person => h('div', { class: 'cl-person' },
    h('strong', { text: person.name }),
    person.email ? contactLine('Email', person.email) : null,
    person.phone ? contactLine('Phone', person.phone) : null));
  const contactCard = card('Contact details', lines.length || people.length ? null : h('p', { class: 'cl-muted', text: 'Not provided' }), ...lines);
  if (people.length) contactCard.append(h('h4', { text: 'Contact persons' }), ...people);

  card('Account owner', h('p', { class:'cl-owner-name',text:client.creator_name }),
    h('p', { class:'cl-created-note',text:`Created ${new Date(client.created_at).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })}` }));
  card('Enquiry source', client.enquiry_source_name
    ? h('p', { text: `${client.enquiry_source_name}${client.enquiry_source_active ? '' : ' (inactive)'}` })
    : h('p', { class: 'cl-muted', text: 'Not specified' }));

  byId('directoryPanel').hidden = true;
  byId('clientDetail').hidden = false;
  window.scrollTo({ top: 0, behavior: scrollBehavior() });
  byId('detailTitle').focus({ preventScroll: true });
  await window.renderRelatedOrders(body, { client_id: id }, client.can_edit && client.is_active);
}
function closeDetails() {
  profileVersion++;
  byId('clientDetail').hidden = true;
  byId('directoryPanel').hidden = false;
  document.title = baseTitle;
  history.replaceState(null, '', '/clients-orders');
  const target = lastOpenedId && document.querySelector(`.cl-row[data-id="${lastOpenedId}"] .cl-name`);
  (target || byId('addLead')).focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: scrollBehavior() });
}
byId('backDirectory').onclick = closeDetails;

/* ───────────── start ───────────── */
(async () => {
  try {
    await loadOptions();
    byId('content').hidden = false;
    await load();
    const id = new URLSearchParams(location.search).get('client_id');
    if (id) await openDetails(id);
  } catch (error) { message(error.message, true); }
})();
