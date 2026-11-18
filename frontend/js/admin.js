/* ============================================================
   JG INMOBILIARIA — Panel Admin v2
   admin.js  (~700 líneas)
   ============================================================ */

'use strict';

// ── Variables globales ───────────────────────────────────────
const charts = {};
let currentSection = 'dashboard';
let filterFrom = '';
let filterTo   = '';
let allReservations = [];
let allInquiries    = [];
let allProperties   = [];
let resPage = 1;
const RES_PER_PAGE = 10;
let editingPropertyId = null;

// ── Mapa de títulos de sección ───────────────────────────────
const SECTION_TITLES = {
  dashboard:    'Dashboard',
  visitas:      'Métricas de Visita',
  cotizaciones: 'Cotizaciones',
  inventario:   'Inventario',
  mensajes:     'Mensajes',
  agente:       'Agente IA',
};

let agentProviders = {};
let agentDefaultPrompt = '';
let agentTestHistory = [];
let knowledgeEntries = [];
let editingKnowledgeId = null;
const MAX_UPLOAD_BYTES = 8 * 1024 * 1024;

/* ============================================================
   UTILIDADES
   ============================================================ */
function formatCOP(n) {
  return '$' + Number(n).toLocaleString('es-CO') + ' COP';
}

function formatDate(str) {
  if (!str) return '—';
  const d = new Date(str);
  if (isNaN(d)) return str;
  return d.toLocaleDateString('es-CO', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function badgeHTML(status) {
  const safe = (status || 'desconocido').toLowerCase().replace(/\s/g, '_');
  return `<span class="badge badge-${safe}">${status || '—'}</span>`;
}

function escapeHTML(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function apiFetch(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  return res;
}

/* ============================================================
   RELOJ
   ============================================================ */
function startClock() {
  const el = document.getElementById('clock');
  function tick() {
    el.textContent = new Date().toLocaleTimeString('es-CO', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  }
  tick();
  setInterval(tick, 1000);
}

/* ============================================================
   INICIALIZACIÓN
   ============================================================ */
document.addEventListener('DOMContentLoaded', async () => {
  startClock();
  bindStaticEvents();

  try {
    const res = await apiFetch('/api/admin/me');
    if (res.ok) {
      const data = await res.json();
      showPanel(data);
    } else {
      showLogin();
    }
  } catch {
    showLogin();
  }
});

function showLogin() {
  document.getElementById('login-screen').classList.remove('hidden');
  document.getElementById('admin-panel').classList.add('hidden');
}

function showPanel(userData) {
  document.getElementById('login-screen').classList.add('hidden');
  document.getElementById('admin-panel').classList.remove('hidden');
  if (userData && userData.username) {
    document.getElementById('admin-name').textContent = userData.username;
    document.getElementById('sidebar-username').textContent = userData.username;
  }
  showSection('dashboard');
}

/* ============================================================
   LOGIN
   ============================================================ */
function bindStaticEvents() {
  // Login form
  document.getElementById('login-form').addEventListener('submit', handleLogin);

  // Logout
  document.getElementById('btn-logout').addEventListener('click', handleLogout);

  // Nav links
  document.querySelectorAll('.sidebar-nav a[data-section]').forEach(link => {
    link.addEventListener('click', e => {
      e.preventDefault();
      const section = link.dataset.section;
      showSection(section);
      closeSidebar();
    });
  });

  // Hamburguesa
  document.getElementById('menu-toggle').addEventListener('click', toggleSidebar);
  document.getElementById('sidebar-overlay').addEventListener('click', closeSidebar);

  // Filtros de fecha — atajos
  // Filtro de fechas y atajos
  document.querySelectorAll('.btn-shortcut').forEach(btn => {
    btn.addEventListener('click', (e) => applyShortcut(btn.dataset.shortcut, e.currentTarget));
  });
  document.getElementById('btn-apply-filter').addEventListener('click', applyFilter);

  // Dashboard acciones
  document.getElementById('btn-csv').addEventListener('click', downloadCSV);
  document.getElementById('btn-print').addEventListener('click', printReport);

  // Cotizaciones — búsqueda y filtro en tiempo real
  document.getElementById('res-search').addEventListener('input', filterReservations);
  document.getElementById('res-status-filter').addEventListener('change', filterReservations);

  // Inventario — filtros en tiempo real
  document.getElementById('prop-op-filter').addEventListener('change', filterProperties);
  document.getElementById('prop-status-filter').addEventListener('change', filterProperties);
  document.getElementById('prop-city-filter').addEventListener('input', filterProperties);

  // Modal inmueble
  document.getElementById('btn-new-property').addEventListener('click', () => openPropertyModal(null));
  document.getElementById('modal-property-close').addEventListener('click', closePropertyModal);
  document.getElementById('modal-property-cancel').addEventListener('click', closePropertyModal);
  document.getElementById('btn-save-property').addEventListener('click', saveProperty);
  document.getElementById('modal-property').addEventListener('click', e => {
    if (e.target === e.currentTarget) closePropertyModal();
  });

  // Agente IA
  document.getElementById('agent-provider').addEventListener('change', onAgentProviderChange);
  document.getElementById('agent-temperature').addEventListener('input', e => {
    document.getElementById('agent-temperature-value').textContent = Number(e.target.value).toFixed(1);
  });
  document.getElementById('btn-agent-reset-prompt').addEventListener('click', () => {
    document.getElementById('agent-system-prompt').value = agentDefaultPrompt;
  });
  document.getElementById('form-agent-config').addEventListener('submit', e => {
    e.preventDefault();
    saveAgentConfig(false);
  });
  document.getElementById('btn-agent-clear-key').addEventListener('click', () => {
    if (confirm('¿Eliminar la API key guardada? El agente se desactivará.')) saveAgentConfig(true);
  });
  document.getElementById('form-agent-test').addEventListener('submit', sendAgentTest);
  document.getElementById('btn-agent-test-clear').addEventListener('click', resetAgentTest);
  document.getElementById('form-knowledge-text').addEventListener('submit', createKnowledgeText);
  document.getElementById('form-knowledge-file').addEventListener('submit', uploadKnowledgeFile);
  document.getElementById('modal-knowledge-close').addEventListener('click', closeKnowledgeModal);
  document.getElementById('modal-knowledge-cancel').addEventListener('click', closeKnowledgeModal);
  document.getElementById('btn-save-knowledge').addEventListener('click', saveKnowledgeEdit);
  document.getElementById('modal-knowledge').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeKnowledgeModal();
  });
}

async function handleLogin(e) {
  e.preventDefault();
  const username = document.getElementById('login-user').value.trim();
  const password = document.getElementById('login-pass').value;
  const errEl    = document.getElementById('login-error');
  errEl.textContent = '';

  try {
    const res = await apiFetch('/api/admin/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
    if (res.ok) {
      const data = await res.json();
      showPanel(data);
    } else {
      const data = await res.json().catch(() => ({}));
      errEl.textContent = data.error || 'Credenciales incorrectas.';
    }
  } catch {
    errEl.textContent = 'Error de conexión. Intente de nuevo.';
  }
}

async function handleLogout() {
  try {
    await apiFetch('/api/admin/logout', { method: 'POST' });
  } catch { /* ignore */ }

  // Limpiar charts
  Object.keys(charts).forEach(k => {
    if (charts[k]) { charts[k].destroy(); delete charts[k]; }
  });

  showLogin();
}

/* ============================================================
   NAVEGACIÓN
   ============================================================ */
function showSection(name) {
  currentSection = name;

  // Ocultar todas las secciones
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  const target = document.getElementById(`section-${name}`);
  if (target) target.classList.add('active');

  // Actualizar nav activo
  document.querySelectorAll('.sidebar-nav a[data-section]').forEach(link => {
    link.classList.toggle('active', link.dataset.section === name);
  });

  // Título topbar
  document.getElementById('section-title').textContent = SECTION_TITLES[name] || name;

  // Cargar datos
  switch (name) {
    case 'dashboard':    loadDashboard(); break;
    case 'visitas':      loadVisits();    break;
    case 'cotizaciones': loadReservations(); break;
    case 'inventario':   loadProperties();  break;
    case 'mensajes':     loadInquiries();   break;
    case 'agente':       loadAgentConfig(); loadKnowledge(); break;
  }
}

/* ============================================================
   SIDEBAR MÓVIL
   ============================================================ */
function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('sidebar-overlay').classList.toggle('visible');
}
function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebar-overlay').classList.remove('visible');
}

/* ============================================================
   FILTROS DE FECHA
   ============================================================ */
function applyShortcut(shortcut, btnElement) {
  const today = new Date();
  let from = '', to = '';

  document.querySelectorAll('.btn-shortcut').forEach(b => b.classList.remove('active-shortcut'));
  if (btnElement) btnElement.classList.add('active-shortcut');

  to = toISODate(today);

  if (shortcut === 'today') {
    from = to;
  } else if (shortcut === 'week') {
    const d = new Date(today);
    const day = d.getDay();
    const diff = d.getDate() - day + (day === 0 ? -6 : 1);
    d.setDate(diff);
    from = toISODate(d);
  } else if (shortcut === 'month') {
    from = toISODate(new Date(today.getFullYear(), today.getMonth(), 1));
  } else if (shortcut === 'quarter') {
    const currentQuarter = Math.floor(today.getMonth() / 3);
    from = toISODate(new Date(today.getFullYear(), currentQuarter * 3, 1));
  } else if (shortcut === 'year') {
    from = toISODate(new Date(today.getFullYear(), 0, 1));
  } else if (shortcut === 'all' || shortcut === 'clear') {
    from = '';
    to = '';
  }

  document.getElementById('filter-from').value = from;
  document.getElementById('filter-to').value   = to;
  filterFrom = from;
  filterTo   = to;

  loadDashboard();
  if (currentSection === 'visitas') loadVisits();
}

function toISODate(d) {
  return d.toISOString().split('T')[0];
}

function applyFilter() {
  filterFrom = document.getElementById('filter-from').value;
  filterTo   = document.getElementById('filter-to').value;
  loadDashboard();
  if (currentSection === 'visitas') loadVisits();
}

/* ============================================================
   DASHBOARD
   ============================================================ */
async function loadDashboard() {
  const params = new URLSearchParams();
  if (filterFrom) params.set('from', filterFrom);
  if (filterTo)   params.set('to',   filterTo);

  // Metadatos para reporte imprimible / PDF
  const printDateEl = document.getElementById('print-date');
  if (printDateEl) {
    printDateEl.textContent = new Date().toLocaleDateString('es-CO', { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
  const printPeriodEl = document.getElementById('print-period');
  if (printPeriodEl) {
    if (filterFrom && filterTo) {
      printPeriodEl.textContent = `${filterFrom} al ${filterTo}`;
    } else if (filterFrom) {
      printPeriodEl.textContent = `Desde ${filterFrom}`;
    } else if (filterTo) {
      printPeriodEl.textContent = `Hasta ${filterTo}`;
    } else {
      printPeriodEl.textContent = 'Histórico consolidado (General)';
    }
  }

  try {
    const res  = await apiFetch(`/api/admin/dashboard?${params}`);
    if (!res.ok) return;
    const data = await res.json();
    const stats = data.stats || data;

    // Actualización de KPIs
    const incEl = document.getElementById('kpi-income');
    if (incEl) incEl.textContent = formatCOP(stats.total_income_cop ?? stats.total_income ?? 0);

    const ticketEl = document.getElementById('kpi-avg-ticket');
    if (ticketEl) ticketEl.textContent = formatCOP(stats.average_ticket ?? 0);

    const resEl = document.getElementById('kpi-total-res');
    if (resEl) resEl.textContent = stats.total_reservations ?? 0;

    const convEl = document.getElementById('kpi-conversion');
    if (convEl) convEl.textContent = stats.conversion_rate ?? 0;

    const propsEl = document.getElementById('kpi-active-props');
    if (propsEl) propsEl.textContent = stats.available_properties ?? 0;

    const inqEl = document.getElementById('kpi-inquiries');
    if (inqEl) inqEl.textContent = stats.new_inquiries ?? 0;

    // Render de Charts
    if (data.charts) renderCharts(data.charts);
  } catch (err) {
    console.error('loadDashboard error:', err);
  }
}

function renderCharts(chartData) {
  // Destruir instancias previas
  ['chart-monthly','chart-dist','chart-city','chart-top'].forEach(id => {
    if (charts[id]) { charts[id].destroy(); delete charts[id]; }
  });

  // 1. Ingresos por mes — Bar
  const monthly = chartData.monthly_income || { labels: [], values: [] };
  const monthlyLabels = (monthly.labels && monthly.labels.length) ? monthly.labels : ['Sin registros'];
  const monthlyValues = (monthly.values && monthly.values.length) ? monthly.values.map(v => +(v / 1_000_000).toFixed(2)) : [0];

  const ctxMonthly = document.getElementById('chart-monthly');
  if (ctxMonthly) {
    charts['chart-monthly'] = new Chart(ctxMonthly.getContext('2d'), {
      type: 'bar',
      data: {
        labels: monthlyLabels,
        datasets: [{
          label: 'Ventas (Millones COP)',
          data: monthlyValues,
          backgroundColor: 'rgba(26, 35, 126, 0.85)',
          borderColor: '#1a237e',
          borderWidth: 1,
          borderRadius: 6,
        }],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => ` Ingresos: $${ctx.raw}M COP`
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: { callback: v => '$' + v + 'M' }
          }
        },
      },
    });
  }

  // 2. Venta vs Arriendo — Doughnut
  const dist = chartData.operation_distribution || chartData.operation_dist || { venta: 0, arriendo: 0 };
  const ctxDist = document.getElementById('chart-dist');
  if (ctxDist) {
    const hasDistData = (dist.venta || 0) + (dist.arriendo || 0) > 0;
    charts['chart-dist'] = new Chart(ctxDist.getContext('2d'), {
      type: 'doughnut',
      data: {
        labels: hasDistData ? ['Venta', 'Arriendo'] : ['Sin cotizaciones'],
        datasets: [{
          data: hasDistData ? [dist.venta || 0, dist.arriendo || 0] : [1],
          backgroundColor: hasDistData ? ['#1a237e', '#c9a84c'] : ['#e2e8f0'],
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { position: 'bottom' },
        },
      },
    });
  }

  // 3. Demanda por Ciudad (Medellín vs Bogotá) — Bar
  const city = chartData.city_distribution || { labels: ['Medellín', 'Bogotá'], values: [0, 0] };
  const ctxCity = document.getElementById('chart-city');
  if (ctxCity) {
    charts['chart-city'] = new Chart(ctxCity.getContext('2d'), {
      type: 'bar',
      data: {
        labels: city.labels || ['Medellín', 'Bogotá'],
        datasets: [{
          label: 'Cotizaciones recibidas',
          data: city.values || [0, 0],
          backgroundColor: ['rgba(26, 35, 126, 0.85)', 'rgba(201, 168, 76, 0.85)'],
          borderRadius: 6,
        }],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          y: {
            beginAtZero: true,
            ticks: { stepSize: 1 }
          }
        },
      },
    });
  }

  // 4. Top 5 Inmuebles más demandados — Bar horizontal
  const top = chartData.top_properties || { labels: [], values: [] };
  const topLabels = (top.labels && top.labels.length) ? top.labels : ['Sin cotizaciones'];
  const topValues = (top.values && top.values.length) ? top.values : [0];

  const ctxTop = document.getElementById('chart-top');
  if (ctxTop) {
    charts['chart-top'] = new Chart(ctxTop.getContext('2d'), {
      type: 'bar',
      data: {
        labels: topLabels,
        datasets: [{
          label: 'Cotizaciones',
          data: topValues,
          backgroundColor: 'rgba(201, 168, 76, 0.85)',
          borderRadius: 4,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            beginAtZero: true,
            ticks: { stepSize: 1 }
          }
        },
      },
    });
  }
}

/* ============================================================
   CSV / PRINT
   ============================================================ */
function downloadCSV() {
  const params = new URLSearchParams();
  if (filterFrom) params.set('from', filterFrom);
  if (filterTo)   params.set('to',   filterTo);
  window.location.href = `/api/admin/reports/csv?${params}`;
}

function printReport() {
  window.print();
}

/* ============================================================
   VISITAS
   ============================================================ */
async function loadVisits() {
  const params = new URLSearchParams();
  if (filterFrom) params.set('from', filterFrom);
  if (filterTo)   params.set('to',   filterTo);

  try {
    const res  = await apiFetch(`/api/admin/visits?${params}`);
    if (!res.ok) return;
    const data = await res.json();

    // KPIs
    const totalVisits = data.total_visits ?? data.total ?? 0;
    document.getElementById('kpi-total-visits').textContent = totalVisits;

    const byDevice = data.by_device || {};
    document.getElementById('kpi-mobile').textContent  = byDevice.mobile || 0;
    document.getElementById('kpi-desktop').textContent = byDevice.desktop || 0;
    document.getElementById('kpi-tablet').textContent  = byDevice.tablet || 0;

    // Gráfica de visitas diarias
    if (data.daily && document.getElementById('chart-daily-visits')) {
      if (charts['chart-daily-visits']) {
        charts['chart-daily-visits'].destroy();
        delete charts['chart-daily-visits'];
      }
      const days = data.daily.map(d => d.day);
      const counts = data.daily.map(d => d.count);
      charts['chart-daily-visits'] = new Chart(
        document.getElementById('chart-daily-visits').getContext('2d'),
        {
          type: 'line',
          data: {
            labels: days.length ? days : ['Hoy'],
            datasets: [{
              label: 'Visitas',
              data: counts.length ? counts : [totalVisits],
              borderColor: '#1a237e',
              backgroundColor: 'rgba(26, 35, 126, 0.1)',
              tension: 0.3,
              fill: true,
              pointRadius: 4,
            }],
          },
          options: {
            responsive: true,
            plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
          },
        }
      );
    }

    // Tabla de páginas más visitadas
    const tbodyPages = document.getElementById('tbody-pages');
    if (tbodyPages && data.by_page) {
      if (data.by_page.length === 0) {
        tbodyPages.innerHTML = '<tr><td colspan="2" style="text-align:center;color:var(--text-muted);padding:15px;">Sin visitas registradas</td></tr>';
      } else {
        tbodyPages.innerHTML = data.by_page.map(p => `
          <tr>
            <td><code>${escapeHTML(p.page)}</code></td>
            <td style="font-weight:600;">${p.count}</td>
          </tr>
        `).join('');
      }
    }

    // Dona de dispositivos
    const ctxDevices = document.getElementById('chart-devices');
    if (ctxDevices) {
      if (charts['chart-devices']) {
        charts['chart-devices'].destroy();
        delete charts['chart-devices'];
      }
      charts['chart-devices'] = new Chart(ctxDevices.getContext('2d'), {
        type: 'doughnut',
        data: {
          labels: ['Móvil', 'Desktop', 'Tablet'],
          datasets: [{
            data: [byDevice.mobile || 0, byDevice.desktop || 0, byDevice.tablet || 0],
            backgroundColor: ['#c9a84c', '#1a237e', '#0288d1'],
            borderWidth: 2,
          }],
        },
        options: {
          responsive: true,
          plugins: { legend: { position: 'bottom' } },
        },
      });
    }
  } catch (err) {
    console.error('loadVisits error:', err);
  }
}

/* ============================================================
   COTIZACIONES
   ============================================================ */
async function loadReservations() {
  try {
    const res  = await apiFetch('/api/admin/reservations');
    if (!res.ok) return;
    const data = await res.json();
    allReservations = Array.isArray(data) ? data : (data.reservations || []);
    resPage = 1;
    renderReservationsTable(filteredReservations());
  } catch (err) {
    console.error('loadReservations error:', err);
  }
}

function filteredReservations() {
  const q      = document.getElementById('res-search').value.toLowerCase();
  const status = document.getElementById('res-status-filter').value;
  return allReservations.filter(r => {
    const matchQ = !q || (r.client_name || '').toLowerCase().includes(q)
                       || (r.code || '').toLowerCase().includes(q)
                       || (r.id + '').includes(q);
    const matchS = !status || r.status === status;
    return matchQ && matchS;
  });
}

function filterReservations() {
  resPage = 1;
  renderReservationsTable(filteredReservations());
}

function renderReservationsTable(list) {
  const tbody  = document.getElementById('tbody-reservations');
  const pagDiv = document.getElementById('res-pagination');
  const total  = list.length;
  const pages  = Math.max(1, Math.ceil(total / RES_PER_PAGE));
  if (resPage > pages) resPage = pages;

  const slice = list.slice((resPage - 1) * RES_PER_PAGE, resPage * RES_PER_PAGE);

  if (slice.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:20px;">Sin resultados</td></tr>';
    pagDiv.innerHTML = '';
    return;
  }

  tbody.innerHTML = slice.map(r => {
    const statusOptions = ['pendiente','en_revision','aprobado','cerrado','cancelado']
      .map(s => `<option value="${s}"${r.status === s ? ' selected' : ''}>${s}</option>`).join('');
    return `<tr>
      <td><code>#${escapeHTML(r.code || r.id)}</code></td>
      <td>${escapeHTML(r.client_name)}</td>
      <td>${escapeHTML(r.property_title || r.property_id || '—')}</td>
      <td style="white-space:nowrap">${formatCOP(r.total_amount || 0)}</td>
      <td>${escapeHTML(r.payment_method || '—')}</td>
      <td>${badgeHTML(r.status)}</td>
      <td style="white-space:nowrap">${formatDate(r.created_at)}</td>
      <td>
        <select class="status-select" data-id="${r.id}" onchange="updateReservationStatus(${r.id}, this.value)">
          ${statusOptions}
        </select>
      </td>
    </tr>`;
  }).join('');

  // Paginación
  let pagHTML = '';
  if (pages > 1) {
    if (resPage > 1) pagHTML += `<button onclick="gotoResPage(${resPage-1})">‹</button>`;
    for (let i = 1; i <= pages; i++) {
      pagHTML += `<button class="${i === resPage ? 'current' : ''}" onclick="gotoResPage(${i})">${i}</button>`;
    }
    if (resPage < pages) pagHTML += `<button onclick="gotoResPage(${resPage+1})">›</button>`;
  }
  pagDiv.innerHTML = pagHTML;
}

function gotoResPage(p) {
  resPage = p;
  renderReservationsTable(filteredReservations());
}

async function updateReservationStatus(id, status) {
  try {
    const res = await apiFetch(`/api/admin/reservations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
    if (res.ok) {
      const idx = allReservations.findIndex(r => r.id === id);
      if (idx !== -1) allReservations[idx].status = status;
      renderReservationsTable(filteredReservations());
    }
  } catch (err) {
    console.error('updateReservationStatus error:', err);
  }
}

/* ============================================================
   INVENTARIO
   ============================================================ */
async function loadProperties() {
  try {
    const res  = await apiFetch('/api/admin/properties');
    if (!res.ok) return;
    const data = await res.json();
    allProperties = Array.isArray(data) ? data : (data.properties || []);
    renderPropertiesTable(filteredProperties());
  } catch (err) {
    console.error('loadProperties error:', err);
  }
}

function filteredProperties() {
  const op     = document.getElementById('prop-op-filter').value;
  const status = document.getElementById('prop-status-filter').value;
  const city   = document.getElementById('prop-city-filter').value.toLowerCase();
  return allProperties.filter(p => {
    const matchOp     = !op     || p.operation === op;
    const matchStatus = !status || p.status    === status;
    const matchCity   = !city   || (p.city || '').toLowerCase().includes(city);
    return matchOp && matchStatus && matchCity;
  });
}

function filterProperties() {
  renderPropertiesTable(filteredProperties());
}

function renderPropertiesTable(list) {
  const tbody = document.getElementById('tbody-properties');
  if (list.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:20px;">Sin inmuebles</td></tr>';
    return;
  }
  tbody.innerHTML = list.map(p => {
    const thumb = p.image_url || 'https://images.unsplash.com/photo-1512917774080-9991f1c4c750?auto=format&fit=crop&w=120&q=80';
    const propType = p.property_type || p.type || 'apartamento';
    return `
    <tr>
      <td>
        <div style="display:flex;align-items:center;gap:12px;">
          <img src="${escapeHTML(thumb)}" alt="" style="width:48px;height:48px;border-radius:6px;object-fit:cover;border:1px solid #e2e8f0;flex-shrink:0;" onerror="this.src='https://images.unsplash.com/photo-1512917774080-9991f1c4c750?auto=format&fit=crop&w=120&q=80'">
          <div>
            <div style="font-weight:600;color:var(--text-main);">${escapeHTML(p.title)}</div>
            <div style="font-size:11px;color:var(--text-muted);">${escapeHTML(p.neighborhood || '')}</div>
          </div>
        </div>
      </td>
      <td style="text-transform:capitalize;">${escapeHTML(propType)}</td>
      <td style="text-transform:capitalize;">${escapeHTML(p.operation || '—')}</td>
      <td style="text-transform:capitalize;">${escapeHTML(p.city || '—')}</td>
      <td style="white-space:nowrap;font-weight:600;">${formatCOP(p.price || 0)}</td>
      <td>${badgeHTML(p.status)}</td>
      <td style="white-space:nowrap">
        <button class="btn btn-secondary btn-xs" onclick='openPropertyModal(${JSON.stringify(p)})'>✏️ Editar</button>
        <button class="btn btn-danger btn-xs" onclick="deleteProperty(${p.id})" style="margin-left:4px;">🗑️</button>
      </td>
    </tr>
  `}).join('');
}

function openPropertyModal(prop) {
  editingPropertyId = prop ? prop.id : null;
  document.getElementById('modal-property-title').textContent = prop ? 'Editar Inmueble' : 'Nuevo Inmueble';

  // Limpiar/rellenar campos
  const fields = {
    'prop-id':           prop ? prop.id           : '',
    'prop-title':        prop ? prop.title         : '',
    'prop-type':         prop ? (prop.property_type || prop.type || 'apartamento') : 'apartamento',
    'prop-operation':    prop ? prop.operation     : 'venta',
    'prop-status':       prop ? prop.status        : 'disponible',
    'prop-city':         prop ? (prop.city || 'medellin') : 'medellin',
    'prop-neighborhood': prop ? (prop.neighborhood || '') : '',
    'prop-price':        prop ? prop.price         : '',
    'prop-area':         prop ? (prop.area_m2 || prop.area || '')  : '',
    'prop-rooms':        prop ? (prop.bedrooms || prop.rooms || '') : '',
    'prop-baths':        prop ? (prop.bathrooms || prop.baths || '') : '',
    'prop-description':  prop ? (prop.description || '') : '',
    'prop-image':        prop ? (prop.image_url || '') : '',
  };
  Object.entries(fields).forEach(([id, val]) => {
    const el = document.getElementById(id);
    if (el) el.value = val || '';
  });

  document.getElementById('modal-property').classList.remove('hidden');
}

function closePropertyModal() {
  document.getElementById('modal-property').classList.add('hidden');
  editingPropertyId = null;
}

async function saveProperty() {
  const form = document.getElementById('form-property');
  if (!form.checkValidity()) { form.reportValidity(); return; }

  const price = parseFloat(document.getElementById('prop-price').value) || 0;
  const pType = document.getElementById('prop-type').value.toLowerCase();
  const city = document.getElementById('prop-city').value.trim().toLowerCase();
  const separation_fee = Math.max(1000000, Math.round(price * 0.01));

  const body = {
    title:         document.getElementById('prop-title').value.trim(),
    property_type: (pType === 'casa' || pType === 'apartamento') ? pType : 'apartamento',
    type:          (pType === 'casa' || pType === 'apartamento') ? pType : 'apartamento',
    operation:     document.getElementById('prop-operation').value,
    status:        document.getElementById('prop-status').value,
    city:          (city.includes('bogot') || city === 'bogota') ? 'bogota' : 'medellin',
    neighborhood:  document.getElementById('prop-neighborhood').value.trim() || 'Sector Residencial',
    price:         price,
    separation_fee: separation_fee,
    admin_fee:     0,
    area_m2:       parseFloat(document.getElementById('prop-area').value) || 100,
    bedrooms:      parseInt(document.getElementById('prop-rooms').value) || 2,
    bathrooms:     parseInt(document.getElementById('prop-baths').value) || 2,
    parking:       1,
    stratum:       6,
    description:   document.getElementById('prop-description').value.trim() || 'Excelente propiedad residencial con acabados de lujo.',
    image_url:     document.getElementById('prop-image').value.trim() || 'https://images.unsplash.com/photo-1512917774080-9991f1c4c750?auto=format&fit=crop&w=1200&q=80',
  };

  const isEdit = editingPropertyId !== null;
  const url    = isEdit ? `/api/admin/properties/${editingPropertyId}` : '/api/admin/properties';
  const method = isEdit ? 'PUT' : 'POST';

  try {
    const res = await apiFetch(url, { method, body: JSON.stringify(body) });
    if (res.ok) {
      closePropertyModal();
      loadProperties();
    } else {
      const data = await res.json().catch(() => ({}));
      alert(data.error || 'Error al guardar el inmueble.');
    }
  } catch (err) {
    console.error('saveProperty error:', err);
    alert('Error de conexión.');
  }
}

async function deleteProperty(id) {
  if (!confirm('¿Eliminar este inmueble? Esta acción no se puede deshacer.')) return;
  try {
    const res = await apiFetch(`/api/admin/properties/${id}`, { method: 'DELETE' });
    if (res.ok) loadProperties();
    else alert('Error al eliminar el inmueble.');
  } catch (err) {
    console.error('deleteProperty error:', err);
  }
}

/* ============================================================
   MENSAJES / INQUIRIES
   ============================================================ */
async function loadInquiries() {
  try {
    const res  = await apiFetch('/api/admin/inquiries');
    if (!res.ok) return;
    const data = await res.json();
    allInquiries = Array.isArray(data) ? data : (data.inquiries || []);

    // Actualizar badge del nav
    const newCount = allInquiries.filter(i => i.status === 'nuevo').length;
    const badge    = document.getElementById('badge-mensajes');
    if (badge) {
      badge.textContent = newCount;
      badge.classList.toggle('hidden', newCount === 0);
    }
    document.getElementById('kpi-inquiries').textContent = newCount;

    renderInquiriesTable(allInquiries);
  } catch (err) {
    console.error('loadInquiries error:', err);
  }
}

function renderInquiriesTable(list) {
  const tbody = document.getElementById('tbody-inquiries');
  if (list.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:20px;">Sin mensajes</td></tr>';
    return;
  }
  tbody.innerHTML = list.map(i => {
    const msgShort = escapeHTML((i.message || '').substring(0, 60)) + ((i.message || '').length > 60 ? '…' : '');
    return `<tr>
      <td>${escapeHTML(i.name)}</td>
      <td style="white-space:nowrap">${escapeHTML(i.phone || '—')}</td>
      <td>${escapeHTML(i.email || '—')}</td>
      <td>${escapeHTML(i.city  || '—')}</td>
      <td title="${escapeHTML(i.message)}">${msgShort}</td>
      <td>${escapeHTML(i.source || '—')}</td>
      <td>${badgeHTML(i.status || 'nuevo')}</td>
      <td style="white-space:nowrap">${formatDate(i.created_at)}</td>
      <td style="white-space:nowrap">
        ${i.status !== 'atendido'
          ? `<button class="btn btn-secondary btn-xs" onclick="markInquiryAttended(${i.id})">✔ Atendido</button>`
          : ''
        }
        ${i.phone
          ? `<button class="btn btn-primary btn-xs" onclick="openWhatsApp('${escapeHTML(i.phone)}')" style="margin-left:4px;">💬 WA</button>`
          : ''
        }
      </td>
    </tr>`;
  }).join('');
}

async function markInquiryAttended(id) {
  try {
    const res = await apiFetch(`/api/admin/inquiries/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: 'atendido' }),
    });
    if (res.ok) loadInquiries();
  } catch (err) {
    console.error('markInquiryAttended error:', err);
  }
}

