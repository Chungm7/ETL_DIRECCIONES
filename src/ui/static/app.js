/**
 * app.js — Lógica y Flujo Interactivo del Asistente Catastral MPCH
 * Identidad Visual y Experiencia de Usuario (UI/UX) Institucional
 * Flujo:
 * 1. Conexión IA (Ollama) -> 2. Conexión BD -> 3. Esquema -> 4. Tabla y Mapeo -> 5. Inspector Catastral
 */

// ── Sistema de Alertas y Notificaciones Institucionales MPCH (Reemplazo de alert/localhost) ──
function showModalAlert(title, message, type = 'info') {
  const overlay = document.getElementById('modalAlertOverlay');
  if (!overlay) {
    console.warn('[ALERTA MPCH]', title, message);
    return;
  }
  const titleEl = document.getElementById('modalAlertTitle');
  const msgEl = document.getElementById('modalAlertMessage');
  const badgeEl = document.getElementById('modalAlertIconBadge');
  const iconInfo = document.getElementById('modalAlertIconInfo');
  const iconWarn = document.getElementById('modalAlertIconWarning');
  const iconErr = document.getElementById('modalAlertIconError');
  const iconSuccess = document.getElementById('modalAlertIconSuccess');
  const btnOk = document.getElementById('modalAlertBtnOk');

  if (titleEl) titleEl.textContent = title || 'Aviso del Sistema';
  if (msgEl) msgEl.textContent = message || '';

  [iconInfo, iconWarn, iconErr, iconSuccess].forEach(ic => ic?.classList.add('hidden'));

  if (type === 'error') {
    iconErr?.classList.remove('hidden');
    if (badgeEl) {
      badgeEl.style.background = '#fef2f2';
      badgeEl.style.borderColor = '#fecaca';
      badgeEl.style.color = '#dc2626';
    }
    if (btnOk) {
      btnOk.className = 'btn btn-red';
    }
  } else if (type === 'warning') {
    iconWarn?.classList.remove('hidden');
    if (badgeEl) {
      badgeEl.style.background = '#fffbeb';
      badgeEl.style.borderColor = '#fef3c7';
      badgeEl.style.color = '#d97706';
    }
    if (btnOk) {
      btnOk.className = 'btn btn-primary';
    }
  } else if (type === 'success') {
    iconSuccess?.classList.remove('hidden');
    if (badgeEl) {
      badgeEl.style.background = '#f0fdf4';
      badgeEl.style.borderColor = '#bbf7d0';
      badgeEl.style.color = '#16a34a';
    }
    if (btnOk) {
      btnOk.className = 'btn btn-green';
    }
  } else {
    iconInfo?.classList.remove('hidden');
    if (badgeEl) {
      badgeEl.style.background = '#eff6ff';
      badgeEl.style.borderColor = '#bfdbfe';
      badgeEl.style.color = '#2563eb';
    }
    if (btnOk) {
      btnOk.className = 'btn btn-primary';
    }
  }

  overlay.classList.remove('hidden');
}

function closeAlertModal() {
  const overlay = document.getElementById('modalAlertOverlay');
  if (overlay) overlay.classList.add('hidden');
}

// Interceptar window.alert nativo para que nunca muestre popup "localhost:8080 dice:"
window.alert = function(msg) {
  showModalAlert('Aviso del Sistema', String(msg || ''), 'info');
};

// ── Estado Global del Asistente ──────────────────────────────────────────────
const wiz = {
  step: 1,
  maxStepUnlocked: 1,

  // Paso 1: IA (Modelo 1 - Extractor)
  ai_host: 'localhost',
  ai_port: 11434,
  ai_model: '',
  aiVerified: false,
  num_workers: (function() {
    try {
      return parseInt(localStorage.getItem('etl_num_workers')) || 2;
    } catch(e) {
      return 2;
    }
  })(),

  // Paso 2: Base de Datos PostgreSQL
  db_host: '',
  db_port: 5432,
  db_name: '',
  db_user: '',
  db_pass: '',
  dbVerified: false,
  availableSchemas: [],

  // Paso 3 & 4: Esquema y Tabla
  schema: null,
  availableTables: [],
  table: null,
  id_col: null,
  addr_col: null,
  columns: [],

  // Paso 5: Inspector Catastral en Tiempo Real
  allRecords: [],
  viewMode: 'cards', // 'cards' | 'table'

  // Filtro y Ejecución
  filter_mode: 'pending',
  batch_size: 50,
  max_retries: 3,
  require_ai: true,
  autoScroll: true,
  searchInspector: '',
  inspectorStatus: 'all',  // 'all' | 'valid' | 'observed' | 'error'
  inspectorMotor: 'all',   // 'all' | 'ia' | 'hibrido' | 'heuristico'
  counts: { all: 0, valid: 0, observed: 0, error: 0 },
  evtSource: null,
  scheduler_enabled: false,
  scheduler_range: '',
  is_running: false,
};

function syncNumWorkers(val) {
  let n = parseInt(val) || 2;
  if (n < 1) n = 1;
  if (n > 16) n = 16;
  wiz.num_workers = n;
  try {
    localStorage.setItem('etl_num_workers', String(n));
  } catch (e) {}
  const el1 = document.getElementById('ai_num_workers');
  const el5 = document.getElementById('inp_num_workers');
  const elSumm = document.getElementById('summWorkers');
  if (el1 && parseInt(el1.value) !== n) el1.value = n;
  if (el5 && parseInt(el5.value) !== n) el5.value = n;
  if (elSumm) elSumm.textContent = n;
}

// ── Navegación e Interactividad del Stepper ──────────────────────────────────
function tryGoStep(n) {
  if (n === 5) n = 4;
  if (n === 4) {
    if (!wiz.schema || !wiz.table || wiz.source_mode !== 'central_tb_direccion' || n > wiz.maxStepUnlocked) {
      if (wiz.centralStats && (wiz.centralStats.has_records || (wiz.centralStats.total || 0) > 0)) {
        resumeAllCentral();
        return;
      }
      showModalAlert(
        'Normalización con IA Bloqueada',
        'Para ingresar a la Normalización con IA (Paso 4), primero debe:\n1. Migrar e ingestar una tabla a public.tb_direccion, o\n2. Seleccionar una fuente en el Centro de Gestión Catastral (Paso 3).',
        'warning'
      );
      return;
    }
  }
  if (n <= wiz.maxStepUnlocked) {
    goStep(n);
  }
}

function goStep(n) {
  if (n === 5) n = 4;

  [1, 2, 3, 4].forEach(i => {
    const el = document.getElementById(`step${i}`);
    if (el) el.classList.toggle('hidden', i !== n);

    const tab = document.getElementById(`tab${i}`);
    const tabIcon = document.getElementById(`tabIcon${i}`);

    if (tab && tabIcon) {
      tab.classList.remove('active', 'done');

      if (i <= wiz.maxStepUnlocked) {
        tab.classList.remove('locked');
      } else {
        tab.classList.add('locked');
      }

      if (i < n || (i < wiz.maxStepUnlocked && i !== n)) {
        tab.classList.add('done');
        tabIcon.innerHTML = `
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>`;
      } else {
        tabIcon.textContent = i;
      }
    }
  });

  const curTab = document.getElementById(`tab${n}`);
  if (curTab) {
    curTab.classList.add('active');
    curTab.classList.remove('done');
    const curIcon = document.getElementById(`tabIcon${n}`);
    if (curIcon) curIcon.textContent = n;
  }

  wiz.step = n;
  window.scrollTo({ top: 0, behavior: 'smooth' });

  if (n === 3) {
    if (wiz.centralStats && (wiz.centralStats.has_records || (wiz.centralStats.total || 0) > 0)) {
      switchHubSubView('resume');
    } else {
      switchHubSubView('migrate');
    }
    loadIngestedSources();
  } else if (n === 4) {
    if (!wiz.is_running && wiz.schema && wiz.table) {
      initStep5();
    }
  }
}

// ── Helpers Visuales y Diagnóstico ──────────────────────────────────────────
function showDiag(containerId, type, title, message, meta = '') {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (!message && !title) {
    el.innerHTML = '';
    return;
  }

  let iconSvg = '';
  if (type === 'ok') {
    iconSvg = `
      <svg class="diag-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
      </svg>`;
  } else if (type === 'error') {
    iconSvg = `
      <svg class="diag-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
      </svg>`;
  } else if (type === 'warn') {
    iconSvg = `
      <svg class="diag-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>`;
  } else {
    iconSvg = `
      <svg class="diag-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
      </svg>`;
  }

  el.innerHTML = `
    <div class="diag-box ${type}">
      ${iconSvg}
      <div class="diag-content">
        ${title ? `<strong>${escapeHtml(title)}</strong>` : ''}
        <span>${message}</span>
        ${meta ? `<div class="diag-meta">${meta}</div>` : ''}
      </div>
    </div>`;
}

function setLoading(btnId, spinId, loading) {
  const btn = document.getElementById(btnId);
  const spin = document.getElementById(spinId);
  if (btn)  btn.disabled = loading;
  if (spin) spin.classList.toggle('hidden', !loading);
}

function kpi(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val !== undefined && val !== null ? val.toLocaleString() : '0';
}

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDateTime(val) {
  if (!val) return '—';
  try {
    const d = new Date(val);
    if (isNaN(d.getTime())) {
      return String(val).replace('T', ' ').slice(0, 19);
    }
    return d.toLocaleString('es-PE', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    });
  } catch {
    return String(val).replace('T', ' ').slice(0, 19);
  }
}

function isCleanSublote(sl) {
  if (!sl) return false;
  const s = String(sl).trim().toUpperCase();
  if (['SLT', 'SLOTE', 'SUBLOTE', 'S/L', 'S/LT', 'NO', 'N/A', 'NA', 'NONE', 'NULL', '-', '.'].includes(s)) return false;
  if (/^(?:INT(?:ERIOR)?|DPTO|DEP|TIENDA|TDA|STAND|OF(?:ICINA)?|PUERTA|PTA|LOCAL|BLOCK|TORRE|PISO)\b/i.test(s)) return false;
  return true;
}

// ── PASO 1: Motor IA (Ollama) ────────────────────────────────────────────────
function onModelSelectChange() {
  const sel = document.getElementById('ai_model_select');
  const custom = document.getElementById('ai_model_custom');
  if (!sel || !custom) return;
  if (sel.value === 'custom') {
    custom.classList.remove('hidden');
    custom.focus();
  } else {
    custom.classList.add('hidden');
  }
}

async function detectAIModels() {
  showDiag('diagAI', '');
  const host = (document.getElementById('ai_host')?.value || '').trim();
  const portStr = (document.getElementById('ai_port')?.value || '').trim();
  const port = portStr ? parseInt(portStr) : 11434;

  if (!host) {
    showDiag('diagAI', 'warn', 'Atención', 'Ingrese el Host o IP del servidor Ollama antes de detectar modelos.');
    return;
  }

  showDiag('diagAI', 'info', 'Consultando servidor Ollama...', `Conectando con http://${host}:${port}/api/tags`);

  try {
    const res = await fetch('/api/detect-models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host, port }),
    });
    const data = await res.json();

    if (data.connected && data.models && data.models.length > 0) {
      const sel = document.getElementById('ai_model_select');
      sel.innerHTML = '';
      data.models.forEach(m => {
        const isPatroclo = m.toLowerCase().includes('patroclo');
        const opt = new Option(isPatroclo ? `${m} (Recomendado)` : m, m);
        sel.appendChild(opt);
      });
      sel.appendChild(new Option('Otro modelo (ingresar manualmente)...', 'custom'));

      const patrocloMatch = data.models.find(m => m.toLowerCase().includes('patroclo'));
      if (patrocloMatch) {
        sel.value = patrocloMatch;
      }
      onModelSelectChange();
      showDiag('diagAI', 'ok', 'Modelos Detectados', `Se encontraron ${data.models.length} modelo(s) disponibles en el servidor http://${host}:${port}. Presione "Verificar Conexión IA" para validar.`);
    } else {
      showDiag('diagAI', 'warn', 'Servidor Alcanzado sin Modelos', data.message || 'No se encontraron modelos descargados en el servidor Ollama.');
    }
  } catch (e) {
    showDiag('diagAI', 'error', 'Error al Consultar Ollama', `No fue posible comunicarse con http://${host}:${port}. Verifique que Ollama esté ejecutándose ('ollama serve'). Detalle: ${e.message}`);
  }
}

async function verifyAIConnection() {
  showDiag('diagAI', '');

  const host = (document.getElementById('ai_host')?.value || '').trim();
  const portStr = (document.getElementById('ai_port')?.value || '').trim();
  const port = portStr ? parseInt(portStr) : 11434;
  const selVal = document.getElementById('ai_model_select')?.value || '';
  let model = selVal;

  if (selVal === 'custom') {
    model = (document.getElementById('ai_model_custom')?.value || '').trim();
  }

  if (!host) {
    showDiag('diagAI', 'warn', 'Dato Requerido', 'Debe ingresar el Host o IP del servidor Ollama.');
    return;
  }
  if (!model) {
    showDiag('diagAI', 'warn', 'Modelo No Seleccionado', 'Presione "Detectar modelos" o ingrese un nombre de modelo para continuar.');
    return;
  }

  const workersVal = parseInt(document.getElementById('ai_num_workers')?.value) || wiz.num_workers || 4;
  syncNumWorkers(workersVal);

  setLoading('btnConnectAI', 'spinConnectAI', true);

  try {
    const res = await fetch('/api/connect-ai', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host, port, model, num_workers: wiz.num_workers }),
    });
    const data = await res.json();

    if (!res.ok) {
      wiz.aiVerified = false;
      document.getElementById('btnGoStep2').disabled = true;
      showDiag('diagAI', 'error', 'Error de Verificación IA', data.detail || 'No se pudo validar el modelo en el servidor Ollama.');
      return;
    }

    wiz.ai_host = host;
    wiz.ai_port = port;
    wiz.ai_model = model;
    if (data.num_workers) {
      syncNumWorkers(data.num_workers);
    }
    wiz.aiVerified = true;
    wiz.maxStepUnlocked = Math.max(wiz.maxStepUnlocked, 2);

    const btnNext = document.getElementById('btnGoStep2');
    if (btnNext) btnNext.disabled = false;

    // Desbloquear tab 2 visualmente
    const tab2 = document.getElementById('tab2');
    if (tab2) tab2.classList.remove('locked');

    showDiag(
      'diagAI',
      'ok',
      'Conexión Verificada con Éxito',
      `El motor de Inteligencia Artificial está listo para homologación catastral con el modelo <strong>${escapeHtml(model)}</strong>.`,
      `Endpoint: <code>http://${host}:${port}</code> &nbsp;|&nbsp; Latencia de respuesta: <strong>${data.latency_ms} ms</strong>`
    );

  } catch (e) {
    wiz.aiVerified = false;
    document.getElementById('btnGoStep2').disabled = true;
    showDiag('diagAI', 'error', 'Error de Red', `No se pudo establecer conexión con http://${host}:${port}. Detalle: ${e.message}`);
  } finally {
    setLoading('btnConnectAI', 'spinConnectAI', false);
  }
}

