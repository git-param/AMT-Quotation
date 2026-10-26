/* Country suggestions and consignee GST, shared by orders and PI previews. */
(() => {
  const countries = new Set();
  let callingCodes = {};
  function phoneBlock(value, country) {
    const prefix = callingCodes[country.trim().toUpperCase()];
    if (!prefix) return value;
    return value.replace(/^\s*(?:Tel\/Phone|Tel|Telephone|Phone)\s*:[ \t]*(.*)$/gim, (_, raw) => {
      let number = raw.trim();
      if (!number || /^\+[0-9]{1,3}$/.test(number)) number = prefix;
      else if (number.startsWith('00')) number = '+' + number.slice(2);
      else if (!number.startsWith('+') && /^[0-9 ()-]+$/.test(number)) {
        let digits = number.replace(/[^0-9]/g, '');
        if (['UK','UNITED KINGDOM','UAE','UNITED ARAB EMIRATES','INDIA'].includes(country.trim().toUpperCase())) digits = digits.replace(/^0+/, '');
        number = prefix + ' ' + digits;
      }
      return 'Tel/Phone: ' + number;
    });
  }
  function phoneBlockForCountry(value, previousCountry, country) {
    const previous = callingCodes[previousCountry.trim().toUpperCase()];
    const next = callingCodes[country.trim().toUpperCase()];
    if (!next || previous === next) return phoneBlock(value, country);
    return value.replace(/^\s*(?:Tel\/Phone|Tel|Telephone|Phone)\s*:[ \t]*(.*)$/gim, (_, raw) => {
      let number=raw.trim();
      if (!number || (previous && number.startsWith(previous) && !number.slice(previous.length).replace(/\D/g,''))) number=next;
      else if (previous && number.startsWith(previous)) {
        const national=number.slice(previous.length).trim();
        number=next+(national?' '+national:'');
      }
      else if (!number.startsWith('+') && /^[0-9 ()-]+$/.test(number)) number=next+' '+number.replace(/\D/g,'');
      return 'Tel/Phone: '+number;
    });
  }
  const gstLine = /^\s*GST(?:IN|\s*(?:No\.?|Number))?\s*:\s*(.*)$/i;
  const contactLine = /^\s*(?:GST(?:IN|\s*(?:No\.?|Number))?|Tel(?:\/Phone)?|Telephone|Phone|PIC|E-?mail)\s*:/i;
  function addressOnly(value, country = '') {
    return value.split('\n').filter((line,index)=>!index||(
      !/^\s*(?:Country|GST(?:IN|\s*(?:No\.?|Number))?|Tel(?:\/Phone)?|Telephone|Phone|PIC|E-?mail)\s*:/i.test(line)
      && !countries.has(line.trim().toUpperCase())
      && !(country && line.trim().toUpperCase()===country.trim().toUpperCase())
    )).join('\n').trimEnd();
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
    return phoneBlock(result.join('\n'), country);
  }
  function gstNumber(value) {
    return value.split('\n').slice(1).map(line => line.match(gstLine)).find(Boolean)?.[1].trim() || '';
  }
  function withGst(value, number) {
    const lines = value.split('\n').filter((line, index) => !index || !gstLine.test(line));
    if(number.trim()){
      const country=lines.findIndex((line,index)=>index>0&&(/^\s*Country\s*:/i.test(line)||countries.has(line.trim().toUpperCase())));
      const contact=lines.findIndex((line,index)=>index>0&&contactLine.test(line));
      lines.splice(country>=0?country+1:contact>=0?contact:lines.length,0,'GST No.: '+number.trim());
    }
    return lines.join('\n');
  }
  const callingReady = fetch('/static/common/calling-codes.json').then(response => {
    if (!response.ok) throw new Error('Unable to load calling codes.');
    return response.json();
  }).then(values => { if (!Array.isArray(values)) callingCodes = values; }).catch(() => {});
  const countriesReady = fetch('/static/common/countries.json').then(response => {
    if (!response.ok) throw new Error('Unable to load country suggestions.');
    return response.json();
  }).then(values => {
    const list = document.getElementById('orderCountries');
    for (const value of values) {
      countries.add(value);
      if (list) { const option = document.createElement('option'); option.value = value; list.append(option); }
    }
  }).catch(() => {});
  const ready = Promise.all([countriesReady, callingReady]);
  window.orderLocations = {countryBlock, phoneBlock, phoneBlockForCountry, gstNumber, withGst, partyParts, joinParty, addressOnly,
    isCountry:value=>countries.has(String(value||'').trim().toUpperCase()), ready};
})();
