'use strict';
(() => {
  let root = document.querySelector('[data-programme]');
  if (!root) return;
  root.dataset.enhanced = 'true';
  let serverOffset = 0;
  let refreshing = false;

  function activateDay(tab, focus = false) {
    root.querySelectorAll('[data-programme-day]').forEach(item => {
      const selected = item === tab;
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
      const panel = document.getElementById(item.getAttribute('aria-controls'));
      if (panel) panel.hidden = !selected;
    });
    if (focus) tab.focus({preventScroll: true});
    if (!document.body.dataset.preview && location.protocol !== 'file:') {
      const url = new URL(location.href);
      url.searchParams.set('day', tab.dataset.programmeDay);
      history.replaceState(null, '', url);
    }
  }

  // Delegate through the document so a fresh server snapshot needs no rebinding.
  document.addEventListener('click', event => {
    const tab = event.target.closest('[data-programme-day]');
    if (tab && root.contains(tab)) activateDay(tab);
  });
  document.addEventListener('keydown', event => {
    const tab = event.target.closest('[data-programme-day]');
    if (!tab || !root.contains(tab)) return;
    const tabs = [...root.querySelectorAll('[data-programme-day]')];
    const index = tabs.indexOf(tab);
    let next;
    if (['ArrowDown', 'ArrowRight'].includes(event.key)) next = (index + 1) % tabs.length;
    if (['ArrowUp', 'ArrowLeft'].includes(event.key)) next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = tabs.length - 1;
    if (next !== undefined) {
      event.preventDefault();
      activateDay(tabs[next], true);
    }
  });

  function markCurrentEvents() {
    const now = Date.now() + serverOffset;
    root.querySelectorAll('[data-programme-event]').forEach(event => {
      const live = event.dataset.confirmed === 'true' &&
        Date.parse(event.dataset.start) <= now && Date.parse(event.dataset.end) > now;
      event.classList.toggle('is-live', live);
      const label = event.querySelector('.programme-live-label');
      if (label) label.hidden = !live;
    });
    root.querySelectorAll('[data-programme-round]').forEach(round => {
      const label = round.querySelector('[data-round-live]');
      if (label) label.hidden = !round.querySelector('.programme-run.is-live');
    });
  }
  document.addEventListener('asr:server-time', event => {
    const parsed = Date.parse(event.detail);
    if (Number.isFinite(parsed)) serverOffset = parsed - Date.now();
    markCurrentEvents();
  });

  async function refreshProgramme() {
    if (refreshing || document.hidden || document.body.dataset.preview || location.protocol === 'file:') return;
    refreshing = true;
    try {
      const selectedDay = root.querySelector('[data-programme-day][aria-selected=true]')?.dataset.programmeDay || '';
      const response = await fetch('/schedule/fragment/?day=' + encodeURIComponent(selectedDay), {
        credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'text/html'},
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok || !response.headers.get('Content-Type')?.includes('text/html')) throw new Error('Programme unavailable');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const replacement = page.querySelector('[data-programme]');
      if (!replacement) throw new Error('Invalid programme response');
      if (replacement.dataset.version !== root.dataset.version) {
        // Capture state after transfer: people can keep interacting while it loads.
        const selected = root.querySelector('[data-programme-day][aria-selected=true]')?.dataset.programmeDay;
        const roundState = new Map([...root.querySelectorAll('[data-programme-round]')]
          .map(round => [round.dataset.programmeRound, round.open]));
        const noticeState = new Map([...root.querySelectorAll('[data-programme-notice]')]
          .map(notice => [notice.dataset.programmeNotice, notice.open]));
        const focused = document.activeElement;
        const focusedTab = focused?.dataset.programmeDay;
        const focusedRound = focused?.closest('[data-programme-round]')?.dataset.programmeRound;
        const focusedNotice = focused?.closest('[data-programme-notice]')?.dataset.programmeNotice;
        const inside = root.contains(focused);
        const scroll = window.scrollY;
        replacement.querySelectorAll('[data-programme-round]').forEach(round => {
          if (roundState.has(round.dataset.programmeRound)) round.open = roundState.get(round.dataset.programmeRound);
        });
        replacement.querySelectorAll('[data-programme-notice]').forEach(notice => {
          if (noticeState.has(notice.dataset.programmeNotice)) notice.open = noticeState.get(notice.dataset.programmeNotice);
        });
        replacement.dataset.enhanced = 'true';
        root.replaceWith(replacement);
        root = replacement;
        const selectedTab = [...root.querySelectorAll('[data-programme-day]')].find(tab => tab.dataset.programmeDay === selected);
        if (selectedTab) activateDay(selectedTab);
        if (inside) {
          const target = [...root.querySelectorAll('[data-programme-day]')].find(tab => tab.dataset.programmeDay === focusedTab) ||
            [...root.querySelectorAll('[data-programme-round]')].find(round => round.dataset.programmeRound === focusedRound)?.querySelector('summary') ||
            [...root.querySelectorAll('[data-programme-notice]')].find(notice => notice.dataset.programmeNotice === focusedNotice)?.querySelector('summary') || selectedTab;
          target?.focus({preventScroll: true});
        }
        window.scrollTo({top: scroll, behavior: 'instant'});
        const status = root.querySelector('[data-programme-update-status]');
        if (status) status.textContent = 'The organizer’s programme has been updated.';
      } else {
        root.querySelectorAll('[data-feed-status]').forEach(label => {
          if (label.dataset.original) {label.textContent = label.dataset.original; delete label.dataset.original;}
        });
      }
      root.removeAttribute('data-feed-offline');
      markCurrentEvents();
    } catch {
      root.dataset.feedOffline = 'true';
      root.querySelectorAll('[data-feed-status]').forEach(label => {
        label.dataset.original ||= label.textContent;
        label.textContent = 'Connection interrupted · showing saved schedule';
      });
    } finally { refreshing = false; }
  }
  // Native details and server-rendered day selection remain usable without JS.
  markCurrentEvents();
  setInterval(markCurrentEvents, 15000);
  setInterval(refreshProgramme, 30000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {markCurrentEvents(); refreshProgramme();}
  });
})();
