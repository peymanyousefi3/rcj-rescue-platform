# Browser dependencies

Local, pinned distributions; no CDN requests are made by the dashboard.

- FullCalendar Standard 6.1.22: https://cdn.jsdelivr.net/npm/fullcalendar@6.1.22/index.global.min.js
  - Official integration documentation: https://legacy.fullcalendar.io/v6/initialize-globals
  - Includes day, week and month views, touch interaction and drag/resize support.
  - Its styles use a fresh per-request CSP style nonce. Executable inline scripts remain blocked.
- SortableJS 1.15.6: https://cdn.jsdelivr.net/npm/sortablejs@1.15.6/Sortable.min.js
  - Official repository: https://github.com/SortableJS/Sortable
  - Team order also has native keyboard-operable move buttons.

Upstream license files are included alongside these distributions.

- Google model-viewer 4.4.0 (Apache 2.0): https://ajax.googleapis.com/ajax/libs/model-viewer/4.4.0/model-viewer.min.js
  - Official documentation: https://modelviewer.dev/docs/
  - Isolated field viewer; self-contained GLB assets only. No model is loaded on the maps index.
  - The upstream debug source-map comment is removed; runtime code is unchanged.
