"""Módulo de servicio para la programación y persistencia de horarios diarios de ejecución (Scheduler).

Permite configurar y persistir horarios fuera de horario laboral (nocturnos) para procesar
con IA las direcciones pendientes de Catastro Central (public.tb_direccion) de forma desatendida,
evitando la saturación del servidor de inferencia compartido con otros sistemas municipales.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("etl_mpch.scheduler_service")

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "scheduler_config.json")


class SchedulerConfig(BaseModel):
    """Modelo de configuración persistente para la programación diaria desatendida."""
    enabled: bool = Field(default=False, description="Indica si la ejecución diaria automática está activa")
    time_str: str = Field(default="23:00", description="Hora de disparo diario en formato HH:MM (24h)")
    max_records: Optional[int] = Field(default=None, description="Límite de registros a procesar (None = todos los pendientes)")
    num_workers: int = Field(default=2, ge=1, le=16, description="Cantidad de hilos concurrentes para la ejecución programada")
    batch_size: int = Field(default=50, ge=1, le=200, description="Tamaño del lote de base de datos")
    target_schema: str = Field(default="public", description="Esquema objetivo (por defecto 'public')")
    target_table: str = Field(default="tb_direccion", description="Tabla objetivo (por defecto 'tb_direccion')")
    source_mode: str = Field(default="central_tb_direccion", description="Modo de origen ('central_tb_direccion' o 'source_table')")
    filter_mode: str = Field(default="pending", description="Filtro de registros ('pending', 'all', 'observed')")
    require_ai: bool = Field(default=True, description="Requiere normalización con modelo de Inteligencia Artificial")
    last_run_at: Optional[str] = Field(default=None, description="Fecha y hora ISO del último disparo")
    last_run_status: Optional[str] = Field(default=None, description="Estado del último disparo (SUCCESS, RUNNING, ERROR, STOPPED)")
    last_run_message: Optional[str] = Field(default=None, description="Detalle del último resultado")
    next_run_at: Optional[str] = Field(default=None, description="Próxima fecha y hora ISO programada para el disparo")
    end_time_str: Optional[str] = Field(default=None, description="Hora de fin del rango horario en formato HH:MM (24h). Si se define, el proceso no iniciará fuera de este rango y será detenido automáticamente al superarla.")


class SchedulerService:
    """Servicio autónomo de monitoreo y disparo programado diario en segundo plano."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        on_trigger: Optional[Callable[[SchedulerConfig], Any]] = None,
    ):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.on_trigger = on_trigger
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._last_triggered_date: Optional[str] = None
        self.config: SchedulerConfig = self.load_config()

        # Asegurar cálculo inicial del próximo disparo si está habilitado
        if self.config.enabled:
            next_dt = self.compute_next_run(self.config.time_str)
            self.config.next_run_at = next_dt.isoformat()
            self.save_config(self.config)

    def load_config(self) -> SchedulerConfig:
        """Carga la configuración desde el archivo JSON persistente o genera una con valores seguros por defecto."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                config = SchedulerConfig(**data)
                return config
            except Exception as e:
                logger.warning("Aviso al leer configuración de scheduler desde %s: %s. Creando configuración por defecto.", self.config_path, e)

        # Configuración por defecto segura
        default_cfg = SchedulerConfig()
        self.save_config(default_cfg)
        return default_cfg

    def save_config(self, new_config: SchedulerConfig) -> bool:
        """Persiste la configuración en disco en formato JSON atómico."""
        with self._lock:
            self.config = new_config
            try:
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self.config.model_dump(), f, indent=2, ensure_ascii=False)
                return True
            except Exception as e:
                logger.error("Error al persistir configuración de scheduler en %s: %s", self.config_path, e)
                return False

    @staticmethod
    def compute_next_run(time_str: str) -> datetime:
        """Calcula el próximo datetime exacto en que debe ejecutarse el disparo diario."""
        now = datetime.now()
        try:
            parts = str(time_str).strip().split(":")
            hh = int(parts[0])
            mm = int(parts[1]) if len(parts) > 1 else 0
        except Exception:
            hh, mm = 23, 0

        target_today = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target_today > now:
            return target_today
        else:
            return target_today + timedelta(days=1)

    def update_settings(
        self,
        enabled: bool,
        time_str: str,
        num_workers: Optional[int] = None,
        max_records: Optional[int] = None,
        batch_size: Optional[int] = None,
        target_schema: Optional[str] = None,
        target_table: Optional[str] = None,
        end_time_str: Optional[str] = None,
    ) -> SchedulerConfig:
        """Actualiza la configuración programada y recalcula la próxima ejecución."""
        with self._lock:
            # Validar formato de hora HH:MM
            clean_time = str(time_str).strip()
            try:
                p = clean_time.split(":")
                hh = int(p[0])
                mm = int(p[1]) if len(p) > 1 else 0
                if not (0 <= hh <= 23 and 0 <= mm <= 59):
                    raise ValueError()
                clean_time = f"{hh:02d}:{mm:02d}"
            except Exception:
                clean_time = self.config.time_str or "23:00"

            self.config.enabled = bool(enabled)
            self.config.time_str = clean_time

            if num_workers is not None:
                self.config.num_workers = max(1, min(16, int(num_workers)))
            if max_records is not None:
                self.config.max_records = max(1, int(max_records)) if max_records > 0 else None
            if batch_size is not None:
                self.config.batch_size = max(1, min(200, int(batch_size)))
            if target_schema is not None:
                self.config.target_schema = target_schema
            if target_table is not None:
                self.config.target_table = target_table
            if end_time_str is not None:
                clean_end = str(end_time_str).strip()
                try:
                    ep = clean_end.split(':')
                    ehh = int(ep[0])
                    emm = int(ep[1]) if len(ep) > 1 else 0
                    if not (0 <= ehh <= 23 and 0 <= emm <= 59):
                        raise ValueError()
                    self.config.end_time_str = f"{ehh:02d}:{emm:02d}"
                except Exception:
                    self.config.end_time_str = None
            else:
                self.config.end_time_str = None

            if self.config.enabled:
                next_dt = self.compute_next_run(self.config.time_str)
                self.config.next_run_at = next_dt.isoformat()
            else:
                self.config.next_run_at = None

            # Persistir
            try:
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self.config.model_dump(), f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.error("Error al persistir scheduler: %s", e)

            return self.config

    def get_status_dict(self) -> Dict[str, Any]:
        """Retorna el estado completo del scheduler para consumo de la UI."""
        data = self.config.model_dump()
        next_dt_str = self.config.next_run_at
        countdown_human = "Programación inactiva"
        seconds_remaining = None

        if self.config.enabled and next_dt_str:
            try:
                next_dt = datetime.fromisoformat(next_dt_str)
                now = datetime.now()
                delta = next_dt - now
                total_secs = int(delta.total_seconds())
                if total_secs > 0:
                    seconds_remaining = total_secs
                    hours = total_secs // 3600
                    minutes = (total_secs % 3600) // 60
                    if hours > 0:
                        countdown_human = f"en ~{hours}h {minutes:02d}m"
                    else:
                        countdown_human = f"en ~{minutes} min"
                else:
                    countdown_human = "Por ejecutarse en breve"
            except Exception:
                pass

        data["scheduled_time"] = self.config.time_str
        data["end_time"] = self.config.end_time_str
        data["next_run"] = self.config.next_run_at
        data["seconds_remaining"] = seconds_remaining
        data["countdown_human"] = countdown_human
        data["is_monitoring"] = bool(self._monitor_thread and self._monitor_thread.is_alive())
        return data

    def start(self):
        """Inicia el hilo monitor en segundo plano si no está activo."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="SchedulerMonitorThread",
            daemon=True,
        )
        self._monitor_thread.start()
        logger.info("Scheduler de ejecuciones diarias iniciado. Horario: %s - %s (Activo: %s).", self.config.time_str, self.config.end_time_str or "sin límite", self.config.enabled)

    def stop(self):
        """Detiene el hilo monitor en segundo plano."""
        self._stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)
        logger.info("Scheduler de ejecuciones diarias detenido.")

    def trigger_now(self) -> Dict[str, Any]:
        """Fuerza un disparo manual o de prueba inmediato del scheduler."""
        logger.info("[SCHEDULER] Disparo manual/prueba solicitado.")
        now = datetime.now()
        self.config.last_run_at = now.isoformat()
        self.config.last_run_status = "RUNNING"
        self.config.last_run_message = "Disparo forzado/manual de prueba iniciado."
        self.save_config(self.config)

        if self.on_trigger:
            # Ejecutar callback en hilo separado para no bloquear la API
            t = threading.Thread(
                target=self._execute_trigger,
                name="SchedulerForcedExecutionThread",
                daemon=True,
            )
            t.start()
            return {"status": "TRIGGERED", "message": "Ejecución programada iniciada de inmediato en segundo plano."}
        else:
            return {"status": "NO_CALLBACK", "message": "No hay callback de ejecución registrado en el scheduler."}

    def _execute_trigger(self):
        """Ejecuta el callback registrado capturando excepciones."""
        try:
            if self.on_trigger:
                self.on_trigger(self.config)
        except Exception as e:
            logger.error("[SCHEDULER] Error al ejecutar callback de disparo: %s", e)
            self.config.last_run_status = "ERROR"
            self.config.last_run_message = f"Error al disparar: {e}"
            self.save_config(self.config)

    def _monitor_loop(self):
        """Bucle de evaluación continua en segundo plano."""
        while not self._stop_event.is_set():
            try:
                if self.config.enabled:
                    now = datetime.now()
                    today_str = now.strftime("%Y-%m-%d")
                    current_hm = now.strftime("%H:%M")

                    # Verificar si coincide la hora de inicio y no se ha disparado hoy
                    # y que aún estemos dentro del rango horario configurado (si existe hora fin)
                    within_window = True
                    if self.config.end_time_str:
                        within_window = current_hm <= self.config.end_time_str
                        if not within_window and self._last_triggered_date == today_str:
                            # Fuera del rango: si hay proceso corriendo pedir detención
                            pass  # La detención la gestiona el pipeline worker según su propia lógica
                    if current_hm == self.config.time_str and self._last_triggered_date != today_str and within_window:
                        self._last_triggered_date = today_str
                        logger.info("[SCHEDULER] Coincidencia horaria alcanzada (%s). Iniciando disparo automático diario...", current_hm)
                        
                        self.config.last_run_at = now.isoformat()
                        self.config.last_run_status = "RUNNING"
                        self.config.last_run_message = f"Disparo automático diario ejecutado a las {current_hm}."

                        # Recalcular siguiente disparo para mañana
                        next_dt = self.compute_next_run(self.config.time_str)
                        self.config.next_run_at = next_dt.isoformat()
                        self.save_config(self.config)

                        # Ejecutar en hilo desacoplado
                        if self.on_trigger:
                            t = threading.Thread(
                                target=self._execute_trigger,
                                name="SchedulerDailyExecutionThread",
                                daemon=True,
                            )
                            t.start()

                # Esperar 20 segundos antes de la siguiente comprobación
                self._stop_event.wait(20.0)

            except Exception as e:
                logger.error("[SCHEDULER] Error inesperado en monitor loop: %s", e)
                self._stop_event.wait(30.0)
