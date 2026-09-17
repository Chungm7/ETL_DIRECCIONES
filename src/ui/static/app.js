/**
 * app.js — Lógica del wizard ETL MPCH
 * Flujo: Conexión → Esquema → Tabla → Ejecución ETL (SSE en tiempo real)
 */

// ── Estado del wizard ────────────────────────────────────────────────────────
const wiz = {
  step: 1,
  schema: null,
  table: null,
  id_col: null,
  addr_col: null,
  columns: [],
  allRecords: [],
  evtSource: null,
};

// ── Navegación entre pasos ───────────────────────────────────────────────────
function goStep(n) {
  // Ocultar todos los pasos
  [1, 2, 3, 4].forEach(i => {
    document.getElementById(`step${i}`).classList.add('hidden');
    const tab = document.getElementById(`tab${i}`);
    tab.classList.remove('active', 'done');
    if (i < n) tab.classList.add('done');
  });

  // Mostrar paso activo
  document.getElementById(`step${n}`).classList.remove('hidden');
  document.getElementById(`tab${n}`).classList.add('active');
  wiz.step = n;

  // Marcar completados
  for (let i = 1; i < n; i++) {
    document.getElementById(`tab${i}`).classList.add('done');
    document.getElementById(`tab${i}`).classList.remove('active');
  }

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function showAlert(containerId, msg, type = 'error') {
  const el = document.getElementById(containerId);
  if (!msg) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="alert alert-${type}">${msg}</div>`;
}

function setLoading(btnId, spinId, loading) {
  const btn = document.getElementById(btnId);
  const spin = document.getElementById(spinId);
  if (btn)  btn.disabled = loading;
  if (spin) spin.classList.toggle('hidden', !loading);
}

function kpi(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val !== undefined && val !== null ? val : 0;
}

// ── PASO 1: Conexión ─────────────────────────────────────────────────────────
async function connectDB() {
  showAlert('alertConnect', '');
  setLoading('btnConnect', 'spinConnect', true);

  const body = {
    host:     document.getElementById('db_host').value.trim() || 'localhost',
    port:     parseInt(document.getElementById('db_port').value) || 5432,
    dbname:   document.getElementById('db_name').value.trim() || 'bd_mpch',
    user:     document.getElementById('db_user').value.trim() || 'postgres',
    password: document.getElementById('db_pass').value,
  };

  try {
    const res = await fetch('/api/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();

    if (!res.ok) {
      showAlert('alertConnect', data.detail || 'No se pudo conectar.', 'error');
      return;
    }

    // Renderizar tarjetas de esquemas
    renderSchemaCards(data.schemas || []);
    showAlert('alertConnect', '');
    goStep(2);
    showAlert('alertSchema', `Conectado a <strong>${body.dbname}</strong> en ${body.host}:${body.port}. Seleccione un esquema.`, 'ok');

  } catch (e) {
    showAlert('alertConnect', `Error de red: ${e.message}`, 'error');
  } finally {
    setLoading('btnConnect', 'spinConnect', false);
  }
}

// ── PASO 2: Esquema ──────────────────────────────────────────────────────────
function renderSchemaCards(schemas) {
  const grid = document.getElementById('schemaCards');
  grid.innerHTML = '';

  if (!schemas.length) {
    grid.innerHTML = '<p style="color:var(--gray-lt); font-size:13px;">No se encontraron esquemas disponibles.</p>';
    return;
  }

  schemas.forEach(s => {
    const card = document.createElement('div');
    card.className = 'card-item';
    card.innerHTML = `
      <div class="card-name">${s}</div>
      <div class="card-meta">esquema PostgreSQL</div>
    `;
    card.onclick = () => {
      document.querySelectorAll('.card-item[data-schema]').forEach(c => c.classList.remove('selected'));
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
  showAlert('alertSchema', '');
  setLoading('btnSchema', 'spinSchema', true);

  try {
    const res = await fetch('/api/inspect-schema', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schema_name: wiz.schema }),
    });
    const data = await res.json();

    if (!res.ok) {
      showAlert('alertSchema', data.detail || 'Error inspeccionando el esquema.', 'error');
      return;
    }

    renderTableCards(data.tables || []);
    document.getElementById('labelSchema').textContent = wiz.schema;
    goStep(3);

  } catch (e) {
    showAlert('alertSchema', `Error de red: ${e.message}`, 'error');
  } finally {
    setLoading('btnSchema', 'spinSchema', false);
  }
}

// ── PASO 3: Tabla ────────────────────────────────────────────────────────────
function renderTableCards(tables) {
  const grid = document.getElementById('tableCards');
  grid.innerHTML = '';

  if (!tables.length) {
    grid.innerHTML = '<p style="color:var(--gray-lt); font-size:13px;">No se encontraron tablas en este esquema.</p>';
    return;
  }

  tables.forEach(t => {
    const card = document.createElement('div');
    card.className = 'card-item';
    card.innerHTML = `
      <div class="card-name">${t.name}</div>
      <div class="card-meta">${t.row_count >= 0 ? t.row_count.toLocaleString() + ' registros' : 'N/A'}</div>
      <div class="card-meta" style="margin-top:3px;">${t.columns.length} columnas</div>
    `;
    card.onclick = () => {
      document.querySelectorAll('.card-item[data-table]').forEach(c => c.classList.remove('selected'));
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

  // Rellenar selects de columnas
  const selId   = document.getElementById('sel_id_col');
  const selAddr = document.getElementById('sel_addr_col');
  selId.innerHTML = '';
  selAddr.innerHTML = '';

  tableInfo.columns.forEach(col => {
    const o1 = new Option(col.name + ' (' + col.type + ')', col.name);
    const o2 = new Option(col.name + ' (' + col.type + ')', col.name);
    selId.appendChild(o1);
    selAddr.appendChild(o2);
  });

  // Heurística: pre-seleccionar columnas probables
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

  // Ocultar preview anterior
  document.getElementById('previewSection').classList.add('hidden');
  document.getElementById('btnConfirmTable').disabled = true;
}

async function previewTable() {
  const id_col   = document.getElementById('sel_id_col').value;
  const addr_col = document.getElementById('sel_addr_col').value;

  if (!id_col || !addr_col) {
    showAlert('alertTable', 'Debe seleccionar la columna ID y la columna de dirección.', 'warn');
    return;
  }

  showAlert('alertTable', '');
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
      showAlert('alertTable', data.detail || 'Error al obtener vista previa.', 'error');
      return;
    }

    wiz.id_col   = data.id_col;
    wiz.addr_col = data.address_col;

    // Mostrar conteos
    const countDiv = document.getElementById('tableCountInfo');
    const c = data.counts || {};
    countDiv.innerHTML = `
      <span style="font-size:13px;"><strong>${(c.total||0).toLocaleString()}</strong> total</span>
      <span style="font-size:13px; color:var(--blue);"><strong>${(c.pendientes||0).toLocaleString()}</strong> pendientes</span>
      <span style="font-size:13px; color:var(--green);"><strong>${(c.validos||0).toLocaleString()}</strong> normalizados</span>
      <span style="font-size:13px; color:var(--amber);"><strong>${(c.observados||0).toLocaleString()}</strong> observados</span>
    `;

    // Rellenar tabla preview
    const tbody = document.getElementById('previewBody');
    tbody.innerHTML = '';
    (data.preview || []).forEach(row => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="font-family:monospace; color:var(--blue); font-weight:600;">${row.id ?? '—'}</td>
        <td>${row.direccion ?? '—'}</td>
      `;
      tbody.appendChild(tr);
    });

    document.getElementById('previewSection').classList.remove('hidden');
    document.getElementById('btnConfirmTable').disabled = false;

  } catch (e) {
    showAlert('alertTable', `Error de red: ${e.message}`, 'error');
  } finally {
    setLoading('btnPreview', 'spinPreview', false);
  }
}