function openWhatsApp(phone) {
  const number = phone.replace(/\D/g, '');
  window.open(`https://wa.me/57${number}`, '_blank');
}

/* ============================================================
   AGENTE IA — CONFIGURACIÓN
   ============================================================ */
function setAgentMsg(id, text, kind) {
  const el = document.getElementById(id);
  el.textContent = text || '';
  el.className = 'agent-msg' + (kind ? ` ${kind}` : '');
}

function renderAgentStatus(cfg) {
  const pill = document.getElementById('agent-status-pill');
  const on = cfg.active && cfg.has_api_key;
  pill.textContent = on ? 'Activo en la web' : 'Inactivo';
  pill.className = 'agent-pill ' + (on ? 'agent-pill-on' : 'agent-pill-off');
}

function fillModelOptions(providerKey) {
  const provider = agentProviders[providerKey];
  const list = document.getElementById('agent-model-options');
  list.innerHTML = (provider?.models || []).map(m => `<option value="${escapeHTML(m)}"></option>`).join('');
  document.getElementById('agent-model').placeholder = provider?.default_model || '';
}

function onAgentProviderChange() {
  const key = document.getElementById('agent-provider').value;
  fillModelOptions(key);
  document.getElementById('agent-model').value = agentProviders[key]?.default_model || '';
  setAgentMsg('agent-config-msg', 'Si cambias de proveedor, ingresa también la API key de ese proveedor.', 'warn');
}

