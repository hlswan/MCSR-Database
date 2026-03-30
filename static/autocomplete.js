document.addEventListener("DOMContentLoaded", () => {
  const input   = document.getElementById('runner-search');
  const list    = document.getElementById('autocomplete-list');
  const items   = Array.from(list.querySelectorAll('.autocomplete-item'));
  let activeIdx = -1;

  input.addEventListener('input', () => {
    const q = input.value.trim().toLowerCase();
    let anyVisible = false;
    activeIdx = -1;
    items.forEach(el => {
      const match = q && el.dataset.name.toLowerCase().includes(q);
      el.style.display = match ? '' : 'none';
      if (match) anyVisible = true;
    });
    list.classList.toggle('open', anyVisible);
  });

  input.addEventListener('keydown', e => {
    const visible = items.filter(el => el.style.display !== 'none');
    if (e.key === 'ArrowDown') {
      activeIdx = Math.min(activeIdx + 1, visible.length - 1);
    } else if (e.key === 'ArrowUp') {
      activeIdx = Math.max(activeIdx - 1, 0);
    } else if (e.key === 'Enter') {
      if (activeIdx >= 0 && visible[activeIdx]) {
        selectRunner(visible[activeIdx].dataset.name);
      } else if (input.value.trim()) {
        selectRunner(input.value.trim());
      }
      return;
    } else if (e.key === 'Escape') {
      list.classList.remove('open');
      return;
    }
    visible.forEach((el, i) => el.classList.toggle('active', i === activeIdx));
  });

  items.forEach(el => {
    el.addEventListener('mousedown', () => selectRunner(el.dataset.name));
  });

  document.addEventListener('click', e => {
    if (!e.target.closest('.search-box')) list.classList.remove('open');
  });

  function selectRunner(name) {
    window.location.href = '/stats/player?runner=' + encodeURIComponent(name);
  }
});