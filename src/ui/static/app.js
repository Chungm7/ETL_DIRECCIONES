/**
 * app.js — Lógica del wizard ETL MPCH
 * Flujo de 5 Pasos:
 * 1. Conexión IA (Ollama) -> 2. Conexión BD -> 3. Esquema -> 4. Tabla -> 5. Inspector de Registros Catastrales
 */

// ── Estado del wizard ────────────────────────────────────────────────────────
const wiz = {
  step: 1,
  ai_host: '',
  ai_port: null,
  ai_model: '',
  schema: null,
  table: null,
  id_col: null,
  addr_col: null,
  columns: [],
  allRecords: [],
  autoScroll: true,
  searchInspector: '',
  inspectorStatus: 'all',  // 'all' | 'valid' | 'observed' | 'error'
  inspectorMotor: 'all',   // 'all' | 'ia' | 'hibrido' | 'heuristico'
  counts: { all: 0, valid: 0, observed: 0, error: 0 },
  evtSource: null,
};

// ── Navegación entre pasos (1 a 5) ───────────────────────────────────────────
function goStep(n) {
  [1, 2, 3, 4, 5].forEach(i => {
    const el = document.getElementById(`step${i}`);
    if (el) el.classList.add('hidden');
    const tab = document.getElementById(`tab${i}`);
    if (tab) {
      tab.classList.remove('active', 'done');
      if (i < n) tab.classList.add('done');
    }
  });

  const curStep = document.getElementById(`step${n}`);
  if (curStep) curStep.classList.remove('hidden');
  const curTab = document.getElementById(`tab${n}`);
  if (curTab) curTab.classList.add('active');
  wiz.step = n;

  for (let i = 1; i < n; i++) {
    const prevTab = document.getElementById(`tab${i}`);
    if (prevTab) {
      prevTab.classList.add('done');
      prevTab.classList.remove('active');
    }
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

// ── PASO 1: Inteligencia Artificial (Ollama) ─────────────────────────────────
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
  showAlert('alertAI', '');
  const host = (document.getElementById('ai_host')?.value || '').trim();
  const portStr = (document.getElementById('ai_port')?.value || '').trim();
  const port = portStr ? parseInt(portStr) : 11434;

  if (!host) {
    showAlert('alertAI', 'Por favor ingrese el Host o IP del servidor Ollama antes de detectar modelos.', 'warn');
    return;
  }

  showAlert('alertAI', `Consultando modelos en http://${host}:${port}/api/tags ...`, 'info');

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
      sel.appendChild(new Option('Otro (ingresar manualmente)...', 'custom'));

      const patrocloMatch = data.models.find(m => m.toLowerCase().includes('patroclo'));
      if (patrocloMatch) {
        sel.value = patrocloMatch;
      }
      onModelSelectChange();
      showAlert('alertAI', `Se detectaron ${data.models.length} modelo(s) en ${host}:${port}.`, 'ok');
    } else {
      showAlert('alertAI', data.message || 'No se pudieron detectar modelos en el servidor Ollama.', 'warn');
    }
  } catch (e) {
    showAlert('alertAI', `Error consultando servidor Ollama: ${e.message}`, 'error');
  }
}

async function connectAI() {
  showAlert('alertAI', '');

  const host = (document.getElementById('ai_host')?.value || '').trim();
  const portStr = (document.getElementById('ai_port')?.value || '').trim();
  const port = portStr ? parseInt(portStr) : 11434;
  const selVal = document.getElementById('ai_model_select')?.value || '';
  let model = selVal;

  if (selVal === 'custom') {
    model = (document.getElementById('ai_model_custom')?.value || '').trim();
  }

  if (!host) {
    showAlert('alertAI', 'Debe ingresar el Host o IP del servidor Ollama.', 'warn');
    return;
  }
  if (!model) {
    showAlert('alertAI', 'Debe seleccionar o ingresar el nombre del modelo de IA (detecte los modelos o use opción manual).', 'warn');
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
      showAlert('alertAI', data.detail || 'No se pudo conectar al motor de IA.', 'error');
      return;
    }

    wiz.ai_host  = host;
    wiz.ai_port  = port;
    wiz.ai_model = model;

    showAlert('alertAI', `Conexión exitosa a Ollama con modelo <strong>${model}</strong> (${data.latency_ms} ms).`, 'ok');
    const btnNext = document.getElementById('btnGoStep2');
    if (btnNext) btnNext.classList.remove('hidden');

    // Transición suave al paso 2
    setTimeout(() => {
      goStep(2);
      showAlert('alertConnect', `Motor IA configurado en http://${host}:${port} (${model}). Ingrese ahora los parámetros de PostgreSQL.`, 'info');
    }, 500);

  } catch (e) {
    showAlert('alertAI', `Error de red al conectar con IA: ${e.message}`, 'error');
  } finally {
    setLoading('btnConnectAI', 'spinConnectAI', false);
  }
}

