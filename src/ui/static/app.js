/**
 * app.js — Lógica y Flujo Interactivo del Asistente Catastral MPCH
 * Identidad Visual y Experiencia de Usuario (UI/UX) Institucional
 * Flujo:
 * 1. Conexión IA (Ollama) -> 2. Conexión BD -> 3. Esquema -> 4. Tabla y Mapeo -> 5. Inspector Catastral
 */

// ── Estado Global del Asistente ──────────────────────────────────────────────
const wiz = {
  step: 1,
  maxStepUnlocked: 1,

  // Paso 1: IA
  ai_host: 'localhost',
  ai_port: 11434,
  ai_model: '',
  aiVerified: false,

  // Paso 2: BD
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

  // Paso 5: Inspector en Tiempo Real
  allRecords: [],
  autoScroll: true,
  searchInspector: '',
  inspectorStatus: 'all',  // 'all' | 'valid' | 'observed' | 'error'
  inspectorMotor: 'all',   // 'all' | 'ia' | 'hibrido' | 'heuristico'
  counts: { all: 0, valid: 0, observed: 0, error: 0 },
  evtSource: null,
};

// ── Navegación e Interactividad del Stepper ──────────────────────────────────
function tryGoStep(n) {
  if (n <= wiz.maxStepUnlocked) {
    goStep(n);
  }
}

function goStep(n) {
  [1, 2, 3, 4, 5].forEach(i => {
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

  setLoading('btnConnectAI', 'spinConnectAI', true);

  try {
    const res = await fetch('/api/connect-ai', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host, port, model }),
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

    renderSchemaCards(wiz.availableSchemas);

    const btnNext = document.getElementById('btnGoStep3');
    if (btnNext) btnNext.disabled = false;

    // Desbloquear tab 3
    const tab3 = document.getElementById('tab3');
    if (tab3) tab3.classList.remove('locked');

    showDiag(
      'diagDB',
      'ok',
      'Conexión Establecida con Éxito',
      `Conectado a la base de datos <strong>${escapeHtml(dbname)}</strong> en ${escapeHtml(host)}:${port}.`,
      `Esquemas detectados: <strong>${wiz.availableSchemas.length}</strong> disponible(s). Presione "Continuar a Esquemas" para seleccionarlo.`
    );

  } catch (e) {
    wiz.dbVerified = false;
    document.getElementById('btnGoStep3').disabled = true;
    showDiag('diagDB', 'error', 'Error de Red PostgreSQL', `No fue posible conectar con el servidor: ${e.message}`);
  } finally {
    setLoading('btnConnectDB', 'spinConnectDB', false);
  }
}

// ── PASO 3: Selección de Esquema ────────────────────────────────────────────
function renderSchemaCards(schemas) {
  const grid = document.getElementById('schemaCards');
  if (!grid) return;
  grid.innerHTML = '';

  if (!schemas || !schemas.length) {
    grid.innerHTML = '<p style="color:var(--slate-500); font-size:13px;">No se encontraron esquemas disponibles en la base de datos.</p>';
    return;
  }

  schemas.forEach(s => {
    const card = document.createElement('div');
    card.className = 'card-item';
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
      alert('Error al inspeccionar el esquema: ' + (data.detail || 'Error desconocido'));
      return;
    }

    wiz.availableTables = data.tables || [];
    renderTableCards(wiz.availableTables);
    document.getElementById('labelSchema').textContent = wiz.schema;

    wiz.maxStepUnlocked = Math.max(wiz.maxStepUnlocked, 4);
    const tab4 = document.getElementById('tab4');
    if (tab4) tab4.classList.remove('locked');

    goStep(4);

  } catch (e) {
    alert('Error de red al consultar tablas: ' + e.message);
  } finally {
    setLoading('btnSchema', 'spinSchema', false);
  }
}

// ── PASO 4: Tablas y Mapeo de Columnas ───────────────────────────────────────
function filterTableCards() {
  const query = (document.getElementById('searchTable')?.value || '').toLowerCase().trim();
  const filtered = wiz.availableTables.filter(t => t.name.toLowerCase().includes(query));
  renderTableCards(filtered);
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

  // Sugerencias de coincidencia inteligente
  const idHints   = ['id', 'id_', '_id', 'codigo', 'cod', 'pk', 'licencia', 'nro', 'correlativo'];
  const addrHints = ['direccion', 'dir', 'address', 'emp_', 'domicilio', 'ubica'];

  const bestId = tableInfo.columns.find(c =>
    idHints.some(h => c.name.toLowerCase().includes(h))
  );
  const bestAddr = tableInfo.columns.find(c =>
    addrHints.some(h => c.name.toLowerCase().includes(h))
  );

  if (bestId)   selId.value   = bestId.name;
  if (bestAddr) selAddr.value = bestAddr.name;

  document.getElementById('previewSection').classList.add('hidden');
  document.getElementById('btnConfirmTable').disabled = true;
}

async function previewTable() {
  const id_col   = document.getElementById('sel_id_col').value;
  const addr_col = document.getElementById('sel_addr_col').value;

  if (!id_col || !addr_col) {
    alert('Debe seleccionar la columna identificador único (ID) y la columna de dirección.');
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
      alert('Error al obtener vista previa: ' + (data.detail || 'Error desconocido'));
      return;
    }

    wiz.id_col   = data.id_col;
    wiz.addr_col = data.address_col;

    const countDiv = document.getElementById('tableCountInfo');
    const c = data.counts || {};
    countDiv.innerHTML = `
      <span class="badge" style="background:var(--slate-100); color:var(--slate-800); border:1px solid var(--slate-300);"><strong>${(c.total||0).toLocaleString()}</strong> Total</span>
      <span class="badge" style="background:var(--blue-accent-bg); color:var(--blue-accent); border:1px solid var(--blue-accent-border);"><strong>${(c.pendientes||0).toLocaleString()}</strong> Pendientes</span>
      <span class="badge badge-valid"><strong>${(c.validos||0).toLocaleString()}</strong> Normalizados</span>
      <span class="badge badge-observed"><strong>${(c.observados||0).toLocaleString()}</strong> Observados</span>
    `;

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
    document.getElementById('btnConfirmTable').disabled = false;

  } catch (e) {
    alert('Error de red al previsualizar tabla: ' + e.message);
  } finally {
    setLoading('btnPreview', 'spinPreview', false);
  }
}

