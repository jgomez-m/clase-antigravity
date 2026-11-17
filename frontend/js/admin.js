/* Lógica del Panel Administrador JG Inmobiliaria */

let adminProperties = [];
let adminReservations = [];
let adminInquiries = [];

function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatCOP(num) {
  return '$' + Math.round(Number(num) || 0).toLocaleString('es-CO');
}

async function checkAdminSession() {
  try {
    const res = await fetch('/api/admin/me');
    if (res.ok) {
      const data = await res.json();
      showDashboard(data.username);
    } else {
      showLogin();
    }
  } catch {
    showLogin();
  }
}

function showLogin() {
  document.getElementById('login-view').classList.remove('hidden');
  document.getElementById('dashboard-view').classList.add('hidden');
}

function showDashboard(username) {
  document.getElementById('login-view').classList.add('hidden');
  document.getElementById('dashboard-view').classList.remove('hidden');
  document.getElementById('admin-user-label').textContent = `Sesión: ${username}`;
  refreshAllAdminData();
}

async function handleAdminLogin(e) {
  e.preventDefault();
  const errEl = document.getElementById('login-error');
  const btn = document.getElementById('login-btn');
  errEl.classList.add('hidden');
  btn.disabled = true;

  try {
    const res = await fetch('/api/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: document.getElementById('login-user').value.trim(),
        password: document.getElementById('login-pass').value,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      errEl.textContent = data.error || 'No fue posible iniciar sesión.';
      errEl.classList.remove('hidden');
      return;
    }
    showDashboard(data.username);
  } catch {
    errEl.textContent = 'Error de conexión con el servidor.';
    errEl.classList.remove('hidden');
  } finally {
    btn.disabled = false;
  }
}

async function logoutAdmin() {
  await fetch('/api/admin/logout', { method: 'POST' });
  showLogin();
}

async function refreshAllAdminData() {
  await Promise.all([loadDashboardStats(), loadAdminProperties(), loadAdminReservations(), loadAdminInquiries()]);
}

async function loadDashboardStats() {
  const res = await fetch('/api/admin/dashboard');
  if (res.status === 401) return showLogin();
  const data = await res.json();
  const s = data.stats || {};
  document.getElementById('kpi-total-props').textContent = s.total_properties ?? 0;
  document.getElementById('kpi-avail-props').textContent = `${s.available_properties ?? 0} disponibles`;
  document.getElementById('kpi-pending-res').textContent = s.pending_reservations ?? 0;
  document.getElementById('kpi-total-cop').textContent = `${formatCOP(s.total_reserved_cop ?? 0)} COP`;
  document.getElementById('kpi-inquiries').textContent = s.new_inquiries ?? 0;
}

async function loadAdminProperties() {
  const res = await fetch('/api/admin/properties');
  if (res.status === 401) return showLogin();
  const data = await res.json();
  adminProperties = data.properties || [];
  renderPropertiesTable();
}

function renderPropertiesTable() {
  const tbody = document.getElementById('admin-properties-tbody');
  if (adminProperties.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="px-4 py-8 text-center text-slate-500">No hay viviendas registradas.</td></tr>';
    return;
  }
  tbody.innerHTML = adminProperties
    .map(
      (p) => `
      <tr class="hover:bg-slate-50 dark:hover:bg-dark-surface/40">
        <td class="px-4 py-3">
          <div class="font-bold">${escapeHtml(p.title)}</div>
          <div class="text-xs text-slate-500 capitalize">${escapeHtml(p.property_type)} · ${p.bedrooms} hab · ${p.area_m2} m²</div>
        </td>
        <td class="px-4 py-3 capitalize font-semibold">${escapeHtml(p.operation)}</td>
        <td class="px-4 py-3">
          <div class="capitalize">${escapeHtml(p.city)}</div>
          <div class="text-xs text-slate-500">${escapeHtml(p.neighborhood)}</div>
        </td>
        <td class="px-4 py-3 tabular-nums font-semibold">${formatCOP(p.price)}</td>
        <td class="px-4 py-3 tabular-nums text-accent font-semibold">${formatCOP(p.separation_fee)}</td>
        <td class="px-4 py-3">
          <span class="px-2.5 py-0.5 rounded-full text-xs font-semibold capitalize bg-slate-100 dark:bg-slate-800">${escapeHtml(p.status)}</span>
        </td>
        <td class="px-4 py-3 text-right space-x-2 whitespace-nowrap">
          <button onclick="openPropertyForm(${p.id})" class="px-2.5 py-1 rounded border border-light-outline dark:border-dark-outline text-xs font-semibold hover:bg-slate-100 dark:hover:bg-slate-800">Editar</button>
          <button onclick="deleteProperty(${p.id}, '${escapeHtml(p.title)}')" class="px-2.5 py-1 rounded border border-red-200 text-red-600 text-xs font-semibold hover:bg-red-50">Eliminar</button>
        </td>
      </tr>
    `
    )
    .join('');
}