// ── PASO 2: Conexión BD ───────────────────────────────────────────────────────
async function connectDB() {
  showAlert('alertConnect', '');

  const host = (document.getElementById('db_host')?.value || '').trim();
  const portStr = (document.getElementById('db_port')?.value || '').trim();
  const port = portStr ? parseInt(portStr) : 5432;
  const dbname = (document.getElementById('db_name')?.value || '').trim();
  const user = (document.getElementById('db_user')?.value || '').trim();
  const password = document.getElementById('db_pass')?.value || '';

  if (!host || !dbname || !user) {
    showAlert('alertConnect', 'Por favor complete el Servidor (Host), Base de Datos y Usuario para conectar.', 'warn');
    return;
  }

  setLoading('btnConnect', 'spinConnect', true);

  const body = { host, port, dbname, user, password };

  try {
    const res = await fetch('/api/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();

    if (!res.ok) {
      showAlert('alertConnect', data.detail || 'No se pudo conectar a la base de datos.', 'error');
      return;
    }

    renderSchemaCards(data.schemas || []);
    showAlert('alertConnect', '');
    goStep(3);
    showAlert('alertSchema', `Conectado a <strong>${body.dbname}</strong> en ${body.host}:${body.port}. Seleccione el esquema a trabajar:`, 'ok');

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
    goStep(4);

  } catch (e) {
    showAlert('alertSchema', `Error de red: ${e.message}`, 'error');
  } finally {
    setLoading('btnSchema', 'spinSchema', false);
  }
}

// ── PASO 4: Tabla ────────────────────────────────────────────────────────────
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
  const elAiModel = document.getElementById('summAiModel');
  if (elAiModel) elAiModel.textContent = wiz.ai_model || 'Ollama';
  const elAiHost = document.getElementById('summAiHost');
  if (elAiHost) elAiHost.textContent = `http://${wiz.ai_host}:${wiz.ai_port}`;

  goStep(5);
  initStep5();
}

// ── PASO 5: Ejecución e Inspector en Tiempo Real ─────────────────────────────
async function initStep5() {
  try {
    const res  = await fetch('/api/status');
    const data = await res.json();
    const ai   = data.ai || {};
    const badge = document.getElementById('aiStatusBadge');

    // Comprobar estado de IA:
    const isModelReady = Boolean(ai.installed || ai.model_available);
    const isAiActive   = (ai.connected && isModelReady) || Boolean(wiz.ai_model && (ai.connected || wiz.ai_host));
    const activeModel  = wiz.ai_model || ai.model || 'Ollama';

    if (isAiActive && activeModel) {
      badge.innerHTML = `<span class="ai-badge ai-on"><span class="dot dot-green"></span>IA activa — ${escapeHtml(activeModel)}</span>`;
    } else {
      badge.innerHTML = `<span class="ai-badge ai-off"><span class="dot dot-red"></span>IA no disponible</span>`;
    }

    // Inicializar registros previos si existen
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
    case 'connected':
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

// ── Procesamiento de Registros del Inspector ─────────────────────────────────
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
  };

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

  filterInspectorRecords(shouldScroll);
}

