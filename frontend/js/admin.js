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
};

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
  document.querySelectorAll('.btn-shortcut').forEach(btn => {
    btn.addEventListener('click', () => applyShortcut(btn.dataset.shortcut));
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
function applyShortcut(shortcut) {
  const today = new Date();
  let from, to;

  document.querySelectorAll('.btn-shortcut').forEach(b => b.classList.remove('active-shortcut'));

  if (shortcut === 'clear') {
    document.getElementById('filter-from').value = '';
    document.getElementById('filter-to').value   = '';
    filterFrom = '';
    filterTo   = '';
    return;
  }

  to = toISODate(today);

  if (shortcut === 'today') {
    from = to;
  } else if (shortcut === 'week') {
    const d = new Date(today);
    d.setDate(d.getDate() - d.getDay());
    from = toISODate(d);
  } else if (shortcut === 'month') {
    from = toISODate(new Date(today.getFullYear(), today.getMonth(), 1));
  } else if (shortcut === 'year') {
    from = toISODate(new Date(today.getFullYear(), 0, 1));
  }

  document.getElementById('filter-from').value = from;
  document.getElementById('filter-to').value   = to;
  event.currentTarget && event.currentTarget.classList.add('active-shortcut');
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

  try {
    const res  = await apiFetch(`/api/admin/dashboard?${params}`);
    if (!res.ok) return;
    const data = await res.json();

    // KPIs
    document.getElementById('kpi-income').textContent      = formatCOP(data.total_income || 0);
    document.getElementById('kpi-total-res').textContent   = data.total_reservations ?? 0;
    document.getElementById('kpi-approved').textContent    = data.approved_reservations ?? 0;
    document.getElementById('kpi-conversion').textContent  = data.conversion_rate ?? 0;
    document.getElementById('kpi-active-props').textContent= data.available_properties ?? 0;
    document.getElementById('kpi-inquiries').textContent   = data.new_inquiries ?? 0;

    // Charts
    if (data.charts) renderCharts(data.charts);
  } catch (err) {
    console.error('loadDashboard error:', err);
  }
}

function renderCharts(chartData) {
  // Destruir charts previos
  ['chart-monthly','chart-dist','chart-weekly','chart-top'].forEach(id => {
    if (charts[id]) { charts[id].destroy(); delete charts[id]; }
  });

  // 1. Ingresos por mes — Bar
  const monthly = chartData.monthly_income || { labels: [], values: [] };
  charts['chart-monthly'] = new Chart(
    document.getElementById('chart-monthly').getContext('2d'),
    {
      type: 'bar',
      data: {
        labels: monthly.labels || [],
        datasets: [{
          label: 'Ingresos (millones COP)',
          data: (monthly.values || []).map(v => +(v / 1_000_000).toFixed(2)),
          backgroundColor: 'rgba(26,35,126,.75)',
          borderRadius: 6,
        }],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { callback: v => '$' + v + 'M' } } },
      },
    }
  );

  // 2. Venta vs Arriendo — Doughnut
  const dist = chartData.operation_distribution || { venta: 0, arriendo: 0 };
  charts['chart-dist'] = new Chart(
    document.getElementById('chart-dist').getContext('2d'),
    {
      type: 'doughnut',
      data: {
        labels: ['Venta', 'Arriendo'],
        datasets: [{
          data: [dist.venta || 0, dist.arriendo || 0],
          backgroundColor: ['#1a237e', '#c9a84c'],
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        plugins: { legend: { position: 'bottom' } },
      },
    }
  );

  // 3. Cotizaciones por semana — Line
  const weekly = chartData.weekly_reservations || { labels: [], values: [] };
  charts['chart-weekly'] = new Chart(
    document.getElementById('chart-weekly').getContext('2d'),
    {
      type: 'line',
      data: {
        labels: weekly.labels || [],
        datasets: [{
          label: 'Cotizaciones',
          data: weekly.values || [],
          borderColor: '#1a237e',
          backgroundColor: 'rgba(26,35,126,.10)',
          tension: 0.4,
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

  // 4. Top inmuebles — Bar horizontal
  const top = chartData.top_properties || { labels: [], values: [] };
  charts['chart-top'] = new Chart(
    document.getElementById('chart-top').getContext('2d'),
    {
      type: 'bar',
      data: {
        labels: top.labels || [],
        datasets: [{
          label: 'Cotizaciones',
          data: top.values || [],
          backgroundColor: 'rgba(201,168,76,.8)',
          borderRadius: 4,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, ticks: { stepSize: 1 } } },
      },
    }
  );
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
    document.getElementById('kpi-total-visits').textContent = data.total || 0;
    document.getElementById('kpi-mobile').textContent       = data.by_device?.mobile  || 0;
    document.getElementById('kpi-desktop').textContent      = data.by_device?.desktop || 0;
    document.getElementById('kpi-tablet').textContent       = data.by_device?.tablet  || 0;

    // Tabla páginas
    const tbody = document.getElementById('tbody-pages');
    const pages = data.by_page || [];
    if (pages.length === 0) {
      tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;color:var(--text-muted);padding:20px;">Sin datos</td></tr>';
    } else {
      tbody.innerHTML = pages.map(p =>
        `<tr><td>${escapeHTML(p.page)}</td><td>${p.count}</td></tr>`
      ).join('');
    }

    // Dona dispositivos
    if (charts['chart-devices']) { charts['chart-devices'].destroy(); delete charts['chart-devices']; }
    if (charts['chart-daily-visits']) { charts['chart-daily-visits'].destroy(); delete charts['chart-daily-visits']; }

    const devData = data.by_device || {};
    charts['chart-devices'] = new Chart(
      document.getElementById('chart-devices').getContext('2d'),
      {
        type: 'doughnut',
        data: {
          labels: ['Desktop', 'Móvil', 'Tablet'],
          datasets: [{
            data: [devData.desktop || 0, devData.mobile || 0, devData.tablet || 0],
            backgroundColor: ['#1a237e', '#c9a84c', '#0288d1'],
          }],
        },
        options: {
          responsive: true,
          plugins: { legend: { position: 'bottom' } },
        },
      }
    );

    // Gráfica diaria
    const daily = data.daily || { labels: [], values: [] };
    charts['chart-daily-visits'] = new Chart(
      document.getElementById('chart-daily-visits').getContext('2d'),
      {
        type: 'line',
        data: {
          labels: daily.labels || [],
          datasets: [{
            label: 'Visitas',
            data: daily.values || [],
            borderColor: '#1a237e',
            backgroundColor: 'rgba(26,35,126,.10)',
            tension: 0.4,
            fill: true,
          }],
        },
        options: {
          responsive: true,
          plugins: { legend: { display: false } },
          scales: { y: { beginAtZero: true } },
        },
      }
    );

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

/* ── Exponer funciones globales necesarias para los onclick HTML ── */
window.updateReservationStatus = updateReservationStatus;
window.gotoResPage             = gotoResPage;
window.openPropertyModal       = openPropertyModal;
window.deleteProperty          = deleteProperty;
window.markInquiryAttended     = markInquiryAttended;
window.openWhatsApp            = openWhatsApp;