async function loadAdminReservations() {
  const res = await fetch('/api/admin/reservations');
  if (res.status === 401) return showLogin();
  const data = await res.json();
  adminReservations = data.reservations || [];
  renderReservationsList();
}

function renderReservationsList() {
  const container = document.getElementById('admin-reservations-list');
  if (adminReservations.length === 0) {
    container.innerHTML = '<div class="p-8 text-center bg-white dark:bg-dark-surface-variant rounded-xl border text-slate-500 text-sm">Aún no hay reservas registradas desde la tienda.</div>';
    return;
  }
  container.innerHTML = adminReservations
    .map((r) => {
      const itemsHtml = (r.items || []).map((i) => `<li class="text-xs">• <strong>${escapeHtml(i.property_title)}</strong> (${escapeHtml(i.operation)}) — ${formatCOP(i.separation_fee)} COP</li>`).join('');
      const waMsg = `Hola ${r.customer_name}, te escribimos de JG Inmobiliaria respecto a tu reserva ${r.order_code}.`;
      const waPhone = (r.customer_phone || '').replace(/\D/g, '');
      return `
        <div class="bg-white dark:bg-dark-surface-variant rounded-xl border border-light-outline-variant dark:border-dark-outline p-5 shadow-sm space-y-3">
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-light-outline-variant dark:border-dark-outline pb-3">
            <div>
              <span class="font-headline text-lg font-bold text-accent">${escapeHtml(r.order_code)}</span>
              <span class="ml-2 text-xs px-2.5 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 font-semibold uppercase">${escapeHtml(r.status.replace('_', ' '))}</span>
              <p class="text-xs text-slate-500 mt-0.5">Fecha: ${escapeHtml(r.created_at)} · Método: <strong class="uppercase">${escapeHtml(r.payment_method)}</strong> · Ref: ${escapeHtml(r.payment_reference)}</p>
            </div>
            <div class="font-headline text-xl font-bold tabular-nums">${formatCOP(r.total_amount)} COP</div>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            <div class="space-y-1">
              <p><strong>Cliente:</strong> ${escapeHtml(r.customer_name)} (Doc: ${escapeHtml(r.customer_doc)})</p>
              <p><strong>Contacto:</strong> ${escapeHtml(r.customer_phone)} · ${escapeHtml(r.customer_email)}</p>
              <p><strong>Ciudad:</strong> ${escapeHtml(r.customer_city)}</p>
              ${r.notes ? `<p><strong>Notas:</strong> ${escapeHtml(r.notes)}</p>` : ''}
            </div>
            <div>
              <p class="font-bold mb-1">Viviendas incluidas:</p>
              <ul class="space-y-1">${itemsHtml}</ul>
            </div>
          </div>

          <div class="flex flex-wrap items-center gap-2 pt-2 border-t border-light-outline-variant dark:border-dark-outline">
            <select id="res-status-${r.id}" class="px-3 py-1.5 rounded-lg border border-light-outline dark:border-dark-outline bg-white dark:bg-dark-surface text-xs font-semibold">
              ${['pendiente', 'en_revision', 'aprobado', 'cerrado', 'cancelado']
                .map((st) => `<option value="${st}" ${r.status === st ? 'selected' : ''}>Reserva: ${st.replace('_', ' ')}</option>`)
                .join('')}
            </select>
            <select id="res-prop-status-${r.id}" class="px-3 py-1.5 rounded-lg border border-light-outline dark:border-dark-outline bg-white dark:bg-dark-surface text-xs">
              <option value="">No cambiar estado del inmueble</option>
              <option value="reservado">Marcar inmueble como: En Reserva</option>
              <option value="arrendado">Marcar inmueble como: Arrendado</option>
              <option value="vendido">Marcar inmueble como: Vendido</option>
              <option value="disponible">Marcar inmueble como: Disponible</option>
            </select>
            <button onclick="updateReservation(${r.id})" class="px-3.5 py-1.5 rounded-lg bg-light-primary text-white text-xs font-semibold">Actualizar</button>
            ${
              waPhone
                ? `<a href="https://wa.me/${waPhone}?text=${encodeURIComponent(waMsg)}" target="_blank" rel="noopener noreferrer" class="ml-auto px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-semibold">WhatsApp Cliente</a>`
                : ''
            }
          </div>
        </div>
      `;
    })
    .join('');
}