async function loadAgentConfig() {
  try {
    const res = await apiFetch('/api/admin/agent-config');
    if (!res.ok) return;
    const data = await res.json();
    agentProviders = data.providers || {};
    agentDefaultPrompt = data.default_system_prompt || '';
    const cfg = data.config;

    const select = document.getElementById('agent-provider');
    select.innerHTML = Object.entries(agentProviders)
      .map(([key, p]) => `<option value="${key}">${escapeHTML(p.name)}</option>`).join('');
    select.value = cfg.provider;
    fillModelOptions(cfg.provider);

    document.getElementById('agent-model').value = cfg.model || '';
    document.getElementById('agent-api-key').value = '';
    document.getElementById('agent-api-key').placeholder = cfg.has_api_key
      ? `Guardada (${cfg.api_key_masked}). Escribe una nueva para reemplazarla.`
      : 'Sin API key configurada';
    document.getElementById('btn-agent-clear-key').classList.toggle('hidden', !cfg.has_api_key);
    document.getElementById('agent-temperature').value = cfg.temperature;
    document.getElementById('agent-temperature-value').textContent = Number(cfg.temperature).toFixed(1);
    document.getElementById('agent-max-tokens').value = cfg.max_tokens;
    document.getElementById('agent-system-prompt').value = cfg.system_prompt || '';
    document.getElementById('agent-active').checked = !!cfg.active;
    renderAgentStatus(cfg);
  } catch (err) {
    console.error('loadAgentConfig error:', err);
  }
}