function confirmTable() {
  if (!wiz.table || !wiz.id_col || !wiz.addr_col) return;

  document.getElementById('summSchema').textContent  = wiz.schema;
  document.getElementById('summTable').textContent   = wiz.table;
  document.getElementById('summId').textContent      = wiz.id_col;
  document.getElementById('summAddr').textContent    = wiz.addr_col;

  const elAiModel = document.getElementById('summAiModel');
  if (elAiModel) elAiModel.textContent = wiz.ai_model || 'Ollama';
  const elAiHost = document.getElementById('summAiHost');
  if (elAiHost) elAiHost.textContent = `http://${wiz.ai_host}:${wiz.ai_port}`;

  wiz.maxStepUnlocked = Math.max(wiz.maxStepUnlocked, 5);
  const tab5 = document.getElementById('tab5');
  if (tab5) tab5.classList.remove('locked');

  goStep(5);
  initStep5();
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

    if (badge) {
      if (isAiActive && activeModel) {
        badge.innerHTML = `<span class="badge badge-valid"><span class="dot-live"></span>IA Conectada — ${escapeHtml(activeModel)}</span>`;
      } else {
        badge.innerHTML = `<span class="badge badge-error">IA No Disponible</span>`;
      }
    }

    if (data.recent_records && data.recent_records.length > 0 && wiz.allRecords.length === 0) {
      data.recent_records.forEach(r => addRecord(r, false));
      filterInspectorRecords();
    }
    if (data.stats) updateStats(data.stats);
  } catch (_) {}

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
  }
}