function updateCounterBadges() {
  const ca = document.getElementById('cntAll');
  const cv = document.getElementById('cntValid');
  const co = document.getElementById('cntObs');
  const ce = document.getElementById('cntErr');
  if (ca) ca.textContent = wiz.counts.all;
  if (cv) cv.textContent = wiz.counts.valid;
  if (co) co.textContent = wiz.counts.observed;
  if (ce) ce.textContent = wiz.counts.error;
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
    countLabel.textContent = `Mostrando ${filtered.length} de ${wiz.allRecords.length} registros procesados`;
  }

  if (!filtered.length) {
    list.innerHTML = `<p style="text-align:center; color:var(--gray-lt); padding:40px; font-size:13px;">No hay registros que coincidan con los filtros seleccionados.</p>`;
    return;
  }

  list.innerHTML = filtered.map(r => createConciseRecordCard(r)).join('');

  if (autoScroll && wiz.autoScroll) {
    list.scrollTop = 0; // El registro más reciente está arriba
  }
}

function createConciseRecordCard(r) {
  const isErr = !r.success || r.metodo === 'ERROR';
  const isObs = !r.es_procesado && !isErr;
  const cardClass = isErr ? 'card-error' : (isObs ? 'card-observed' : 'card-valid');

  // Badge de Estado
  const statusBadge = isErr
    ? `<span class="badge badge-error">ERROR ❌</span>`
    : (isObs ? `<span class="badge badge-observed">OBSERVADO ⚠️</span>` : `<span class="badge badge-valid">NORMALIZADO ✅</span>`);

  // Badge de Motor
  let motorBadge = `<span class="badge badge-motor-ai">🤖 ${escapeHtml(r.metodo || 'IA')}</span>`;
  if (r.metodo && (r.metodo.includes('Híbrido') || r.metodo.includes('Hibrido'))) {
    motorBadge = `<span class="badge badge-motor-hy">🧩 ${escapeHtml(r.metodo)}</span>`;
  } else if (r.metodo && !r.metodo.includes('IA')) {
    motorBadge = `<span class="badge badge-motor-he">⚠️ ${escapeHtml(r.metodo)}</span>`;
  }

  // Diagnóstico si fue observado o con error
  let diagHtml = '';
  if (r.observacion) {
    const diagClass = isErr ? 'diag-err' : 'diag-obs';
    diagHtml = `
      <div class="record-diagnosis ${diagClass}">
        <strong>⚠️ Diagnóstico:</strong> <span>${escapeHtml(r.observacion)}</span>
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
    ? `<div class="breakdown-item"><span class="breakdown-lbl">Ref</span> <span class="breakdown-val" style="color:var(--blue);">${escapeHtml(r.referencia)}</span></div>`
    : '';

  return `
    <div class="record-card ${cardClass}">
      <div class="record-header">
        <div class="record-meta">
          <span class="record-id-chip">ID: ${r.id_licencia}</span>
          <span class="record-index">#${r.index} de ${r.total || '?'}</span>
          ${statusBadge}
          ${motorBadge}
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="font-size:11px; color:var(--gray-lt);">${r.time || ''}</span>
          <button class="btn btn-ghost" style="padding:2px 7px; font-size:11px;" onclick="copySingleRecord(${r.id_licencia})">Copiar</button>
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
  navigator.clipboard.writeText(JSON.stringify(rec, null, 2)).then(() => {
    alert(`Registro ID ${idLicencia} copiado en formato JSON.`);
  });
}

function copyInspectorData() {
  navigator.clipboard.writeText(JSON.stringify(wiz.allRecords, null, 2)).then(() => {
    alert(`${wiz.allRecords.length} registros copiados en formato JSON.`);
  });
}

function clearRecords() {
  wiz.allRecords = [];
  wiz.counts = { all: 0, valid: 0, observed: 0, error: 0 };
  updateCounterBadges();
  filterInspectorRecords();
}

// ── Iniciar / Detener ETL ────────────────────────────────────────────────────
async function startETL() {
  const limit      = parseInt(document.getElementById('inp_limit').value) || null;
  const batch      = parseInt(document.getElementById('inp_batch').value) || 50;
  const filter     = document.getElementById('inp_filter').value || 'pending';
  const require_ai = document.getElementById('inp_require_ai')?.checked ?? true;

  wiz.allRecords = [];
  wiz.counts = { all: 0, valid: 0, observed: 0, error: 0 };
  updateCounterBadges();

  const iList = document.getElementById('inspectorCardsList');
  if (iList) {
    iList.innerHTML = '<p style="text-align:center; color:var(--gray-lt); padding:40px; font-size:13px;">Iniciando pipeline... Conectando con PostgreSQL y el motor de normalización...</p>';
  }

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
      alert('Error al iniciar pipeline: ' + (data.detail || 'Error desconocido'));
      document.getElementById('btnStart').disabled = false;
      document.getElementById('btnStop').disabled  = true;
    }
  } catch (e) {
    alert('Error de conexión: ' + e.message);
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
  document.getElementById('statusLabel').textContent = 'Completado';
  const dot = document.getElementById('termLiveDot');
  if (dot) dot.style.background = '#94a3b8';
}