// ── PASO 2: Conexión a Base de Datos PostgreSQL ─────────────────────────────
async function verifyDBConnection() {
  showDiag('diagDB', '');

  const host = (document.getElementById('db_host')?.value || '').trim();
  const portStr = (document.getElementById('db_port')?.value || '').trim();
  const port = portStr ? parseInt(portStr) : 5432;
  const dbname = (document.getElementById('db_name')?.value || '').trim();
  const user = (document.getElementById('db_user')?.value || '').trim();
  const password = document.getElementById('db_pass')?.value || '';

  if (!host || !dbname || !user) {
    showDiag('diagDB', 'warn', 'Datos Incompletos', 'Por favor complete el Servidor (Host), Base de Datos y Usuario para conectar.');
    return;
  }

  setLoading('btnConnectDB', 'spinConnectDB', true);

  const body = { host, port, dbname, user, password };

  try {
    const res = await fetch('/api/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();

    if (!res.ok) {
      wiz.dbVerified = false;
      document.getElementById('btnGoStep3').disabled = true;
      showDiag('diagDB', 'error', 'Error de Conexión a Base de Datos', data.detail || 'Credenciales no válidas o servidor PostgreSQL no responde.');
      return;
    }

    wiz.db_host = host;
    wiz.db_port = port;
    wiz.db_name = dbname;
    wiz.db_user = user;
    wiz.dbVerified = true;
    wiz.maxStepUnlocked = Math.max(wiz.maxStepUnlocked, 3);
    wiz.availableSchemas = data.schemas || [];

    const searchInput = document.getElementById('searchSchema');
    if (searchInput) searchInput.value = '';

    renderSchemaCards(wiz.availableSchemas);
    updateSchemaCountBadge(wiz.availableSchemas.length, wiz.availableSchemas.length);

    const btnNext = document.getElementById('btnGoStep3');
    if (btnNext) btnNext.disabled = false;

    // Desbloquear tab 3 (Centro de Gestión Catastral)
    const tab3 = document.getElementById('tab3');
    if (tab3) tab3.classList.remove('locked');

    if (data.central_stats) {
      updateCentralResumeUI(data.central_stats, data.ingested_sources);
    }

    const hasData = Boolean(data.central_stats && (data.central_stats.has_records || (data.central_stats.total || 0) > 0));
    if (hasData) {
      wiz.maxStepUnlocked = Math.max(wiz.maxStepUnlocked, 4);
      document.getElementById('tab4')?.classList.remove('locked');
      switchHubSubView('resume');
    } else {
      switchHubSubView('migrate');
    }

    showDiag(
      'diagDB',
      'ok',
      'Conexión Establecida con Éxito',
      `Conectado a la base de datos <strong>${escapeHtml(dbname)}</strong> en ${escapeHtml(host)}:${port}.`,
      `Esquemas detectados: <strong>${wiz.availableSchemas.length}</strong> disponible(s). Presione "Continuar al Centro de Gestión" para reanudar o migrar.`
    );

  } catch (e) {
    wiz.dbVerified = false;
    document.getElementById('btnGoStep3').disabled = true;
    showDiag('diagDB', 'error', 'Error de Red PostgreSQL', `No fue posible conectar con el servidor: ${e.message}`);
  } finally {
    setLoading('btnConnectDB', 'spinConnectDB', false);
  }
}

// ── PASO 4: Selección de Esquema ────────────────────────────────────────────
function filterSchemaCards() {
  const query = (document.getElementById('searchSchema')?.value || '').toLowerCase().trim();
  const allSchemas = wiz.availableSchemas || [];
  const filtered = allSchemas.filter(s => s.toLowerCase().includes(query));
  renderSchemaCards(filtered);
  updateSchemaCountBadge(filtered.length, allSchemas.length);
}

function handleSchemaSearchKey(e) {
  if (e.key === 'Enter') {
    const query = (document.getElementById('searchSchema')?.value || '').toLowerCase().trim();
    const allSchemas = wiz.availableSchemas || [];
    const filtered = allSchemas.filter(s => s.toLowerCase().includes(query));
    if (filtered.length === 1) {
      wiz.schema = filtered[0];
      const card = document.querySelector(`#schemaCards .card-item[data-schema="${CSS.escape(filtered[0])}"]`);
      if (card) {
        document.querySelectorAll('#schemaCards .card-item').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
        document.getElementById('btnSchema').disabled = false;
      }
    }
  }
}

function updateSchemaCountBadge(filteredCount, totalCount) {
  const badge = document.getElementById('schemaCountBadge');
  if (!badge) return;
  if (!totalCount) {
    badge.textContent = '';
    return;
  }
  if (filteredCount === totalCount) {
    badge.textContent = `${totalCount} esquema${totalCount === 1 ? '' : 's'}`;
  } else {
    badge.textContent = `${filteredCount} de ${totalCount}`;
  }
}

function renderSchemaCards(schemas) {
  const grid = document.getElementById('schemaCards');
  if (!grid) return;
  grid.innerHTML = '';

  if (!schemas || !schemas.length) {
    grid.innerHTML = '<p style="color:var(--slate-500); font-size:13px; padding:10px;">No se encontraron esquemas que coincidan con la búsqueda.</p>';
    return;
  }

  schemas.forEach(s => {
    const card = document.createElement('div');
    card.className = 'card-item';
    if (wiz.schema === s) card.classList.add('selected');
    card.innerHTML = `
      <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        <div class="card-name">${escapeHtml(s)}</div>
      </div>
      <div class="card-meta">Esquema PostgreSQL</div>
    `;
    card.onclick = () => {
      document.querySelectorAll('#schemaCards .card-item').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      wiz.schema = s;
      document.getElementById('btnSchema').disabled = false;
    };
    card.setAttribute('data-schema', s);
    grid.appendChild(card);
  });
}

async function inspectSchema() {
  if (!wiz.schema) return;
  setLoading('btnSchema', 'spinSchema', true);

  try {
    const res = await fetch('/api/inspect-schema', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schema_name: wiz.schema }),
    });
    const data = await res.json();

    if (!res.ok) {
      showModalAlert('Error al Inspeccionar Esquema', data.detail || 'Error desconocido', 'error');
      return;
    }

    wiz.availableTables = data.tables || [];
    const searchTbl = document.getElementById('searchTable');
    if (searchTbl) searchTbl.value = '';
    renderTableCards(wiz.availableTables);
    updateTableCountBadge(wiz.availableTables.length, wiz.availableTables.length);
    document.getElementById('labelSchema').textContent = wiz.schema;

    const secTbl = document.getElementById('sectionTableSelect');
    if (secTbl) {
      secTbl.classList.remove('hidden');
      secTbl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

  } catch (e) {
    showModalAlert('Error de Red', 'Error al consultar tablas: ' + e.message, 'error');
  } finally {
    setLoading('btnSchema', 'spinSchema', false);
  }
}

// ── PASO 5: Tablas y Mapeo de Columnas ───────────────────────────────────────
function filterTableCards() {
  const query = (document.getElementById('searchTable')?.value || '').toLowerCase().trim();
  const allTables = wiz.availableTables || [];
  const filtered = allTables.filter(t => t.name.toLowerCase().includes(query));
  renderTableCards(filtered);
  updateTableCountBadge(filtered.length, allTables.length);
}

function updateTableCountBadge(filteredCount, totalCount) {
  const badge = document.getElementById('tableCountBadge');
  if (!badge) return;
  if (!totalCount) {
    badge.textContent = '';
    return;
  }
  if (filteredCount === totalCount) {
    badge.textContent = `${totalCount} tabla${totalCount === 1 ? '' : 's'}`;
  } else {
    badge.textContent = `${filteredCount} de ${totalCount}`;
  }
}

function renderTableCards(tables) {
  const grid = document.getElementById('tableCards');
  if (!grid) return;
  grid.innerHTML = '';

  if (!tables || !tables.length) {
    grid.innerHTML = '<p style="color:var(--slate-500); font-size:13px; padding:10px;">No se encontraron tablas en este esquema.</p>';
    return;
  }

  tables.forEach(t => {
    const card = document.createElement('div');
    card.className = 'card-item';
    if (wiz.table === t.name) card.classList.add('selected');

    card.innerHTML = `
      <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3h18v18H3zM3 9h18M3 15h18M9 3v18M15 3v18"/></svg>
        <div class="card-name">${escapeHtml(t.name)}</div>
      </div>
      <div class="card-meta">${t.row_count >= 0 ? t.row_count.toLocaleString() + ' registros estimados' : 'Tabla PostgreSQL'}</div>
      <div class="card-meta" style="margin-top:2px;">${t.columns.length} columnas detectadas</div>
    `;
    card.onclick = () => {
      document.querySelectorAll('#tableCards .card-item').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      wiz.table = t.name;
      wiz.columns = t.columns;
      showColumnConfig(t);
    };
    card.setAttribute('data-table', t.name);
    grid.appendChild(card);
  });
}

function showColumnConfig(tableInfo) {
  const cfg = document.getElementById('colConfig');
  cfg.classList.remove('hidden');
  document.getElementById('labelTable').textContent = tableInfo.name;

  const selId   = document.getElementById('sel_id_col');
  const selAddr = document.getElementById('sel_addr_col');
  selId.innerHTML = '';
  selAddr.innerHTML = '';

  tableInfo.columns.forEach(col => {
    const o1 = new Option(`${col.name} (${col.type})`, col.name);
    const o2 = new Option(`${col.name} (${col.type})`, col.name);
    selId.appendChild(o1);
    selAddr.appendChild(o2);
  });

  // Sugerencias de coincidencia inteligente (priorizando PK reales y descartando FKs como id_distrito)
  let bestId = null;
  if (tableInfo.recommended_id_col) {
    bestId = tableInfo.columns.find(c => c.name.toLowerCase() === tableInfo.recommended_id_col.toLowerCase());
  }

  if (!bestId) {
    const fkNames = ['id_distrito', 'id_provincia', 'id_departamento', 'id_ubigeo', 'id_zona', 'id_via', 'id_tipo_via', 'id_tipo_zona', 'id_tipo', 'id_estado', 'id_pais', 'distrito_id', 'provincia_id', 'departamento_id', 'zona_id', 'via_id'];
    const primeCandidates = ['id_licencia', 'id_direccion', 'id', 'pk', 'codigo', 'cod', 'correlativo', `${(tableInfo.name||'').toLowerCase()}_id`, `id_${(tableInfo.name||'').toLowerCase()}`];
    
    // 1. Candidatos primarios directos
    bestId = tableInfo.columns.find(c => primeCandidates.includes(c.name.toLowerCase()));

    // 2. Columnas con _id o id_ que no sean llaves foráneas conocidas
    if (!bestId) {
      bestId = tableInfo.columns.find(c => {
        const lower = c.name.toLowerCase();
        return (lower.endsWith('_id') || lower.startsWith('id_') || lower.includes('id') || lower.includes('cod'))
               && !fkNames.includes(lower);
      });
    }

    if (!bestId) {
      bestId = tableInfo.columns[0];
    }
  }

  let bestAddr = null;
  if (tableInfo.recommended_addr_col) {
    bestAddr = tableInfo.columns.find(c => c.name.toLowerCase() === tableInfo.recommended_addr_col.toLowerCase());
  }

  if (!bestAddr) {
    const addrExact = ['emp_direccion', 'direccion', 'dir_direccion', 'address', 'domicilio', 'ubicacion'];
    bestAddr = tableInfo.columns.find(c => addrExact.includes(c.name.toLowerCase()));
  }

  if (!bestAddr) {
    const addrHints = ['direccion', 'dir', 'address', 'emp_', 'domicilio', 'ubica'];
    bestAddr = tableInfo.columns.find(c => addrHints.some(h => c.name.toLowerCase().includes(h)));
  }

  // Si la columna de dirección original ya fue eliminada tras migración exitosa:
  if (!bestAddr) {
    bestAddr = tableInfo.columns.find(c => c.name.toLowerCase() === 'dire_id')
      || tableInfo.columns.find(c => c.name !== (bestId ? bestId.name : ''))
      || tableInfo.columns[0];
  }

  if (bestId)   selId.value   = bestId.name;
  if (bestAddr) selAddr.value = bestAddr.name;

  wiz.id_col = selId.value || null;
  wiz.addr_col = selAddr.value || null;

  selId.onchange = () => {
    wiz.id_col = selId.value;
    if (wiz.id_col && wiz.addr_col) {
      document.getElementById('btnConfirmTable').disabled = false;
      previewTable();
    }
  };
  selAddr.onchange = () => {
    wiz.addr_col = selAddr.value;
    if (wiz.id_col && wiz.addr_col) {
      document.getElementById('btnConfirmTable').disabled = false;
      previewTable();
    }
  };

  if (wiz.id_col && wiz.addr_col) {
    document.getElementById('btnConfirmTable').disabled = false;
    previewTable();
  } else {
    document.getElementById('previewSection').classList.add('hidden');
    document.getElementById('btnConfirmTable').disabled = true;
  }
}

