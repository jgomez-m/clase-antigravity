/* Lógica principal del E-Commerce JG Inmobiliaria */

const CART_STORAGE_KEY = 'jg_cart_property_ids';
const THEME_STORAGE_KEY = 'jg_theme';
const WHATSAPP_NUMBER = '573114436916';

let allProperties = [];
let filteredProperties = [];
let cartIds = loadCartIds();

let cotizadorMode = 'compra';
let valorTotal = 2650000000;
let cuotaInicialPct = 30;
let selectedCotizadorPropId = null;

let isRotationActive = true;
let isWireframeActive = false;
let isChatOpen = false;

const FALLBACK_SVG =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500">
      <defs>
        <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#0F172A"/>
          <stop offset="100%" stop-color="#1E293B"/>
        </linearGradient>
      </defs>
      <rect width="800" height="500" fill="url(#g)"/>
      <rect x="260" y="110" width="280" height="290" fill="none" stroke="#B45309" stroke-width="4"/>
      <line x1="260" y1="180" x2="540" y2="180" stroke="#38BDF8" stroke-width="2" opacity="0.6"/>
      <line x1="260" y1="250" x2="540" y2="250" stroke="#38BDF8" stroke-width="2" opacity="0.6"/>
      <line x1="260" y1="320" x2="540" y2="320" stroke="#38BDF8" stroke-width="2" opacity="0.6"/>
      <line x1="400" y1="110" x2="400" y2="400" stroke="#B45309" stroke-width="2" opacity="0.7"/>
      <text x="400" y="455" text-anchor="middle" fill="#F8FAFC" font-family="serif" font-size="24" letter-spacing="4">JG INMOBILIARIA</text>
    </svg>`
  );

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

function cityLabel(city) {
  return city === 'medellin' ? 'Medellín' : 'Bogotá D.C.';
}

function statusBadgeHtml(status) {
  const map = {
    disponible: ['Disponible', 'bg-emerald-500/90 text-white'],
    reservado: ['En Reserva', 'bg-amber-600 text-white'],
    arrendado: ['Arrendado', 'bg-slate-600 text-white'],
    vendido: ['Vendido', 'bg-slate-700 text-white'],
  };
  const [label, cls] = map[status] || ['Disponible', 'bg-emerald-500 text-white'];
  return `<span class="${cls} text-[11px] px-2.5 py-0.5 rounded-sm font-semibold uppercase tracking-wider">${label}</span>`;
}

// ------------------------------------------------------------------
// TEMA CLARO / OSCURO
// ------------------------------------------------------------------
function initTheme() {
  const saved = localStorage.getItem(THEME_STORAGE_KEY);
  if (saved === 'dark') {
    document.documentElement.classList.add('dark');
  }
  updateThemeIcon();
}

function toggleTheme() {
  const isDark = document.documentElement.classList.toggle('dark');
  localStorage.setItem(THEME_STORAGE_KEY, isDark ? 'dark' : 'light');
  updateThemeIcon();
}

function updateThemeIcon() {
  const icon = document.getElementById('theme-icon');
  if (!icon) return;
  icon.textContent = document.documentElement.classList.contains('dark') ? 'light_mode' : 'dark_mode';
}

// ------------------------------------------------------------------
// CARGA DE INMUEBLES Y FILTROS
// ------------------------------------------------------------------
async function fetchProperties() {
  try {
    const res = await fetch('/api/properties');
    const data = await res.json();
    allProperties = data.properties || [];
    syncCartWithCatalog();
    populateCotizadorSelect();
    applyFilters();
  } catch (err) {
    console.error('Error cargando inmuebles:', err);
  }
}

function applyFilters() {
  const tx = document.getElementById('filter-transaction')?.value || 'all';
  const type = document.getElementById('filter-property-type')?.value || 'all';
  const city = document.getElementById('filter-location')?.value || 'all';
  const budget = document.getElementById('filter-budget')?.value || 'all';
  const search = (document.getElementById('filter-search')?.value || '').trim().toLowerCase();

  filteredProperties = allProperties.filter((p) => {
    if (tx !== 'all' && p.operation !== tx) return false;
    if (type !== 'all' && p.property_type !== type) return false;
    if (city !== 'all' && p.city !== city) return false;

    if (budget === 'under-2b' && p.price >= 2000000000) return false;
    if (budget === '2b-4b' && (p.price < 2000000000 || p.price > 4000000000)) return false;
    if (budget === 'over-4b' && p.price <= 4000000000) return false;

    if (search) {
      const hay = `${p.title} ${p.neighborhood} ${p.description} ${cityLabel(p.city)}`.toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });

  renderPropertiesGrid();
}

function applyHeroSearch(e) {
  e.preventDefault();
  document.getElementById('filter-location').value = document.getElementById('hero-city').value;
  document.getElementById('filter-transaction').value = document.getElementById('hero-tx').value;
  document.getElementById('filter-property-type').value = document.getElementById('hero-type').value;
  applyFilters();
  document.getElementById('inmuebles').scrollIntoView({ behavior: 'smooth' });
}

function quickFilterCity(city) {
  document.getElementById('filter-location').value = city;
  document.querySelectorAll('.mobile-city-chip').forEach((btn) => {
    const active = btn.getAttribute('data-chip-city') === city;
    btn.className = active
      ? 'mobile-city-chip px-3 py-1 rounded-full text-xs font-semibold whitespace-nowrap bg-light-primary text-white'
      : 'mobile-city-chip px-3 py-1 rounded-full text-xs font-semibold whitespace-nowrap bg-light-surface-variant dark:bg-dark-surface-variant border border-light-outline dark:border-dark-outline';
  });
  applyFilters();
  document.getElementById('inmuebles').scrollIntoView({ behavior: 'smooth' });
}

function resetFiltersUI() {
  document.getElementById('filter-search').value = '';
  document.getElementById('filter-transaction').value = 'all';
  document.getElementById('filter-property-type').value = 'all';
  document.getElementById('filter-location').value = 'all';
  document.getElementById('filter-budget').value = 'all';
  applyFilters();
}

function renderPropertiesGrid() {
  const grid = document.getElementById('properties-grid');
  const countEl = document.getElementById('visible-count');
  const emptyEl = document.getElementById('no-results-message');
  if (!grid) return;

  countEl.textContent = filteredProperties.length;
  if (filteredProperties.length === 0) {
    grid.innerHTML = '';
    emptyEl.classList.remove('hidden');
    return;
  }
  emptyEl.classList.add('hidden');

  grid.innerHTML = filteredProperties
    .map((p) => {
      const inCart = cartIds.includes(p.id);
      const isAvail = p.status === 'disponible';
      const imgSrc = p.image_url ? escapeHtml(p.image_url) : FALLBACK_SVG;
      const opBadge =
        p.operation === 'venta'
          ? '<span class="bg-light-primary text-white text-[11px] px-2.5 py-0.5 rounded-sm uppercase tracking-wider font-semibold">Venta</span>'
          : '<span class="bg-amber-600 text-white text-[11px] px-2.5 py-0.5 rounded-sm uppercase tracking-wider font-semibold">Arriendo</span>';
      const priceSuffix = p.operation === 'arriendo' ? ' / mes' : '';

      let reserveBtn = '';
      if (!isAvail) {
        reserveBtn = `<button disabled class="flex-1 py-2.5 rounded-DEFAULT bg-slate-200 dark:bg-slate-800 text-slate-500 text-xs font-semibold cursor-not-allowed">No disponible</button>`;
      } else if (inCart) {
        reserveBtn = `<button onclick="openCartDrawer()" class="flex-1 py-2.5 rounded-DEFAULT bg-emerald-600 text-white text-xs font-semibold hover:opacity-95 transition flex items-center justify-center gap-1"><span class="material-symbols-outlined text-[16px]">check</span> En tu reserva</button>`;
      } else {
        reserveBtn = `<button onclick="addToCart(${p.id})" class="flex-1 py-2.5 rounded-DEFAULT bg-accent text-white text-xs font-semibold hover:opacity-95 transition flex items-center justify-center gap-1"><span class="material-symbols-outlined text-[16px]">shopping_bag</span> Separar</button>`;
      }

      return `
        <article class="flex flex-col rounded-xl overflow-hidden border border-light-outline-variant dark:border-dark-outline-variant bg-light-surface dark:bg-dark-surface-variant shadow-sm hover:shadow-md transition group">
          <div class="relative w-full h-56 bg-slate-900 overflow-hidden cursor-pointer" onclick="openPropertyModal(${p.id})">
            <img src="${imgSrc}" onerror="this.onerror=null;this.src='${FALLBACK_SVG}'" alt="${escapeHtml(p.title)}" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300">
            <div class="absolute top-3 left-3 flex flex-wrap gap-1.5">
              ${opBadge}
              <span class="bg-white/90 text-slate-900 text-[11px] px-2.5 py-0.5 rounded-sm font-medium capitalize">${escapeHtml(p.property_type)}</span>
              ${statusBadgeHtml(p.status)}
            </div>
            <div class="absolute bottom-3 right-3 bg-light-surface/95 dark:bg-dark-surface/95 backdrop-blur px-3 py-1 rounded-sm shadow-sm font-headline font-bold text-sm sm:text-base tabular-nums">
              ${formatCOP(p.price)} COP${priceSuffix}
            </div>
          </div>

          <div class="p-5 flex flex-col flex-1 justify-between gap-4">
            <div>
              <h3 onclick="openPropertyModal(${p.id})" class="font-headline text-lg font-bold cursor-pointer hover:text-accent transition">${escapeHtml(p.title)}</h3>
              <p class="text-xs text-light-on-surface-variant dark:text-dark-on-surface-variant flex items-center gap-1 mt-1">
                <span class="material-symbols-outlined text-[15px] text-accent">location_on</span>
                ${escapeHtml(p.neighborhood)}, ${cityLabel(p.city)}
              </p>
              <p class="text-xs text-light-on-surface-variant dark:text-dark-on-surface-variant mt-2 line-clamp-2">
                ${escapeHtml(p.description)}
              </p>
            </div>

            <div>
              <div class="flex items-center justify-between text-xs text-light-on-surface-variant dark:text-dark-on-surface-variant border-t border-b border-light-outline-variant dark:border-dark-outline py-2.5 mb-3">
                <span class="flex items-center gap-1"><span class="material-symbols-outlined text-[16px]">bed</span> ${p.bedrooms} Hab</span>
                <span class="flex items-center gap-1"><span class="material-symbols-outlined text-[16px]">bathtub</span> ${p.bathrooms} Baños</span>
                <span class="flex items-center gap-1"><span class="material-symbols-outlined text-[16px]">square_foot</span> ${p.area_m2} m²</span>
              </div>
              <div class="flex items-center justify-between text-[11px] mb-3">
                <span class="text-light-on-surface-variant dark:text-dark-on-surface-variant">Valor de separación:</span>
                <span class="font-bold text-accent tabular-nums">${formatCOP(p.separation_fee)} COP</span>
              </div>
              <div class="flex items-center gap-2">
                ${reserveBtn}
                <button onclick="openPropertyModal(${p.id})" class="px-3 py-2.5 rounded-DEFAULT border border-light-outline dark:border-dark-outline text-xs font-semibold hover:bg-light-primary-container dark:hover:bg-dark-surface transition" title="Ver ficha completa">
                  Detalle
                </button>
                <button onclick="prefillCotizadorById(${p.id})" class="p-2 rounded-DEFAULT border border-light-outline dark:border-dark-outline hover:bg-light-primary-container dark:hover:bg-dark-surface transition" title="Simular en cotizador">
                  <span class="material-symbols-outlined text-[18px]">calculate</span>
                </button>
              </div>
            </div>
          </div>
        </article>
      `;
    })
    .join('');
}

// ------------------------------------------------------------------
// MODAL DETALLE DE VIVIENDA
// ------------------------------------------------------------------
function openPropertyModal(id) {
  const p = allProperties.find((x) => x.id === id);
  if (!p) return;
  const imgSrc = p.image_url ? escapeHtml(p.image_url) : FALLBACK_SVG;
  const amenitiesHtml = (p.amenities || [])
    .map((a) => `<span class="px-2.5 py-1 rounded-full bg-light-surface-variant dark:bg-dark-surface-variant border border-light-outline-variant dark:border-dark-outline text-xs">${escapeHtml(a)}</span>`)
    .join('');

  const modal = document.getElementById('property-modal');
  const content = document.getElementById('property-modal-content');
  const priceSuffix = p.operation === 'arriendo' ? ' / mes' : '';
  const isAvail = p.status === 'disponible';

  content.innerHTML = `
    <div class="relative h-64 bg-slate-900">
      <img src="${imgSrc}" onerror="this.onerror=null;this.src='${FALLBACK_SVG}'" alt="${escapeHtml(p.title)}" class="w-full h-full object-cover">
      <button onclick="closePropertyModal()" type="button" class="absolute top-4 right-4 w-9 h-9 rounded-full bg-black/60 text-white flex items-center justify-center hover:bg-black/80">
        <span class="material-symbols-outlined">close</span>
      </button>
      <div class="absolute bottom-4 left-4 flex gap-2">
        <span class="bg-light-primary text-white text-xs px-3 py-1 rounded-sm uppercase font-semibold">${escapeHtml(p.operation)}</span>
        ${statusBadgeHtml(p.status)}
      </div>
    </div>
    <div class="p-6 space-y-5">
      <div class="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
        <div>
          <h3 class="font-headline text-2xl font-bold">${escapeHtml(p.title)}</h3>
          <p class="text-sm text-light-on-surface-variant dark:text-dark-on-surface-variant flex items-center gap-1 mt-1">
            <span class="material-symbols-outlined text-[16px] text-accent">location_on</span>
            ${escapeHtml(p.address || `${p.neighborhood}, ${cityLabel(p.city)}`)}
          </p>
        </div>
        <div class="sm:text-right">
          <div class="font-headline text-2xl font-bold text-accent tabular-nums">${formatCOP(p.price)} COP${priceSuffix}</div>
          <div class="text-xs text-light-on-surface-variant dark:text-dark-on-surface-variant">Separación online: <strong>${formatCOP(p.separation_fee)} COP</strong></div>
        </div>
      </div>

      <p class="text-sm leading-relaxed text-light-on-surface-variant dark:text-dark-on-surface-variant">${escapeHtml(p.description)}</p>

      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-light-surface-variant dark:bg-dark-surface-variant p-4 rounded-xl text-xs">
        <div><span class="block text-slate-500">Área</span><strong>${p.area_m2} m²</strong></div>
        <div><span class="block text-slate-500">Habitaciones</span><strong>${p.bedrooms}</strong></div>
        <div><span class="block text-slate-500">Baños</span><strong>${p.bathrooms}</strong></div>
        <div><span class="block text-slate-500">Parqueaderos</span><strong>${p.parking} · Estrato ${p.stratum}</strong></div>
      </div>

      ${p.admin_fee > 0 ? `<p class="text-xs text-light-on-surface-variant dark:text-dark-on-surface-variant">Cuota de administración mensual aproximada: <strong>${formatCOP(p.admin_fee)} COP</strong></p>` : ''}

      <div>
        <h4 class="text-xs font-bold uppercase tracking-wider mb-2">Amenidades</h4>
        <div class="flex flex-wrap gap-2">${amenitiesHtml || '<span class="text-xs text-slate-500">Acabados residenciales premium</span>'}</div>
      </div>

      <div class="flex flex-col sm:flex-row gap-3 pt-2 border-t border-light-outline-variant dark:border-dark-outline-variant">
        ${
          isAvail
            ? `<button onclick="addToCart(${p.id}); closePropertyModal();" class="flex-1 py-3 rounded-DEFAULT bg-accent text-white text-sm font-semibold hover:opacity-95 transition">Separar por ${formatCOP(p.separation_fee)} COP</button>`
            : `<button disabled class="flex-1 py-3 rounded-DEFAULT bg-slate-300 text-slate-600 text-sm font-semibold">Vivienda no disponible</button>`
        }
        <button onclick="prefillCotizadorById(${p.id}); closePropertyModal();" class="px-5 py-3 rounded-DEFAULT border border-light-outline dark:border-dark-outline text-sm font-semibold hover:bg-light-surface-variant dark:hover:bg-dark-surface-variant transition">
          Simular Cuota
        </button>
        <a href="https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(`Hola JG Inmobiliaria, deseo información sobre: ${p.title}`)}" target="_blank" rel="noopener noreferrer" class="px-5 py-3 rounded-DEFAULT bg-emerald-600 text-white text-sm font-semibold text-center hover:opacity-95 transition">
          WhatsApp
        </a>
      </div>
    </div>
  `;
  modal.classList.remove('hidden');
}

function closePropertyModal() {
  document.getElementById('property-modal').classList.add('hidden');
}

// ------------------------------------------------------------------
// CARRITO DE SEPARACIÓN Y CHECKOUT
// ------------------------------------------------------------------
function loadCartIds() {
  try {
    const raw = localStorage.getItem(CART_STORAGE_KEY);
    const parsed = JSON.parse(raw || '[]');
    return Array.isArray(parsed) ? parsed.map(Number).filter(Boolean) : [];
  } catch {
    return [];
  }
}

function saveCartIds() {
  localStorage.setItem(CART_STORAGE_KEY, JSON.stringify(cartIds));
  updateCartBadges();
}

function syncCartWithCatalog() {
  const availableSet = new Set(allProperties.filter((p) => p.status === 'disponible').map((p) => p.id));
  cartIds = cartIds.filter((id) => availableSet.has(id));
  saveCartIds();
}

function updateCartBadges() {
  const count = cartIds.length;
  const b1 = document.getElementById('cart-badge');
  const b2 = document.getElementById('cart-badge-mobile');
  if (b1) b1.textContent = count;
  if (b2) b2.textContent = count;
}

function addToCart(id) {
  const prop = allProperties.find((p) => p.id === id);
  if (!prop || prop.status !== 'disponible') return;
  if (!cartIds.includes(id)) {
    cartIds.push(id);
    saveCartIds();
    renderPropertiesGrid();
  }
  openCartDrawer();
}

function removeFromCart(id) {
  cartIds = cartIds.filter((x) => x !== id);
  saveCartIds();
  renderPropertiesGrid();
  renderCartDrawer();
}

function openCartDrawer() {
  document.getElementById('checkout-success').classList.add('hidden');
  renderCartDrawer();
  document.getElementById('cart-drawer').classList.remove('hidden');
}

function closeCartDrawer() {
  document.getElementById('cart-drawer').classList.add('hidden');
}

function renderCartDrawer() {
  const container = document.getElementById('cart-items-container');
  const form = document.getElementById('checkout-form');
  const totalBtn = document.getElementById('checkout-total-btn');

  const items = cartIds.map((id) => allProperties.find((p) => p.id === id)).filter(Boolean);

  if (items.length === 0) {
    container.innerHTML = `
      <div class="text-center py-10 bg-light-surface-variant dark:bg-dark-surface-variant rounded-xl border border-dashed border-light-outline dark:border-dark-outline">
        <span class="material-symbols-outlined text-[42px] text-slate-400 mb-2">shopping_bag</span>
        <p class="font-semibold text-sm">Aún no has seleccionado viviendas para separar</p>
        <p class="text-xs text-light-on-surface-variant dark:text-dark-on-surface-variant mt-1">Explora el catálogo y presiona "Separar" en la propiedad que te interese.</p>
      </div>
    `;
    form.classList.add('hidden');
    return;
  }

  const total = items.reduce((acc, p) => acc + p.separation_fee, 0);
  container.innerHTML =
    items
      .map(
        (p) => `
      <div class="flex items-center justify-between gap-3 p-3.5 rounded-xl bg-light-surface-variant dark:bg-dark-surface-variant border border-light-outline-variant dark:border-dark-outline">
        <div>
          <span class="text-[10px] font-bold uppercase text-accent">${escapeHtml(p.operation)} · ${cityLabel(p.city)}</span>
          <h4 class="font-headline font-bold text-sm">${escapeHtml(p.title)}</h4>
          <p class="text-xs text-light-on-surface-variant dark:text-dark-on-surface-variant">Separación: <strong class="text-light-on-surface dark:text-white">${formatCOP(p.separation_fee)} COP</strong></p>
        </div>
        <button onclick="removeFromCart(${p.id})" type="button" class="p-2 rounded-DEFAULT text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30" title="Quitar">
          <span class="material-symbols-outlined text-[18px]">delete</span>
        </button>
      </div>
    `
      )
      .join('') +
    `
    <div class="flex items-center justify-between pt-2 text-sm font-bold">
      <span>Total Separación:</span>
      <span class="text-lg text-accent font-headline tabular-nums">${formatCOP(total)} COP</span>
    </div>
  `;

  totalBtn.textContent = `${formatCOP(total)} COP`;
  form.classList.remove('hidden');
}

function onPaymentMethodChange() {
  const selected = document.querySelector('input[name="payment_method"]:checked')?.value || 'transferencia';
  ['transferencia', 'tarjeta', 'whatsapp'].forEach((m) => {
    const box = document.getElementById(`pay-box-${m}`);
    if (box) box.classList.toggle('hidden', m !== selected);
  });
}

async function submitReservation(e) {
  e.preventDefault();
  const errorEl = document.getElementById('checkout-error');
  const submitBtn = document.getElementById('checkout-submit-btn');
  errorEl.classList.add('hidden');

  const paymentMethod = document.querySelector('input[name="payment_method"]:checked')?.value || 'transferencia';
  let paymentReference = '';
  if (paymentMethod === 'transferencia') {
    paymentReference = document.getElementById('co-transfer-ref').value.trim();
  } else if (paymentMethod === 'tarjeta') {
    const holder = document.getElementById('co-card-holder').value.trim();
    const last4 = document.getElementById('co-card-last4').value.trim();
    if (!holder || last4.length < 4) {
      errorEl.textContent = 'Ingresa el titular y los últimos 4 dígitos de la tarjeta para la pre-autorización.';
      errorEl.classList.remove('hidden');
      return;
    }
    paymentReference = `TC-${last4}-${holder.split(' ')[0].toUpperCase()}`;
  }

  const payload = {
    customer_name: document.getElementById('co-name').value.trim(),
    customer_doc: document.getElementById('co-doc').value.trim(),
    customer_email: document.getElementById('co-email').value.trim(),
    customer_phone: document.getElementById('co-phone').value.trim(),
    customer_city: document.getElementById('co-city').value.trim(),
    payment_method: paymentMethod,
    payment_reference: paymentReference,
    notes: document.getElementById('co-notes').value.trim(),
    property_ids: cartIds,
  };

  submitBtn.disabled = true;
  try {
    const res = await fetch('/api/reservations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      errorEl.textContent = data.error || 'No pudimos registrar la reserva.';
      errorEl.classList.remove('hidden');
      return;
    }

    const r = data.reservation;
    cartIds = [];
    saveCartIds();
    renderPropertiesGrid();

    document.getElementById('cart-items-container').innerHTML = '';
    document.getElementById('checkout-form').classList.add('hidden');

    const successEl = document.getElementById('checkout-success');
    successEl.innerHTML = `
      <div class="w-14 h-14 mx-auto rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center">
        <span class="material-symbols-outlined text-[32px]">verified</span>
      </div>
      <h4 class="font-headline text-2xl font-bold">¡Reserva Registrada!</h4>
      <p class="text-sm text-light-on-surface-variant dark:text-dark-on-surface-variant">Guarda este código para hacer seguimiento a tu proceso:</p>
      <div class="p-4 rounded-xl bg-light-primary text-white font-headline text-2xl font-bold tracking-wider">${escapeHtml(r.order_code)}</div>
      <div class="text-xs text-left bg-light-surface-variant dark:bg-dark-surface-variant p-4 rounded-xl space-y-1.5">
        <p><strong>Total separación:</strong> ${formatCOP(r.total_amount)} COP</p>
        <p><strong>Método elegido:</strong> ${escapeHtml(r.payment_method.toUpperCase())}</p>
        <p><strong>Referencia:</strong> ${escapeHtml(r.payment_reference)}</p>
        <p><strong>Estado actual:</strong> ${escapeHtml(r.status.replace('_', ' '))}</p>
      </div>
      <a href="${escapeHtml(r.whatsapp_url)}" target="_blank" rel="noopener noreferrer" class="w-full py-3 rounded-DEFAULT bg-emerald-600 text-white text-sm font-semibold flex items-center justify-center gap-2 hover:opacity-95">
        <span class="material-symbols-outlined text-[18px]">chat</span>
        Confirmar ahora por WhatsApp
      </a>
      <button onclick="closeCartDrawer()" type="button" class="w-full py-2.5 rounded-DEFAULT border border-light-outline dark:border-dark-outline text-xs font-semibold">
        Seguir explorando viviendas
      </button>
    `;
    successEl.classList.remove('hidden');
    document.getElementById('checkout-form').reset();
    onPaymentMethodChange();
  } catch (err) {
    errorEl.textContent = 'Error de conexión con el servidor.';
    errorEl.classList.remove('hidden');
  } finally {
    submitBtn.disabled = false;
  }
}

// ------------------------------------------------------------------
// CONSULTA DE CÓDIGO DE RESERVA
// ------------------------------------------------------------------
function openLookupModal() {
  document.getElementById('lookup-result').innerHTML = '';
  document.getElementById('order-lookup-modal').classList.remove('hidden');
}

function closeLookupModal() {
  document.getElementById('order-lookup-modal').classList.add('hidden');
}

async function lookupOrder(e) {
  e.preventDefault();
  const code = document.getElementById('lookup-code-input').value.trim().toUpperCase();
  const out = document.getElementById('lookup-result');
  out.innerHTML = '<p class="text-xs text-slate-500">Consultando...</p>';
  try {
    const res = await fetch(`/api/reservations/${encodeURIComponent(code)}`);
    const data = await res.json();
    if (!res.ok) {
      out.innerHTML = `<p class="text-xs text-red-600 font-semibold">${escapeHtml(data.error)}</p>`;
      return;
    }
    const r = data.reservation;
    const itemsList = (r.items || []).map((i) => `<li>• ${escapeHtml(i.property_title)} (${formatCOP(i.separation_fee)} COP)</li>`).join('');
    out.innerHTML = `
      <div class="p-4 rounded-xl bg-light-surface-variant dark:bg-dark-surface-variant border border-light-outline-variant dark:border-dark-outline space-y-2 text-xs">
        <div class="flex justify-between items-center">
          <strong class="text-sm font-headline">${escapeHtml(r.order_code)}</strong>
          <span class="px-2 py-0.5 rounded-full bg-accent text-white font-semibold uppercase">${escapeHtml(r.status.replace('_', ' '))}</span>
        </div>
        <p><strong>Titular:</strong> ${escapeHtml(r.customer_name)} · ${escapeHtml(r.customer_city)}</p>
        <p><strong>Total separación:</strong> ${formatCOP(r.total_amount)} COP (${escapeHtml(r.payment_method)})</p>
        <ul class="pt-1 border-t border-light-outline-variant dark:border-dark-outline">${itemsList}</ul>
      </div>
    `;
  } catch {
    out.innerHTML = '<p class="text-xs text-red-600">Error consultando el servidor.</p>';
  }
}

// ------------------------------------------------------------------
// COTIZADOR EN LÍNEA
// ------------------------------------------------------------------
function populateCotizadorSelect() {
  const select = document.getElementById('cotizador-propiedad');
  if (!select || allProperties.length === 0) return;

  select.innerHTML =
    allProperties
      .map(
        (p) =>
          `<option value="${p.id}">${escapeHtml(p.title)} (${formatCOP(p.price)} COP${p.operation === 'arriendo' ? '/mes' : ''})</option>`
      )
      .join('') + `<option value="custom">Otro valor personalizado</option>`;

  const first = allProperties[0];
  selectedCotizadorPropId = first.id;
  valorTotal = first.price;
  setCotizadorMode(first.operation === 'arriendo' ? 'arriendo' : 'compra', false);
}

function setCotizadorMode(mode, resetDefaultValue = true) {
  cotizadorMode = mode;
  const btnCompra = document.getElementById('btn-mode-compra');
  const btnArriendo = document.getElementById('btn-mode-arriendo');
  const containerInicial = document.getElementById('container-cuota-inicial');
  const containerPlazo = document.getElementById('container-plazo');

  if (mode === 'compra') {
    btnCompra.className = 'py-3 px-4 rounded-DEFAULT text-sm border-2 border-light-primary bg-light-primary text-white font-semibold transition';
    btnArriendo.className = 'py-3 px-4 rounded-DEFAULT text-sm border border-light-outline dark:border-dark-outline bg-light-surface dark:bg-dark-surface-variant font-semibold transition';
    containerInicial.classList.remove('hidden');
    containerPlazo.classList.remove('hidden');
    if (resetDefaultValue && valorTotal < 100000000) valorTotal = 2650000000;
  } else {
    btnArriendo.className = 'py-3 px-4 rounded-DEFAULT text-sm border-2 border-accent bg-accent text-white font-semibold transition';
    btnCompra.className = 'py-3 px-4 rounded-DEFAULT text-sm border border-light-outline dark:border-dark-outline bg-light-surface dark:bg-dark-surface-variant font-semibold transition';
    containerInicial.classList.add('hidden');
    containerPlazo.classList.add('hidden');
    if (resetDefaultValue && valorTotal > 100000000) valorTotal = 14500000;
  }
  actualizarValoresCotizador();
}

function onPropiedadChange(val) {
  if (val === 'custom') {
    selectedCotizadorPropId = null;
    actualizarValoresCotizador();
    return;
  }
  const prop = allProperties.find((p) => String(p.id) === String(val));
  if (!prop) return;
  selectedCotizadorPropId = prop.id;
  valorTotal = prop.price;
  setCotizadorMode(prop.operation === 'arriendo' ? 'arriendo' : 'compra', false);
}

function prefillCotizadorById(id) {
  const select = document.getElementById('cotizador-propiedad');
  if (select) {
    select.value = String(id);
    onPropiedadChange(String(id));
  }
  document.getElementById('cotizador').scrollIntoView({ behavior: 'smooth' });
}

function onValorSlider(val) {
  valorTotal = parseFloat(val);
  actualizarValoresCotizador();
}

function onInicialSlider(val) {
  cuotaInicialPct = parseFloat(val);
  actualizarValoresCotizador();
}

function actualizarValoresCotizador() {
  const slider = document.getElementById('cotizador-slider-valor');
  if (slider) slider.value = Math.min(8000000000, Math.max(5000000, valorTotal));

  document.getElementById('valor-display').textContent = `${formatCOP(valorTotal)} COP`;
  document.getElementById('resumen-valor-inmueble').textContent = `${formatCOP(valorTotal)} COP`;

  if (cotizadorMode === 'compra') {
    const inicialMonto = valorTotal * (cuotaInicialPct / 100);
    const montoFinanciar = valorTotal - inicialMonto;
    const plazoAnios = parseInt(document.getElementById('cotizador-plazo').value, 10);
    const nMeses = plazoAnios * 12;
    const tasaEA = parseFloat(document.getElementById('cotizador-tasa').value) / 100;
    const tasaMensual = Math.pow(1 + tasaEA, 1 / 12) - 1;
    const cuotaMensual = montoFinanciar * (tasaMensual / (1 - Math.pow(1 + tasaMensual, -nMeses)));

    document.getElementById('label-resumen-2').textContent = 'Cuota Inicial Proyectada:';
    document.getElementById('label-resumen-3').textContent = `Monto a Financiar (${100 - cuotaInicialPct}%):`;
    document.getElementById('cuota-inicial-pct-display').textContent = `${cuotaInicialPct}% (${formatCOP(inicialMonto)} COP)`;
    document.getElementById('resumen-cuota-inicial').textContent = `${formatCOP(inicialMonto)} COP`;
    document.getElementById('resumen-monto-financiar').textContent = `${formatCOP(montoFinanciar)} COP`;
    document.getElementById('resumen-plazo').textContent = `${plazoAnios} Años (${nMeses} cuotas)`;
    document.getElementById('resumen-cuota-mensual').textContent = formatCOP(cuotaMensual);
  } else {
    const prop = allProperties.find((p) => p.id === selectedCotizadorPropId);
    const poliza = valorTotal * 0.025;
    const admin = prop && prop.admin_fee > 0 ? prop.admin_fee : valorTotal * 0.12;
    const totalMes = valorTotal + poliza + admin;

    document.getElementById('label-resumen-2').textContent = 'Póliza Arrendamiento (2.5%):';
    document.getElementById('label-resumen-3').textContent = 'Administración Estimada:';
    document.getElementById('resumen-cuota-inicial').textContent = `${formatCOP(poliza)} COP`;
    document.getElementById('resumen-monto-financiar').textContent = `${formatCOP(admin)} COP`;
    document.getElementById('resumen-plazo').textContent = 'Contrato a 12 meses';
    document.getElementById('resumen-cuota-mensual').textContent = formatCOP(totalMes);
  }
}

function separarDesdeCotizador() {
  if (selectedCotizadorPropId) {
    addToCart(selectedCotizadorPropId);
  } else {
    document.getElementById('inmuebles').scrollIntoView({ behavior: 'smooth' });
  }
}

function enviarCotizacionWhatsApp() {
  const val = document.getElementById('resumen-valor-inmueble').textContent;
  const cuota = document.getElementById('resumen-cuota-mensual').textContent;
  const prop = allProperties.find((p) => p.id === selectedCotizadorPropId);
  const nombre = prop ? prop.title : 'Vivienda personalizada';
  const msg = `Hola JG Inmobiliaria, simulé en el cotizador: ${nombre} (${val}) con cuota mensual estimada de ${cuota} COP. Quiero recibir asesoría.`;
  window.open(`https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(msg)}`, '_blank', 'noopener');
}

// ------------------------------------------------------------------
// FORMULARIO DE CONTACTO Y MAPAS
// ------------------------------------------------------------------
async function submitInquiry(e) {
  e.preventDefault();
  const feedback = document.getElementById('inq-feedback');
  feedback.classList.add('hidden');
  const payload = {
    name: document.getElementById('inq-name').value.trim(),
    phone: document.getElementById('inq-phone').value.trim(),
    city: document.getElementById('inq-city').value,
    message: document.getElementById('inq-message').value.trim(),
    source: 'contacto',
  };
  try {
    const res = await fetch('/api/inquiries', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      feedback.textContent = data.error || 'No se pudo enviar tu solicitud.';
      feedback.className = 'text-xs font-semibold text-red-600';
      return;
    }
    feedback.textContent = '¡Solicitud recibida! Un asesor de JG Inmobiliaria se comunicará contigo muy pronto.';
    feedback.className = 'text-xs font-semibold text-emerald-600';
    document.getElementById('contact-form').reset();
  } catch {
    feedback.textContent = 'Error de conexión con el servidor.';
    feedback.className = 'text-xs font-semibold text-red-600';
  }
}

function switchMap(city) {
  const iframe = document.getElementById('map-iframe');
  const tabMed = document.getElementById('tab-map-med');
  const tabBog = document.getElementById('tab-map-bog');
  const floatTitle = document.getElementById('float-title');
  const floatDesc = document.getElementById('float-desc');
  const floatLink = document.getElementById('float-link');

  if (city === 'medellin') {
    iframe.src = 'https://www.openstreetmap.org/export/embed.html?bbox=-75.578%2C6.205%2C-75.568%2C6.215&layer=mapnik&marker=6.210%2C-75.573';
    tabMed.className = 'px-3 py-1 rounded-sm text-xs font-semibold bg-light-primary text-white';
    tabBog.className = 'px-3 py-1 rounded-sm text-xs font-semibold bg-light-surface dark:bg-dark-surface-variant';
    floatTitle.textContent = 'Sede El Poblado - Milla de Oro';
    floatDesc.textContent = 'Cra. 43A # 1-50, Piso 18. Parqueadero de visitantes exclusivo.';
    floatLink.href = 'https://maps.google.com/?q=El+Poblado+Medellin+Cra+43A+1-50';
  } else {
    iframe.src = 'https://www.openstreetmap.org/export/embed.html?bbox=-74.055%2C4.675%2C-74.045%2C4.685&layer=mapnik&marker=4.680%2C-74.050';
    tabBog.className = 'px-3 py-1 rounded-sm text-xs font-semibold bg-light-primary text-white';
    tabMed.className = 'px-3 py-1 rounded-sm text-xs font-semibold bg-light-surface dark:bg-dark-surface-variant';
    floatTitle.textContent = 'Sede Chicó Rosales - Bogotá D.C.';
    floatDesc.textContent = 'Calle 93 # 11-45, Of. 602. Frente al Parque de la 93.';
    floatLink.href = 'https://maps.google.com/?q=Calle+93+Bogota+Chico';
  }
}

// ------------------------------------------------------------------
// CHAT ASESORÍA EN LÍNEA
// ------------------------------------------------------------------
function toggleChatWindow() {
  const win = document.getElementById('chat-window');
  isChatOpen = !isChatOpen;
  win.classList.toggle('hidden', !isChatOpen);
  win.classList.toggle('flex', isChatOpen);
}

function appendChatBubble(text, isUser) {
  const box = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = isUser
    ? 'bg-light-primary text-white p-3 rounded-xl ml-auto max-w-[85%]'
    : 'bg-white dark:bg-dark-surface-variant p-3 rounded-xl border border-light-outline-variant dark:border-dark-outline max-w-[88%]';
  div.textContent = text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function sendQuickReply(text) {
  if (text.includes('WhatsApp')) {
    window.open(`https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent('Hola JG Inmobiliaria, deseo asesoría sobre viviendas disponibles.')}`, '_blank', 'noopener');
    return;
  }
  appendChatBubble(text, true);
  setTimeout(() => {
    const reply = text.includes('Medellín')
      ? 'En Medellín tenemos viviendas en El Poblado, Provenza y Llanogrande. Puedes filtrarlas arriba y separar en línea.'
      : 'En Bogotá tenemos viviendas disponibles en Rosales, Chicó Reservado y Santa Ana Oriental.';
    appendChatBubble(reply, false);
  }, 400);
}

function handleChatSubmit(e) {
  e.preventDefault();
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;
  appendChatBubble(text, true);
  input.value = '';
  setTimeout(() => {
    appendChatBubble('Gracias por tu mensaje. También puedes confirmar o resolver dudas inmediatas por WhatsApp al +57 311 443 6916.', false);
  }, 500);
}

// ------------------------------------------------------------------
// ESCENAS 3D THREE.JS (DEL MOCKUP)
// ------------------------------------------------------------------
function initHero3D() {
  if (typeof THREE === 'undefined') return;
  const container = document.getElementById('hero-3d-container');
  if (!container) return;
  try {
    const width = container.clientWidth || window.innerWidth;
    const height = container.clientHeight || 640;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
    camera.position.set(28, 22, 38);
    camera.lookAt(0, 8, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0xffffff, 0.65));
    const dirLight = new THREE.DirectionalLight(0xf59e0b, 1.2);
    dirLight.position.set(20, 40, 20);
    scene.add(dirLight);
    const blueLight = new THREE.DirectionalLight(0x38bdf8, 0.8);
    blueLight.position.set(-20, 20, -20);
    scene.add(blueLight);

    const group = new THREE.Group();
    const baseMesh = new THREE.Mesh(
      new THREE.BoxGeometry(16, 1.5, 16),
      new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.3 })
    );
    baseMesh.position.y = 0.75;
    group.add(baseMesh);

    const floorMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, metalness: 0.2, roughness: 0.1 });
    const glassMat = new THREE.MeshPhysicalMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.65, roughness: 0.1 });
    const balconyMat = new THREE.MeshStandardMaterial({ color: 0xb45309, metalness: 0.6, roughness: 0.3 });

    for (let i = 0; i < 8; i++) {
      const size = 11 - i * 0.7;
      const yPos = 1.5 + i * 2.2;
      const slab = new THREE.Mesh(new THREE.BoxGeometry(size, 0.3, size), floorMat);
      slab.position.y = yPos;
      group.add(slab);

      const glass = new THREE.Mesh(new THREE.BoxGeometry(size - 0.4, 1.8, size - 0.4), glassMat);
      glass.position.y = yPos + 1.0;
      group.add(glass);

      if (i % 2 === 0) {
        const balcony = new THREE.Mesh(new THREE.BoxGeometry(size + 0.8, 0.2, 2.5), balconyMat);
        balcony.position.set(0, yPos + 0.3, size / 2 + 0.2);
        group.add(balcony);
      }
    }

    const grid = new THREE.GridHelper(50, 25, 0xb45309, 0x334155);
    scene.add(grid);
    scene.add(group);

    let dragging = false;
    let prev = { x: 0, y: 0 };
    container.addEventListener('mousedown', (e) => {
      dragging = true;
      prev = { x: e.clientX, y: e.clientY };
    });
    window.addEventListener('mouseup', () => {
      dragging = false;
    });
    window.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      group.rotation.y += (e.clientX - prev.x) * 0.008;
      group.rotation.x += (e.clientY - prev.y) * 0.005;
      prev = { x: e.clientX, y: e.clientY };
    });

    function animate() {
      requestAnimationFrame(animate);
      if (isRotationActive && !dragging) group.rotation.y += 0.003;
      renderer.render(scene, camera);
    }
    animate();

    window.addEventListener('resize', () => {
      const w = container.clientWidth || window.innerWidth;
      const h = container.clientHeight || 640;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    });
  } catch (err) {
    console.warn('WebGL no disponible para Hero 3D:', err);
  }
}

function initInteractiveSection3D() {
  if (typeof THREE === 'undefined') return;
  const container = document.getElementById('interactive-model-canvas');
  if (!container) return;
  try {
    const w = container.clientWidth || 500;
    const h = container.clientHeight || 460;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, w / h, 0.1, 1000);
    camera.position.set(22, 16, 26);
    camera.lookAt(0, 6, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(w, h);
    renderer.setClearColor(0x020617);
    container.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0xffffff, 0.8));
    const d1 = new THREE.DirectionalLight(0xb45309, 1.5);
    d1.position.set(15, 25, 15);
    scene.add(d1);

    const tower = new THREE.Group();
    for (let f = 0; f < 10; f++) {
      const geo = new THREE.CylinderGeometry(5 - f * 0.15, 5 - f * 0.15, 1.4, 8);
      const mat = new THREE.MeshStandardMaterial({ color: 0x1e293b, wireframe: false, roughness: 0.2 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.y = f * 1.6;
      tower.add(mesh);
    }
    scene.add(tower);

    let dragging = false;
    let prevX = 0;
    container.addEventListener('mousedown', (e) => {
      dragging = true;
      prevX = e.clientX;
    });
    window.addEventListener('mouseup', () => {
      dragging = false;
    });
    window.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      tower.rotation.y += (e.clientX - prevX) * 0.01;
      prevX = e.clientX;
    });

    function loop() {
      requestAnimationFrame(loop);
      if (isRotationActive && !dragging) tower.rotation.y += 0.005;
      renderer.render(scene, camera);
    }
    loop();

    document.getElementById('btn-3d-wireframe')?.addEventListener('click', () => {
      isWireframeActive = !isWireframeActive;
      tower.children.forEach((c) => {
        if (c.material) c.material.wireframe = isWireframeActive;
      });
    });

    const btnRot = document.getElementById('btn-3d-rotate');
    btnRot?.addEventListener('click', () => {
      isRotationActive = !isRotationActive;
      btnRot.innerHTML = isRotationActive
        ? '<span class="material-symbols-outlined text-[16px]">pause</span> Pausar Rotación'
        : '<span class="material-symbols-outlined text-[16px]">play_arrow</span> Reanudar Rotación';
    });
  } catch (err) {
    console.warn('WebGL no disponible para Sección 3D:', err);
  }
}

// ------------------------------------------------------------------
// INICIALIZACIÓN
// ------------------------------------------------------------------
window.addEventListener('DOMContentLoaded', () => {
  initTheme();
  updateCartBadges();
  fetchProperties();
  initHero3D();
  initInteractiveSection3D();

  document.getElementById('filter-transaction')?.addEventListener('change', applyFilters);
  document.getElementById('filter-property-type')?.addEventListener('change', applyFilters);
  document.getElementById('filter-location')?.addEventListener('change', applyFilters);
  document.getElementById('filter-budget')?.addEventListener('change', applyFilters);
  document.getElementById('filter-search')?.addEventListener('input', applyFilters);
  document.getElementById('btn-reset-filters')?.addEventListener('click', resetFiltersUI);
});

