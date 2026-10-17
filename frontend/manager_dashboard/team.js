// Quick date-range chips for the TL dashboard. Fills the From/To inputs (IST) and
// submits the existing filter form, so team.js handles the rest unchanged.
(() => {
  const chips = [...document.querySelectorAll('.tl-chip')];
  const from = document.getElementById('tlFrom');
  const to = document.getElementById('tlTo');
  const form = document.getElementById('tlFilters');
  if (!chips.length || !from || !to || !form) return;

  const istToday = () => new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit'
  }).format(new Date());

  const shift = (iso, days) => {
    const d = new Date(iso + 'T00:00:00Z');
    d.setUTCDate(d.getUTCDate() + days);
    return d.toISOString().slice(0, 10);
  };

  const ranges = {
    today: t => [t, t],
    '7': t => [shift(t, -6), t],
    '30': t => [shift(t, -29), t],
    month: t => [t.slice(0, 8) + '01', t]
  };

  const clearActive = () => chips.forEach(c => c.classList.remove('is-active'));

  chips.forEach(chip => chip.addEventListener('click', () => {
    const [a, b] = ranges[chip.dataset.range](istToday());
    from.value = a;
    to.value = b;
    clearActive();
    chip.classList.add('is-active');
    form.requestSubmit();
  }));

  [from, to].forEach(input => input.addEventListener('input', clearActive));
  document.getElementById('tlClear')?.addEventListener('click', clearActive);
})();