async function previewTable() {
  const id_col   = document.getElementById('sel_id_col').value;
  const addr_col = document.getElementById('sel_addr_col').value;

  if (!id_col || !addr_col) {
    showModalAlert('Columnas Requeridas', 'Debe seleccionar la columna identificador único (ID) y la columna de dirección.', 'warning');
    return;
  }

  setLoading('btnPreview', 'spinPreview', true);

  try {
    const res = await fetch('/api/inspect-table', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        schema_name:  wiz.schema,
        table_name:   wiz.table,
        id_col,
        address_col:  addr_col,
      }),
    });
    const data = await res.json();

    if (!res.ok) {
      showModalAlert('Error de Vista Previa', data.detail || 'Error desconocido', 'error');
      return;
    }

    wiz.id_col   = data.id_col;
    wiz.addr_col = data.address_col;
    wiz.tableCounts = data.counts || {};
    wiz.is_ingested = Boolean(data.is_ingested);
    wiz.centralCounts = data.central_counts || {};

    const countDiv = document.getElementById('tableCountInfo');
    const c = data.counts || {};
    const c_cent = data.central_counts || {};
    let badgeHtml = `
      <span class="badge" style="background:var(--slate-100); color:var(--slate-800); border:1px solid var(--slate-300);"><strong>${(c.total||0).toLocaleString()}</strong> Total Fuente</span>
      <span class="badge" style="background:var(--blue-accent-bg); color:var(--blue-accent); border:1px solid var(--blue-accent-border);"><strong>${(c.pendientes||0).toLocaleString()}</strong> Pendientes Fuente</span>
      <span class="badge badge-valid"><strong>${(c.validos||0).toLocaleString()}</strong> Normalizados</span>
      <span class="badge badge-observed"><strong>${(c.observados||0).toLocaleString()}</strong> Observados</span>
    `;
    if (data.is_ingested) {
      badgeHtml += `
        <span class="badge" style="background:#f0fdf4; color:#15803d; border:1px solid #bbf7d0; font-weight:700;">
          ✓ Ya migrado a tb_direccion (${(c_cent.pendientes||0).toLocaleString()} pendientes en catastro central)
        </span>
      `;
    }
    countDiv.innerHTML = badgeHtml;

    const btnStep4 = document.getElementById('btnStep4ExportDirect');
    if (btnStep4) {
      if ((c.validos || 0) > 0 || (c.observados || 0) > 0 || (c_cent.normalizados || 0) > 0) {
        btnStep4.classList.remove('hidden');
      } else {
        btnStep4.classList.add('hidden');
      }
    }

    const tbody = document.getElementById('previewBody');
    tbody.innerHTML = '';
    (data.preview || []).forEach(row => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="font-family:monospace; color:var(--mpch-navy); font-weight:700;">${escapeHtml(row.id ?? '—')}</td>
        <td style="font-family:monospace; color:var(--slate-800);">${escapeHtml(row.direccion ?? '—')}</td>
      `;
      tbody.appendChild(tr);
    });

    document.getElementById('previewSection').classList.remove('hidden');

    const statusBanner = document.getElementById('migrationStatusBanner');
    const statusText   = document.getElementById('migrationStatusText');
    if (data.is_ingested && (c_cent.total || 0) > 0) {
      if (statusBanner && statusText) {
        statusText.innerHTML = `Esta tabla ya cuenta con <strong>${(c_cent.total||0).toLocaleString()}</strong> registros en <code>public.tb_direccion</code> (${(c_cent.pendientes||0).toLocaleString()} pendientes). Puede pasar a normalizar con IA directamente o volver a sincronizar.`;
        statusBanner.classList.remove('hidden');
      }
    } else {
      if (statusBanner) statusBanner.classList.add('hidden');
    }

  } catch (e) {
    showModalAlert('Error de Red', 'Error al previsualizar tabla: ' + e.message, 'error');
  } finally {
    setLoading('btnPreview', 'spinPreview', false);
  }
}

// ── Centro de Gestión: Conmutador de Subvistas (Reanudación vs Migración) ────
function switchHubSubView(mode) {
  const resumeView = document.getElementById('hubResumeView');
  const migrateView = document.getElementById('hubMigrateView');
  const btnResume = document.getElementById('btnHubTabResume');
  const btnMigrate = document.getElementById('btnHubTabMigrate');

  if (mode === 'resume') {
    resumeView?.classList.remove('hidden');
    migrateView?.classList.add('hidden');

    if (btnResume) {
      btnResume.className = 'btn btn-primary';
    }
    if (btnMigrate) {
      btnMigrate.className = 'btn btn-ghost';
    }
    loadIngestedSources();
  } else {
    migrateView?.classList.remove('hidden');
    resumeView?.classList.add('hidden');

    if (btnMigrate) {
      btnMigrate.className = 'btn btn-primary';
    }
    if (btnResume) {
      btnResume.className = 'btn btn-ghost';
    }
    if (wiz.availableSchemas && wiz.availableSchemas.length > 0) {
      renderSchemaCards(wiz.availableSchemas);
      updateSchemaCountBadge(wiz.availableSchemas.length, wiz.availableSchemas.length);
    }
  }
}

function switchWorkflowMode(mode) {
  switchHubSubView(mode);
}

let pendingMigrationConfig = null;

function openMigrationConfirmModal() {
  const id_col   = document.getElementById('sel_id_col')?.value || wiz.id_col;
  const addr_col = document.getElementById('sel_addr_col')?.value || wiz.addr_col;
  const dropCol  = document.getElementById('chkDropSourceCol')?.checked || false;

  if (!wiz.schema || !wiz.table || !id_col || !addr_col) {
    showModalAlert('Campos Incompletos', 'Debe seleccionar la tabla y las columnas de ID y Dirección antes de migrar.', 'warning');
    return;
  }

  pendingMigrationConfig = {
    schema_name: wiz.schema,
    table_name: wiz.table,
    id_col: id_col,
    address_col: addr_col,
    drop_source_column: dropCol,
  };

  document.getElementById('modalMigrateSchemaText').textContent = wiz.schema;
  document.getElementById('modalMigrateTableText').textContent = wiz.table;
  document.getElementById('modalMigrateIdColText').textContent = id_col;
  document.getElementById('modalMigrateAddrColText').textContent = addr_col;

  const dropBadge = document.getElementById('modalMigrateDropColBadge');
  if (dropBadge) {
    if (dropCol) {
      dropBadge.innerHTML = `<span class="badge" style="background:#fef2f2; color:#dc2626; border:1px solid #fecaca; font-weight:700;">Sí, eliminar columna en origen</span>`;
    } else {
      dropBadge.innerHTML = `<span class="badge" style="background:#f0fdf4; color:#16a34a; border:1px solid #bbf7d0; font-weight:700;">No, conservar columna</span>`;
    }
  }

  document.getElementById('modalConfirmMigrationOverlay').classList.remove('hidden');
}

function closeMigrationConfirmModal() {
  document.getElementById('modalConfirmMigrationOverlay').classList.add('hidden');
}

async function executeConfirmedMigration() {
  closeMigrationConfirmModal();
  if (!pendingMigrationConfig) return;

  const progressOverlay = document.getElementById('modalMigrationProgressOverlay');
  if (progressOverlay) progressOverlay.classList.remove('hidden');

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 120000); // 2 minutos de timeout de seguridad

  try {
    const res = await fetch('/api/migrate-source-table', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(pendingMigrationConfig),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    const data = await res.json();

    if (!res.ok) {
      showModalAlert('Error en la Migración', data.detail || data.error || 'Error desconocido', 'error');
      return;
    }

    // Cargar datos en el modal de resultado
    document.getElementById('resMigrateTotalSource').textContent = (data.total_source || 0).toLocaleString();
    const totalInDir = data.total_in_tb_direccion || ((data.already_migrated || data.already_linked || 0) + (data.migrated || 0));
    document.getElementById('resMigrateLinked').textContent = totalInDir.toLocaleString();
    document.getElementById('resMigrateUnlinked').textContent = (data.remaining_unlinked || 0).toLocaleString();
    document.getElementById('resMigrateColDropped').textContent = data.column_dropped ? 'Eliminada (Desacoplada)' : 'Conservada';

    // Desbloquear Paso 4 (Normalización con IA) para esta tabla migrada
    wiz.maxStepUnlocked = Math.max(wiz.maxStepUnlocked, 4);
    const tab4 = document.getElementById('tab4');
    if (tab4) tab4.classList.remove('locked');

    // Abrir modal de resultado
    document.getElementById('modalMigrationResultOverlay').classList.remove('hidden');

    // Refrescar tablas y fuentes en background sin bloquear la UI
    previewTable().catch(err => console.debug("previewTable bg err:", err));
    loadIngestedSources().catch(err => console.debug("loadIngestedSources bg err:", err));

  } catch (e) {
    clearTimeout(timeoutId);
    const msg = (e.name === 'AbortError') 
      ? 'La migración tomó más tiempo del esperado en responder. Verifique la base de datos o reintente.'
      : 'Error al ejecutar migración: ' + e.message;
    showModalAlert('Aviso de Migración', msg, 'error');
  } finally {
    if (progressOverlay) progressOverlay.classList.add('hidden');
  }
}

function migrateAnotherTable() {
  document.getElementById('modalMigrationResultOverlay')?.classList.add('hidden');
  document.querySelectorAll('#tableCards .card-item').forEach(c => c.classList.remove('selected'));
  document.getElementById('colConfig')?.classList.add('hidden');
  document.getElementById('previewSection')?.classList.add('hidden');
  document.getElementById('migrationStatusBanner')?.classList.add('hidden');
  wiz.table = null;
  wiz.columns = [];
  switchHubSubView('migrate');
}

function goToResumeWorkflow() {
  document.getElementById('modalMigrationResultOverlay')?.classList.add('hidden');
  wiz.maxStepUnlocked = Math.max(wiz.maxStepUnlocked, 4);
  const tab4 = document.getElementById('tab4');
  if (tab4) tab4.classList.remove('locked');
  goStep(3);
  switchHubSubView('resume');
  loadIngestedSources();
}

function resumeFromJustMigrated() {
  goToResumeWorkflow();
}

async function migrateSourceTable() {
  openMigrationConfirmModal();
}

async function loadIngestedSources() {
  const tbody = document.getElementById('bodyIngestedSources');
  if (!tbody) return;

  try {
    const res = await fetch('/api/ingested-sources');
    const data = await res.json();
    if (data.stats || data.sources) {
      updateCentralResumeUI(data.stats, data.sources);
    }
    if (!data.success || !data.sources || data.sources.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--slate-400); padding:16px;">No hay tablas ingestadas en tb_direccion todavía. Seleccione "Migrar Nueva Tabla" para comenzar.</td></tr>`;
      return;
    }

    tbody.innerHTML = '';
    data.sources.forEach(s => {
      const tr = document.createElement('tr');
      const isPending = (s.pendientes || 0) > 0;
      tr.innerHTML = `
        <td style="font-weight:700; color:var(--mpch-navy);">${escapeHtml(s.dire_esquema)}</td>
        <td style="font-weight:600;">${escapeHtml(s.dire_tabla)}</td>
        <td><strong>${(s.total || 0).toLocaleString()}</strong></td>
        <td><span class="badge" style="background:#eff6ff; color:#2563eb; border:1px solid #bfdbfe;">${(s.pendientes || 0).toLocaleString()}</span></td>
        <td><span class="badge badge-valid">${(s.normalizados || 0).toLocaleString()}</span></td>
        <td><span class="badge badge-observed">${(s.rechazados || 0).toLocaleString()}</span></td>
        <td style="text-align:right;">
          <button class="btn ${isPending ? 'btn-green' : 'btn-ghost'}" style="padding:4px 10px; font-size:11.5px;" onclick="resumeFromCentralSource('${escapeHtml(s.dire_esquema)}', '${escapeHtml(s.dire_tabla)}')">
            <span>${isPending ? 'Reanudar' : 'Ver / Reprocesar'}</span>
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:#dc2626; padding:12px;">Error al cargar fuentes ingestadas: ${escapeHtml(e.message)}</td></tr>`;
  }
}

function updateCentralResumeUI(stats, sources) {
  if (!stats && (!sources || sources.length === 0)) return;
  stats = stats || {};
  wiz.centralStats = stats;
  if (sources) wiz.ingestedSources = sources;

  let total = stats.total || 0;
  let pendientes = stats.pendientes || 0;

  // Consolidar conteos desde sources si stats.total es 0
  if (total === 0 && sources && sources.length > 0) {
    total = sources.reduce((acc, s) => acc + (s.total || 0), 0);
    pendientes = sources.reduce((acc, s) => acc + (s.pendientes || 0), 0);
    stats.total = total;
    stats.pendientes = pendientes;
    stats.has_records = total > 0;
  }

  const hasData = Boolean(stats.has_records || total > 0 || (sources && sources.some(s => (s.total || 0) > 0)));

  const lblTotal = document.getElementById('lblCentralTotal');
  const lblPending = document.getElementById('lblCentralPending');
  const btnPending = document.getElementById('btnLblCentralPending');
  const btnResumeAll = document.getElementById('btnLblResumeAll');

  if (lblTotal) lblTotal.textContent = total.toLocaleString();
  if (lblPending) lblPending.textContent = pendientes.toLocaleString();
  if (btnPending) btnPending.textContent = pendientes.toLocaleString();
  if (btnResumeAll) btnResumeAll.textContent = pendientes.toLocaleString();

  const cardSummary = document.getElementById('cardCentralGlobalSummary');
  const emptyState = document.getElementById('hubEmptyState');
  const sourcesWrap = document.getElementById('hubSourcesWrap');
  const cardStep2 = document.getElementById('cardCentralDirectResume');

  if (cardStep2) cardStep2.classList.toggle('hidden', !hasData);
  if (cardSummary) cardSummary.classList.toggle('hidden', !hasData);
  if (emptyState) emptyState.classList.toggle('hidden', hasData);
  if (sourcesWrap) sourcesWrap.classList.toggle('hidden', !hasData);

  if (hasData) {
    wiz.maxStepUnlocked = Math.max(wiz.maxStepUnlocked, 4);
    document.getElementById('tab3')?.classList.remove('locked');
    document.getElementById('tab4')?.classList.remove('locked');
  }
}

function resumeFromCentralSource(schema, table) {
  wiz.schema = schema;
  wiz.table = table;
  wiz.id_col = 'dire_id';
  wiz.addr_col = 'dire_valor_origen';
  wiz.source_mode = 'central_tb_direccion';

  document.getElementById('summSchema').textContent  = schema;
  document.getElementById('summTable').textContent   = table;
  document.getElementById('summId').textContent      = 'dire_id';
  document.getElementById('summAddr').textContent    = 'dire_valor_origen (tb_direccion)';

  const elAiModel = document.getElementById('summAiModel');
  if (elAiModel) elAiModel.textContent = `Extractor: ${wiz.ai_model || 'Ollama'}`;
  const elAiHost = document.getElementById('summAiHost');
  if (elAiHost) elAiHost.textContent = `http://${wiz.ai_host}:${wiz.ai_port}`;

  syncNumWorkers(wiz.num_workers || 4);

  wiz.maxStepUnlocked = Math.max(wiz.maxStepUnlocked, 4);
  const tab4 = document.getElementById('tab4');
  if (tab4) tab4.classList.remove('locked');

  goStep(4);
  initStep5();
}

function resumeAllCentral() {
  wiz.schema = 'public';
  wiz.table  = 'tb_direccion';
  wiz.id_col = 'dire_id';
  wiz.addr_col = 'dire_valor_origen';
  wiz.source_mode = 'central_tb_direccion';

  const elSchema = document.getElementById('summSchema');
  const elTable  = document.getElementById('summTable');
  const elId     = document.getElementById('summId');
  const elAddr   = document.getElementById('summAddr');

  if (elSchema) elSchema.textContent = 'public';
  if (elTable)  elTable.textContent  = 'tb_direccion (Todo el Catastro Central)';
  if (elId)     elId.textContent     = 'dire_id';
  if (elAddr)   elAddr.textContent   = 'dire_valor_origen (tb_direccion)';

  const elAiModel = document.getElementById('summAiModel');
  if (elAiModel) elAiModel.textContent = `Extractor: ${wiz.ai_model || 'Ollama'}`;
  const elAiHost = document.getElementById('summAiHost');
  if (elAiHost) elAiHost.textContent = `http://${wiz.ai_host}:${wiz.ai_port}`;

  syncNumWorkers(wiz.num_workers || 4);

  wiz.maxStepUnlocked = Math.max(wiz.maxStepUnlocked, 4);
  const tab4 = document.getElementById('tab4');
  if (tab4) tab4.classList.remove('locked');

  goStep(4);
  initStep5();
}