function onError(data) {
  document.getElementById('btnStart').disabled = false;
  document.getElementById('btnStop').disabled  = true;
  document.getElementById('statusLabel').textContent = 'Error';
  const dot = document.getElementById('termLiveDot');
  if (dot) dot.style.background = '#ef4444';
}

const initStep4 = initStep5;

// ── Control de Apagado y Cierre de la Aplicación ───────────────────────────
function confirmShutdown() {
  const isRunning = !document.getElementById('btnStop')?.disabled;
  const warn = document.getElementById('shutdownWarningText');
  const title = document.getElementById('shutdownModalTitle');
  const footer = document.getElementById('shutdownModalFooter');

  if (title) title.textContent = '¿Apagar el servicio?';
  if (footer) footer.style.display = 'flex';

  if (warn) {
    if (isRunning) {
      warn.innerHTML = '<span style="color:#b91c1c; font-weight:700;">⚠️ Hay un proceso ETL ejecutándose actualmente.</span><br><br>Al confirmar, <strong>se detendrá de inmediato el proceso</strong> y <strong>se apagará el servicio de la aplicación (equivalente a presionar Ctrl + C en la consola)</strong>.';
    } else {
      warn.innerHTML = '¿Confirmas que deseas apagar el servicio? Se cerrará el servidor local y la aplicación (equivalente a presionar <strong>Ctrl + C</strong> en la consola).';
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
  if (title) title.textContent = 'Apagando servicio...';

  if (body) {
    body.innerHTML = `
      <div style="text-align:center; padding:18px 0;">
        <div class="spinner" style="border-color:#cbd5e1; border-top-color:#dc2626; width:30px; height:30px; margin:0 auto 14px auto;"></div>
        <p style="font-weight:700; color:#1e293b; font-size:14px; margin-bottom:4px;">Apagando servidor local...</p>
        <p style="font-size:12px; color:#64748b;">Liberando recursos y finalizando procesos.</p>
      </div>
    `;
  }

  try {
    await fetch('/api/shutdown', { method: 'POST' });
  } catch (_) {
    // Si la conexión se corta inmediatamente debido al shutdown, es el comportamiento esperado
  }

  setTimeout(() => {
    if (title) title.textContent = '🔴 Servicio Apagado';
    if (body) {
      body.innerHTML = `
        <div style="text-align:center; padding:12px 0;">
          <div style="font-size:42px; margin-bottom:12px;">🛑</div>
          <p style="font-size:15px; font-weight:700; color:#1e293b; margin-bottom:6px;">
            El servidor local se ha apagado correctamente.
          </p>
          <p style="font-size:13px; color:#64748b; margin-bottom:18px;">
            La aplicación ha finalizado su ejecución de forma segura. Ya puedes cerrar esta ventana.
          </p>
          <button class="btn btn-ghost" onclick="window.close()" style="border:1px solid #cbd5e1; font-weight:600; padding:8px 18px;">
            Cerrar Ventana
          </button>
        </div>
      `;
    }
  }, 900);
}

// Inicialización al cargar la interfaz
document.addEventListener('DOMContentLoaded', () => {
  // Inicialización limpia en Paso 1
  goStep(1);
});