async function updateReservation(id) {
  const status = document.getElementById(`res-status-${id}`).value;
  const property_status = document.getElementById(`res-prop-status-${id}`).value;
  await fetch(`/api/admin/reservations/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, property_status }),
  });
  refreshAllAdminData();
}

async function loadAdminInquiries() {
  const res = await fetch('/api/admin/inquiries');
  if (res.status === 401) return showLogin();
  const data = await res.json();
  adminInquiries = data.inquiries || [];
  renderInquiriesList();
}

function renderInquiriesList() {
  const container = document.getElementById('admin-inquiries-list');
  if (adminInquiries.length === 0) {
    container.innerHTML = '<div class="p-8 text-center bg-white dark:bg-dark-surface-variant rounded-xl border text-slate-500 text-sm">No hay mensajes de contacto todavía.</div>';
    return;
  }
  container.innerHTML = adminInquiries
    .map(
      (inq) => `
      <div class="bg-white dark:bg-dark-surface-variant rounded-xl border border-light-outline-variant dark:border-dark-outline p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div class="space-y-1 text-xs">
          <div class="flex items-center gap-2">
            <strong class="text-sm">${escapeHtml(inq.name)}</strong>
            <span class="px-2 py-0.5 rounded-full text-[11px] font-semibold uppercase ${inq.status === 'nuevo' ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-800'}">${escapeHtml(inq.status)}</span>
          </div>
          <p class="text-slate-600 dark:text-slate-300">Tel: <strong>${escapeHtml(inq.phone)}</strong> · Ciudad: ${escapeHtml(inq.city || 'No indicada')} · ${escapeHtml(inq.created_at)}</p>
          ${inq.message ? `<p class="italic text-slate-500">"${escapeHtml(inq.message)}"</p>` : ''}
        </div>
        <div class="flex gap-2">
          ${
            inq.status === 'nuevo'
              ? `<button onclick="markInquiryDone(${inq.id})" class="px-3 py-1.5 rounded-lg bg-light-primary text-white text-xs font-semibold">Marcar atendido</button>`
              : ''
          }
        </div>
      </div>
    `
    )
    .join('');
}

async function markInquiryDone(id) {
  await fetch(`/api/admin/inquiries/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status: 'atendido' }),
  });
  refreshAllAdminData();
}

// ------------------------------------------------------------------
// PESTAÑAS Y FORMULARIO CRUD DE VIVIENDAS
// ------------------------------------------------------------------
function switchTab(tab) {
  ['properties', 'reservations', 'inquiries'].forEach((t) => {
    document.getElementById(`tab-${t}`).classList.toggle('hidden', t !== tab);
    document.getElementById(`tab-btn-${t}`).className =
      t === tab
        ? 'px-4 py-2 rounded-lg text-sm font-semibold bg-light-primary text-white'
        : 'px-4 py-2 rounded-lg text-sm font-semibold bg-light-surface-variant dark:bg-dark-surface-variant';
  });
}