function goToResumeMode() {
  wiz.maxStepUnlocked = Math.max(wiz.maxStepUnlocked, 3);
  goStep(3);
  switchHubSubView('resume');
}

function confirmTable() {
  const selId   = document.getElementById('sel_id_col')?.value;
  const selAddr = document.getElementById('sel_addr_col')?.value;
  if (selId) wiz.id_col = selId;
  if (selAddr) wiz.addr_col = selAddr;

  if (!wiz.table || !wiz.id_col || !wiz.addr_col) {
    showModalAlert('Selección Requerida', 'Por favor seleccione la tabla y las columnas de ID y Dirección antes de continuar.', 'warning');
    return;
  }

  if (!wiz.is_ingested || (wiz.centralCounts?.total || 0) === 0) {
    showModalAlert(
      'Migración Requerida',
      'Esta tabla aún no ha sido migrada a public.tb_direccion. Por favor haga clic en "Migrar e Ingestar a tb_direccion" antes de normalizar con IA.',
      'warning'
    );
    return;
  }

  resumeFromCentralSource(wiz.schema, wiz.table);
}

// ── PASO 5: Ejecución y Monitoreo del Inspector Catastral ────────────────────
async function initStep5() {
  try {
    const res  = await fetch('/api/status');
    const data = await res.json();
    const ai   = data.ai || {};
    const badge = document.getElementById('aiStatusBadge');

    const isModelReady = Boolean(ai.installed || ai.model_available);
    const isAiActive   = (ai.connected && isModelReady) || Boolean(wiz.ai_model && (ai.connected || wiz.ai_host));
    const activeModel  = wiz.ai_model || ai.model || 'Ollama';

    const elAiModel = document.getElementById('summAiModel');
    if (elAiModel) elAiModel.textContent = `Extractor: ${activeModel}`;

    if (badge) {
      if (isAiActive && activeModel) {
        badge.innerHTML = `<span class="badge badge-valid"><span class="dot-live"></span>Extractor: ${escapeHtml(activeModel)}</span>`;
      } else {
        badge.innerHTML = `<span class="badge badge-error">IA No Disponible</span>`;
      }
    }

    if (data.is_running && data.num_workers) {
      syncNumWorkers(data.num_workers);
    } else if (wiz.num_workers) {
      syncNumWorkers(wiz.num_workers);
    }
    if (data.active_table && !wiz.table) wiz.table = data.active_table;
    if (data.active_schema && !wiz.schema) wiz.schema = data.active_schema;
    if (data.table_counts && !wiz.tableCounts) wiz.tableCounts = data.table_counts;

    try {
      const mode = wiz.source_mode || 'central_tb_direccion';
      const cRes = await fetch(`/api/counts?schema=${encodeURIComponent(wiz.schema || 'public')}&table=${encodeURIComponent(wiz.table || 'tb_direccion')}&source_mode=${encodeURIComponent(mode)}`);
      if (cRes.ok) {
        const counts = await cRes.json();
        wiz.tableCounts = counts;
        const progressLabel = document.getElementById('progressLabel');
        if (progressLabel && !data.is_running) {
          const pend = counts.pendientes || 0;
          const tot = counts.total || 0;
          progressLabel.textContent = `${pend.toLocaleString()} pendientes de ${tot.toLocaleString()} en Catastro Central`;
        }
      }
    } catch (_) {}

    if (data.recent_records && data.recent_records.length > 0 && wiz.allRecords.length === 0) {
      data.recent_records.forEach(r => addRecord(r, false));
      filterInspectorRecords();
    }
    if (data.stats) updateStats(data.stats);
  } catch (_) {}

  // Cargar configuración de programación horaria diaria (Scheduler)
  loadSchedulerConfig();

  if (!wiz.evtSource) connectSSE();
}

function connectSSE() {
  if (wiz.evtSource) { wiz.evtSource.close(); wiz.evtSource = null; }

  const es = new EventSource('/api/stream');
  wiz.evtSource = es;

  es.onmessage = e => {
    try {
      const ev = JSON.parse(e.data);
      handleEvent(ev);
    } catch (_) {}
  };

  es.onerror = () => {
    const dot = document.getElementById('termLiveDot');
    if (dot) dot.style.background = '#f59e0b';
  };
}

function handleEvent(ev) {
  switch (ev.type) {
    case 'stats':
      updateStats(ev.payload);
      break;
    case 'record':
      addRecord(ev.payload, true);
      break;
    case 'done':
      onDone(ev.payload);
      break;
    case 'error':
      onError(ev.payload);
      break;
    case 'stopping':
      onStopping(ev.payload);
      break;
    case 'init':
      onInitSnapshot(ev.payload);
      break;
  }
}

function onStopping(payload) {
  stopLiveTicker();
  const btnStop = document.getElementById('btnStop');
  const btnStopSync = document.getElementById('btnStopSync');
  if (btnStop) btnStop.disabled = true;
  if (btnStopSync) btnStopSync.disabled = true;
  const statusLabel = document.getElementById('statusLabel');
  if (statusLabel) statusLabel.textContent = 'Detención solicitada. Culminando registros en curso...';
  const dot = document.getElementById('termLiveDot');
  if (dot) dot.style.background = 'var(--amber)';
}

function onInitSnapshot(payload) {
  if (!payload) return;
  if (payload.num_workers) {
    syncNumWorkers(payload.num_workers);
  }
  if (payload.active_table && !wiz.table) wiz.table = payload.active_table;
  if (payload.active_schema && !wiz.schema) wiz.schema = payload.active_schema;
  if (payload.active_model) {
    wiz.ai_model = payload.active_model;
    const summAiModel = document.getElementById('summAiModel');
    if (summAiModel) summAiModel.textContent = payload.active_model;
  }
  if (payload.stats) {
    updateStats(payload.stats);
  }
  if (payload.records && payload.records.length > 0 && wiz.allRecords.length === 0) {
    payload.records.forEach(r => addRecord(r, false));
    filterInspectorRecords();
  }
  if (payload.is_running) {
    document.getElementById('btnStart').disabled = true;
    document.getElementById('btnStop').disabled = false;
    const btnStopSync = document.getElementById('btnStopSync');
    if (btnStopSync) btnStopSync.disabled = false;
    const banner = document.getElementById('bannerActiveSession');
    if (banner) banner.classList.remove('hidden');
    [1, 2, 3, 4].forEach(i => document.getElementById(`tab${i}`)?.classList.add('locked'));
  }
}