async function saveAgentConfig(clearKey) {
  const body = {
    provider:      document.getElementById('agent-provider').value,
    model:         document.getElementById('agent-model').value.trim(),
    api_key:       clearKey ? '' : document.getElementById('agent-api-key').value.trim(),
    clear_api_key: !!clearKey,
    temperature:   parseFloat(document.getElementById('agent-temperature').value),
    max_tokens:    parseInt(document.getElementById('agent-max-tokens').value, 10),
    system_prompt: document.getElementById('agent-system-prompt').value,
    active:        clearKey ? false : document.getElementById('agent-active').checked,
  };
  try {
    const res = await apiFetch('/api/admin/agent-config', { method: 'PUT', body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setAgentMsg('agent-config-msg', data.error || 'No se pudo guardar la configuración.', 'error');
      return;
    }
    await loadAgentConfig();
    setAgentMsg('agent-config-msg', clearKey ? 'API key eliminada.' : 'Configuración guardada.', 'ok');
  } catch (err) {
    console.error('saveAgentConfig error:', err);
    setAgentMsg('agent-config-msg', 'Error de conexión.', 'error');
  }
}

/* ============================================================
   AGENTE IA — CHAT DE PRUEBA
   ============================================================ */
function appendAgentTestBubble(text, kind) {
  const box = document.getElementById('agent-test-messages');
  const div = document.createElement('div');
  div.className = `agent-bubble ${kind}`;
  div.textContent = text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  return div;
}

function resetAgentTest() {
  agentTestHistory = [];
  document.getElementById('agent-test-messages').innerHTML = '';
}

async function sendAgentTest(e) {
  e.preventDefault();
  const input = document.getElementById('agent-test-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  appendAgentTestBubble(text, 'user');
  agentTestHistory.push({ role: 'user', content: text });
  const typing = appendAgentTestBubble('Escribiendo…', 'assistant typing');
  input.disabled = true;

  try {
    const res = await apiFetch('/api/admin/agent-test', {
      method: 'POST',
      body: JSON.stringify({ messages: agentTestHistory }),
    });
    const data = await res.json().catch(() => ({}));
    typing.remove();
    if (res.ok) {
      appendAgentTestBubble(data.reply, 'assistant');
      agentTestHistory.push({ role: 'assistant', content: data.reply });
    } else {
      agentTestHistory.pop();
      appendAgentTestBubble(data.error || 'El agente no respondió.', 'error');
    }
  } catch (err) {
    typing.remove();
    agentTestHistory.pop();
    appendAgentTestBubble('Error de conexión.', 'error');
  } finally {
    input.disabled = false;
    input.focus();
  }
}

/* ============================================================
   AGENTE IA — BASE DE CONOCIMIENTO
   ============================================================ */
const KN_TYPE_LABELS = { text: 'Texto', pdf: 'PDF', image: 'Imagen' };

async function loadKnowledge() {
  try {
    const res = await apiFetch('/api/admin/knowledge');
    if (!res.ok) return;
    const data = await res.json();
    knowledgeEntries = data.entries || [];
    renderKnowledgeTable();
  } catch (err) {
    console.error('loadKnowledge error:', err);
  }
}

function renderKnowledgeTable() {
  const tbody = document.getElementById('tbody-knowledge');
  if (knowledgeEntries.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:20px;">Aún no hay entradas. El agente usará solo el inventario y el prompt.</td></tr>';
    return;
  }
  tbody.innerHTML = knowledgeEntries.map(k => {
    const content = k.content || '';
    const preview = content
      ? `<span class="kn-preview">${escapeHTML(content.substring(0, 140))}${content.length > 140 ? '…' : ''}</span>`
      : '<span class="kn-empty">Sin texto: edítala para que el agente la use</span>';
    const fileLink = k.has_file
      ? `<a class="btn btn-outline btn-xs" href="/api/admin/knowledge/${k.id}/file" target="_blank" rel="noopener" style="margin-left:4px;">📎</a>`
      : '';
    return `<tr>
      <td><strong>${escapeHTML(k.title)}</strong>${k.original_filename ? `<div style="font-size:11px;color:var(--text-muted);">${escapeHTML(k.original_filename)}</div>` : ''}</td>
      <td><span class="kn-type kn-type-${k.entry_type}">${KN_TYPE_LABELS[k.entry_type] || k.entry_type}</span></td>
      <td>${preview}</td>
      <td style="white-space:nowrap">${formatDate(k.created_at)}</td>
      <td style="white-space:nowrap">
        <button class="btn btn-secondary btn-xs" onclick="openKnowledgeModal(${k.id})">✏️ Editar</button>${fileLink}
        <button class="btn btn-danger btn-xs" onclick="deleteKnowledge(${k.id})" style="margin-left:4px;">🗑️</button>
      </td>
    </tr>`;
  }).join('');
}

async function createKnowledgeText(e) {
  e.preventDefault();
  const body = {
    title:   document.getElementById('kn-text-title').value.trim(),
    content: document.getElementById('kn-text-content').value.trim(),
  };
  try {
    const res = await apiFetch('/api/admin/knowledge', { method: 'POST', body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setAgentMsg('knowledge-msg', data.error || 'No se pudo guardar la entrada.', 'error');
      return;
    }
    e.target.reset();
    setAgentMsg('knowledge-msg', 'Entrada agregada.', 'ok');
    loadKnowledge();
  } catch (err) {
    setAgentMsg('knowledge-msg', 'Error de conexión.', 'error');
  }
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function uploadKnowledgeFile(e) {
  e.preventDefault();
  const file = document.getElementById('kn-file-input').files[0];
  if (!file) return;
  if (file.size > MAX_UPLOAD_BYTES) {
    setAgentMsg('knowledge-msg', 'El archivo supera el máximo de 8 MB.', 'error');
    return;
  }
  const btn = document.getElementById('btn-kn-upload');
  btn.disabled = true;
  setAgentMsg('knowledge-msg', 'Subiendo y procesando archivo…', '');
  try {
    const body = {
      title:       document.getElementById('kn-file-title').value.trim(),
      description: document.getElementById('kn-file-description').value.trim(),
      filename:    file.name,
      mime_type:   file.type || (/\.pdf$/i.test(file.name) ? 'application/pdf' : ''),
      data:        await readFileAsBase64(file),
    };
    const res = await apiFetch('/api/admin/knowledge/upload', { method: 'POST', body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setAgentMsg('knowledge-msg', data.error || 'No se pudo subir el archivo.', 'error');
      return;
    }
    e.target.reset();
    if (data.warning) setAgentMsg('knowledge-msg', data.warning, 'warn');
    else setAgentMsg('knowledge-msg', `Archivo procesado (${data.entry.content_length.toLocaleString('es-CO')} caracteres de texto).`, 'ok');
    loadKnowledge();
  } catch (err) {
    console.error('uploadKnowledgeFile error:', err);
    setAgentMsg('knowledge-msg', 'Error de conexión.', 'error');
  } finally {
    btn.disabled = false;
  }
}

function openKnowledgeModal(id) {
  const entry = knowledgeEntries.find(k => k.id === id);
  if (!entry) return;
  editingKnowledgeId = id;
  document.getElementById('kn-edit-title').value = entry.title || '';
  document.getElementById('kn-edit-content').value = entry.content || '';
  const link = document.getElementById('kn-edit-file-link');
  link.classList.toggle('hidden', !entry.has_file);
  link.href = entry.has_file ? `/api/admin/knowledge/${id}/file` : '#';
  document.getElementById('modal-knowledge').classList.remove('hidden');
}

function closeKnowledgeModal() {
  document.getElementById('modal-knowledge').classList.add('hidden');
  editingKnowledgeId = null;
}

async function saveKnowledgeEdit() {
  if (editingKnowledgeId === null) return;
  const body = {
    title:   document.getElementById('kn-edit-title').value.trim(),
    content: document.getElementById('kn-edit-content').value.trim(),
  };
  try {
    const res = await apiFetch(`/api/admin/knowledge/${editingKnowledgeId}`, { method: 'PUT', body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      alert(data.error || 'No se pudo guardar la entrada.');
      return;
    }
    closeKnowledgeModal();
    loadKnowledge();
  } catch (err) {
    alert('Error de conexión.');
  }
}

async function deleteKnowledge(id) {
  if (!confirm('¿Eliminar esta entrada de la base de conocimiento?')) return;
  try {
    const res = await apiFetch(`/api/admin/knowledge/${id}`, { method: 'DELETE' });
    if (res.ok) loadKnowledge();
    else alert('Error al eliminar la entrada.');
  } catch (err) {
    console.error('deleteKnowledge error:', err);
  }
}

/* ── Exponer funciones globales necesarias para los onclick HTML ── */
window.updateReservationStatus = updateReservationStatus;
window.gotoResPage             = gotoResPage;
window.openPropertyModal       = openPropertyModal;
window.deleteProperty          = deleteProperty;
window.markInquiryAttended     = markInquiryAttended;
window.openWhatsApp            = openWhatsApp;
window.openKnowledgeModal      = openKnowledgeModal;
window.deleteKnowledge         = deleteKnowledge;