function confirmTable() {
  if (!wiz.table || !wiz.id_col || !wiz.addr_col) return;

  // Actualizar resumen en paso 4
  document.getElementById('summSchema').textContent  = wiz.schema;
  document.getElementById('summTable').textContent   = wiz.table;
  document.getElementById('summId').textContent      = wiz.id_col;
  document.getElementById('summAddr').textContent    = wiz.addr_col;

  goStep(4);
  initStep4();
}

// ── PASO 4: Ejecución ────────────────────────────────────────────────────────
async function initStep4() {
  // Verificar estado IA
  try {
    const res  = await fetch('/api/status');
    const data = await res.json();
    const ai   = data.ai || {};
    const badge = document.getElementById('aiStatusBadge');
    if (ai.connected && ai.installed) {
      badge.innerHTML = `<span class="ai-badge ai-on"><span class="dot dot-green"></span>IA activa — ${ai.model}</span>`;
    } else {
      badge.innerHTML = `<span class="ai-badge ai-off"><span class="dot dot-red"></span>IA no disponible</span>`;
    }
  } catch (_) {}

  // Conectar SSE si no está conectado
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
    addLog('Conexión SSE interrumpida. Reconectando...', 'warn');
  };
}

function handleEvent(ev) {
  switch (ev.type) {
    case 'connected':
      addLog('Canal de eventos conectado.', 'info');
      break;
    case 'log':
      addLog(ev.payload);
      break;
    case 'stats':
      updateStats(ev.payload);
      break;
    case 'record':
      addRecord(ev.payload);
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
  const labels = { RUNNING: 'Ejecutando...', IDLE: 'En espera', FINISHED: 'Completado', ERROR: 'Error durante ejecución' };
  document.getElementById('statusLabel').textContent = labels[status] || status;
}

function addRecord(r) {
  wiz.allRecords.unshift(r);
  if (wiz.allRecords.length > 300) wiz.allRecords.pop();
  filterRecords();
}

function filterRecords() {
  const search  = (document.getElementById('searchRec')?.value || '').toLowerCase();
  const status  = document.getElementById('filterStatus')?.value || '';

  const filtered = wiz.allRecords.filter(r => {
    const orig = (r.original_address || '').toLowerCase();
    const norm = (r.normalized_address || '').toLowerCase();
    const matchSearch = !search || orig.includes(search) || norm.includes(search);

    let matchStatus = true;
    if (status === 'ok')  matchStatus = r.status === 'VALID' || r.status === 'OK';
    if (status === 'obs') matchStatus = r.status === 'OBSERVED' || r.is_observed;
    if (status === 'err') matchStatus = r.status === 'ERROR' || r.status === 'FAILED';

    return matchSearch && matchStatus;
  });

  renderRecords(filtered.slice(0, 100));
}

function renderRecords(records) {
  const list = document.getElementById('recordsList');
  if (!records.length) {
    list.innerHTML = '<p style="text-align:center; color:var(--gray-lt); padding:30px; font-size:13px;">Sin registros que mostrar.</p>';
    return;
  }

  list.innerHTML = records.map(r => {
    const st = (r.status || '').toUpperCase();
    const isObs = r.is_observed || st === 'OBSERVED';
    const isErr = st === 'ERROR' || st === 'FAILED';
    const isAI  = r.method === 'ai' || r.method === 'AI';

    let badgeClass = 'badge-ok';
    let badgeText  = 'OK';
    if (isErr) { badgeClass = 'badge-err'; badgeText = 'Error'; }
    else if (isObs) { badgeClass = 'badge-obs'; badgeText = 'Observado'; }

    const aiBadge = isAI ? `<span class="record-badge badge-ai" style="margin-left:4px;">IA</span>` : '';

    const orig  = r.original_address || r.address || '—';
    const norm  = r.normalized_address || '';
    const normLine = norm && norm !== orig
      ? `<div class="normalized">${norm}</div>`
      : '';

    return `
      <div class="record-row">
        <div>
          <span class="record-badge ${badgeClass}">${badgeText}</span>
          ${aiBadge}
        </div>
        <div class="record-text">
          <div class="orig">${escapeHtml(orig)}</div>
          ${normLine}
        </div>
      </div>`;
  }).join('');
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function addLog(msg, level = '') {
  const feed = document.getElementById('logFeed');
  if (!feed) return;

  const cls =
    level === 'warn' ? 'log-warn' :
    level === 'info' ? 'log-info' :
    msg.toLowerCase().includes('error') ? 'log-err' :
    msg.toLowerCase().includes('exitoso') || msg.toLowerCase().includes('completado') ? 'log-ok' :
    '';

  const time = new Date().toLocaleTimeString('es-PE', { hour12: false });
  const line = document.createElement('div');
  line.className = cls;
  line.textContent = `[${time}] ${msg}`;
  feed.appendChild(line);
  feed.scrollTop = feed.scrollHeight;
}

// ── Iniciar ETL ──────────────────────────────────────────────────────────────
async function startETL() {
  const limit      = parseInt(document.getElementById('inp_limit').value) || null;
  const batch      = parseInt(document.getElementById('inp_batch').value) || 50;
  const filter     = document.getElementById('inp_filter').value || 'pending';
  const require_ai = document.getElementById('inp_require_ai')?.checked ?? true;

  // Reset records y stats visuales
  wiz.allRecords = [];
  renderRecords([]);
  kpi('kpiProcessed', 0); kpi('kpiValid', 0);
  kpi('kpiObserved', 0);  kpi('kpiFailed', 0);
  document.getElementById('progressFill').style.width = '0%';
  document.getElementById('progressLabel').textContent = '0 de 0 registros';
  document.getElementById('logFeed').innerHTML = '';

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
      addLog('Error al iniciar: ' + (data.detail || 'Error desconocido'), 'warn');
      document.getElementById('btnStart').disabled = false;
      document.getElementById('btnStop').disabled  = true;
    } else {
      addLog('Pipeline iniciado correctamente.', 'info');
    }
  } catch (e) {
    addLog('Error de red: ' + e.message);
    document.getElementById('btnStart').disabled = false;
    document.getElementById('btnStop').disabled  = true;
  }
}

// ── Detener ETL ──────────────────────────────────────────────────────────────
async function stopETL() {
  document.getElementById('btnStop').disabled = true;
  addLog('Solicitando detención del pipeline...', 'warn');
  try {
    await fetch('/api/stop', { method: 'POST' });
  } catch (_) {}
}

// ── Callbacks de fin/error ───────────────────────────────────────────────────
function onDone(data) {
  document.getElementById('btnStart').disabled = false;
  document.getElementById('btnStop').disabled  = true;
  document.getElementById('statusLabel').textContent = 'Completado';
  addLog(`ETL completado. Procesados: ${data.processed_records ?? data.processed ?? 0} | Normalizados: ${data.valid_processed_records ?? data.valid ?? 0}`, '');
}

function onError(data) {
  document.getElementById('btnStart').disabled = false;
  document.getElementById('btnStop').disabled  = true;
  document.getElementById('statusLabel').textContent = 'Error';
  addLog('Error: ' + (data.error || 'Error desconocido'));
}