function formatTimeHMS(totalSeconds) {
  if (totalSeconds === null || totalSeconds === undefined || isNaN(totalSeconds) || totalSeconds < 0) {
    return '00h 00m 00s';
  }
  const sec = Math.floor(totalSeconds);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(h)}h ${pad(m)}m ${pad(s)}s`;
}

let _deviceClockInterval = null;
function startDeviceClock(tzDesc = null) {
  const tzEl = document.getElementById('schedulerTzText');
  const clockEl = document.getElementById('schedulerClockText');
  if (tzDesc && tzEl) {
    tzEl.textContent = tzDesc;
  } else if (tzEl && (tzEl.textContent === 'Detectando...' || !tzEl.textContent)) {
    try {
      const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Local';
      tzEl.textContent = browserTz;
    } catch (_) {}
  }
  if (!_deviceClockInterval) {
    _deviceClockInterval = setInterval(() => {
      const cEl = document.getElementById('schedulerClockText');
      if (cEl) {
        cEl.textContent = new Date().toLocaleTimeString();
      }
    }, 1000);
  }
  if (clockEl) {
    clockEl.textContent = new Date().toLocaleTimeString();
  }
}

function updateStartButtonState(isRunning = null) {
  if (isRunning !== null) {
    wiz.is_running = Boolean(isRunning);
  }
  const btnStart = document.getElementById('btnStart');
  const warningEl = document.getElementById('lblSchedulerBlockWarning');
  const warningText = document.getElementById('lblSchedulerBlockWarningText');
  if (!btnStart) return;

  if (wiz.is_running) {
    btnStart.disabled = true;
    btnStart.title = 'El proceso ya se encuentra en ejecución activa.';
    if (warningEl) warningEl.style.display = 'none';
    return;
  }

  if (wiz.scheduler_enabled) {
    btnStart.disabled = true;
    const rangeText = wiz.scheduler_range ? ` (${wiz.scheduler_range})` : '';
    btnStart.title = `Inicio manual bloqueado: La programación automática diaria está activa${rangeText}. Desactive la casilla en el panel inferior para ejecutar manualmente.`;
    if (warningEl) {
      warningEl.style.display = 'inline-flex';
      if (warningText) {
        warningText.textContent = `Controlado por Programación Diaria${rangeText} (Inicio manual bloqueado)`;
      }
    }
  } else {
    btnStart.disabled = false;
    btnStart.title = 'Iniciar Normalización';
    if (warningEl) warningEl.style.display = 'none';
  }
}


function updateTimeBadges(s) {
  if (!s) return;
  const total  = s.total_to_process || 0;
  const proc   = s.processed || 0;
  const secs   = s.elapsed_seconds || 0;
  const status = s.status || 'IDLE';

  // 1. Tiempo transcurrido en horas, minutos y segundos
  const elapsedEl = document.getElementById('elapsedLabel');
  if (elapsedEl) {
    const span = elapsedEl.querySelector('span') || elapsedEl;
    span.textContent = `Tiempo: ${formatTimeHMS(secs)}`;
  }

  // 2. Velocidad de procesamiento
  let rps = 0.0;
  if (s.speed_rps !== undefined && s.speed_rps !== null && Number(s.speed_rps) > 0) {
    rps = Number(s.speed_rps);
  } else if (secs > 0 && proc > 0) {
    rps = proc / secs;
  }
  const speedEl = document.getElementById('speedLabel');
  if (speedEl) {
    speedEl.textContent = `${rps.toFixed(1)} reg/s`;
  }

  // 3. Tiempo restante estimado (Horas, minutos y segundos)
  const etaEl = document.getElementById('etaLabel');
  if (etaEl) {
    const span = etaEl.querySelector('span') || etaEl;
    if (status === 'FINISHED') {
      span.textContent = 'Completado';
    } else if (status === 'ERROR') {
      span.textContent = 'Interrumpido';
    } else if (proc === 0 || total === 0) {
      span.textContent = 'Restante: —';
    } else if (proc >= total) {
      span.textContent = 'Restante: 00h 00m 00s';
    } else {
      let etaSec = s.eta_seconds;
      if (etaSec === undefined || etaSec === null) {
        const remaining = Math.max(0, total - proc);
        etaSec = rps > 0 ? (remaining / rps) : 0;
      }
      if (etaSec > 0) {
        span.textContent = `Restante: ~${formatTimeHMS(etaSec)}`;
      } else {
        span.textContent = 'Restante: Calculando...';
      }
    }
  }
}

function startLiveTicker() {
  if (wiz.liveTickerInterval) return;
  wiz.liveTickerInterval = setInterval(() => {
    if (wiz.lastStats && wiz.lastStats.status === 'RUNNING' && wiz.lastStats.start_time) {
      const nowSec = Date.now() / 1000;
      const currentElapsed = Math.max(0, nowSec - wiz.lastStats.start_time);
      wiz.lastStats.elapsed_seconds = currentElapsed;

      const proc = wiz.lastStats.processed || 0;
      const total = wiz.lastStats.total_to_process || 0;
      if (currentElapsed > 0 && proc > 0) {
        const currentSpeed = proc / currentElapsed;
        wiz.lastStats.speed_rps = currentSpeed;
        const remaining = Math.max(0, total - proc);
        wiz.lastStats.eta_seconds = currentSpeed > 0 ? (remaining / currentSpeed) : 0;
      }
      updateTimeBadges(wiz.lastStats);
    }
  }, 1000);
}

function stopLiveTicker() {
  if (wiz.liveTickerInterval) {
    clearInterval(wiz.liveTickerInterval);
    wiz.liveTickerInterval = null;
  }
}

function updateStats(s) {
  if (!s) return;
  wiz.lastStats = s;

  kpi('kpiProcessed', s.processed);
  kpi('kpiValid',     s.valid);
  kpi('kpiObserved',  s.observed);
  kpi('kpiFailed',    s.failed);

  const pct   = s.progress_pct || 0;
  const total = s.total_to_process || 0;
  const proc  = s.processed || 0;
  const status = s.status || 'IDLE';

  const progressFill = document.getElementById('progressFill');
  if (progressFill) progressFill.style.width = pct + '%';

  const progressLabel = document.getElementById('progressLabel');
  if (progressLabel) {
    if (status === 'PREPARING') {
      progressLabel.textContent = 'Analizando registros y preparando catálogos...';
    } else {
      progressLabel.textContent = `${proc.toLocaleString()} de ${total.toLocaleString()} registros (${pct}%)`;
    }
  }

  updateTimeBadges(s);

  const labels = {
    PREPARING: 'Preparando entorno y tablas maestras...',
    RUNNING: 'Ejecutando proceso de normalización...',
    IDLE: 'Listo para iniciar',
    FINISHED: 'Proceso completado',
    ERROR: 'Error en procesamiento'
  };
  const statusLabel = document.getElementById('statusLabel');
  if (statusLabel) statusLabel.textContent = labels[status] || status;

  const dot = document.getElementById('termLiveDot');
  if (dot) {
    dot.className = (status === 'RUNNING' || status === 'PREPARING') ? 'dot-live' : '';
    dot.style.background = status === 'RUNNING' ? 'var(--green)' : (status === 'PREPARING' ? 'var(--amber)' : 'var(--slate-400)');
  }

  if (status === 'RUNNING') {
    startLiveTicker();
  } else {
    stopLiveTicker();
  }
}

function addRecord(r, shouldScroll = true) {
  // Extraer componentes estructurados con fallback dinámico
  const rawComponents = Array.isArray(r.componentes) ? r.componentes : [];
  let mzVal = r.manzana || '';
  let ltVal = r.lote || '';
  let sltVal = r.slote || '';
  let blockVal = r.block || '';
  let pisoVal = r.piso || '';

  for (const c of rawComponents) {
    const nom = (c.codi_nombre || '').toUpperCase().trim();
    if (!mzVal && (nom === 'MANZANA' || nom === 'MZ' || c.codi_id === 1)) mzVal = c.diti_nombre || '';
    if (!ltVal && (nom === 'LOTE' || nom === 'LT' || c.codi_id === 2)) ltVal = c.diti_nombre || '';
    if (!sltVal && (nom === 'SUBLOTE' || nom === 'SLT' || c.codi_id === 3)) sltVal = c.diti_nombre || '';
    if (!blockVal && (nom === 'BLOCK' || nom === 'BLOQUE' || nom === 'TORRE' || c.codi_id === 11)) blockVal = c.diti_nombre || '';
    if (!pisoVal && (nom === 'PISO' || c.codi_id === 12)) pisoVal = c.diti_nombre || '';
  }

  const rawVias = Array.isArray(r.vias) ? r.vias : [];
  const rawModulos = Array.isArray(r.modulos) ? r.modulos : [];

  const normRec = {
    index:          r.index || (wiz.allRecords.length + 1),
    total:          r.total || 0,
    id_licencia:    r.id_licencia ?? r.id ?? '—',
    raw_text:       r.raw_text || r.original_address || r.emp_direccion || '',
    metodo:         r.metodo || r.method || 'IA',
    es_procesado:   Boolean(r.es_procesado),
    observacion:    r.observacion || '',
    success:        r.success !== false,
    nom_via:        r.nom_via || '',
    num_via:        r.num_via || '',
    id_via:         r.id_via || null,
    tipo_via_name:  r.tipo_via_name || r.tipo_via || '',
    nom_zona:       r.nom_zona || '',
    id_zona:        r.id_zona || null,
    tipo_zona_name: r.tipo_zona_name || r.tipo_zona || '',
    manzana:        mzVal,
    lote:           ltVal,
    slote:          sltVal,
    block:          blockVal,
    piso:           pisoVal,
    vias:           rawVias,
    componentes:    rawComponents,
    modulos:        rawModulos,
    dire_id:        r.dire_id ?? null,
    worker_id:      r.worker_id || '',
    referencia:     r.referencia || r.dire_referencia || '',
    time:           new Date().toLocaleTimeString('es-PE', { hour12: false }),
    reprocesado:    false,
  };

  const isErr = !normRec.success || normRec.metodo === 'ERROR';
  const isObs = !normRec.es_procesado && !isErr;
  const newStatus = isErr ? 'error' : (isObs ? 'observed' : 'valid');

  // Buscar si ya existía este registro en la sesión activa
  const existingIndex = wiz.allRecords.findIndex(
    x => String(x.id_licencia) === String(normRec.id_licencia)
  );

  if (existingIndex !== -1) {
    // Ya existía en una corrida anterior: actualizar estado y contadores
    const prev = wiz.allRecords[existingIndex];
    const prevErr = !prev.success || prev.metodo === 'ERROR';
    const prevObs = !prev.es_procesado && !prevErr;
    const prevStatus = prevErr ? 'error' : (prevObs ? 'observed' : 'valid');

    // Descontar estado previo
    wiz.counts[prevStatus] = Math.max(0, (wiz.counts[prevStatus] || 0) - 1);
    // Sumar nuevo estado
    wiz.counts[newStatus] = (wiz.counts[newStatus] || 0) + 1;

    normRec.reprocesado = true;

    // Reemplazar y posicionar al principio de la vista
    wiz.allRecords.splice(existingIndex, 1);
    wiz.allRecords.unshift(normRec);
  } else {
    // Registro nuevo en la sesión
    wiz.counts.all++;
    wiz.counts[newStatus] = (wiz.counts[newStatus] || 0) + 1;

    wiz.allRecords.unshift(normRec);
    if (wiz.allRecords.length > 2000) wiz.allRecords.pop();
  }

  updateCounterBadges();
  filterInspectorRecords(shouldScroll);
}

function updateCounterBadges() {
  const ca = document.getElementById('cntAll');
  const cv = document.getElementById('cntValid');
  const co = document.getElementById('cntObs');
  const ce = document.getElementById('cntErr');
  if (ca) ca.textContent = wiz.counts.all.toLocaleString();
  if (cv) cv.textContent = wiz.counts.valid.toLocaleString();
  if (co) co.textContent = wiz.counts.observed.toLocaleString();
  if (ce) ce.textContent = wiz.counts.error.toLocaleString();
}

function setInspectorStatus(st) {
  wiz.inspectorStatus = st;
  ['pillAll', 'pillValid', 'pillObserved', 'pillError'].forEach(id => {
    document.getElementById(id)?.classList.remove('active');
  });

  if (st === 'all')      document.getElementById('pillAll')?.classList.add('active');
  if (st === 'valid')    document.getElementById('pillValid')?.classList.add('active');
  if (st === 'observed') document.getElementById('pillObserved')?.classList.add('active');
  if (st === 'error')    document.getElementById('pillError')?.classList.add('active');

  filterInspectorRecords(false);
}

function toggleAutoScroll(checked) {
  wiz.autoScroll = checked;
}

function filterInspectorRecords(autoScroll = false) {
  wiz.searchInspector = (document.getElementById('searchInspector')?.value || '').toLowerCase().trim();
  wiz.inspectorMotor  = document.getElementById('filterInspectorMotor')?.value || 'all';

  const list = document.getElementById('inspectorCardsList');
  const tbody = document.getElementById('inspectorTableBody');
  if (!list && !tbody) return;

  const q  = wiz.searchInspector;
  const st = wiz.inspectorStatus;
  const mt = wiz.inspectorMotor;

  const filtered = wiz.allRecords.filter(r => {
    if (q) {
      const matchId   = String(r.id_licencia).includes(q);
      const matchRaw  = (r.raw_text || '').toLowerCase().includes(q);
      const matchVia  = (r.nom_via || '').toLowerCase().includes(q);
      const matchNum  = (r.num_via || '').toLowerCase().includes(q);
      const matchZona = (r.nom_zona || '').toLowerCase().includes(q);
      const matchMz   = (r.manzana || '').toLowerCase().includes(q);
      const matchLt   = (r.lote || '').toLowerCase().includes(q);
      const matchBlk  = (r.block || '').toLowerCase().includes(q);
      const matchPiso = (r.piso || '').toLowerCase().includes(q);
      const matchObs  = (r.observacion || '').toLowerCase().includes(q);
      const matchViasArr = (r.vias || []).some(v => (v.via_nombre || '').toLowerCase().includes(q) || (v.divi_numero || '').toLowerCase().includes(q));
      const matchModArr  = (r.modulos || []).some(m => (m.timo_nombre || '').toLowerCase().includes(q) || (m.ditm_nombre || '').toLowerCase().includes(q));

      if (!matchId && !matchRaw && !matchVia && !matchNum && !matchZona && !matchMz && !matchLt && !matchBlk && !matchPiso && !matchObs && !matchViasArr && !matchModArr) {
        return false;
      }
    }

    if (st === 'valid' && !r.es_procesado) return false;
    if (st === 'observed' && (r.es_procesado || !r.success)) return false;
    if (st === 'error' && r.success && r.metodo !== 'ERROR') return false;

    if (mt === 'ia' && !(r.metodo || '').toLowerCase().includes('ia')) return false;
    if (mt === 'hibrido' && !(r.metodo || '').toLowerCase().includes('híbrido') && !(r.metodo || '').toLowerCase().includes('hibrido')) return false;
    if (mt === 'heuristico' && !(r.metodo || '').toLowerCase().includes('heur')) return false;

    return true;
  });

  const countLabel = document.getElementById('inspectorCountLabel');
  if (countLabel) {
    countLabel.textContent = `Mostrando ${filtered.length.toLocaleString()} de ${wiz.allRecords.length.toLocaleString()} registros procesados`;
  }

  // Renderizar según el modo de vista seleccionado
  if (wiz.viewMode === 'table') {
    renderInspectorTable(filtered);
  } else {
    if (!filtered.length) {
      if (list) list.innerHTML = `<p style="text-align:center; color:var(--slate-400); padding:40px; font-size:13px;">No hay registros que coincidan con los filtros seleccionados.</p>`;
    } else {
      if (list) list.innerHTML = filtered.map(r => createConciseRecordCard(r)).join('');
    }
  }

  if (autoScroll && wiz.autoScroll) {
    if (wiz.viewMode === 'table') {
      const tableWrap = document.getElementById('inspectorTableWrap');
      if (tableWrap) tableWrap.scrollTop = 0;
    } else {
      if (list) list.scrollTop = 0;
    }
  }
}

function setInspectorViewMode(mode) {
  wiz.viewMode = mode;
  const btnCards = document.getElementById('btnViewCards');
  const btnTable = document.getElementById('btnViewTable');
  const cardsList = document.getElementById('inspectorCardsList');
  const tableWrap = document.getElementById('inspectorTableWrap');

  if (mode === 'table') {
    btnCards?.classList.remove('active');
    btnTable?.classList.add('active');
    cardsList?.classList.add('hidden');
    tableWrap?.classList.remove('hidden');
  } else {
    btnCards?.classList.add('active');
    btnTable?.classList.remove('active');
    cardsList?.classList.remove('hidden');
    tableWrap?.classList.add('hidden');
  }

  filterInspectorRecords(false);
}

function renderInspectorTable(records) {
  const tbody = document.getElementById('inspectorTableBody');
  if (!tbody) return;

  if (!records.length) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:var(--slate-400); padding:40px;">No hay registros que coincidan con los filtros seleccionados.</td></tr>`;
    return;
  }

  tbody.innerHTML = records.map(r => {
    const isErr = !r.success || r.metodo === 'ERROR';
    const isObs = !r.es_procesado && !isErr;
    const statusBadge = isErr
      ? `<span class="badge badge-error">ERROR</span>`
      : (isObs ? `<span class="badge badge-observed">OBSERVADO</span>` : `<span class="badge badge-valid">NORMALIZADO</span>`);

    let motorBadge = `<span class="badge badge-motor-ai" style="font-size:10px;">IA</span>`;
    if (r.metodo && (r.metodo.includes('Híbrido') || r.metodo.includes('Hibrido'))) {
      motorBadge = `<span class="badge badge-motor-hy" style="font-size:10px;">HÍBRIDO</span>`;
    } else if (r.metodo && !r.metodo.includes('IA')) {
      motorBadge = `<span class="badge badge-motor-he" style="font-size:10px;">HEURÍSTICO</span>`;
    }

    // Vías
    let viasText = '';
    if (r.vias && r.vias.length > 1) {
      viasText = r.vias.map(v => `${escapeHtml(v.tipo_via_name || '')} ${escapeHtml(v.via_nombre || '')} ${v.divi_numero ? 'N° ' + escapeHtml(v.divi_numero) : 'S/N'}`.trim()).join(' <span style="color:var(--slate-400); font-weight:700;">con</span> ');
    } else {
      const tipo = r.tipo_via_name ? escapeHtml(r.tipo_via_name) + ' ' : '';
      const nom = escapeHtml(r.nom_via || 'Sin vía');
      const num = r.num_via ? `N° ${escapeHtml(r.num_via)}` : 'S/N';
      viasText = `${tipo}${nom} ${num}`;
    }

    // Zona
    const zonaText = `${escapeHtml(r.tipo_zona_name ? r.tipo_zona_name + ' ' : '')}${escapeHtml(r.nom_zona || 'Sin zona')}`;

    // Predio
    const predChips = [];
    if (r.manzana) predChips.push(`<span class="chip-predio chip-mz">Mz:${escapeHtml(r.manzana)}</span>`);
    if (r.lote)    predChips.push(`<span class="chip-predio chip-lt">Lt:${escapeHtml(r.lote)}</span>`);
    if (r.slote && isCleanSublote(r.slote)) predChips.push(`<span class="chip-predio chip-slt">Slt:${escapeHtml(r.slote)}</span>`);
    if (r.block)   predChips.push(`<span class="chip-predio chip-block">Blk:${escapeHtml(r.block)}</span>`);
    if (r.piso)    predChips.push(`<span class="chip-predio chip-piso">Piso:${escapeHtml(r.piso)}</span>`);
    const predioText = predChips.length > 0 ? predChips.join('') : '—';

    // Módulos
    let modText = '—';
    if (r.modulos && r.modulos.length > 0) {
      modText = r.modulos.map(m => `${escapeHtml(m.timo_nombre || '')} ${escapeHtml(m.ditm_nombre || '')}`.trim()).join(', ');
    }

    // Diagnóstico
    let diagText = '—';
    if (r.observacion) {
      const color = isErr ? '#dc2626' : (isObs ? '#d97706' : '#64748b');
      diagText = `<span style="color:${color}; font-weight:600;">${escapeHtml(r.observacion)}</span>`;
    }

    return `
      <tr>
        <td style="font-family:monospace; font-weight:700;">${r.id_licencia}</td>
        <td>${statusBadge}</td>
        <td>${motorBadge}</td>
        <td style="font-family:monospace; font-size:11.5px; max-width:240px; word-break:break-word;">${escapeHtml(r.raw_text)}</td>
        <td style="font-weight:600;">${viasText}</td>
        <td>${zonaText}</td>
        <td>${predioText}</td>
        <td style="color:#5b21b6; font-weight:600;">${modText}</td>
        <td style="font-size:11.5px;">${diagText}</td>
      </tr>
    `;
  }).join('');
}

