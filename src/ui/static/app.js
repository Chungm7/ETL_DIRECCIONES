/**
 * MPCH ETL - Cliente Frontend y Receptor SSE en Tiempo Real
 */

document.addEventListener('DOMContentLoaded', () => {
  // Elementos DOM
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

  // Badges y Estado
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

  // Contenedores de vistas
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

  // Filtros de tarjetas
  const filterChips = document.querySelectorAll('.filter-chip');
  let currentCardFilter = 'all';

  // Estado local
  let isRunning = false;
  let recordsList = [];
  let eventSource = null;
  let timerInterval = null;
  let startTime = null;

  // ==========================================
  // INICIALIZACIÓN Y CONEXIONES
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

      // BD Health
      if (data.db.connected) {
        dbIndicator.className = 'w-2.5 h-2.5 rounded-full bg-emerald-400';
        dbName.textContent = data.db.schema;
        dbName.className = 'text-emerald-400 font-bold';
        diagDbDetail.textContent = `✅ ${data.db.message} (Tabla existe: ${data.db.table_exists ? 'Sí' : 'No'})`;
      } else {
        dbIndicator.className = 'w-2.5 h-2.5 rounded-full bg-rose-500';
        dbName.textContent = 'Desconectado';
        dbName.className = 'text-rose-400 font-bold';
        diagDbDetail.textContent = `❌ ${data.db.message}`;
      }

      // AI Health
      statAiModel.textContent = data.ai.model || 'patroclo';
      if (data.ai.connected) {
        aiIndicator.className = 'w-2.5 h-2.5 rounded-full bg-purple-400';
        aiName.textContent = data.ai.model;
        aiName.className = 'text-purple-300 font-bold';
        diagAiDetail.textContent = `✅ ${data.ai.message} (Modelo '${data.ai.model}')`;
      } else {
        aiIndicator.className = 'w-2.5 h-2.5 rounded-full bg-rose-500';
        aiName.textContent = 'Sin Conexión';
        aiName.className = 'text-rose-400 font-bold';
        diagAiDetail.textContent = `⚠️ ${data.ai.message}`;
      }

      // Conteos
      updateTableCountsDisplay(data.table_counts);
      activeSchemaBadge.textContent = `Esquema: ${data.active_schema}`;

      // Si hay registros recientes recibidos previamente
      if (data.recent_records && data.recent_records.length > 0 && recordsList.length === 0) {
        data.recent_records.forEach(r => renderRecordCard(r));
      }

      // Si ya estaba corriendo
      if (data.running) {
        setRunningState(true);
        updateStatsDisplay(data.stats);
      }
    } catch (err) {
      console.error('Fallo cargando estado inicial:', err);
      appendLog(`[ERROR] No se pudo comunicar con el servidor: ${err.message}`);
    }
  }

  function updateTableCountsDisplay(counts) {
    if (!counts) return;
    statTotalBd.textContent = counts.total != null ? Number(counts.total).toLocaleString() : '-';
    progressPendingLabel.textContent = `Pendientes en BD: ${counts.pendientes != null ? Number(counts.pendientes).toLocaleString() : '-'}`;
  }

  // ==========================================
  // CONEXIÓN SSE (Server-Sent Events)
  // ==========================================

  function connectSSE() {
    if (eventSource) {
      eventSource.close();
    }

    eventSource = new EventSource('/api/stream');

    eventSource.onopen = () => {
      appendLog('[SISTEMA] Canal SSE establecido con el servidor.');
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
      // Reintento automático por parte del navegador
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
        statusText.textContent = 'FINALIZADO ✅';
        statusText.className = 'text-emerald-400 font-black';
        progressStatusLabel.textContent = 'Ejecución completada con éxito';
        appendLog('[SISTEMA] Pipeline ETL completado.');
        refreshCounts();
        break;

      case 'error':
        setRunningState(false);
        statusText.textContent = 'ERROR ⚠️';
        statusText.className = 'text-rose-500 font-black';
        appendLog(`[ERROR CRÍTICO] ${payload.error}`);
        alert(`Error en el pipeline: ${payload.error}`);
        break;

      default:
        break;
    }
  }

  // ==========================================
  // RENDERIZADO DE REGISTRO POR REGISTRO (CARDS)
  // ==========================================

  function renderRecordCard(rec) {
    if (emptyState) emptyState.style.display = 'none';

    recordsList.unshift(rec);
    if (recordsList.length > 300) recordsList.pop();

    badgeRecordsCount.textContent = recordsList.length;

    const isValid = !!rec.es_procesado;
    const cardStatus = isValid ? 'valid' : 'observed';

    const card = document.createElement('div');
    card.className = `record-card rounded-xl p-4 border transition-all shadow-sm ${
      isValid
        ? 'bg-white border-emerald-200 hover:border-emerald-400'
        : 'bg-amber-50/40 border-amber-300 hover:border-amber-400'
    }`;
    card.setAttribute('data-status', cardStatus);

    // Si hay un filtro activo y no coincide, ocultarlo
    if (currentCardFilter !== 'all' && currentCardFilter !== cardStatus) {
      card.style.display = 'none';
    }

    // Identificar motor utilizado
    let methodBadgeClass = 'bg-slate-100 text-slate-700 border-slate-200';
    let methodIcon = '⚙️';
    if (rec.metodo && rec.metodo.includes('IA')) {
      methodBadgeClass = 'bg-purple-100 text-purple-800 border-purple-300 font-bold';
      methodIcon = '🤖';
    } else if (rec.metodo && rec.metodo.includes('Híbrido')) {
      methodBadgeClass = 'bg-blue-100 text-blue-800 border-blue-300 font-bold';
      methodIcon = '⚡';
    }

    // Cabecera de la tarjeta
    const statusBadge = isValid
      ? `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-black bg-emerald-100 text-emerald-800 border border-emerald-300">
           ✅ CATASTRO VÁLIDO
         </span>`
      : `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-black bg-amber-200 text-amber-900 border border-amber-400 animate-pulse">
           ⚠️ OBSERVADO
         </span>`;

    // Normalizado Vía
    const viaText = rec.nom_via
      ? `<b class="text-slate-900">${rec.nom_via}</b> ${rec.num_via ? `<span class="text-slate-700 font-mono">#${rec.num_via}</span>` : ''}`
      : `<span class="text-slate-400 italic">No identificada</span>`;
    const viaBadge = rec.id_via
      ? `<span class="px-1.5 py-0.5 text-[10px] rounded bg-blue-100 text-blue-800 font-mono font-bold">ID: ${rec.id_via}</span>`
      : `<span class="px-1.5 py-0.5 text-[10px] rounded bg-slate-100 text-slate-500 font-mono">ID: -</span>`;

    // Normalizado Zona
    const zonaText = rec.nom_zona
      ? `<b class="text-slate-900">${rec.nom_zona}</b>`
      : `<span class="text-slate-400 italic">No identificada</span>`;
    const zonaBadge = rec.id_zona
      ? `<span class="px-1.5 py-0.5 text-[10px] rounded bg-indigo-100 text-indigo-800 font-mono font-bold">ID: ${rec.id_zona}</span>`
      : `<span class="px-1.5 py-0.5 text-[10px] rounded bg-slate-100 text-slate-500 font-mono">ID: -</span>`;

    // Mz / Lt / Slote
    const mzLtParts = [];
    if (rec.manzana) mzLtParts.push(`<b>Mz:</b> ${rec.manzana}`);
    if (rec.lote) mzLtParts.push(`<b>Lt:</b> ${rec.lote}`);
    if (rec.slote) mzLtParts.push(`<b>Slote:</b> ${rec.slote}`);
    const mzLtText = mzLtParts.length > 0 ? mzLtParts.join(' &bull; ') : '<span class="text-slate-400 italic">-</span>';

    // Bloque de observación detallada
    let obsBox = '';
    if (!isValid && rec.observacion) {
      obsBox = `
        <div class="mt-3 p-2.5 rounded-lg bg-amber-100/70 border border-amber-300 text-xs text-amber-900 flex items-start gap-2">
          <span class="text-sm">⚠️</span>
          <div>
            <span class="font-bold uppercase tracking-wider text-[11px] text-amber-950">Motivo de Observación:</span>
            <p class="font-mono mt-0.5 text-[11.5px]">${escapeHtml(rec.observacion)}</p>
          </div>
        </div>
      `;
    }

    card.innerHTML = `
      <div class="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-slate-100">
        <div class="flex items-center space-x-2">
          <span class="px-2 py-0.5 text-xs font-mono font-black bg-slate-800 text-white rounded">
            #${rec.id_licencia}
          </span>
          <span class="text-xs text-slate-500 font-medium">
            Registro ${rec.index} de ${rec.total}
          </span>
          <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] border ${methodBadgeClass}">
            ${methodIcon} ${escapeHtml(rec.metodo || 'Heurístico')}
          </span>
        </div>
        <div class="flex items-center space-x-2">
          ${statusBadge}
        </div>
      </div>

      <!-- Dirección Original -->
      <div class="mt-2.5">
        <span class="text-[11px] font-bold uppercase tracking-wider text-slate-400">Texto Original:</span>
        <div class="text-xs font-semibold text-slate-800 bg-slate-50 p-2 rounded-lg border border-slate-200 mt-1 font-mono">
          "${escapeHtml(rec.raw_text)}"
        </div>
      </div>

      <!-- Resultado Catastral Normalizado -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3 text-xs">
        <div class="p-2 bg-white rounded-lg border border-slate-100 shadow-2xs">
          <div class="flex items-center justify-between text-slate-500 mb-1">
            <span class="text-[10px] font-bold uppercase">🛣️ Vía Oficial:</span>
            ${viaBadge}
          </div>
          <div>${viaText}</div>
        </div>

        <div class="p-2 bg-white rounded-lg border border-slate-100 shadow-2xs">
          <div class="flex items-center justify-between text-slate-500 mb-1">
            <span class="text-[10px] font-bold uppercase">🏘️ Zona Oficial:</span>
            ${zonaBadge}
          </div>
          <div>${zonaText}</div>
        </div>

        <div class="p-2 bg-white rounded-lg border border-slate-100 shadow-2xs">
          <div class="text-[10px] font-bold uppercase text-slate-500 mb-1">📐 Mz / Lt / Slote:</div>
          <div>${mzLtText}</div>
        </div>
      </div>

      ${obsBox}
    `;

    recordsContainer.insertBefore(card, recordsContainer.firstChild);
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
      progressCountLabel.textContent = `${processed} de ${total} registros procesados`;

      const validPct = ((valid / total) * 100).toFixed(1);
      const obsPct = ((observed / total) * 100).toFixed(1);
      statValidPct.textContent = `${validPct}%`;
      statObservedPct.textContent = `${obsPct}%`;
    }

    if (stats.elapsed_seconds != null) {
      statElapsed.textContent = `${stats.elapsed_seconds}s`;
      if (stats.elapsed_seconds > 0 && processed > 0) {
        const speed = (processed / stats.elapsed_seconds).toFixed(1);
        statSpeed.textContent = `${speed} reg/seg`;
      }
    }
  }

  function appendLog(message) {
    const timestamp = new Date().toLocaleTimeString();
    const line = document.createElement('div');
    line.className = 'hover:bg-slate-900 px-1 py-0.5 rounded leading-relaxed';

    let colorClass = 'text-slate-300';
    if (message.includes('ERROR')) colorClass = 'text-rose-400 font-bold';
    else if (message.includes('✅') || message.includes('exitosamente')) colorClass = 'text-emerald-400';
    else if (message.includes('⚠️') || message.includes('Aviso')) colorClass = 'text-amber-400';
    else if (message.includes('🤖')) colorClass = 'text-purple-300';
    else if (message.includes('⏳')) colorClass = 'text-cyan-300';

    line.innerHTML = `<span class="text-slate-500">[${timestamp}]</span> <span class="${colorClass}">${escapeHtml(message)}</span>`;
    logsContainer.appendChild(line);

    // Auto-scroll al fondo
    viewLogs.scrollTop = viewLogs.scrollHeight;
  }

  // ==========================================
  // ACCIONES Y MANEJADORES DE EVENTOS
  // ==========================================

  function setupEventHandlers() {
    // Cambio de esquema
    schemaSelect.addEventListener('change', () => {
      activeSchemaBadge.textContent = `Esquema: ${schemaSelect.value}`;
      refreshCounts();
    });

    tableInput.addEventListener('change', () => {
      refreshCounts();
    });

    // Envío del formulario (Iniciar)
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (isRunning) return;

      const payload = {
        schema_name: schemaSelect.value,
        table_name: tableInput.value.trim(),
        filter_mode: filterSelect.value,
        limit: limitInput.value ? parseInt(limitInput.value, 10) : null,
        batch_size: parseInt(batchInput.value, 10) || 10,
        require_ai: requireAiCheckbox.checked,
      };

      try {
        setRunningState(true);
        statusText.textContent = 'EJECUTANDO ⚡';
        statusText.className = 'text-blue-400 font-black';
        progressStatusLabel.textContent = `Procesando en esquema [${payload.schema_name}]...`;

        // Switch to records view
        switchView('records');

        const res = await fetch('/api/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || 'Error al iniciar pipeline');
        }

        appendLog(`[SISTEMA] Pipeline iniciado en lote de ${payload.batch_size} registros.`);
      } catch (err) {
        setRunningState(false);
        alert(`No se pudo iniciar: ${err.message}`);
        appendLog(`[ERROR] Inicio fallido: ${err.message}`);
      }
    });

    // Detener pipeline
    btnStop.addEventListener('click', async () => {
      if (!isRunning) return;
      btnStop.disabled = true;
      btnStop.innerHTML = '<span>⏳</span><span>Deteniendo...</span>';

      try {
        const res = await fetch('/api/stop', { method: 'POST' });
        const data = await res.json();
        appendLog(`[SISTEMA] ${data.message}`);
      } catch (err) {
        appendLog(`[ERROR] Fallo al solicitar detención: ${err.message}`);
      }
    });

    // Diagnóstico Rápido
    btnQuickDiag.addEventListener('click', () => {
      diagModal.classList.remove('hidden');
    });

    btnCloseDiag.addEventListener('click', () => {
      diagModal.classList.add('hidden');
    });

    btnRunSampleAi.addEventListener('click', async () => {
      btnRunSampleAi.disabled = true;
      btnRunSampleAi.textContent = 'Consultando Ollama...';
      try {
        const res = await fetch('/api/test-ai', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          diagAiDetail.textContent = `✅ Éxito (${data.latency_ms} ms) - Modelo: ${data.model}\nResultado: ${JSON.stringify(data.parsed)}`;
        } else {
          diagAiDetail.textContent = `❌ Falló: ${data.message}`;
        }
      } catch (err) {
        diagAiDetail.textContent = `❌ Error: ${err.message}`;
      } finally {
        btnRunSampleAi.disabled = false;
        btnRunSampleAi.textContent = 'Probar Inferencia IA en Vivo';
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

    // Filtros de tarjetas
    filterChips.forEach(chip => {
      chip.addEventListener('click', () => {
        filterChips.forEach(c => {
          c.classList.remove('bg-slate-200', 'text-slate-800');
          c.classList.add('text-slate-600');
        });
        chip.classList.add('bg-slate-200', 'text-slate-800');
        chip.classList.remove('text-slate-600');

        currentCardFilter = chip.getAttribute('data-filter');
        applyCardFilter(currentCardFilter);
      });
    });
  }

  function applyCardFilter(filter) {
    const cards = recordsContainer.querySelectorAll('.record-card');
    cards.forEach(c => {
      const status = c.getAttribute('data-status');
      if (filter === 'all' || filter === status) {
        c.style.display = 'block';
      } else {
        c.style.display = 'none';
      }
    });
  }

  function switchView(target) {
    if (target === 'records') {
      viewRecords.classList.remove('hidden');
      viewLogs.classList.add('hidden');
      tabBtnRecords.className = 'px-3.5 py-1.5 rounded-lg text-xs font-bold bg-white text-slate-900 shadow-sm border border-slate-200 flex items-center gap-1.5 transition';
      tabBtnLogs.className = 'px-3.5 py-1.5 rounded-lg text-xs font-bold text-slate-600 hover:text-slate-900 border border-transparent transition flex items-center gap-1.5';
    } else {
      viewRecords.classList.add('hidden');
      viewLogs.classList.remove('hidden');
      tabBtnLogs.className = 'px-3.5 py-1.5 rounded-lg text-xs font-bold bg-white text-slate-900 shadow-sm border border-slate-200 flex items-center gap-1.5 transition';
      tabBtnRecords.className = 'px-3.5 py-1.5 rounded-lg text-xs font-bold text-slate-600 hover:text-slate-900 border border-transparent transition flex items-center gap-1.5';
    }
  }

  function setRunningState(running) {
    isRunning = running;
    if (running) {
      btnStart.disabled = true;
      btnStart.classList.add('opacity-50', 'cursor-not-allowed');
      btnStop.disabled = false;
      btnStop.classList.remove('bg-slate-200', 'text-slate-400', 'cursor-not-allowed');
      btnStop.classList.add('bg-rose-600', 'hover:bg-rose-700', 'text-white', 'cursor-pointer');
      schemaSelect.disabled = true;
      tableInput.disabled = true;
      filterSelect.disabled = true;
      limitInput.disabled = true;
      batchInput.disabled = true;
    } else {
      btnStart.disabled = false;
      btnStart.classList.remove('opacity-50', 'cursor-not-allowed');
      btnStop.disabled = true;
      btnStop.classList.add('bg-slate-200', 'text-slate-400', 'cursor-not-allowed');
      btnStop.classList.remove('bg-rose-600', 'hover:bg-rose-700', 'text-white', 'cursor-pointer');
      btnStop.innerHTML = '<span>⏹️</span><span>Detener Seguro</span>';
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
      console.warn('Error refrescando conteos:', err);
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // Arrancar
  init();
});