function openPropertyForm(id = null) {
  document.getElementById('pf-error').classList.add('hidden');
  if (id) {
    const p = adminProperties.find((x) => x.id === id);
    if (!p) return;
    document.getElementById('prop-form-title').textContent = 'Editar Vivienda';
    document.getElementById('pf-id').value = p.id;
    document.getElementById('pf-title').value = p.title;
    document.getElementById('pf-operation').value = p.operation;
    document.getElementById('pf-type').value = p.property_type;
    document.getElementById('pf-city').value = p.city;
    document.getElementById('pf-neighborhood').value = p.neighborhood;
    document.getElementById('pf-address').value = p.address || '';
    document.getElementById('pf-price').value = p.price;
    document.getElementById('pf-separation').value = p.separation_fee;
    document.getElementById('pf-admin-fee').value = p.admin_fee || 0;
    document.getElementById('pf-status').value = p.status;
    document.getElementById('pf-area').value = p.area_m2;
    document.getElementById('pf-bedrooms').value = p.bedrooms;
    document.getElementById('pf-bathrooms').value = p.bathrooms;
    document.getElementById('pf-parking').value = p.parking;
    document.getElementById('pf-image').value = p.image_url || '';
    document.getElementById('pf-amenities').value = (p.amenities || []).join(', ');
    document.getElementById('pf-description').value = p.description;
    document.getElementById('pf-featured').checked = Boolean(p.featured);
  } else {
    document.getElementById('prop-form-title').textContent = 'Nueva Vivienda';
    document.getElementById('pf-id').value = '';
    document.querySelector('#prop-form-modal form').reset();
    document.getElementById('pf-status').value = 'disponible';
    document.getElementById('pf-parking').value = 1;
    document.getElementById('pf-admin-fee').value = 0;
  }
  document.getElementById('prop-form-modal').classList.remove('hidden');
}

function closePropertyForm() {
  document.getElementById('prop-form-modal').classList.add('hidden');
}

async function saveProperty(e) {
  e.preventDefault();
  const errEl = document.getElementById('pf-error');
  errEl.classList.add('hidden');

  const id = document.getElementById('pf-id').value;
  const payload = {
    title: document.getElementById('pf-title').value.trim(),
    operation: document.getElementById('pf-operation').value,
    property_type: document.getElementById('pf-type').value,
    city: document.getElementById('pf-city').value,
    neighborhood: document.getElementById('pf-neighborhood').value.trim(),
    address: document.getElementById('pf-address').value.trim(),
    price: Number(document.getElementById('pf-price').value),
    separation_fee: Number(document.getElementById('pf-separation').value),
    admin_fee: Number(document.getElementById('pf-admin-fee').value || 0),
    status: document.getElementById('pf-status').value,
    area_m2: Number(document.getElementById('pf-area').value),
    bedrooms: Number(document.getElementById('pf-bedrooms').value),
    bathrooms: Number(document.getElementById('pf-bathrooms').value),
    parking: Number(document.getElementById('pf-parking').value || 0),
    image_url: document.getElementById('pf-image').value.trim(),
    amenities: document.getElementById('pf-amenities').value.trim(),
    description: document.getElementById('pf-description').value.trim(),
    featured: document.getElementById('pf-featured').checked,
  };

  const url = id ? `/api/admin/properties/${id}` : '/api/admin/properties';
  const method = id ? 'PUT' : 'POST';

  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    errEl.textContent = data.error || 'No se pudo guardar el inmueble.';
    errEl.classList.remove('hidden');
    return;
  }
  closePropertyForm();
  refreshAllAdminData();
}

async function deleteProperty(id, title) {
  if (!confirm(`¿Seguro que deseas eliminar "${title}" del catálogo?`)) return;
  await fetch(`/api/admin/properties/${id}`, { method: 'DELETE' });
  refreshAllAdminData();
}

window.addEventListener('DOMContentLoaded', checkAdminSession);