function createConciseRecordCard(r) {
  const isErr = !r.success || r.metodo === 'ERROR';
  const isObs = !r.es_procesado && !isErr;
  const cardClass = isErr ? 'card-error' : (isObs ? 'card-observed' : 'card-valid');

  // Badges de Estado Institucional (Sin Emojis)
  const statusBadge = isErr
    ? `<span class="badge badge-error">ERROR</span>`
    : (isObs ? `<span class="badge badge-observed">OBSERVADO</span>` : `<span class="badge badge-valid">NORMALIZADO</span>`);

  // Badge de Motor Técnico
  let motorBadge = `<span class="badge badge-motor-ai">MOTOR IA</span>`;
  if (r.metodo && (r.metodo.includes('Híbrido') || r.metodo.includes('Hibrido'))) {
    motorBadge = `<span class="badge badge-motor-hy">HÍBRIDO</span>`;
  } else if (r.metodo && !r.metodo.includes('IA')) {
    motorBadge = `<span class="badge badge-motor-he">HEURÍSTICO</span>`;
  }

  // Diagnóstico Catastral Sobrio y Amplio
  let diagHtml = '';
  if (r.observacion) {
    const diagClass = isErr ? 'diag-err' : 'diag-obs';
    diagHtml = `
      <div class="record-diagnosis ${diagClass}">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0; margin-top:2px;">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <div><strong>Diagnóstico Catastral:</strong> <span>${escapeHtml(r.observacion)}</span></div>
      </div>`;
  }

  // Columna 1: Vías (Principal y Esquinas)
  let viasHtml = '';
  const viasArr = (r.vias && r.vias.length > 0) ? r.vias : [];
  if (viasArr.length > 1) {
    viasHtml = viasArr.map((v, i) => {
      const label = i === 0 ? 'Vía 1' : 'Vía 2';
      const tipo = v.tipo_via_name ? escapeHtml(v.tipo_via_name) + ' ' : '';
      const nom = escapeHtml(v.via_nombre || 'Sin nombre');
      const num = v.divi_numero
        ? `<span class="via-badge-num">N° ${escapeHtml(v.divi_numero)}</span>`
        : `<span class="via-badge-num" style="background:#f1f5f9; color:#64748b; border-color:#cbd5e1;">S/N</span>`;
      const idChip = v.via_id ? `<span class="chip-id chip-via">ID: ${v.via_id}</span>` : '';
      return `<div class="via-entry"><span style="font-size:10px; font-weight:700; color:var(--slate-400);">${label}:</span> <strong>${tipo}${nom}</strong> ${num} ${idChip}</div>`;
    }).join('<div class="via-corner-divider"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="7 13 12 18 17 13"/><polyline points="7 6 12 11 17 6"/></svg> Intersección (Esquina)</div>');
  } else if (viasArr.length === 1) {
    const v = viasArr[0];
    const tipo = v.tipo_via_name ? escapeHtml(v.tipo_via_name) + ' ' : '';
    const nom = escapeHtml(v.via_nombre || r.nom_via || 'Sin vía');
    const num = v.divi_numero
      ? `<span class="via-badge-num">N° ${escapeHtml(v.divi_numero)}</span>`
      : (r.num_via ? `<span class="via-badge-num">N° ${escapeHtml(r.num_via)}</span>` : `<span class="via-badge-num" style="background:#f1f5f9; color:#64748b; border-color:#cbd5e1;">S/N</span>`);
    const idChip = v.via_id ? `<span class="chip-id chip-via">ID: ${v.via_id}</span>` : (r.id_via ? `<span class="chip-id chip-via">ID: ${r.id_via}</span>` : '');
    viasHtml = `<div class="via-entry"><strong>${tipo}${nom}</strong> ${num} ${idChip}</div>`;
  } else {
    const tipo = r.tipo_via_name ? escapeHtml(r.tipo_via_name) + ' ' : '';
    const nom = escapeHtml(r.nom_via || 'Sin vía');
    const num = r.num_via
      ? `<span class="via-badge-num">N° ${escapeHtml(r.num_via)}</span>`
      : `<span class="via-badge-num" style="background:#f1f5f9; color:#64748b; border-color:#cbd5e1;">S/N</span>`;
    const idChip = r.id_via ? `<span class="chip-id chip-via">ID: ${r.id_via}</span>` : '';
    viasHtml = `<div class="via-entry"><strong>${tipo}${nom}</strong> ${num} ${idChip}</div>`;
  }

  // Columna 2: Zona Catastral
  const zonaTipo = r.tipo_zona_name ? escapeHtml(r.tipo_zona_name) + ' ' : '';
  const zonaNom = escapeHtml(r.nom_zona || 'Sin zona');
  const zonaChip = r.id_zona ? `<span class="chip-id chip-zona">ID: ${r.id_zona}</span>` : '';
  const zonaHtml = `<div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;"><strong>${zonaTipo}${zonaNom}</strong> ${zonaChip}</div>`;

  // Columna 3: Predio Catastral (Componentes Núcleo)
  const predioChips = [];
  if (r.manzana) predioChips.push(`<span class="chip-predio chip-mz">Mz: ${escapeHtml(r.manzana)}</span>`);
  if (r.lote)    predioChips.push(`<span class="chip-predio chip-lt">Lt: ${escapeHtml(r.lote)}</span>`);
  if (r.slote && isCleanSublote(r.slote)) predioChips.push(`<span class="chip-predio chip-slt">Slt: ${escapeHtml(r.slote)}</span>`);
  if (r.block)   predioChips.push(`<span class="chip-predio chip-block">Block: ${escapeHtml(r.block)}</span>`);
  if (r.piso)    predioChips.push(`<span class="chip-predio chip-piso">Piso: ${escapeHtml(r.piso)}</span>`);

  if (Array.isArray(r.componentes)) {
    for (const c of r.componentes) {
      const cnom = (c.codi_nombre || '').toUpperCase().trim();
      if (!['MANZANA','MZ','LOTE','LT','SUBLOTE','SLT','BLOCK','BLOQUE','TORRE','PISO'].includes(cnom) && ![1,2,3,11,12].includes(c.codi_id)) {
        predioChips.push(`<span class="chip-predio" style="background:#f1f5f9; color:#475569; border:1px solid #cbd5e1;">${escapeHtml(c.codi_nombre || 'COMP')}: ${escapeHtml(c.diti_nombre || '')}</span>`);
      }
    }
  }
  const predioHtml = predioChips.length > 0
    ? `<div style="display:flex; flex-wrap:wrap; gap:2px;">${predioChips.join('')}</div>`
    : `<span style="color:var(--slate-400); font-size:12px;">Sin componentes prediales</span>`;

  // Columna 4: Módulos Inmobiliarios
  const modArr = Array.isArray(r.modulos) ? r.modulos : [];
  const modHtml = modArr.length > 0
    ? `<div style="display:flex; flex-wrap:wrap; gap:2px;">${modArr.map(m => `<span class="chip-mod">${escapeHtml(m.timo_nombre || 'MOD')}: ${escapeHtml(m.ditm_nombre || '')}</span>`).join('')}</div>`
    : `<span style="color:var(--slate-400); font-size:12px;">Sin módulos</span>`;

  // Columna 5: Referencia
  const refHtml = r.referencia
    ? `<span class="chip-ref-text">${escapeHtml(r.referencia)}</span>`
    : `<span style="color:var(--slate-400); font-size:12px;">—</span>`;

  // Metadatos
  const direIdChip = r.dire_id
    ? `<span class="chip-id" style="background:#e0f2fe; color:#0369a1; border-color:#bae6fd;">DIRE_ID: ${r.dire_id}</span>`
    : '';
  const reproBadge = r.reprocesado
    ? `<span class="badge" style="background:var(--slate-100); color:var(--mpch-navy); border:1px solid var(--slate-300); font-size:10px;">REPROCESADO</span>`
    : '';
  const workerBadge = r.worker_id
    ? `<span class="badge" style="background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; font-weight:700; font-size:10px;">${escapeHtml(r.worker_id)}</span>`
    : '';

  return `
    <div class="record-card ${cardClass}">
      <div class="record-header">
        <div class="record-meta">
          <span class="record-id-chip">ID: ${r.id_licencia}</span>
          ${direIdChip}
          <span class="record-index">#${r.index} de ${r.total || '?'}</span>
          ${statusBadge}
          ${motorBadge}
          ${workerBadge}
          ${reproBadge}
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="font-size:11px; color:var(--slate-500);">${r.time || ''}</span>
          <button class="btn btn-ghost" style="padding:2px 8px; font-size:11px;" onclick="copySingleRecord(${r.id_licencia})" title="Copiar registro JSON">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            <span>Copiar</span>
          </button>
        </div>
      </div>

      <div class="record-raw">
        <span class="lbl-entrada">Entrada</span>
        <span class="val-entrada">"${escapeHtml(r.raw_text)}"</span>
      </div>

      <div class="catastro-matrix">
        <div class="matrix-col">
          <span class="matrix-lbl">Vía(s) Normalizada(s)</span>
          <div class="matrix-val">${viasHtml}</div>
        </div>
        <div class="matrix-col">
          <span class="matrix-lbl">Zona / Hab. Urbana</span>
          <div class="matrix-val">${zonaHtml}</div>
        </div>
        <div class="matrix-col">
          <span class="matrix-lbl">Predio Catastral</span>
          <div class="matrix-val">${predioHtml}</div>
        </div>
        <div class="matrix-col">
          <span class="matrix-lbl">Módulo(s)</span>
          <div class="matrix-val">${modHtml}</div>
        </div>
        <div class="matrix-col">
          <span class="matrix-lbl">Referencia</span>
          <div class="matrix-val">${refHtml}</div>
        </div>
      </div>

      ${diagHtml}
    </div>
  `;
}

function copySingleRecord(idLicencia) {
  const rec = wiz.allRecords.find(r => r.id_licencia == idLicencia);
  if (!rec) return;

  let viaDesc = `${rec.tipo_via_name ? rec.tipo_via_name + ' ' : ''}${rec.nom_via || ''} ${rec.num_via ? 'N° ' + rec.num_via : 'S/N'}`.trim();
  if (rec.vias && rec.vias.length > 1) {
    viaDesc = rec.vias.map(v => `${v.tipo_via_name || ''} ${v.via_nombre || ''} ${v.divi_numero ? 'N° ' + v.divi_numero : 'S/N'}`.trim()).join(' con ');
  }
  const zonaDesc = `${rec.tipo_zona_name ? rec.tipo_zona_name + ' ' : ''}${rec.nom_zona || ''}`.trim();
  const predParts = [];
  if (rec.manzana) predParts.push(`Mz: ${rec.manzana}`);
  if (rec.lote) predParts.push(`Lt: ${rec.lote}`);
  if (rec.slote && isCleanSublote(rec.slote)) predParts.push(`Slt: ${rec.slote}`);
  if (rec.block) predParts.push(`Block: ${rec.block}`);
  if (rec.piso) predParts.push(`Piso: ${rec.piso}`);
  const catText = predParts.join(' | ');

  let modText = '';
  if (rec.modulos && rec.modulos.length > 0) {
    modText = rec.modulos.map(m => `${m.timo_nombre || ''} ${m.ditm_nombre || ''}`.trim()).join(', ');
  }

  const estado = (!rec.success || rec.metodo === 'ERROR') ? 'ERROR' : (rec.es_procesado ? 'NORMALIZADO' : 'OBSERVADO');

  const text = `ID: ${rec.id_licencia} | Entrada: "${rec.raw_text}" | Vía: ${viaDesc || 'N/D'} | Zona: ${zonaDesc || 'N/D'}${catText ? ' | ' + catText : ''}${modText ? ' | Módulos: ' + modText : ''} | Estado: ${estado}${rec.observacion ? ' | Diagnóstico: ' + rec.observacion : ''}`;
  navigator.clipboard.writeText(text).catch(() => {});
}

let currentExportDataSource = 'db'; // 'db' o 'view'
let cachedDbCounts = { total: 0, pendientes: 0, validos: 0, observados: 0 };

async function openExportModal() {
  const overlay = document.getElementById('modalExportOverlay');
  if (!overlay) return;

  const isCentral = (wiz.source_mode === 'central_tb_direccion' || wiz.table === 'tb_direccion');
  const schema = (isCentral && wiz.table === 'tb_direccion') ? 'public' : (wiz.schema || 'public');
  const table = (isCentral && wiz.table === 'tb_direccion') ? 'tb_direccion' : (wiz.table || 'tb_direccion');
  const idCol = isCentral ? 'dire_id' : (wiz.id_col || null);
  const addrCol = isCentral ? 'dire_valor_origen' : (wiz.addr_col || null);

  const tableLabel = document.getElementById('exportModalTable');
  if (tableLabel) tableLabel.textContent = `${schema}.${table}`;

  // Actualizar contador en vivo de registros en pantalla
  const viewCount = document.getElementById('exportViewCount');
  if (viewCount) viewCount.textContent = (wiz.allRecords ? wiz.allRecords.length : 0).toLocaleString();

  overlay.classList.remove('hidden');

  // Si ya tenemos conteos cacheados de la tabla, pintarlos de inmediato
  if (wiz.tableCounts) {
    cachedDbCounts = { ...wiz.tableCounts };
    renderExportModalCounts();
  }

  // Refrescar conteos frescos desde PostgreSQL en segundo plano
  try {
    const res = await fetch('/api/inspect-table', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        schema_name: schema,
        table_name: table,
        id_col: idCol,
        address_col: addrCol,
      }),
    });
    if (res.ok) {
      const data = await res.json();
      if (data.counts) {
        cachedDbCounts = data.counts;
        wiz.tableCounts = data.counts;
        renderExportModalCounts();
      }
    }
  } catch (err) {
    console.debug('Aviso al refrescar conteos para exportar:', err);
  }
}

function closeExportModal() {
  const overlay = document.getElementById('modalExportOverlay');
  if (overlay) overlay.classList.add('hidden');
}

window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeExportModal();
    if (typeof closeShutdownModal === 'function') closeShutdownModal();
  }
});

function setExportDataSource(source) {
  currentExportDataSource = source;
  const btnDb = document.getElementById('btnSourceDb');
  const btnView = document.getElementById('btnSourceView');

  if (source === 'db') {
    if (btnDb) btnDb.classList.add('active');
    if (btnView) btnView.classList.remove('active');
  } else {
    if (btnDb) btnDb.classList.remove('active');
    if (btnView) btnView.classList.add('active');
  }

  renderExportModalCounts();
}

function renderExportModalCounts() {
  const isDb = (currentExportDataSource === 'db');

  let valid = 0;
  let obs = 0;
  let total = 0;

  if (isDb) {
    valid = cachedDbCounts.validos || 0;
    obs = cachedDbCounts.observados || 0;
    total = cachedDbCounts.total || 0;
  } else {
    const records = wiz.allRecords || [];
    valid = records.filter(r => r.es_procesado).length;
    obs = records.filter(r => !r.es_procesado && r.metodo !== 'ERROR').length;
    total = records.length;
  }

  const processed = valid + obs;

  const bValid = document.getElementById('badgeExportValid');
  const bObs = document.getElementById('badgeExportObs');
  const bTotal = document.getElementById('badgeExportTotal');
  const cntProc = document.getElementById('cntExportProcessed');
  const cntObs = document.getElementById('cntExportObserved');
  const cntVal = document.getElementById('cntExportValid');

  if (bValid) bValid.textContent = `${valid.toLocaleString()} Válidos`;
  if (bObs) bObs.textContent = `${obs.toLocaleString()} Observados`;
  if (bTotal) bTotal.textContent = `${total.toLocaleString()} Total`;

  if (cntProc) cntProc.textContent = processed.toLocaleString();
  if (cntObs) cntObs.textContent = obs.toLocaleString();
  if (cntVal) cntVal.textContent = valid.toLocaleString();
}