function updateStats(s) {
  kpi('kpiProcessed', s.processed);
  kpi('kpiValid',     s.valid);
  kpi('kpiObserved',  s.observed);
  kpi('kpiFailed',    s.failed);

  const pct   = s.progress_pct || 0;
  const total = s.total_to_process || 0;
  const proc  = s.processed || 0;
  const secs  = s.elapsed_seconds || 0;

  document.getElementById('progressFill').style.width = pct + '%';
  document.getElementById('progressLabel').textContent =
    `${proc.toLocaleString()} de ${total.toLocaleString()} registros (${pct}%)`;

  if (secs > 0) {
    const m = Math.floor(secs / 60);
    const s2 = Math.floor(secs % 60);
    document.getElementById('elapsedLabel').textContent =
      `Tiempo: ${m > 0 ? m + 'm ' : ''}${s2}s`;
  }

  const status = s.status || 'IDLE';
  const labels = {
    RUNNING: 'Ejecutando proceso de normalización...',
    IDLE: 'Listo para iniciar',
    FINISHED: 'Proceso completado',
    ERROR: 'Error en procesamiento'
  };
  document.getElementById('statusLabel').textContent = labels[status] || status;

  const dot = document.getElementById('termLiveDot');
  if (dot) {
    dot.className = status === 'RUNNING' ? 'dot-live' : '';
    dot.style.background = status === 'RUNNING' ? 'var(--green)' : 'var(--slate-400)';
  }
}

