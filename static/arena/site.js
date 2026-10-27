'use strict';
(() => {
  const menu = document.querySelector('.menu-button');
  const nav = document.querySelector('#navigation');
  const backdrop = document.querySelector('.nav-backdrop');
  const mobile = window.matchMedia('(max-width: 780px)');
  if (nav) nav.inert = mobile.matches;
  function closeMenu(returnFocus = false) {
    nav?.classList.remove('open'); if (nav) nav.inert = mobile.matches;
    menu?.setAttribute('aria-expanded', 'false');
    menu?.setAttribute('aria-label', 'Open navigation');
    if (backdrop) backdrop.hidden = true;
    document.body.classList.remove('menu-open');
    nav?.removeAttribute('aria-modal'); nav?.removeAttribute('role');
    document.querySelectorAll('.masthead,.workspace').forEach(el => { el.inert = false; });
    if (returnFocus) menu?.focus();
  }
  menu?.addEventListener('click', () => {
    if (nav?.classList.contains('open')) { closeMenu(true); return; }
    if (nav) nav.inert = false;
    nav?.classList.add('open'); menu.setAttribute('aria-expanded', 'true');
    menu.setAttribute('aria-label', 'Close navigation');
    if (backdrop) backdrop.hidden = false;
    document.body.classList.add('menu-open');
    nav?.setAttribute('aria-modal','true'); nav?.setAttribute('role','dialog');
    document.querySelectorAll('.masthead,.workspace').forEach(el => { el.inert = true; });
    nav?.querySelector('nav a[aria-current], nav a')?.focus();
  });
  backdrop?.addEventListener('click', () => closeMenu(true));
  document.querySelector('[data-close-menu]')?.addEventListener('click', () => closeMenu(true));
  mobile.addEventListener('change', () => closeMenu());
  document.addEventListener('keydown', e => {
    if (!nav?.classList.contains('open')) return;
    if (e.key === 'Escape') { e.preventDefault(); closeMenu(true); }
    if (e.key === 'Tab') {
      const focusable = [...nav.querySelectorAll('a,button')].filter(el => el.getClientRects().length);
      if (e.shiftKey && document.activeElement === focusable[0]) { e.preventDefault(); focusable.at(-1)?.focus(); }
      else if (!e.shiftKey && document.activeElement === focusable.at(-1)) { e.preventDefault(); focusable[0]?.focus(); }
    }
  });
  nav?.querySelectorAll('a').forEach(a => a.addEventListener('click', () => closeMenu()));
  document.querySelectorAll('input[type="file"]').forEach(input => {
    input.addEventListener('change', () => {
      const label = input.closest('label')?.querySelector('[data-file-name]');
      const file = input.files[0];
      if (label) label.textContent = input.files.length > 1 ? input.files.length + ' files selected' : file ? file.name + ' · ' + (file.size < 1024 ? file.size + ' B' : (file.size / 1024).toFixed(1) + ' KB') : 'Choose a file';
      input.closest('.file-picker')?.classList.toggle('has-file', Boolean(file));
    });
  });
  document.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', e => {
      if (document.body.dataset.preview || form.closest('.auth-card')) return;
      if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) { e.preventDefault(); return; }
      if (form.dataset.submitting) { e.preventDefault(); return; }
      form.dataset.submitting = 'true';
      form.setAttribute('aria-busy', 'true');
      if (form.enctype === 'multipart/form-data') {
        const button = e.submitter;
        if (button) { button.dataset.originalText = button.textContent; button.textContent = 'Uploading…'; }
      }
      // MFA wizard buttons carry action values; preserve them before disabling.
      if (e.submitter?.name) {
        const action = document.createElement('input'); action.type = 'hidden';
        action.name = e.submitter.name; action.value = e.submitter.value;
        action.dataset.submitAction = 'true'; form.append(action);
      }
      form.querySelectorAll('button[type="submit"]:not(:disabled)').forEach(button => {
        button.dataset.temporarilyDisabled = 'true'; button.disabled = true; button.setAttribute('aria-busy', 'true');
      });
    });
  });
  window.addEventListener('pageshow', () => document.querySelectorAll('form').forEach(form => {
    delete form.dataset.submitting; form.removeAttribute('aria-busy');
    form.querySelectorAll('[data-submit-action]').forEach(input => input.remove());
    form.querySelectorAll('[data-temporarily-disabled]').forEach(button => {
      button.disabled = false; delete button.dataset.temporarilyDisabled; button.removeAttribute('aria-busy');
      if (button.dataset.originalText) { button.textContent = button.dataset.originalText; delete button.dataset.originalText; }
    });
  }));
  document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(button.dataset.copy); button.textContent = 'Copied'; showToast(button.dataset.copyLabel || 'SHA-256 hash copied.'); }
    catch { button.textContent = 'Select the text to copy'; }
  }));
  const search = document.querySelector('[data-team-search]');
  search?.addEventListener('input', () => {
    const query = search.value.toLocaleLowerCase().trim(); let found = 0;
    document.querySelectorAll('[data-team-card]').forEach(card => {
      const match = card.dataset.search.toLocaleLowerCase().includes(query);
      card.hidden = !match; if (match) found++;
    });
    document.querySelector('#search-empty').hidden = found > 0;
  });
  let toastTimer;
  function showToast(message) {
    const toast = document.querySelector('.toast');
    if (!toast) return;
    toast.textContent = message; toast.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { toast.hidden = true; }, 4500);
  }
  // Day tabs use roving keyboard focus; the full schedule remains available as an ordinary link.
  const dayTabs = [...document.querySelectorAll('[data-day-tab]')];
  function activateDay(tab, focus = false) {
    dayTabs.forEach(item => {
      const active = item === tab;
      item.setAttribute('aria-selected', String(active)); item.tabIndex = active ? 0 : -1;
      const pane = document.getElementById(item.getAttribute('aria-controls'));
      if (pane) pane.hidden = !active;
    });
    if (focus) tab.focus();
  }
  dayTabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activateDay(tab));
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % dayTabs.length;
      if (event.key === 'ArrowLeft') next = (index - 1 + dayTabs.length) % dayTabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = dayTabs.length - 1;
      if (next !== undefined) { event.preventDefault(); activateDay(dayTabs[next], true); }
    });
  });
  document.querySelectorAll('.file-picker').forEach(picker => {
    let entered = 0;
    picker.addEventListener('dragenter', event => { event.preventDefault(); entered++; picker.classList.add('drag-over'); });
    picker.addEventListener('dragover', event => event.preventDefault());
    picker.addEventListener('dragleave', () => { if (--entered <= 0) { entered = 0; picker.classList.remove('drag-over'); } });
    picker.addEventListener('drop', event => {
      event.preventDefault(); entered = 0; picker.classList.remove('drag-over');
      const input = picker.querySelector('input[type=file]');
      if (!input || input.disabled || !event.dataTransfer?.files.length) return;
      if (!input.multiple && event.dataTransfer.files.length > 1) { showToast('Choose one file for each submission slot.'); return; }
      input.files = event.dataTransfer.files; input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });
  const dialog = document.querySelector('.command-dialog');
  const commandInput = document.querySelector('#command-input');
  const commandResults = document.querySelector('.command-results');
  let commandOpener;
  const pageLinks = [
    ['Competition programme', '/', 'Public'], ['Full schedule', '/schedule/', 'Public'],
    ['Results & scores', '/results/', 'Public'], ['Teams & archive', '/teams/', 'Public'],
    ['Round maps', '/maps/', 'Public'], ['Competition resources', '/resources/', 'Public'],
    ...[...document.querySelectorAll('#navigation nav a')].map(a => [a.textContent.trim(), a.dataset.sourceHref || a.getAttribute('href'), 'Workspace']).filter(([,href]) => href?.startsWith('/portal/') || href?.startsWith('#') || href?.startsWith('/system/'))
  ];
  function filterCommands() {
    if (!commandResults || !commandInput) return;
    const query = commandInput.value.toLocaleLowerCase().trim();
    const matches = pageLinks.filter(([name]) => name.toLocaleLowerCase().includes(query));
    commandResults.replaceChildren(...matches.map(([name, href, group]) => {
      const item = document.createElement('div'); item.setAttribute('role', 'listitem');
      const link = document.createElement('a'); link.href = href;
      const label = document.createElement('span'); label.textContent = name;
      const category = document.createElement('small'); category.textContent = group;
      link.append(label, category); link.addEventListener('click', () => dialog.close()); item.append(link); return item;
    }));
    const empty = document.querySelector('.command-empty'); if (empty) empty.hidden = Boolean(matches.length);
  }
  function openCommands() {
    if (!dialog || !commandInput || dialog.open) return;
    commandOpener = document.activeElement; closeMenu(); commandInput.value = ''; filterCommands();
    dialog.showModal(); commandInput.focus();
  }
  document.querySelectorAll('[data-open-search]').forEach(button => button.addEventListener('click', openCommands));
  document.querySelector('[data-close-search]')?.addEventListener('click', () => dialog?.close());
  commandInput?.addEventListener('input', filterCommands);
  dialog?.addEventListener('close', () => commandOpener?.focus());
  dialog?.addEventListener('click', e => { if (e.target === dialog) { const b = dialog.getBoundingClientRect(); if (e.clientX < b.left || e.clientX > b.right || e.clientY < b.top || e.clientY > b.bottom) dialog.close(); } });
  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openCommands(); }
    if (!dialog?.open) return;
    const links = [...commandResults.querySelectorAll('a')];
    const current = links.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); links[(current + 1) % links.length]?.focus(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); links[(current - 1 + links.length) % links.length]?.focus(); }
    if (e.key === 'Enter' && document.activeElement === commandInput) { e.preventDefault(); links[0]?.click(); }
  });
  function openAnchor(href) {
    if (!href?.startsWith('#')) return;
    const target = document.getElementById(href.slice(1));
    let container = target?.closest('details');
    while (container) { container.open = true; container = container.parentElement?.closest('details'); }
    if (target) requestAnimationFrame(() => target.scrollIntoView({block:'start',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'}));
  }
  document.querySelectorAll('a[href^="#"]').forEach(link => link.addEventListener('click', () => openAnchor(link.getAttribute('href'))));
  document.querySelectorAll('.account-menu').forEach(account => {
    document.addEventListener('click', event => { if (!account.contains(event.target)) account.open = false; });
    document.addEventListener('keydown', event => { if (event.key === 'Escape' && account.open) { account.open = false; account.querySelector('summary')?.focus(); } });
  });
  if (location.hash) openAnchor(location.hash);
  window.addEventListener('hashchange', () => openAnchor(location.hash));
  window.addEventListener('pageshow', () => { if (location.hash) openAnchor(location.hash); });
  // Real anchor navigation also works when scripting is unavailable.
  const sectionLinks = [...document.querySelectorAll('#navigation nav a[href^="#"], .day-tabs a[href^="#"]')];
  if ('IntersectionObserver' in window && sectionLinks.length) {
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting && (!document.body.classList.contains('admin-page') || entry.target.open)).sort((a,b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (!visible.length) return;
      const id = '#' + visible[0].target.id;
      sectionLinks.forEach(link => { if (link.getAttribute('href') === id) link.setAttribute('aria-current','location'); else link.removeAttribute('aria-current'); });
    }, { rootMargin: '-10% 0px -60% 0px', threshold: 0 });
    sectionLinks.forEach(link => { const section = document.getElementById(link.getAttribute('href').slice(1)); if (section) observer.observe(section); });
  }
  let offset = 0;
  const clocks = [...document.querySelectorAll('[data-clock]')];
  const countdowns = [...document.querySelectorAll('[data-countdown]')];
  function updateTime() {
    const now = new Date(Date.now() + offset);
    clocks.forEach(clock => clock.textContent = 'Toronto · ' + new Intl.DateTimeFormat('en-CA', { timeZone:'America/Toronto',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false }).format(now) + ' EDT');
    countdowns.forEach(el => {
      const remaining = new Date(el.dataset.countdown).getTime() - now.getTime();
      if (remaining <= 0) {
        el.textContent = 'Quarantine started · uploads locked';
        const state = el.closest('.quarantine-card')?.querySelector('[data-quarantine-state]');
        if (state) { state.textContent = 'Locked'; state.classList.remove('success'); state.classList.add('neutral'); }
        el.closest('.submission-round, .quarantine-card')?.querySelectorAll('.upload-form button, .upload-form input, .file-receipt form button').forEach(button => { button.disabled = true; });
      } else {
        const seconds = Math.floor(remaining / 1000);
        const days = Math.floor(seconds / 86400);
        el.textContent = (days ? days + 'd ' : '') + String(Math.floor(seconds / 3600) % 24).padStart(2,'0') + ':' + String(Math.floor(seconds / 60) % 60).padStart(2,'0') + ':' + String(seconds % 60).padStart(2,'0') + ' until lock';
      }
    });
  }
  updateTime(); setInterval(updateTime, 1000);
  let noticesLoading = false;
  async function refreshTeamNotices() {
    const nav = document.querySelector('[data-team-notices-url]');
    if (!nav || noticesLoading) return;
    noticesLoading = true;
    try {
      const current = document.querySelector('[data-team-notices]');
      const response = await fetch(nav.dataset.teamNoticesUrl + (current?.dataset.compact === '1' ? '?compact=1' : ''),
        {credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'},signal:AbortSignal.timeout(15000)});
      if (!response.ok || response.redirected) return;
      const data = await response.json();
      document.querySelectorAll('[data-unread-count]').forEach(badge => {
        badge.textContent = data.unread; badge.hidden = data.unread === 0;
      });
      if (current && current.dataset.version !== data.version && !current.contains(document.activeElement)) {
        const next = new DOMParser().parseFromString(data.html, 'text/html').querySelector('[data-team-notices]');
        if (next) current.replaceWith(next);
      }
    } catch { /* Keep the last private dashboard render when offline or signed out. */ }
    finally { noticesLoading = false; }
  }
  async function refreshLive() {
    if (document.hidden || document.body.dataset.preview) return;
    refreshTeamNotices();
    try {
      const response = await fetch('/live.json', {credentials:'omit',cache:'no-cache',headers:{Accept:'application/json'}});
      if (!response.ok) return;
      const data = await response.json();
      const serverTime = Date.parse(data.server_time);
      if (Number.isFinite(serverTime)) offset = serverTime - Date.now();
      document.dispatchEvent(new CustomEvent('asr:server-time', {detail: data.server_time}));
      updateTime();
      const status = document.querySelector('#live-status');
      const content = document.querySelector('#live-programme');
      if (status) status.textContent = data.events.length ? 'Live' : 'Upcoming';
      if (content && data.events.length) {
        content.replaceChildren(...data.events.map(event => {
          const row = document.createElement('div'); row.className = 'now-event';
          const title = document.createElement('h3'); title.textContent = event.title;
          const sub = document.createElement('p'); sub.textContent = event.team || 'Competition programme';
          row.append(title, sub); return row;
        }));
        content.dataset.wasLive = 'true';
      } else if (content?.dataset.wasLive) {
        const heading = document.createElement('h3'); heading.textContent = 'Between programme events';
        const paragraph = document.createElement('p'); paragraph.textContent = 'See the full schedule for the next event.';
        content.replaceChildren(heading, paragraph); delete content.dataset.wasLive;
      }
    } catch { /* Preserve last good render. No false live state after a network error. */ }
  }
  refreshLive(); setInterval(refreshLive, 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshLive(); });
})();
