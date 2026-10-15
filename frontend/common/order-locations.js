/* Country suggestions and editable buyer GST, shared by orders and PI previews. */
(() => {
  const countries = new Set();
  const gstLine = /^\s*GST(?:IN|\s*(?:No\.?|Number))?\s*:\s*(.*)$/i;
  const contactLine = /^\s*(?:GST(?:IN|\s*(?:No\.?|Number))?|Tel|Telephone|Phone|PIC|E-?mail)\s*:/i;
  function addressOnly(value) {
    return value.split('\n').filter((line,index)=>!index||!/^\s*(?:Tel|Telephone|Phone|PIC|E-?mail)\s*:/i.test(line)).join('\n').trimEnd();
  }
  function partyParts(value, country = '') {
    const lines = value.split('\n');
    const boundary = lines.findIndex((line, index) => index > 0 && (
      !line.trim() || /^\s*Country\s*:/i.test(line) || contactLine.test(line) ||
      countries.has(line.trim().toUpperCase()) || (country && line.trim().toUpperCase() === country.trim().toUpperCase())));
    return boundary < 0 ? [value, ''] : [lines.slice(0, boundary).join('\n').trimEnd(), lines.slice(boundary).join('\n').trimStart()];
  }
  function joinParty(primary, secondary) {
    return [primary.trimEnd(), secondary.trimStart()].filter(Boolean).join('\n\n');
  }
  function countryBlock(value, country, previous = []) {
    country = country.trim().toUpperCase();
    if (!country) return value;
    const known = new Set([...countries, ...previous.filter(Boolean).map(item => item.trim().toUpperCase())]);
    const result = []; let inserted = false;
    value.split('\n').forEach((line, index) => {
      if (index && (/^\s*Country\s*:/i.test(line) || known.has(line.trim().toUpperCase()))) {
        if (!inserted) { result.push(country); inserted = true; }
      } else result.push(line);
    });
    if (!inserted) {
      const contact = result.findIndex((line, index) => index > 0 && contactLine.test(line));
      result.splice(contact < 0 ? result.length : contact, 0, country);
    }
    return result.join('\n');
  }
  function gstNumber(value) {
    return value.split('\n').slice(1).map(line => line.match(gstLine)).find(Boolean)?.[1].trim() || '';
  }
  function withGst(value, number) {
    const block = value.split('\n').filter((line, index) => !index || !gstLine.test(line)).join('\n');
    return block + (number.trim() ? '\nGST No.: ' + number.trim() : '');
  }
  const ready = fetch('/static/common/countries.json').then(response => {
    if (!response.ok) throw new Error('Unable to load country suggestions.');
    return response.json();
  }).then(values => {
    const list = document.getElementById('orderCountries');
    for (const value of values) {
      countries.add(value);
      if (list) { const option = document.createElement('option'); option.value = value; list.append(option); }
    }
  }).catch(() => {});
  window.orderLocations = {countryBlock, gstNumber, withGst, partyParts, joinParty, addressOnly, ready};
})();
