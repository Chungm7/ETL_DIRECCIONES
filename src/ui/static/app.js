/**
 * MPCH ETL - Cliente Frontend y Receptor en Tiempo Real
 * Interfaz profesional, limpia e interactiva para normalización de direcciones.
 */

document.addEventListener('DOMContentLoaded', () => {
  // Elementos del formulario y controles
  const form = document.getElementById('etl-form');
  const schemaSelect = document.getElementById('schema-select');
  const tableInput = document.getElementById('table-input');
  const filterSelect = document.getElementById('filter-select');
  const limitInput = document.getElementById('limit-input');
  const batchInput = document.getElementById('batch-input');
  const requireAiCheckbox = document.getElementById('require-ai-checkbox');

  const btnStart = document.getElementById('btn-start');
  const btnStop = document.getElementById('btn-stop');
  const btnQuickDiag = document.getElementById('btn-quick-diag');
  const btnCloseDiag = document.getElementById('btn-close-diag');
  const btnRunSampleAi = document.getElementById('btn-run-sample-ai');
  const btnClearFeed = document.getElementById('btn-clear-feed');
  const searchFilterInput = document.getElementById('search-filter-input');

  // Indicadores de estado
  const dbIndicator = document.getElementById('db-indicator');
  const dbName = document.getElementById('db-name');
  const aiIndicator = document.getElementById('ai-indicator');
  const aiName = document.getElementById('ai-name');
  const statusText = document.getElementById('status-text');
  const activeSchemaBadge = document.getElementById('active-schema-badge');

  // KPIs
  const statTotalBd = document.getElementById('stat-total-bd');
  const statToProcess = document.getElementById('stat-to-process');
  const statValid = document.getElementById('stat-valid');
  const statValidPct = document.getElementById('stat-valid-pct');
  const statObserved = document.getElementById('stat-observed');
  const statObservedPct = document.getElementById('stat-observed-pct');
  const statAiCount = document.getElementById('stat-ai-count');
  const statAiModel = document.getElementById('stat-ai-model');
  const statElapsed = document.getElementById('stat-elapsed');
  const statSpeed = document.getElementById('stat-speed');

  // Barra de progreso
  const progressBarFill = document.getElementById('progress-bar-fill');
  const progressPercentageLabel = document.getElementById('progress-percentage-label');
  const progressCountLabel = document.getElementById('progress-count-label');
  const progressPendingLabel = document.getElementById('progress-pending-label');
  const progressStatusLabel = document.getElementById('progress-status-label');

  // Vistas y contenedores
  const tabBtnRecords = document.getElementById('tab-btn-records');
  const tabBtnLogs = document.getElementById('tab-btn-logs');
  const viewRecords = document.getElementById('view-records');
  const viewLogs = document.getElementById('view-logs');
  const recordsContainer = document.getElementById('records-container');
  const logsContainer = document.getElementById('logs-container');
  const emptyState = document.getElementById('empty-state');
  const badgeRecordsCount = document.getElementById('badge-records-count');
  const diagModal = document.getElementById('diag-modal');
  const diagDbDetail = document.getElementById('diag-db-detail');
  const diagAiDetail = document.getElementById('diag-ai-detail');

  // Filtros
  const filterChips = document.querySelectorAll('.filter-chip');
  let currentCardFilter = 'all';
  let currentSearchQuery = '';

  // Estado
  let isRunning = false;
  let recordsList = [];
  let eventSource = null;
  let latestCounts = null;

  // ==========================================
  // INICIALIZACIÓN
  // ==========================================

  async function init() {
    await loadStatus();
    connectSSE();
    setupEventHandlers();
  }

  async function loadStatus() {
    try {
      const res = await fetch('/api/status');
      if (!res.ok) throw new Error('Error al consultar estado');
      const data = await res.json();

      // Esquemas disponibles
      if (data.available_schemas && data.available_schemas.length > 0) {
        schemaSelect.innerHTML = '';
        data.available_schemas.forEach(s => {
          const opt = document.createElement('option');
          opt.value = s;
          opt.textContent = s;
          if (s === data.active_schema) opt.selected = true;
          schemaSelect.appendChild(opt);
        });
      }

      // Conexión Base de Datos
      if (data.db.connected) {
        dbIndicator.className = 'w-2 h-2 rounded-full bg-emerald-500';
        dbName.textContent = data.db.schema;
        diagDbDetail.textContent = `Conectado a PostgreSQL en esquema '${data.db.schema}' (Tabla disponible: ${data.db.table_exists ? 'Sí' : 'No'})`;
      } else {
        dbIndicator.className = 'w-2 h-2 rounded-full bg-rose-500';
        dbName.textContent = 'Sin conexión';
        diagDbDetail.textContent = `Fallo de conexión: ${data.db.message}`;
      }

      // Servicio de IA
      statAiModel.textContent = data.ai.model || 'patroclo';
      if (data.ai.connected) {
        aiIndicator.className = 'w-2 h-2 rounded-full bg-emerald-500';
        aiName.textContent = data.ai.model;
        diagAiDetail.textContent = `Disponible: ${data.ai.message}`;
      } else {
        aiIndicator.className = 'w-2 h-2 rounded-full bg-amber-500';
        aiName.textContent = 'Fuera de línea';
        diagAiDetail.textContent = `Aviso: ${data.ai.message}`;
      }

      // Valores activos en el formulario
      if (data.active_schema) {
        schemaSelect.value = data.active_schema;
      }
      if (data.active_table) {
        tableInput.value = data.active_table;
      }

      // Actualizar conteos
      updateTableCountsDisplay(data.table_counts);
      activeSchemaBadge.textContent = `${data.active_schema || 'public'}.${data.active_table || 'direcciones_actual'}`;

      // Registros previos si existieran
      if (data.recent_records && data.recent_records.length > 0 && recordsList.length === 0) {
        data.recent_records.forEach(r => renderRecordCard(r));
      }

      // Estado de ejecución activo
      if (data.running) {
        setRunningState(true);
        updateStatsDisplay(data.stats);
      }
    } catch (err) {
      console.error('Error cargando estado:', err);
      appendLog(`[Error] No se pudo comunicar con el servidor: ${err.message}`);
    }
  }

  function updateTableCountsDisplay(counts) {
    if (!counts) return;
    latestCounts = counts;

    const total = counts.total != null ? Number(counts.total) : 0;
    const pendientes = counts.pendientes != null ? Number(counts.pendientes) : 0;
    const validos = counts.validos != null ? Number(counts.validos) : 0;
    const observados = counts.observados != null ? Number(counts.observados) : 0;

    statTotalBd.textContent = total.toLocaleString();

    if (!isRunning) {
      statValid.textContent = validos.toLocaleString();
      statObserved.textContent = observados.toLocaleString();

      const validPct = total > 0 ? ((validos / total) * 100).toFixed(1) : '0.0';
      const obsPct = total > 0 ? ((observados / total) * 100).toFixed(1) : '0.0';
      statValidPct.textContent = `${validPct}%`;
      statObservedPct.textContent = `${obsPct}%`;

      recalcTargetToProcess();
    }

    progressPendingLabel.textContent = `Pendientes: ${pendientes.toLocaleString()}`;
  }

  function recalcTargetToProcess() {
    if (!latestCounts || isRunning) return;

    const total = latestCounts.total != null ? Number(latestCounts.total) : 0;
    const pendientes = latestCounts.pendientes != null ? Number(latestCounts.pendientes) : 0;
    const observados = latestCounts.observados != null ? Number(latestCounts.observados) : 0;

    const filter = filterSelect ? filterSelect.value : 'pending';
    let pool = pendientes;
    if (filter === 'observed') {
      pool = observados;
    } else if (filter === 'all') {
      pool = total;
    }

    const rawLimit = limitInput ? limitInput.value.trim() : '';
    const limitNum = (rawLimit !== '' && !isNaN(rawLimit)) ? parseInt(rawLimit, 10) : null;
    const target = limitNum ? Math.min(limitNum, pool) : pool;

    statToProcess.textContent = target.toLocaleString();
    progressCountLabel.textContent = `0 de ${target.toLocaleString()} registros`;
  }

  // ==========================================
  // CONEXIÓN SSE
  // ==========================================

  function connectSSE() {
    if (eventSource) {
      eventSource.close();
    }

    eventSource = new EventSource('/api/stream');

    eventSource.onopen = () => {
      appendLog('[Sistema] Canal de eventos en vivo conectado.');
    };

    eventSource.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        handleServerEvent(msg);
      } catch (err) {
        console.warn('Mensaje SSE no JSON:', e.data);
      }
    };

    eventSource.onerror = () => {
      // Reconexión automática nativa
    };
  }

  function handleServerEvent(event) {
    const { type, payload } = event;

    switch (type) {
      case 'record':
        renderRecordCard(payload);
        break;

      case 'stats':
        updateStatsDisplay(payload);
        break;

      case 'log':
        appendLog(payload);
        break;

      case 'done':
        setRunningState(false);
        statusText.textContent = 'Completado';
        statusText.className = 'font-semibold text-emerald-700';
        progressStatusLabel.textContent = 'Proceso finalizado correctamente';
        appendLog('[Sistema] Proceso de normalización finalizado.');
        refreshCounts();
        break;

      case 'error':
        setRunningState(false);
        statusText.textContent = 'Detenido con error';
        statusText.className = 'font-semibold text-rose-600';
        appendLog(`[Error] ${payload.error}`);
        alert(`Aviso: ${payload.error}`);
        break;

      default:
        break;
    }
  }

  // ==========================================
  // RENDERIZADO DE RESULTADOS
  // ==========================================

  function renderRecordCard(rec) {
    if (emptyState) emptyState.style.display = 'none';

    recordsList.unshift(rec);
    if (recordsList.length > 400) recordsList.pop();

    badgeRecordsCount.textContent = recordsList.length;

    const isValid = !!rec.es_procesado;
    const cardStatus = isValid ? 'valid' : 'observed';

    const card = document.createElement('div');
    card.className = `result-row rounded-lg p-3.5 border text-xs transition bg-white ${
      isValid ? 'border-slate-200 hover:border-slate-300' : 'border-amber-200 bg-amber-50/20'
    }`;

    // Atributos de búsqueda y filtrado
    card.setAttribute('data-status', cardStatus);
    const searchCorpus = [
      rec.id_licencia,
      rec.raw_text,
      rec.nom_via,
      rec.nom_zona,
      rec.observacion,
    ].filter(Boolean).join(' ').toLowerCase();
    card.setAttribute('data-search', searchCorpus);

    // Estado de visibilidad inicial
    applyItemVisibility(card, cardStatus, searchCorpus);

    // Método utilizado
    let methodLabel = rec.metodo || 'Reglas';
    if (methodLabel.includes('IA')) methodLabel = 'IA';
    else if (methodLabel.includes('Híbrido')) methodLabel = 'Híbrido';
    else methodLabel = 'Heurística';

    // Badges de estado
    const statusBadge = isValid
      ? `<span class="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
           Validado en catastro
         </span>`
      : `<span class="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-amber-50 text-amber-800 border border-amber-200">
           Observado
         </span>`;

    // Datos de Vía
    const viaText = rec.nom_via
      ? `<span class="font-medium text-slate-900">${escapeHtml(rec.nom_via)}</span> ${rec.num_via ? `<span class="text-slate-600 font-mono">#${escapeHtml(rec.num_via)}</span>` : ''}`
      : `<span class="text-slate-400 italic">No determinada</span>`;
    const viaIdBadge = rec.id_via
      ? `<span class="text-[10px] text-slate-500 font-mono font-medium">(ID: ${rec.id_via})</span>`
      : '';

    // Datos de Zona
    const zonaText = rec.nom_zona
      ? `<span class="font-medium text-slate-900">${escapeHtml(rec.nom_zona)}</span>`
      : `<span class="text-slate-400 italic">No determinada</span>`;
    const zonaIdBadge = rec.id_zona
      ? `<span class="text-[10px] text-slate-500 font-mono font-medium">(ID: ${rec.id_zona})</span>`
      : '';

    // Mz y Lote
    const parts = [];
    if (rec.manzana) parts.push(`Mz. ${escapeHtml(rec.manzana)}`);
    if (rec.lote) parts.push(`Lt. ${escapeHtml(rec.lote)}`);
    if (rec.slote) parts.push(`Slote. ${escapeHtml(rec.slote)}`);
    const mzLtText = parts.length > 0 ? parts.join(', ') : '<span class="text-slate-400">-</span>';

    // Alerta de observación si corresponde
    let obsBox = '';
    if (!isValid && rec.observacion) {
      obsBox = `
        <div class="mt-2.5 p-2 rounded bg-amber-50 border border-amber-200 text-amber-900 text-[11px]">
          <span class="font-semibold text-amber-950">Motivo:</span> ${escapeHtml(rec.observacion)}
        </div>
      `;
    }

    card.innerHTML = `
      <div class="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-100">
        <div class="flex items-center space-x-2">
          <span class="px-1.5 py-0.5 text-[11px] font-mono font-bold bg-slate-100 text-slate-800 rounded border border-slate-200">
            #${rec.id_licencia}
          </span>
          <span class="text-[11px] text-slate-400">
            Registro ${rec.index} de ${rec.total}
          </span>
          <span class="px-1.5 py-0.5 text-[10px] rounded bg-slate-50 text-slate-600 border border-slate-200">
            ${escapeHtml(methodLabel)}
          </span>
        </div>
        <div>
          ${statusBadge}
        </div>
      </div>

      <!-- Dirección Original -->
      <div class="mt-2">
        <div class="text-[11px] text-slate-400 font-medium">Texto original:</div>
        <div class="font-mono text-xs text-slate-800 bg-slate-50 px-2 py-1 rounded border border-slate-200 mt-0.5">
          ${escapeHtml(rec.raw_text)}
        </div>
      </div>

      <!-- Datos Catastrales -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-2.5 mt-2.5 pt-2 border-t border-slate-100 text-[11px]">
        <div>
          <span class="text-slate-400 block font-medium">Vía homologada:</span>
          <div>${viaText} ${viaIdBadge}</div>
        </div>

        <div>
          <span class="text-slate-400 block font-medium">Zona / Habilitación:</span>
          <div>${zonaText} ${zonaIdBadge}</div>
        </div>

        <div>
          <span class="text-slate-400 block font-medium">Manzana / Lote:</span>
          <div>${mzLtText}</div>
        </div>
      </div>

      ${obsBox}
    `;

    recordsContainer.insertBefore(card, recordsContainer.firstChild);
  }

  // ==========================================
  // FILTRADO Y BÚSQUEDA INTERACTIVA
  // ==========================================

  function applyItemVisibility(element, cardStatus, searchCorpus) {
    const matchesFilter = currentCardFilter === 'all' || currentCardFilter === cardStatus;
    const matchesSearch = !currentSearchQuery || searchCorpus.includes(currentSearchQuery);

    if (matchesFilter && matchesSearch) {
      element.style.display = 'block';
    } else {
      element.style.display = 'none';
    }
  }

  function filterAllItems() {
    const cards = recordsContainer.querySelectorAll('.result-row');
    cards.forEach(c => {
      const status = c.getAttribute('data-status');
      const searchCorpus = c.getAttribute('data-search') || '';
      applyItemVisibility(c, status, searchCorpus);
    });
  }

  // ==========================================
  // ACTUALIZACIÓN DE MÉTRICAS Y PROGRESO
  // ==========================================

  function updateStatsDisplay(stats) {
    if (!stats) return;

    if (stats.total_to_process != null) {
      statToProcess.textContent = Number(stats.total_to_process).toLocaleString();
    }
    if (stats.valid != null) {
      statValid.textContent = Number(stats.valid).toLocaleString();
    }
    if (stats.observed != null) {
      statObserved.textContent = Number(stats.observed).toLocaleString();
    }
    if (stats.ai_records != null) {
      statAiCount.textContent = Number(stats.ai_records).toLocaleString();
    }

    const total = stats.total_to_process || 0;
    const processed = stats.processed || 0;
    const valid = stats.valid || 0;
    const observed = stats.observed || 0;

    if (total > 0) {
      const pct = Math.min(100, Math.round((processed / total) * 100));
      progressBarFill.style.width = `${pct}%`;
      progressPercentageLabel.textContent = `${pct}%`;
      progressCountLabel.textContent = `${processed.toLocaleString()} de ${total.toLocaleString()} registros`;

      const validPct = ((valid / total) * 100).toFixed(1);
      const obsPct = ((observed / total) * 100).toFixed(1);
      statValidPct.textContent = `${validPct}%`;
      statObservedPct.textContent = `${obsPct}%`;
    }

    if (stats.elapsed_seconds != null) {
      statElapsed.textContent = `${stats.elapsed_seconds}s`;
      if (stats.elapsed_seconds > 0 && processed > 0) {
        const speed = (processed / stats.elapsed_seconds).toFixed(1);
        statSpeed.textContent = `${speed} reg/s`;
      }
    }
  }

  function appendLog(message) {
    const timestamp = new Date().toLocaleTimeString();
    const line = document.createElement('div');
    line.className = 'py-0.5 leading-relaxed font-mono';

    let colorClass = 'text-slate-300';
    if (message.includes('Error') || message.includes('ERROR')) colorClass = 'text-rose-400 font-semibold';
    else if (message.includes('finalizado') || message.includes('exitosamente')) colorClass = 'text-emerald-400 font-medium';
    else if (message.includes('Aviso')) colorClass = 'text-amber-300';

    line.innerHTML = `<span class="text-slate-500">[${timestamp}]</span> <span class="${colorClass}">${escapeHtml(message)}</span>`;
    logsContainer.appendChild(line);

    viewLogs.scrollTop = viewLogs.scrollHeight;
  }

  // ==========================================
  // MANEJADORES DE EVENTOS
  // ==========================================

  function setupEventHandlers() {
    // Cambio de esquema o tabla
    schemaSelect.addEventListener('change', () => {
      activeSchemaBadge.textContent = `${schemaSelect.value}.${tableInput.value.trim()}`;
      refreshCounts();
    });

    tableInput.addEventListener('change', () => {
      activeSchemaBadge.textContent = `${schemaSelect.value}.${tableInput.value.trim()}`;
      refreshCounts();
    });

    // Recálculo dinámico de objetivo
    filterSelect.addEventListener('change', () => {
      recalcTargetToProcess();
    });

    limitInput.addEventListener('input', () => {
      recalcTargetToProcess();
    });

    // Atajos de cantidad
    document.querySelectorAll('.limit-shortcut').forEach(btn => {
      btn.addEventListener('click', () => {
        limitInput.value = btn.getAttribute('data-limit');
        recalcTargetToProcess();
      });
    });

    // Búsqueda interactiva en resultados
    searchFilterInput.addEventListener('input', () => {
      currentSearchQuery = searchFilterInput.value.trim().toLowerCase();
      filterAllItems();
    });

    // Filtros por chip (Todos, Validados, Observados)
    filterChips.forEach(chip => {
      chip.addEventListener('click', () => {
        filterChips.forEach(c => {
          c.classList.remove('bg-slate-200', 'text-slate-800');
          c.classList.add('text-slate-600');
        });
        chip.classList.add('bg-slate-200', 'text-slate-800');
        chip.classList.remove('text-slate-600');

        currentCardFilter = chip.getAttribute('data-filter');
        filterAllItems();
      });
    });

    // Envío del formulario (Iniciar)
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (isRunning) return;

      const rawLimit = limitInput.value.trim();
      const parsedLimit = (rawLimit !== '' && !isNaN(rawLimit)) ? parseInt(rawLimit, 10) : null;

      let filterMode = filterSelect.value;
      if (filterMode === 'unprocessed') filterMode = 'observed';

      const payload = {
        schema_name: schemaSelect.value,
        table_name: tableInput.value.trim() || 'direcciones_actual',
        filter_mode: filterMode,
        limit: parsedLimit,
        batch_size: parseInt(batchInput.value, 10) || 10,
        require_ai: requireAiCheckbox.checked,
      };

      try {
        setRunningState(true);
        statusText.textContent = 'Procesando';
        statusText.className = 'font-semibold text-slate-900';
        progressStatusLabel.textContent = `Procesando en ${payload.schema_name}.${payload.table_name}...`;

        switchView('records');

        const res = await fetch('/api/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || 'Error al iniciar');
        }

        const limText = payload.limit ? `${payload.limit} registros` : 'todos los pendientes';
        appendLog(`[Sistema] Iniciado en ${payload.schema_name}.${payload.table_name} (Límite: ${limText}, Lote: ${payload.batch_size}).`);
      } catch (err) {
        setRunningState(false);
        alert(`No se pudo iniciar: ${err.message}`);
        appendLog(`[Error] Fallo al iniciar: ${err.message}`);
      }
    });

    // Detener proceso
    btnStop.addEventListener('click', async () => {
      if (!isRunning) return;
      btnStop.disabled = true;
      btnStop.textContent = 'Deteniendo...';

      try {
        const res = await fetch('/api/stop', { method: 'POST' });
        const data = await res.json();
        appendLog(`[Sistema] ${data.message}`);
      } catch (err) {
        appendLog(`[Error] ${err.message}`);
      }
    });

    // Limpiar feed
    btnClearFeed.addEventListener('click', () => {
      recordsContainer.innerHTML = '';
      recordsList = [];
      badgeRecordsCount.textContent = '0';
      if (emptyState) emptyState.style.display = 'block';
    });

    // Pestañas
    tabBtnRecords.addEventListener('click', () => switchView('records'));
    tabBtnLogs.addEventListener('click', () => switchView('logs'));

    // Modal de diagnóstico
    btnQuickDiag.addEventListener('click', () => {
      diagModal.classList.remove('hidden');
    });

    btnCloseDiag.addEventListener('click', () => {
      diagModal.classList.add('hidden');
    });

    btnRunSampleAi.addEventListener('click', async () => {
      btnRunSampleAi.disabled = true;
      btnRunSampleAi.textContent = 'Consultando...';
      try {
        const res = await fetch('/api/test-ai', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          diagAiDetail.textContent = `Correcto (${data.latency_ms} ms) - Modelo: ${data.model}\nResultado: ${JSON.stringify(data.parsed)}`;
        } else {
          diagAiDetail.textContent = `Fallo: ${data.message}`;
        }
      } catch (err) {
        diagAiDetail.textContent = `Error: ${err.message}`;
      } finally {
        btnRunSampleAi.disabled = false;
        btnRunSampleAi.textContent = 'Probar inferencia con dirección de prueba';
      }
    });
  }

  function switchView(target) {
    if (target === 'records') {
      viewRecords.classList.remove('hidden');
      viewLogs.classList.add('hidden');
      tabBtnRecords.className = 'px-3 py-1.5 rounded-md text-xs font-semibold bg-white text-slate-900 border border-slate-200 shadow-2xs transition';
      tabBtnLogs.className = 'px-3 py-1.5 rounded-md text-xs font-medium text-slate-600 hover:text-slate-900 border border-transparent transition';
    } else {
      viewRecords.classList.add('hidden');
      viewLogs.classList.remove('hidden');
      tabBtnLogs.className = 'px-3 py-1.5 rounded-md text-xs font-semibold bg-white text-slate-900 border border-slate-200 shadow-2xs transition';
      tabBtnRecords.className = 'px-3 py-1.5 rounded-md text-xs font-medium text-slate-600 hover:text-slate-900 border border-transparent transition';
    }
  }

  function setRunningState(running) {
    isRunning = running;
    if (running) {
      btnStart.disabled = true;
      btnStart.classList.add('opacity-40', 'cursor-not-allowed');
      btnStop.disabled = false;
      btnStop.classList.remove('bg-slate-100', 'text-slate-400', 'cursor-not-allowed');
      btnStop.classList.add('bg-rose-600', 'hover:bg-rose-700', 'text-white', 'cursor-pointer');
      schemaSelect.disabled = true;
      tableInput.disabled = true;
      filterSelect.disabled = true;
      limitInput.disabled = true;
      batchInput.disabled = true;
    } else {
      btnStart.disabled = false;
      btnStart.classList.remove('opacity-40', 'cursor-not-allowed');
      btnStop.disabled = true;
      btnStop.classList.add('bg-slate-100', 'text-slate-400', 'cursor-not-allowed');
      btnStop.classList.remove('bg-rose-600', 'hover:bg-rose-700', 'text-white', 'cursor-pointer');
      btnStop.textContent = 'Detener';
      schemaSelect.disabled = false;
      tableInput.disabled = false;
      filterSelect.disabled = false;
      limitInput.disabled = false;
      batchInput.disabled = false;
    }
  }

  async function refreshCounts() {
    try {
      const s = schemaSelect.value;
      const t = tableInput.value.trim();
      const res = await fetch(`/api/counts?schema=${encodeURIComponent(s)}&table=${encodeURIComponent(t)}`);
      if (res.ok) {
        const counts = await res.json();
        updateTableCountsDisplay(counts);
      }
    } catch (err) {
      console.warn('Error al refrescar conteos:', err);
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  init();
});
