/**
 * app.js — Lógica del wizard ETL MPCH
 * Flujo: Conexión → Esquema → Tabla → Ejecución ETL (SSE en tiempo real)
 * Con terminal interactivo estilo consola Rich e inspector detallado de registros.
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
  allLogs: [],
  viewMode: 'console',      // 'console' | 'inspector' | 'split'
  logFilter: 'all',         // 'all' | 'valid' | 'observed' | 'error'
  logFormat: 'rich',        // 'rich' | 'compact'
  autoScroll: true,
  searchInspector: '',
  inspectorStatus: 'all',
  inspectorMotor: 'all',
  counts: { all: 0, valid: 0, observed: 0, error: 0 },
  evtSource: null,
};

// ── Navegación entre pasos ───────────────────────────────────────────────────
function goStep(n) {
  [1, 2, 3, 4].forEach(i => {
    document.getElementById(`step${i}`).classList.add('hidden');
    const tab = document.getElementById(`tab${i}`);
    tab.classList.remove('active', 'done');
    if (i < n) tab.classList.add('done');
  });

  document.getElementById(`step${n}`).classList.remove('hidden');
  document.getElementById(`tab${n}`).classList.add('active');
  wiz.step = n;

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

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
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

    const countDiv = document.getElementById('tableCountInfo');
    const c = data.counts || {};
    countDiv.innerHTML = `
      <span style="font-size:13px;"><strong>${(c.total||0).toLocaleString()}</strong> total</span>
      <span style="font-size:13px; color:var(--blue);"><strong>${(c.pendientes||0).toLocaleString()}</strong> pendientes</span>
      <span style="font-size:13px; color:var(--green);"><strong>${(c.validos||0).toLocaleString()}</strong> normalizados</span>
      <span style="font-size:13px; color:var(--amber);"><strong>${(c.observados||0).toLocaleString()}</strong> observados</span>
    `;

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

  document.getElementById('summSchema').textContent  = wiz.schema;
  document.getElementById('summTable').textContent   = wiz.table;
  document.getElementById('summId').textContent      = wiz.id_col;
  document.getElementById('summAddr').textContent    = wiz.addr_col;

  goStep(4);
  initStep4();
}

// ── PASO 4: Ejecución y Visualización ─────────────────────────────────────────
async function initStep4() {
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

    // Si ya existen registros previos del servidor, inicializarlos
    if (data.recent_records && data.recent_records.length > 0 && wiz.allRecords.length === 0) {
      data.recent_records.forEach(r => addRecord(r, false));
      rebuildConsoleDisplay();
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
    addSystemLog('Conexión SSE interrumpida. Reconectando...', 'warn');
  };
}

function handleEvent(ev) {
  switch (ev.type) {
    case 'connected':
      addSystemLog('Canal de eventos en vivo conectado al servidor.', 'info');
      break;
    case 'log':
      if (typeof ev.payload === 'string') {
        addSystemLog(ev.payload);
      }
      break;
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
  const labels = { RUNNING: 'Ejecutando...', IDLE: 'En espera', FINISHED: 'Completado', ERROR: 'Error en proceso' };
  document.getElementById('statusLabel').textContent = labels[status] || status;

  const dot = document.getElementById('termLiveDot');
  if (dot) {
    dot.className = status === 'RUNNING' ? 'dot dot-green' : 'dot';
    dot.style.background = status === 'RUNNING' ? '#22c55e' : '#94a3b8';
  }
}

// ── Manejo de Modos de Vista ─────────────────────────────────────────────────
function setViewMode(mode) {
  wiz.viewMode = mode;
  const secConsole = document.getElementById('sectionConsole');
  const secInsp    = document.getElementById('sectionInspector');
  const bConsole   = document.getElementById('btnViewConsole');
  const bInsp      = document.getElementById('btnViewInspector');
  const bSplit     = document.getElementById('btnViewSplit');

  bConsole.classList.toggle('active', mode === 'console');
  bInsp.classList.toggle('active', mode === 'inspector');
  bSplit.classList.toggle('active', mode === 'split');

  if (mode === 'console') {
    secConsole.classList.remove('hidden');
    secInsp.classList.add('hidden');
  } else if (mode === 'inspector') {
    secConsole.classList.add('hidden');
    secInsp.classList.remove('hidden');
    filterInspectorRecords();
  } else if (mode === 'split') {
    secConsole.classList.remove('hidden');
    secInsp.classList.remove('hidden');
    filterInspectorRecords();
  }
}

// ── Procesamiento de Registros y Consola Enriquecida ─────────────────────────
function addRecord(r, shouldScroll = true) {
  // Normalizar datos del registro
  const normRec = {
    index:        r.index || (wiz.allRecords.length + 1),
    total:        r.total || 0,
    id_licencia:  r.id_licencia ?? r.id ?? '—',
    raw_text:     r.raw_text || r.original_address || r.emp_direccion || '',
    metodo:       r.metodo || r.method || 'IA',
    es_procesado: Boolean(r.es_procesado),
    observacion:  r.observacion || '',
    success:      r.success !== false,
    status_str:   r.status_str || (r.success !== false ? 'Cargado en BD ✅' : 'Error en Carga ❌'),
    nom_via:      r.nom_via || '',
    num_via:      r.num_via || '',
    id_via:       r.id_via || null,
    tipo_via_name:r.tipo_via_name || r.tipo_via || '',
    via_desc:     r.via_desc || `${r.nom_via || 'N/D'} N° ${r.num_via || 'S/N'}${r.id_via ? ' [ID Vía: ' + r.id_via + ']' : ''}`,
    nom_zona:     r.nom_zona || '',
    id_zona:      r.id_zona || null,
    tipo_zona_name:r.tipo_zona_name || r.tipo_zona || '',
    zona_desc:    r.zona_desc || `${r.nom_zona || 'N/D'}${r.id_zona ? ' [ID Zona: ' + r.id_zona + ']' : ''}`,
    manzana:      r.manzana || '',
    lote:         r.lote || '',
    slote:        r.slote || '',
    catastro:     r.catastro || `Mz: ${r.manzana || '-'} | Lt: ${r.lote || '-'} | Sublote: ${r.slote || '-'}`,
    referencia:   r.referencia || '',
    time:         new Date().toLocaleTimeString('es-PE', { hour12: false }),
  };

  // Contadores
  wiz.counts.all++;
  if (!normRec.success || normRec.metodo === 'ERROR') {
    wiz.counts.error++;
  } else if (normRec.es_procesado) {
    wiz.counts.valid++;
  } else {
    wiz.counts.observed++;
  }

  updateCounterBadges();

  wiz.allRecords.unshift(normRec);
  if (wiz.allRecords.length > 500) wiz.allRecords.pop();

  // Añadir visualmente a la terminal si corresponde con el filtro
  if (matchesLogFilter(normRec)) {
    appendRecordToTerminal(normRec, shouldScroll);
  }

  // Si el inspector está visible, refrescarlo de forma interactiva
  if (wiz.viewMode !== 'console') {
    filterInspectorRecords();
  }
}

function updateCounterBadges() {
  const badgeLog = document.getElementById('badgeLogCount');
  const badgeRec = document.getElementById('badgeRecCount');
  if (badgeLog) badgeLog.textContent = wiz.counts.all;
  if (badgeRec) badgeRec.textContent = wiz.counts.all;

  const ca = document.getElementById('cntAll');
  const cv = document.getElementById('cntValid');
  const co = document.getElementById('cntObs');
  const ce = document.getElementById('cntErr');
  if (ca) ca.textContent = wiz.counts.all;
  if (cv) cv.textContent = wiz.counts.valid;
  if (co) co.textContent = wiz.counts.observed;
  if (ce) ce.textContent = wiz.counts.error;
}

function matchesLogFilter(r) {
  if (wiz.logFilter === 'all') return true;
  const isErr = !r.success || r.metodo === 'ERROR';
  const isObs = !r.es_procesado && !isErr;
  const isValid = r.es_procesado && !isErr;

  if (wiz.logFilter === 'valid')    return isValid;
  if (wiz.logFilter === 'observed') return isObs;
  if (wiz.logFilter === 'error')    return isErr;
  return true;
}

function setLogFilter(filter) {
  wiz.logFilter = filter;
  ['termFilterAll', 'termFilterValid', 'termFilterObs', 'termFilterErr'].forEach(id => {
    document.getElementById(id)?.classList.remove('active');
  });

  if (filter === 'all')      document.getElementById('termFilterAll')?.classList.add('active');
  if (filter === 'valid')    document.getElementById('termFilterValid')?.classList.add('active');
  if (filter === 'observed') document.getElementById('termFilterObs')?.classList.add('active');
  if (filter === 'error')    document.getElementById('termFilterErr')?.classList.add('active');

  rebuildConsoleDisplay();
}

function setLogFormat(fmt) {
  wiz.logFormat = fmt;
  rebuildConsoleDisplay();
}

function toggleAutoScroll(checked) {
  wiz.autoScroll = checked;
}

function rebuildConsoleDisplay() {
  const body = document.getElementById('consoleBody');
  if (!body) return;
  body.innerHTML = '';

  const recordsToDisplay = [...wiz.allRecords].reverse();
  const matched = recordsToDisplay.filter(r => matchesLogFilter(r));

  if (!matched.length && !wiz.allLogs.length) {
    body.innerHTML = '<div style="color:#64748b; text-align:center; padding:40px 0;">No hay logs para el filtro seleccionado.</div>';
    return;
  }

  // Renderizar logs de sistema al inicio
  wiz.allLogs.forEach(l => {
    const div = document.createElement('div');
    div.className = 'compact-log-row log-system';
    div.textContent = `[${l.time}] ${l.msg}`;
    body.appendChild(div);
  });

  // Renderizar registros
  matched.forEach(r => {
    if (wiz.logFormat === 'rich') {
      const card = document.createElement('div');
      card.innerHTML = renderRichConsoleCard(r);
      body.appendChild(card.firstElementChild);
    } else {
      const row = document.createElement('div');
      row.className = getCompactRowClass(r);
      row.textContent = formatCompactLogRow(r);
      body.appendChild(row);
    }
  });

  if (wiz.autoScroll) {
    body.scrollTop = body.scrollHeight;
  }
}

function appendRecordToTerminal(r, shouldScroll = true) {
  const body = document.getElementById('consoleBody');
  if (!body) return;

  // Si tenía mensaje de espera, removerlo
  if (body.querySelector('div[style*="text-align:center"]')) {
    body.innerHTML = '';
  }

  if (wiz.logFormat === 'rich') {
    const wrap = document.createElement('div');
    wrap.innerHTML = renderRichConsoleCard(r);
    body.appendChild(wrap.firstElementChild);
  } else {
    const row = document.createElement('div');
    row.className = getCompactRowClass(r);
    row.textContent = formatCompactLogRow(r);
    body.appendChild(row);
  }

  if (shouldScroll && wiz.autoScroll) {
    body.scrollTop = body.scrollHeight;
  }
}

function addSystemLog(msg, level = '') {
  const time = new Date().toLocaleTimeString('es-PE', { hour12: false });
  wiz.allLogs.push({ msg, level, time });
  if (wiz.allLogs.length > 300) wiz.allLogs.pop();

  const body = document.getElementById('consoleBody');
  if (!body) return;

  // Si tenía mensaje de espera, removerlo
  if (body.querySelector('div[style*="text-align:center"]')) {
    body.innerHTML = '';
  }

  const row = document.createElement('div');
  const isErr = msg.toLowerCase().includes('error');
  const isOk  = msg.toLowerCase().includes('completado') || msg.toLowerCase().includes('exitoso');
  row.className = isErr ? 'compact-log-row log-error' : (isOk ? 'compact-log-row log-valid' : 'compact-log-row log-system');
  row.textContent = `[${time}] ⚡ ${msg}`;
  body.appendChild(row);

  if (wiz.autoScroll) {
    body.scrollTop = body.scrollHeight;
  }
}

function renderRichConsoleCard(r) {
  const isErr = !r.success || r.metodo === 'ERROR';
  const isObs = !r.es_procesado && !isErr;

  const cardClass = isErr ? 'card-error' : (isObs ? 'card-observed' : 'card-valid');
  const statusBadge = isErr
    ? `<span class="badge badge-error">ERROR ❌</span>`
    : (isObs ? `<span class="badge badge-observed">OBSERVADO ⚠️</span>` : `<span class="badge badge-valid">NORMALIZADO ✅</span>`);

  let motorBadge = `<span class="badge badge-motor-ai">🤖 ${escapeHtml(r.metodo)}</span>`;
  if (r.metodo && r.metodo.includes('Híbrido')) {
    motorBadge = `<span class="badge badge-motor-hy">🧩 ${escapeHtml(r.metodo)}</span>`;
  } else if (r.metodo && !r.metodo.includes('IA')) {
    motorBadge = `<span class="badge badge-motor-he">⚠️ ${escapeHtml(r.metodo)}</span>`;
  }

  let obsHtml = '';
  if (r.observacion) {
    obsHtml = `<div class="${isErr ? 'alert-err-box' : 'alert-obs-box'}">
      <strong>⚠️ Diagnóstico / Motivo:</strong> ${escapeHtml(r.observacion)}
    </div>`;
  }

  let refHtml = '';
  if (r.referencia) {
    refHtml = `<div class="card-row"><span class="row-lbl">🏛️ Ref      :</span> <span class="row-val text-cyan">${escapeHtml(r.referencia)}</span></div>`;
  }

  return `
    <div class="console-card ${cardClass}">
      <div class="card-head">
        <span class="card-title">┌── [Registro ${r.index}/${r.total || '?'}] | ID Licencia: ${r.id_licencia}</span>
        <div style="display:flex; gap:6px; align-items:center;">
          ${statusBadge}
          ${motorBadge}
          <span style="font-size:11px; color:#64748b;">${r.time}</span>
        </div>
      </div>
      <div class="card-row"><span class="row-lbl">📍 Entrada  :</span> <span class="row-val">"${escapeHtml(r.raw_text || 'VACÍO')}"</span></div>
      <div class="card-row"><span class="row-lbl">🛣️ Vía      :</span> <span class="row-val text-yellow">${escapeHtml(r.via_desc)}</span></div>
      <div class="card-row"><span class="row-lbl">🏙️ Zona     :</span> <span class="row-val text-magenta">${escapeHtml(r.zona_desc)}</span></div>
      <div class="card-row"><span class="row-lbl">📐 Catastro :</span> <span class="row-val text-cyan">${escapeHtml(r.catastro)}</span></div>
      ${refHtml}
      ${obsHtml}
      <div style="margin-top:6px; padding-top:4px; border-top:1px solid rgba(255,255,255,0.06); font-size:11px; color:#94a3b8; display:flex; justify-content:space-between; align-items:center;">
        <span>└── 💾 Estado: ${escapeHtml(r.status_str)}</span>
        <span style="cursor:pointer; color:#38bdf8; font-size:11px;" onclick="copySingleRecord(${r.id_licencia})">Copiar datos</span>
      </div>
    </div>
  `;
}

function getCompactRowClass(r) {
  const isErr = !r.success || r.metodo === 'ERROR';
  const isObs = !r.es_procesado && !isErr;
  return isErr ? 'compact-log-row log-error' : (isObs ? 'compact-log-row log-observed' : 'compact-log-row log-valid');
}

function formatCompactLogRow(r) {
  const isErr = !r.success || r.metodo === 'ERROR';
  const isObs = !r.es_procesado && !isErr;
  const tag = isErr ? '[ERROR]' : (isObs ? '[OBSERVADO]' : '[VALIDO]');
  const via = r.nom_via ? `${r.nom_via} N° ${r.num_via || 'S/N'}` : 'N/D';
  const obs = r.observacion ? ` | Motivo: ${r.observacion}` : '';
  return `[${r.time}] [${r.index}/${r.total || '?'}] [ID:${r.id_licencia}] ${tag} [${r.metodo}] "${r.raw_text}" -> ${via} | ${r.nom_zona || 'N/D'}${obs}`;
}

function clearConsoleLogs() {
  const body = document.getElementById('consoleBody');
  if (body) {
    body.innerHTML = '<div style="color:#64748b; text-align:center; padding:40px 0;">Consola limpia. Nuevos eventos aparecerán a continuación.</div>';
  }
  wiz.allLogs = [];
}

function copyConsoleLogs() {
  const textLines = wiz.allRecords.map(r => formatCompactLogRow(r)).join('\n');
  navigator.clipboard.writeText(textLines).then(() => {
    alert('Logs de consola copiados al portapapeles.');
  });
}

// ── Inspector de Registros Catastrales ───────────────────────────────────────
function filterInspectorRecords() {
  wiz.searchInspector = document.getElementById('searchInspector')?.value || '';
  wiz.inspectorStatus = document.getElementById('filterInspectorStatus')?.value || 'all';
  wiz.inspectorMotor  = document.getElementById('filterInspectorMotor')?.value || 'all';

  const list = document.getElementById('inspectorCardsList');
  if (!list) return;

  const q = wiz.searchInspector.toLowerCase().trim();
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
    countLabel.textContent = `Mostrando ${filtered.length} de ${wiz.allRecords.length} registros`;
  }

  if (!filtered.length) {
    list.innerHTML = `<p style="text-align:center; color:var(--gray-lt); padding:40px; font-size:13px;">No hay registros que coincidan con la búsqueda o filtros aplicados.</p>`;
    return;
  }

  list.innerHTML = filtered.map(r => {
    const isErr = !r.success || r.metodo === 'ERROR';
    const isObs = !r.es_procesado && !isErr;
    const cardClass = isErr ? 'card-error' : (isObs ? 'card-observed' : 'card-valid');

    const statusBadge = isErr
      ? `<span class="badge badge-error">ERROR ❌</span>`
      : (isObs ? `<span class="badge badge-observed">OBSERVADO ⚠️</span>` : `<span class="badge badge-valid">NORMALIZADO ✅</span>`);

    let motorBadge = `<span class="badge badge-motor-ai">🤖 ${escapeHtml(r.metodo || 'IA')}</span>`;
    if (r.metodo && r.metodo.includes('Híbrido')) {
      motorBadge = `<span class="badge badge-motor-hy">🧩 ${escapeHtml(r.metodo)}</span>`;
    } else if (r.metodo && !r.metodo.includes('IA')) {
      motorBadge = `<span class="badge badge-motor-he">⚠️ ${escapeHtml(r.metodo)}</span>`;
    }

    const obsAlert = r.observacion
      ? `<div class="${isErr ? 'err-alert-card' : 'obs-alert-card'}">
          <div><strong>Diagnóstico / Motivo:</strong> ${escapeHtml(r.observacion)}</div>
        </div>`
      : '';

    const viaName = r.nom_via || 'No identificada';
    const numVia = r.num_via ? `N° ${r.num_via}` : 'S/N';
    const idViaChip = r.id_via ? `<span class="chip-id chip-via">ID Vía: ${r.id_via}</span>` : '';
    const idZonaChip = r.id_zona ? `<span class="chip-id chip-zona">ID Zona: ${r.id_zona}</span>` : '';

    return `
      <div class="inspector-card ${cardClass}">
        <div class="inspector-head">
          <div style="display:flex; align-items:center; gap:8px;">
            <strong style="color:var(--blue); font-size:13px;">ID ${r.id_licencia}</strong>
            <span style="color:var(--gray-lt); font-size:12px;">(Reg. ${r.index}/${r.total})</span>
            ${statusBadge}
            ${motorBadge}
          </div>
          <div style="display:flex; gap:6px; align-items:center;">
            <span style="font-size:11px; color:var(--gray-lt);">${r.time}</span>
            <button class="btn btn-ghost" style="padding:2px 8px; font-size:11px;" onclick="copySingleRecord(${r.id_licencia})">Copiar</button>
          </div>
        </div>

        <div class="inspector-orig">
          <span style="color:var(--gray-lt); font-size:12px; font-weight:600;">Entrada original:</span>
          "${escapeHtml(r.raw_text)}"
        </div>

        <div class="inspector-grid">
          <div class="data-box">
            <div class="data-box-title">Vía Estandarizada</div>
            <div class="data-box-val">${escapeHtml(viaName)} ${escapeHtml(numVia)}</div>
            <div class="data-box-sub">${escapeHtml(r.tipo_via_name || 'Tipo vía')} ${idViaChip}</div>
          </div>
          <div class="data-box">
            <div class="data-box-title">Zona / Hab. Urbana</div>
            <div class="data-box-val">${escapeHtml(r.nom_zona || 'No identificada')}</div>
            <div class="data-box-sub">${escapeHtml(r.tipo_zona_name || 'Tipo zona')} ${idZonaChip}</div>
          </div>
          <div class="data-box">
            <div class="data-box-title">Catastro Urbano</div>
            <div class="data-box-val">Mz: ${escapeHtml(r.manzana || '-')} | Lt: ${escapeHtml(r.lote || '-')} | Slt: ${escapeHtml(r.slote || '-')}</div>
            <div class="data-box-sub">${r.referencia ? 'Ref: ' + escapeHtml(r.referencia) : 'Sin referencia'}</div>
          </div>
        </div>

        ${obsAlert}
      </div>
    `;
  }).join('');
}

function copySingleRecord(idLicencia) {
  const rec = wiz.allRecords.find(r => r.id_licencia == idLicencia);
  if (!rec) return;
  navigator.clipboard.writeText(JSON.stringify(rec, null, 2)).then(() => {
    alert(`Datos del registro ID ${idLicencia} copiados como JSON.`);
  });
}

function copyInspectorData() {
  navigator.clipboard.writeText(JSON.stringify(wiz.allRecords, null, 2)).then(() => {
    alert(`${wiz.allRecords.length} registros copiados en formato JSON.`);
  });
}

// ── Iniciar / Detener ETL ────────────────────────────────────────────────────
async function startETL() {
  const limit      = parseInt(document.getElementById('inp_limit').value) || null;
  const batch      = parseInt(document.getElementById('inp_batch').value) || 50;
  const filter     = document.getElementById('inp_filter').value || 'pending';
  const require_ai = document.getElementById('inp_require_ai')?.checked ?? true;

  // Reset registros locales y contadores
  wiz.allRecords = [];
  wiz.counts = { all: 0, valid: 0, observed: 0, error: 0 };
  updateCounterBadges();

  const cBody = document.getElementById('consoleBody');
  if (cBody) cBody.innerHTML = '<div style="color:#64748b; text-align:center; padding:40px 0;">Iniciando pipeline... Conectando con el motor ETL...</div>';

  const iList = document.getElementById('inspectorCardsList');
  if (iList) iList.innerHTML = '<p style="text-align:center; color:var(--gray-lt); padding:40px; font-size:13px;">Procesando... Los registros aparecerán a continuación.</p>';

  kpi('kpiProcessed', 0); kpi('kpiValid', 0);
  kpi('kpiObserved', 0);  kpi('kpiFailed', 0);
  document.getElementById('progressFill').style.width = '0%';
  document.getElementById('progressLabel').textContent = '0 de 0 registros';

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
      addSystemLog('Error al iniciar: ' + (data.detail || 'Error desconocido'), 'warn');
      document.getElementById('btnStart').disabled = false;
      document.getElementById('btnStop').disabled  = true;
    } else {
      addSystemLog('Pipeline iniciado correctamente.', 'info');
    }
  } catch (e) {
    addSystemLog('Error de red: ' + e.message);
    document.getElementById('btnStart').disabled = false;
    document.getElementById('btnStop').disabled  = true;
  }
}

async function stopETL() {
  document.getElementById('btnStop').disabled = true;
  addSystemLog('Solicitando detención segura del pipeline...', 'warn');
  try {
    await fetch('/api/stop', { method: 'POST' });
  } catch (_) {}
}

function onDone(data) {
  document.getElementById('btnStart').disabled = false;
  document.getElementById('btnStop').disabled  = true;
  document.getElementById('statusLabel').textContent = 'Completado';
  const dot = document.getElementById('termLiveDot');
  if (dot) dot.style.background = '#94a3b8';

  addSystemLog(`ETL culminado. Procesados: ${data.processed_records ?? data.processed ?? 0} | Normalizados: ${data.valid_processed_records ?? data.valid ?? 0} | Observados: ${data.observed_records ?? data.observed ?? 0}`, 'ok');
}

function onError(data) {
  document.getElementById('btnStart').disabled = false;
  document.getElementById('btnStop').disabled  = true;
  document.getElementById('statusLabel').textContent = 'Error';
  const dot = document.getElementById('termLiveDot');
  if (dot) dot.style.background = '#ef4444';

  addSystemLog('Fallo durante la ejecución: ' + (data.error || 'Error desconocido'), 'error');
}