async function executeExport(scope, format) {
  const isCentral = (wiz.source_mode === 'central_tb_direccion' || wiz.table === 'tb_direccion');
  const schema = (isCentral && wiz.table === 'tb_direccion') ? 'public' : (wiz.schema || 'public');
  const table = (isCentral && wiz.table === 'tb_direccion') ? 'tb_direccion' : (wiz.table || 'tb_direccion');
  const idCol = isCentral ? 'dire_id' : (wiz.id_col || null);
  const addrCol = isCentral ? 'dire_valor_origen' : (wiz.addr_col || null);
  const isDb = (currentExportDataSource === 'db') && Boolean(schema && table);

  // Identificar botón clickeado para feedback visual (spinner)
  let btnId = '';
  if (scope === 'processed' && format === 'excel') btnId = 'btnDlExcelProcessed';
  else if (scope === 'processed' && format === 'csv') btnId = 'btnDlCsvProcessed';
  else if (scope === 'processed' && format === 'json') btnId = 'btnDlJsonProcessed';
  else if (scope === 'observed' && format === 'excel') btnId = 'btnDlExcelObserved';
  else if (scope === 'observed' && format === 'csv') btnId = 'btnDlCsvObserved';
  else if (scope === 'observed' && format === 'json') btnId = 'btnDlJsonObserved';
  else if (scope === 'valid' && format === 'excel') btnId = 'btnDlExcelValid';
  else if (scope === 'valid' && format === 'csv') btnId = 'btnDlCsvValid';
  else if (scope === 'valid' && format === 'json') btnId = 'btnDlJsonValid';

  const btn = document.getElementById(btnId);
  const origHtml = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<div class="spinner" style="width:11px; height:11px; border-width:1.5px; margin-right:3px;"></div><span>Descargando...</span>`;
  }

  try {
    if (isDb) {
      // Descarga masiva directa desde PostgreSQL
      const res = await fetch('/api/export-db', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          schema_name: schema,
          table_name: table,
          scope: scope,
          format: format,
          id_col: idCol,
          dir_col: addrCol,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showModalAlert('Error de Exportación', err.detail || 'No se pudo generar el archivo.', 'error');
        return;
      }

      const blob = await res.blob();
      const contentDisp = res.headers.get('Content-Disposition') || '';
      let filename = '';
      const match = contentDisp.match(/filename="?([^";]+)"?/);
      if (match && match[1]) {
        filename = match[1];
      } else {
        const now = new Date();
        const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');
        const timeStr = now.toTimeString().slice(0, 8).replace(/:/g, '');
        const ext = format === 'csv' ? 'csv' : (format === 'json' ? 'json' : 'xlsx');
        filename = `reporte_${table}_${scope}_${dateStr}_${timeStr}.${ext}`;
      }

      triggerBrowserDownload(blob, filename);

    } else {
      // Descarga desde la vista activa en memoria
      const all = wiz.allRecords || [];
      let filtered = [];

      if (scope === 'observed') {
        filtered = all.filter(r => !r.es_procesado && r.metodo !== 'ERROR');
      } else if (scope === 'valid') {
        filtered = all.filter(r => r.es_procesado);
      } else if (scope === 'processed') {
        filtered = all.filter(r => r.metodo !== 'ERROR');
      } else {
        filtered = all;
      }

      if (!filtered.length) {
        showModalAlert('Sin Registros', 'No hay registros en la vista activa que coincidan con el filtro seleccionado.', 'info');
        return;
      }

      let endpoint = '/api/export-excel';
      if (format === 'csv') endpoint = '/api/export-csv';
      else if (format === 'json') endpoint = '/api/export-json';

      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ records: filtered }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showModalAlert('Error al Generar Archivo', err.detail || 'Error desconocido', 'error');
        return;
      }

      const blob = await res.blob();
      const now = new Date();
      const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');
      const timeStr = now.toTimeString().slice(0, 8).replace(/:/g, '');
      const ext = format === 'csv' ? 'csv' : (format === 'json' ? 'json' : 'xlsx');
      const filename = `reporte_vista_${scope}_${dateStr}_${timeStr}.${ext}`;

      triggerBrowserDownload(blob, filename);
    }
  } catch (e) {
    showModalAlert('Error de Descarga', e.message, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  }
}

function triggerBrowserDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Compatibilidad directa
function exportRecordsExcel() {
  executeExport('processed', 'excel');
}

function exportRecordsCSV() {
  executeExport('processed', 'csv');
}

function exportRecordsJSON() {
  executeExport('processed', 'json');
}

async function clearRecords() {
  wiz.allRecords = [];
  wiz.counts = { all: 0, valid: 0, observed: 0, error: 0 };
  updateCounterBadges();
  filterInspectorRecords();

  kpi('kpiProcessed', 0);
  kpi('kpiValid', 0);
  kpi('kpiObserved', 0);
  kpi('kpiFailed', 0);

  document.getElementById('progressFill').style.width = '0%';
  document.getElementById('progressLabel').textContent = '0 de 0 registros';

  try {
    await fetch('/api/clear-session', { method: 'POST' });
  } catch (_) {}
}

// ── Iniciar / Detener Proceso ETL ────────────────────────────────────────────
async function startETL() {
  const limit       = parseInt(document.getElementById('inp_limit').value) || null;
  const batch       = parseInt(document.getElementById('inp_batch').value) || 50;
  const num_workers = parseInt(document.getElementById('inp_num_workers')?.value || wiz.num_workers || 4);
  syncNumWorkers(num_workers);
  const filter      = document.getElementById('inp_filter').value || 'pending';
  const require_ai  = document.getElementById('inp_require_ai')?.checked ?? true;

  // NO vaciar wiz.allRecords ni wiz.counts para preservar el historial acumulativo de la sesión

  document.getElementById('progressFill').style.width = '0%';
  document.getElementById('progressLabel').textContent = 'Preparando ejecución...';

  const elapsedEl = document.getElementById('elapsedLabel');
  if (elapsedEl) {
    const span = elapsedEl.querySelector('span') || elapsedEl;
    span.textContent = 'Tiempo: 00h 00m 00s';
  }
  const etaEl = document.getElementById('etaLabel');
  if (etaEl) {
    const span = etaEl.querySelector('span') || etaEl;
    span.textContent = 'Restante: Calculando...';
  }

  if (wiz.scheduler_enabled) {
    showModalAlert(
      'Inicio Manual Bloqueado',
      `No se permite iniciar manualmente mientras la programación horaria automática esté activa (${wiz.scheduler_range || 'diario'}). Desactive la casilla de ejecución diaria en el panel inferior para ejecutar manualmente.`,
      'warning'
    );
    return;
  }

  updateStartButtonState(true);
  document.getElementById('btnStop').disabled  = false;
  const btnStopSync = document.getElementById('btnStopSync');
  if (btnStopSync) btnStopSync.disabled = false;

  const body = {
    schema_name:  wiz.schema,
    table_name:   wiz.table,
    id_col:       wiz.id_col,
    address_col:  wiz.addr_col,
    batch_size:   batch,
    num_workers:  num_workers,
    filter_mode:  filter,
    require_ai:   require_ai,
    limit,
    source_mode:  wiz.source_mode || "central_tb_direccion",
  };

  try {
    const res  = await fetch('/api/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();

    if (!res.ok) {
      showModalAlert('Error al Iniciar Proceso', data.detail || 'Error desconocido', 'error');
      updateStartButtonState(false);
      document.getElementById('btnStop').disabled  = true;
      if (btnStopSync) btnStopSync.disabled = true;
    } else {
      const banner = document.getElementById('bannerActiveSession');
      if (banner) banner.classList.remove('hidden');
      [1, 2, 3, 4, 5].forEach(i => document.getElementById(`tab${i}`)?.classList.add('locked'));
    }
  } catch (e) {
    showModalAlert('Error de Comunicación', e.message, 'error');
    updateStartButtonState(false);
    document.getElementById('btnStop').disabled  = true;
    if (btnStopSync) btnStopSync.disabled = true;
  }
}

async function stopETL() {
  stopLiveTicker();
  document.getElementById('btnStop').disabled = true;
  const btnStopSync = document.getElementById('btnStopSync');
  if (btnStopSync) btnStopSync.disabled = true;
  try {
    await fetch('/api/stop', { method: 'POST' });
  } catch (_) {}
}

function onDone(data) {
  stopLiveTicker();
  const etaEl = document.getElementById('etaLabel');
  if (etaEl) {
    const span = etaEl.querySelector('span') || etaEl;
    span.textContent = 'Completado';
  }
  updateStartButtonState(false);
  document.getElementById('btnStop').disabled  = true;
  const btnStopSync = document.getElementById('btnStopSync');
  if (btnStopSync) btnStopSync.disabled = true;
  document.getElementById('statusLabel').textContent = 'Proceso completado';
  const dot = document.getElementById('termLiveDot');
  if (dot) dot.style.background = 'var(--slate-400)';
  const banner = document.getElementById('bannerActiveSession');
  if (banner) banner.classList.add('hidden');
  [1, 2, 3, 4, 5].forEach(i => {
    if (i <= wiz.maxStepUnlocked) document.getElementById(`tab${i}`)?.classList.remove('locked');
  });
}

function onError(data) {
  stopLiveTicker();
  const etaEl = document.getElementById('etaLabel');
  if (etaEl) {
    const span = etaEl.querySelector('span') || etaEl;
    span.textContent = 'Interrumpido';
  }
  updateStartButtonState(false);
  document.getElementById('btnStop').disabled  = true;
  const btnStopSync = document.getElementById('btnStopSync');
  if (btnStopSync) btnStopSync.disabled = true;
  document.getElementById('statusLabel').textContent = 'Error en el proceso';
  const dot = document.getElementById('termLiveDot');
  if (dot) dot.style.background = 'var(--red)';
  const banner = document.getElementById('bannerActiveSession');
  if (banner) banner.classList.add('hidden');
  [1, 2, 3, 4, 5].forEach(i => {
    if (i <= wiz.maxStepUnlocked) document.getElementById(`tab${i}`)?.classList.remove('locked');
  });
}

// ── Control Institucional de Apagado de Servicio ───────────────────────────
function confirmShutdown() {
  const isRunning = !document.getElementById('btnStop')?.disabled;
  const warn = document.getElementById('shutdownWarningText');
  const title = document.getElementById('shutdownModalTitle');
  const footer = document.getElementById('shutdownModalFooter');

  if (title) title.textContent = '¿Desea apagar el servicio?';
  if (footer) footer.style.display = 'flex';

  if (warn) {
    if (isRunning) {
      warn.innerHTML = '<span style="color:var(--red); font-weight:700;">Aviso: Se está ejecutando un proceso de normalización actualmente.</span><br><br>Al confirmar, <strong>se detendrá de forma segura el proceso</strong> y <strong>se finalizará el servicio local (equivalente a Ctrl + C en la terminal)</strong>.';
    } else {
      warn.innerHTML = 'Esta acción detendrá de forma segura el servidor local de la aplicación (equivalente a presionar <strong>Ctrl + C</strong> en la terminal). ¿Confirma que desea cerrar el servicio?';
    }
  }

  const overlay = document.getElementById('modalShutdownOverlay');
  if (overlay) overlay.classList.remove('hidden');
}

function closeShutdownModal() {
  const overlay = document.getElementById('modalShutdownOverlay');
  if (overlay) overlay.classList.add('hidden');
}

async function executeShutdown() {
  const footer = document.getElementById('shutdownModalFooter');
  const body = document.getElementById('shutdownModalBody');
  const title = document.getElementById('shutdownModalTitle');
  const btnConfirm = document.getElementById('btnConfirmShutdown');

  if (btnConfirm) btnConfirm.disabled = true;
  if (footer) footer.style.display = 'none';
  if (title) title.textContent = 'Apagando servicio local...';

  if (body) {
    body.innerHTML = `
      <div style="text-align:center; padding:18px 0;">
        <div class="spinner" style="border-color:var(--slate-300); border-top-color:var(--red); width:32px; height:32px; margin:0 auto 14px auto;"></div>
        <p style="font-weight:700; color:var(--slate-800); font-size:14px; margin-bottom:4px;">Cerrando conexiones y liberando recursos...</p>
        <p style="font-size:12px; color:var(--slate-500);">Finalizando el servidor local de la aplicación.</p>
      </div>
    `;
  }

  try {
    await fetch('/api/shutdown', { method: 'POST' });
  } catch (_) {
    // Si la conexión finaliza de inmediato, es el resultado previsto del shutdown
  }

  setTimeout(() => {
    if (title) title.textContent = 'Servicio Apagado';
    if (body) {
      body.innerHTML = `
        <div style="text-align:center; padding:12px 0;">
          <div style="width:48px; height:48px; border-radius:50%; background:var(--green-bg); color:var(--green); border:1px solid var(--green-border); display:flex; align-items:center; justify-content:center; margin:0 auto 12px auto;">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
          </div>
          <p style="font-size:15px; font-weight:700; color:var(--slate-900); margin-bottom:6px;">
            El servidor local se ha detenido correctamente.
          </p>
          <p style="font-size:13px; color:var(--slate-600); margin-bottom:18px;">
            La aplicación ha cerrado sus conexiones de forma segura. Ya puede cerrar esta ventana del navegador.
          </p>
          <button class="btn btn-ghost" onclick="window.close()" style="font-weight:600; padding:8px 18px;">
            Cerrar Ventana
          </button>
        </div>
      `;
    }
  }, 900);
}

// ── Sincronización Multi-Sesión en Tiempo Real ───────────────────────────────
async function checkInitialServerState() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) {
      goStep(1);
      return;
    }
    const data = await res.json();

    // 1. Pre-cargar defaults de configuración si están disponibles
    if (data.defaults) {
      const dbHostInput = document.getElementById('db_host');
      const dbPortInput = document.getElementById('db_port');
      const dbNameInput = document.getElementById('db_name');
      const dbUserInput = document.getElementById('db_user');
      const aiHostInput = document.getElementById('ai_host');
      const aiPortInput = document.getElementById('ai_port');

      if (dbHostInput && !dbHostInput.value) dbHostInput.value = data.defaults.db_host || 'localhost';
      if (dbPortInput && !dbPortInput.value) dbPortInput.value = data.defaults.db_port || 5432;
      if (dbNameInput && !dbNameInput.value) dbNameInput.value = data.defaults.db_name || 'bd_mpch';
      if (dbUserInput && !dbUserInput.value) dbUserInput.value = data.defaults.db_user || 'postgres';
      if (aiHostInput && !aiHostInput.value) aiHostInput.value = data.defaults.ai_host || 'localhost';
      if (aiPortInput && !aiPortInput.value) aiPortInput.value = data.defaults.ai_port || 11434;

      wiz.db_host = dbHostInput?.value || 'localhost';
      wiz.db_port = parseInt(dbPortInput?.value) || 5432;
      wiz.db_name = dbNameInput?.value || 'bd_mpch';
      wiz.db_user = dbUserInput?.value || 'postgres';
      wiz.ai_host = aiHostInput?.value || 'localhost';
      wiz.ai_port = parseInt(aiPortInput?.value) || 11434;
    }

    // Scheduler pre-cargado desde status
    if (data.scheduler) {
      updateSchedulerUI(data.scheduler);
    }
    updateStartButtonState(data.is_running);

    // 2. Pre-cargar estado verificado de IA si el servidor reporta conexión positiva
    if (data.ai && data.ai.connected) {
      const activeMdl = data.active_model || data.defaults?.ai_model;
      if (activeMdl) {
        wiz.aiVerified = true;
        wiz.ai_model = activeMdl;
        wiz.maxStepUnlocked = Math.max(wiz.maxStepUnlocked, 2);

        const sel = document.getElementById('ai_model_select');
        if (sel) {
          let found = false;
          for (let opt of sel.options) {
            if (opt.value === activeMdl) { opt.selected = true; found = true; break; }
          }
          if (!found) {
            const opt = new Option(`${activeMdl} (Activo en servidor)`, activeMdl, true, true);
            sel.add(opt, sel.options[0]);
          }
        }

        const btnGo2 = document.getElementById('btnGoStep2');
        if (btnGo2) btnGo2.disabled = false;
        document.getElementById('tab2')?.classList.remove('locked');
        showDiag('diagAI', 'ok', 'Motor IA Verificado y Activo', `Conectado exitosamente con Ollama usando el modelo <strong>${escapeHtml(activeMdl)}</strong>.`);
      }
    }

    // 3. Pre-cargar estado verificado de BD si el servidor reporta conexión positiva
    if (data.db && data.db.connected) {
      wiz.dbVerified = true;
      wiz.maxStepUnlocked = Math.max(wiz.maxStepUnlocked, 3);
      wiz.availableSchemas = data.available_schemas || ['public'];
      renderSchemaCards(wiz.availableSchemas);
      updateSchemaCountBadge(wiz.availableSchemas.length, wiz.availableSchemas.length);

      const btnGo3 = document.getElementById('btnGoStep3');
      if (btnGo3) btnGo3.disabled = false;
      document.getElementById('tab3')?.classList.remove('locked');
      showDiag('diagDB', 'ok', 'Conexión a Base de Datos Detectada', `Servidor PostgreSQL activo. ${wiz.availableSchemas.length} esquema(s) disponible(s).`);

      if (data.central_catalog) {
        updateCentralResumeUI(data.central_catalog);
      }
    }

    // 4. Si hay sesión activa o completada, sincronizar con paso 5
    if (data.is_running || data.running) {
      syncWithActiveSession(data);
      return;
    } else if (data.has_completed_session || (data.stats && data.stats.status === 'FINISHED' && data.recent_records && data.recent_records.length > 0)) {
      syncWithCompletedSession(data);
      return;
    }
  } catch (e) {
    console.warn('Aviso al verificar estado inicial del servidor:', e);
  }
  goStep(1);
}

function syncWithActiveSession(data) {
  wiz.maxStepUnlocked = 4;
  wiz.schema = data.active_schema || wiz.schema || 'public';
  wiz.table  = data.active_table  || wiz.table  || 'direcciones_actual';
  wiz.id_col = data.id_col || wiz.id_col || 'id_licencia';
  wiz.addr_col = data.address_col || wiz.addr_col || 'emp_direccion';
  wiz.ai_model = data.active_model || (data.ai ? data.ai.model : 'Ollama');
  wiz.num_workers = data.num_workers || 4;

  syncNumWorkers(wiz.num_workers);

  const elSchema = document.getElementById('summSchema');
  const elTable = document.getElementById('summTable');
  const elId = document.getElementById('summId');
  const elAddr = document.getElementById('summAddr');
  const elAiModel = document.getElementById('summAiModel');
  const elAiHost = document.getElementById('summAiHost');

  if (elSchema) elSchema.textContent = wiz.schema;
  if (elTable) elTable.textContent = wiz.table;
  if (elId) elId.textContent = wiz.id_col;
  if (elAddr) elAddr.textContent = wiz.addr_col;
  if (elAiModel) elAiModel.textContent = `Extractor: ${wiz.ai_model}`;
  if (elAiHost && data.ai && data.ai.base_url) elAiHost.textContent = data.ai.base_url;

  goStep(4);

  // Bloquear navegación a pasos de configuración durante la ejecución activa
  [1, 2, 3].forEach(i => {
    document.getElementById(`tab${i}`)?.classList.add('locked');
  });

  const banner = document.getElementById('bannerActiveSession');
  if (banner) {
    banner.classList.remove('hidden');
    const bTitle = document.getElementById('bannerActiveTitle');
    const bDesc = document.getElementById('bannerActiveDesc');
    if (bTitle) bTitle.textContent = `Proceso en ejecución en segundo plano [${wiz.schema}.${wiz.table}]`;
    if (bDesc) bDesc.textContent = `Esta sesión está sincronizada en tiempo real con el servidor (${wiz.num_workers} instancias IA en paralelo). Puede monitorear o detener el proceso.`;
  }

  updateStartButtonState(true);
  const btnStop = document.getElementById('btnStop');
  const btnStopSync = document.getElementById('btnStopSync');
  if (btnStop) btnStop.disabled = false;
  if (btnStopSync) btnStopSync.disabled = false;

  if (data.stats) updateStats(data.stats);
  if (data.recent_records && data.recent_records.length > 0 && wiz.allRecords.length === 0) {
    data.recent_records.forEach(r => addRecord(r, false));
    filterInspectorRecords();
  }

  connectSSE();
}

function syncWithCompletedSession(data) {
  wiz.maxStepUnlocked = 4;
  wiz.schema = data.active_schema || wiz.schema || 'public';
  wiz.table  = data.active_table  || wiz.table  || 'direcciones_actual';
  wiz.id_col = data.id_col || wiz.id_col || 'id_licencia';
  wiz.addr_col = data.address_col || wiz.addr_col || 'emp_direccion';
  wiz.ai_model = data.active_model || (data.ai ? data.ai.model : 'Ollama');
  wiz.num_workers = data.num_workers || 4;

  syncNumWorkers(wiz.num_workers);

  const elSchema = document.getElementById('summSchema');
  const elTable = document.getElementById('summTable');
  const elId = document.getElementById('summId');
  const elAddr = document.getElementById('summAddr');
  const elAiModel = document.getElementById('summAiModel');

  if (elSchema) elSchema.textContent = wiz.schema;
  if (elTable) elTable.textContent = wiz.table;
  if (elId) elId.textContent = wiz.id_col;
  if (elAddr) elAddr.textContent = wiz.addr_col;
  if (elAiModel) elAiModel.textContent = `Extractor: ${wiz.ai_model}`;

  goStep(4);

  updateStartButtonState(false);
  const btnStop = document.getElementById('btnStop');
  if (btnStop) btnStop.disabled = true;

  if (data.stats) updateStats(data.stats);
  if (data.recent_records && data.recent_records.length > 0 && wiz.allRecords.length === 0) {
    data.recent_records.forEach(r => addRecord(r, false));
    filterInspectorRecords();
  }

  connectSSE();
}

function resetToNewSession() {
  if (!document.getElementById('btnStop')?.disabled) {
    showModalAlert('Proceso Activo', 'No puede iniciar una nueva configuración mientras haya un proceso en ejecución. Deténgalo primero.', 'warning');
    return;
  }
  wiz.maxStepUnlocked = 1;
  [1, 2, 3, 4, 5].forEach(i => {
    const tab = document.getElementById(`tab${i}`);
    if (tab) {
      tab.classList.remove('done', 'active');
      if (i > 1) tab.classList.add('locked');
      else tab.classList.remove('locked');
    }
  });
  goStep(1);
}

// ── Funciones de Programación Horaria Diaria (Scheduler) ───────────────────
async function loadSchedulerConfig() {
  try {
    const res = await fetch('/api/scheduler/config');
    if (!res.ok) return;
    const cfg = await res.json();
    updateSchedulerUI(cfg);
  } catch (err) {
    console.error('Error al cargar configuración de scheduler:', err);
  }
}

function updateSchedulerUI(cfg) {
  if (!cfg) return;
  const data = cfg.config || cfg;
  const chk = document.getElementById('chkSchedulerEnabled');
  const inpTime = document.getElementById('inpSchedulerTime');
  const inpEndTime = document.getElementById('inpSchedulerEndTime');
  const inpWorkers = document.getElementById('inpSchedulerWorkers');
  const badge = document.getElementById('schedulerBadgeStatus');
  const countdown = document.getElementById('schedulerCountdownText');
  const winStatusEl = document.getElementById('schedulerWindowStatusText');

  const isEnabled = Boolean(data.enabled);
  const timeVal = data.scheduled_time || data.time_str || '23:00';
  const endTimeVal = data.end_time || data.end_time_str || '';
  const nextRun = data.next_run || data.next_run_at;

  wiz.scheduler_enabled = isEnabled;
  wiz.scheduler_range = data.range_human || (endTimeVal ? `${timeVal} a ${endTimeVal}` : timeVal);

  if (chk) chk.checked = isEnabled;
  if (inpTime) inpTime.value = timeVal;
  if (inpEndTime) inpEndTime.value = endTimeVal;
  if (inpWorkers && data.num_workers) inpWorkers.value = data.num_workers;

  toggleSchedulerUI(isEnabled);
  updateStartButtonState();

  if (data.timezone) {
    startDeviceClock(data.timezone.description || data.timezone.tz_name);
  } else {
    startDeviceClock();
  }

  if (winStatusEl) {
    if (!isEnabled) {
      winStatusEl.textContent = 'Inactivo';
      winStatusEl.style.color = 'var(--slate-500)';
    } else if (data.is_in_window) {
      winStatusEl.textContent = '🟢 Dentro de ventana de ejecución activa';
      winStatusEl.style.color = '#15803d';
    } else {
      winStatusEl.textContent = '⚪ Fuera de ventana (esperando inicio programado)';
      winStatusEl.style.color = '#b45309';
    }
  }

  if (badge) {
    if (isEnabled) {
      badge.textContent = 'Programado Activo';
      badge.style.background = '#dcfce7';
      badge.style.color = '#166534';
      badge.style.borderColor = '#86efac';
    } else {
      badge.textContent = 'Inactivo';
      badge.style.background = '#f1f5f9';
      badge.style.color = '#475569';
      badge.style.borderColor = '#cbd5e1';
    }
  }

  if (countdown) {
    if (isEnabled) {
      if (data.is_in_window) {
        const untilEnd = endTimeVal ? ` (cierre: ${endTimeVal} hrs)` : '';
        countdown.textContent = `⚡ Ejecución desatendida en curso dentro del horario permitido${untilEnd}`;
      } else if (nextRun) {
        const nextDate = new Date(nextRun);
        const remaining = data.countdown_human ? ` (${data.countdown_human})` : '';
        const endLabel = endTimeVal ? ` – ${endTimeVal} hrs` : '';
        countdown.textContent = `Próxima ejecución: ${nextDate.toLocaleDateString()} a las ${timeVal}${endLabel}${remaining}`;
      } else {
        countdown.textContent = '';
      }
    } else {
      countdown.textContent = '';
    }
  }
}

function toggleSchedulerUI(enabled) {
  const inpTime = document.getElementById('inpSchedulerTime');
  const inpEndTime = document.getElementById('inpSchedulerEndTime');
  const inpWorkers = document.getElementById('inpSchedulerWorkers');
  const badge = document.getElementById('schedulerBadgeStatus');
  if (inpTime) inpTime.disabled = !enabled;
  if (inpEndTime) inpEndTime.disabled = !enabled;
  if (inpWorkers) inpWorkers.disabled = !enabled;
  if (badge && !enabled) {
    badge.textContent = 'Inactivo';
    badge.style.background = '#f1f5f9';
    badge.style.color = '#475569';
    badge.style.borderColor = '#cbd5e1';
  }
}

async function saveSchedulerSettings() {
  const chk = document.getElementById('chkSchedulerEnabled');
  const inpTime = document.getElementById('inpSchedulerTime');
  const inpWorkers = document.getElementById('inpSchedulerWorkers');
  const btn = document.getElementById('btnSaveScheduler');

  const enabled = chk ? chk.checked : false;
  const scheduledTime = inpTime ? inpTime.value : '23:00';
  const inpEndTime = document.getElementById('inpSchedulerEndTime');
  const endTimeStr = inpEndTime && inpEndTime.value ? inpEndTime.value : null;
  const numWorkers = inpWorkers ? parseInt(inpWorkers.value, 10) || 2 : 2;

  const payload = {
    enabled: enabled,
    scheduled_time: scheduledTime,
    end_time_str: endTimeStr,
    num_workers: numWorkers,
    target_schema: wiz.schema || 'public',
    target_table: wiz.table || 'tb_direccion',
    source_mode: wiz.source_mode || 'central_tb_direccion',
    id_col: wiz.id_col || 'dire_id',
    addr_col: wiz.addr_col || 'dire_nom_via'
  };

  try {
    if (btn) btn.disabled = true;
    const res = await fetch('/api/scheduler/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const err = await res.json();
      showModalAlert('Error en Programación', err.detail || 'No se pudo guardar la configuración', 'error');
      return;
    }
    const updated = await res.json();
    wiz.scheduler_enabled = enabled;
    wiz.scheduler_range = enabled ? (endTimeStr ? `${scheduledTime} a ${endTimeStr}` : scheduledTime) : '';
    updateSchedulerUI(updated);
    updateStartButtonState();
    const rangeLabel = enabled ? 'Activada: ' + scheduledTime + ' hrs' + (endTimeStr ? ' – ' + endTimeStr + ' hrs' : '') : 'Desactivada';
    const actionHint = enabled
      ? ' El botón "Iniciar Normalización" ha sido bloqueado para respetar la ejecución automática.'
      : ' El botón "Iniciar Normalización" ha sido habilitado para ejecución manual.';
    showModalAlert('Horario Guardado', `Programación guardada exitosamente: ${rangeLabel}.${actionHint}`, 'success');
  } catch (err) {
    showModalAlert('Error de Conexión', 'No se pudo comunicar con el servidor para guardar la programación.', 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function triggerSchedulerNow() {
  const btn = document.getElementById('btnTestTriggerScheduler');
  try {
    if (btn) btn.disabled = true;
    const res = await fetch('/api/scheduler/trigger-now', {
      method: 'POST'
    });
    const data = await res.json();
    if (!res.ok) {
      showModalAlert('Aviso', data.detail || 'No se pudo disparar la ejecución', 'warning');
      return;
    }
    showModalAlert('Ejecución Disparada', data.message || 'Se ha iniciado el proceso desatendido en segundo plano.', 'success');
  } catch (err) {
    showModalAlert('Error', 'No se pudo contactar al servidor para disparar la prueba.', 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Inicialización al Cargar ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  syncNumWorkers(wiz.num_workers);
  startDeviceClock();
  loadSchedulerConfig();
  checkInitialServerState();
});
