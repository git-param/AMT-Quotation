const byId = id => document.getElementById(id);
let clients = [];
function message(text, error = false) { byId('message').textContent = text; byId('message').className = error ? 'error' : ''; }
async function api(path, options = {}) {
  const response = await fetch(path, options);
  if ([401, 403].includes(response.status)) {
    byId('content').hidden = true;
    throw new Error(response.status === 401 ? 'Session ended. Please sign in again.' : 'Access denied for your role.');
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Unable to complete this action.');
  return data;
}
function cell(row, value) { const td = document.createElement('td'); td.textContent = value; row.append(td); return td; }
function empty(id, columns, text) {
  const row = document.createElement('tr'); const td = cell(row, text);
  td.colSpan = columns; td.className = 'source-empty'; byId(id).append(row);
}
function date(value) { return value ? new Date(value).toLocaleString() : 'Not recorded'; }
async function details() {
  byId('shares').replaceChildren(); byId('events').replaceChildren();
  if (!byId('client').value) { empty('shares', 5, 'No manageable clients yet. Create a lead first.'); return; }
  const current = byId('client').value;
  const data = await api(`/api/client-access/${current}`);
  if (byId('client').value !== current) return;
  byId('shares').replaceChildren(); byId('events').replaceChildren();
  data.shares.forEach(share => {
    const row = document.createElement('tr');
    cell(row, share.username);
    const state = cell(row, ''); const badge = document.createElement('span');
    badge.className = `badge ${share.is_active ? 'badge-ok' : 'badge-warn'}`;
    badge.textContent = share.is_active ? (share.account_active ? 'Granted' : 'Granted / account inactive') : 'Revoked'; state.append(badge);
    cell(row, date(share.granted_at)); cell(row, share.revoked_at ? date(share.revoked_at) : '-');
    const actions = cell(row, '');
    if (share.is_active) {
      const button = document.createElement('button'); button.className = 'btn-sm btn-del'; button.textContent = 'Revoke';
      button.setAttribute('aria-label', `Revoke access for ${share.username}`);
      button.onclick = async () => {
        button.disabled = true;
        try {
          await api(`/api/client-access/${current}/revoke`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({user_id: share.user_id})});
          await details(); message('Share revoked. Independent access, if any, remains.');
        } catch (error) { message(error.message, true); }
        finally { button.disabled = false; }
      };
      actions.append(button);
    } else { actions.textContent = '-'; }
    byId('shares').append(row);
  });
  data.events.forEach(event => {
    const row = document.createElement('tr');
    [event.action === 'grant' ? 'Granted' : 'Revoked', event.recipient_name, event.actor_name, date(event.occurred_at)].forEach(value => cell(row, value));
    byId('events').append(row);
  });
  if (!data.shares.length) empty('shares', 5, 'No executives have been granted access to this client.');
  if (!data.events.length) empty('events', 4, 'No sharing changes recorded. Imported shares may have no attribution.');
}
async function load() {
  const selected = byId('client').value;
  const data = await api('/api/client-access'); clients = data.leads;
  byId('hdrUser').textContent = data.username;
  byId('client').replaceChildren(...clients.map(lead => new Option(`${lead.name} / ${lead.creator_name}`, lead.id)));
  if (clients.some(lead => String(lead.id) === selected)) byId('client').value = selected;
  byId('executive').replaceChildren(new Option('Choose an executive', ''), ...data.executives.map(user => new Option(user.username, user.id)));
  byId('grant').disabled = !clients.length || !data.executives.length;
  await details();
}
byId('client').onchange = () => details().catch(error => message(error.message, true));
byId('refresh').onclick = () => load().catch(error => message(error.message, true));
byId('grantForm').onsubmit = async event => {
  event.preventDefault(); byId('grant').disabled = true;
  try {
    await api(`/api/client-access/${byId('client').value}/grant`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({user_id: Number(byId('executive').value)})});
    await details(); message('Read-only access granted. Existing edit permissions are unchanged.');
  } catch (error) { message(error.message, true); }
  finally { byId('grant').disabled = !clients.length; }
};
(async () => { try { await load(); byId('content').hidden = false; } catch (error) { message(error.message, true); } })();