function addRecord(r, shouldScroll = true) {
  const normRec = {
    index:        r.index || (wiz.allRecords.length + 1),
    total:        r.total || 0,
    id_licencia:  r.id_licencia ?? r.id ?? '—',
    raw_text:     r.raw_text || r.original_address || r.emp_direccion || '',
    metodo:       r.metodo || r.method || 'IA',
    es_procesado: Boolean(r.es_procesado),
    observacion:  r.observacion || '',
    success:      r.success !== false,
    nom_via:      r.nom_via || '',
    num_via:      r.num_via || '',
    id_via:       r.id_via || null,
    tipo_via_name:r.tipo_via_name || r.tipo_via || '',
    nom_zona:     r.nom_zona || '',
    id_zona:      r.id_zona || null,
    tipo_zona_name:r.tipo_zona_name || r.tipo_zona || '',
    manzana:      r.manzana || '',
    lote:         r.lote || '',
    slote:        r.slote || '',
    referencia:   r.referencia || '',
    time:         new Date().toLocaleTimeString('es-PE', { hour12: false }),
    reprocesado:  false,
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
  if (!list) return;

  const q  = wiz.searchInspector;
  const st = wiz.inspectorStatus;
  const mt = wiz.inspectorMotor;

  const filtered = wiz.allRecords.filter(r => {
    if (q) {
      const matchId   = String(r.id_licencia).includes(q);
      const matchRaw  = (r.raw_text || '').toLowerCase().includes(q);
      const matchVia  = (r.nom_via || '').toLowerCase().includes(q);
      const matchZona = (r.nom_zona || '').toLowerCase().includes(q);
      const matchObs  = (r.observacion || '').toLowerCase().includes(q);
      if (!matchId && !matchRaw && !matchVia && !matchZona && !matchObs) return false;
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

  if (!filtered.length) {
    list.innerHTML = `<p style="text-align:center; color:var(--slate-400); padding:40px; font-size:13px;">No hay registros que coincidan con los filtros seleccionados.</p>`;
    return;
  }

  list.innerHTML = filtered.map(r => createConciseRecordCard(r)).join('');

  if (autoScroll && wiz.autoScroll) {
    list.scrollTop = 0;
  }
}

function createConciseRecordCard(r) {
  const isErr = !r.success || r.metodo === 'ERROR';
  const isObs = !r.es_procesado && !isErr;
  const cardClass = isErr ? 'card-error' : (isObs ? 'card-observed' : 'card-valid');

  // Badge de Estado Institucional (Sin Emojis)
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

  // Diagnóstico Catastral Sobrio
  let diagHtml = '';
  if (r.observacion) {
    const diagClass = isErr ? 'diag-err' : 'diag-obs';
    diagHtml = `
      <div class="record-diagnosis ${diagClass}">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <strong>Diagnóstico Catastral:</strong> <span>${escapeHtml(r.observacion)}</span>
      </div>`;
  }

  // Formato conciso de componentes
  const viaName = r.nom_via || 'Sin vía';
  const numVia = r.num_via ? `N° ${r.num_via}` : 'S/N';
  const viaChip = r.id_via ? `<span class="chip-id chip-via">ID: ${r.id_via}</span>` : '';

  const zonaName = r.nom_zona || 'Sin zona';
  const zonaChip = r.id_zona ? `<span class="chip-id chip-zona">ID: ${r.id_zona}</span>` : '';

  const catastroText = (r.manzana || r.lote)
    ? `Mz: ${r.manzana || '-'} | Lt: ${r.lote || '-'}${r.slote ? ' | Slt: ' + r.slote : ''}`
    : 'N/D';

  const refItem = r.referencia
    ? `<div class="breakdown-item"><span class="breakdown-lbl">Referencia</span> <span class="breakdown-val" style="color:var(--mpch-navy);">${escapeHtml(r.referencia)}</span></div>`
    : '';

  // Badge de Reintento / Actualización si aplica
  const reproBadge = r.reprocesado
    ? `<span class="badge" style="background:var(--slate-100); color:var(--mpch-navy); border:1px solid var(--slate-300); font-size:10px;">REPROCESADO</span>`
    : '';

  return `
    <div class="record-card ${cardClass}">
      <div class="record-header">
        <div class="record-meta">
          <span class="record-id-chip">ID: ${r.id_licencia}</span>
          <span class="record-index">#${r.index} de ${r.total || '?'}</span>
          ${statusBadge}
          ${motorBadge}
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

      <div class="record-breakdown">
        <div class="breakdown-item">
          <span class="breakdown-lbl">Vía</span>
          <span class="breakdown-val">${escapeHtml(r.tipo_via_name ? r.tipo_via_name + ' ' : '')}${escapeHtml(viaName)} ${escapeHtml(numVia)}</span>
          ${viaChip}
        </div>
        <div class="breakdown-item">
          <span class="breakdown-lbl">Zona</span>
          <span class="breakdown-val">${escapeHtml(r.tipo_zona_name ? r.tipo_zona_name + ' ' : '')}${escapeHtml(zonaName)}</span>
          ${zonaChip}
        </div>
        <div class="breakdown-item">
          <span class="breakdown-lbl">Catastro</span>
          <span class="breakdown-val">${escapeHtml(catastroText)}</span>
        </div>
        ${refItem}
      </div>

      ${diagHtml}
    </div>
  `;
}

function copySingleRecord(idLicencia) {
  const rec = wiz.allRecords.find(r => r.id_licencia == idLicencia);
  if (!rec) return;

  const viaDesc = `${rec.tipo_via_name ? rec.tipo_via_name + ' ' : ''}${rec.nom_via || ''} ${rec.num_via ? 'N° ' + rec.num_via : 'S/N'}`.trim();
  const zonaDesc = `${rec.tipo_zona_name ? rec.tipo_zona_name + ' ' : ''}${rec.nom_zona || ''}`.trim();
  const catText = (rec.manzana || rec.lote) ? `Mz: ${rec.manzana || '-'} | Lt: ${rec.lote || '-'}${rec.slote ? ' | Slt: ' + rec.slote : ''}` : '';
  const estado = (!rec.success || rec.metodo === 'ERROR') ? 'ERROR' : (rec.es_procesado ? 'NORMALIZADO' : 'OBSERVADO');

  const text = `ID: ${rec.id_licencia} | Entrada: "${rec.raw_text}" | Vía: ${viaDesc || 'N/D'} | Zona: ${zonaDesc || 'N/D'}${catText ? ' | ' + catText : ''} | Estado: ${estado}${rec.observacion ? ' | Diagnóstico: ' + rec.observacion : ''}`;
  navigator.clipboard.writeText(text);
}

async function exportRecordsExcel() {
  if (!wiz.allRecords || !wiz.allRecords.length) {
    alert('No hay registros disponibles en el Inspector para exportar.');
    return;
  }

  const btn = document.getElementById('btnExportExcel');
  const originalHtml = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `
      <div class="spinner" style="width:12px; height:12px; border-width:1.8px; margin-right:4px;"></div>
      <span>Generando Excel...</span>
    `;
  }

  try {
    const res = await fetch('/api/export-excel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ records: wiz.allRecords }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert('Error al generar Excel: ' + (err.detail || 'Error desconocido'));
      return;
    }

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const now = new Date();
    const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');
    const timeStr = now.toTimeString().slice(0, 8).replace(/:/g, '');
    a.href = url;
    a.download = `reporte_catastral_mpch_${dateStr}_${timeStr}.xlsx`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (e) {
    alert('Error descargando Excel: ' + e.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
  }
}

function exportRecordsCSV() {
  if (!wiz.allRecords || !wiz.allRecords.length) {
    alert('No hay registros disponibles en el Inspector para exportar.');
    return;
  }

  const headers = [
    'ID',
    'Direccion_Original',
    'Tipo_Via',
    'Nombre_Via',
    'Numero_Via',
    'ID_Via',
    'Tipo_Zona',
    'Nombre_Zona',
    'ID_Zona',
    'Manzana',
    'Lote',
    'Sublote',
    'Referencia',
    'Metodo_Normalizacion',
    'Estado',
    'Diagnostico_Observacion',
    'Hora_Proceso'
  ];

  function escapeCsv(val) {
    const s = String(val === undefined || val === null ? '' : val);
    if (s.includes('"') || s.includes(',') || s.includes('\n') || s.includes(';')) {
      return `"${s.replace(/"/g, '""')}"`;
    }
    return s;
  }

  const rows = wiz.allRecords.map(r => {
    const estado = (!r.success || r.metodo === 'ERROR')
      ? 'ERROR'
      : (r.es_procesado ? 'NORMALIZADO' : 'OBSERVADO');

    return [
      escapeCsv(r.id_licencia),
      escapeCsv(r.raw_text),
      escapeCsv(r.tipo_via_name),
      escapeCsv(r.nom_via),
      escapeCsv(r.num_via),
      escapeCsv(r.id_via),
      escapeCsv(r.tipo_zona_name),
      escapeCsv(r.nom_zona),
      escapeCsv(r.id_zona),
      escapeCsv(r.manzana),
      escapeCsv(r.lote),
      escapeCsv(r.slote),
      escapeCsv(r.referencia),
      escapeCsv(r.metodo),
      escapeCsv(estado),
      escapeCsv(r.observacion),
      escapeCsv(r.time)
    ].join(',');
  });

  const csvContent = '\uFEFF' + [headers.join(','), ...rows].join('\r\n');
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const now = new Date();
  const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');
  const timeStr = now.toTimeString().slice(0, 8).replace(/:/g, '');
  a.href = url;
  a.download = `reporte_catastral_mpch_${dateStr}_${timeStr}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
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
  const limit      = parseInt(document.getElementById('inp_limit').value) || null;
  const batch      = parseInt(document.getElementById('inp_batch').value) || 50;
  const filter     = document.getElementById('inp_filter').value || 'pending';
  const require_ai = document.getElementById('inp_require_ai')?.checked ?? true;

  // NO vaciar wiz.allRecords ni wiz.counts para preservar el historial acumulativo de la sesión

  document.getElementById('progressFill').style.width = '0%';
  document.getElementById('progressLabel').textContent = 'Preparando ejecución...';

  document.getElementById('btnStart').disabled = true;
  document.getElementById('btnStop').disabled  = false;

  const body = {
    schema_name:  wiz.schema,
    table_name:   wiz.table,
    id_col:       wiz.id_col,
    address_col:  wiz.addr_col,
    batch_size:   batch,
    filter_mode:  filter,
    require_ai:   require_ai,
    limit,
  };

  try {
    const res  = await fetch('/api/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();

    if (!res.ok) {
      alert('Error al iniciar el proceso: ' + (data.detail || 'Error desconocido'));
      document.getElementById('btnStart').disabled = false;
      document.getElementById('btnStop').disabled  = true;
    }
  } catch (e) {
    alert('Error de comunicación: ' + e.message);
    document.getElementById('btnStart').disabled = false;
    document.getElementById('btnStop').disabled  = true;
  }
}

async function stopETL() {
  document.getElementById('btnStop').disabled = true;
  try {
    await fetch('/api/stop', { method: 'POST' });
  } catch (_) {}
}

function onDone(data) {
  document.getElementById('btnStart').disabled = false;
  document.getElementById('btnStop').disabled  = true;
  document.getElementById('statusLabel').textContent = 'Proceso completado';
  const dot = document.getElementById('termLiveDot');
  if (dot) dot.style.background = 'var(--slate-400)';
}

function onError(data) {
  document.getElementById('btnStart').disabled = false;
  document.getElementById('btnStop').disabled  = true;
  document.getElementById('statusLabel').textContent = 'Error en el proceso';
  const dot = document.getElementById('termLiveDot');
  if (dot) dot.style.background = 'var(--red)';
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

// ── Inicialización al Cargar ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  goStep(1);
});
