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
    end_time_str: Optional[str] = Field(default=None, description="Hora de fin del rango horario en formato HH:MM (24h).")
    max_records: Optional[int] = Field(default=None, description="Límite de registros a procesar (None = todos los pendientes)")
    num_workers: int = Field(default=2, ge=1, le=16, description="Cantidad de hilos concurrentes para la ejecución programada")
    batch_size: int = Field(default=50, ge=1, le=200, description="Tamaño del lote de base de datos")
    target_schema: str = Field(default="public", description="Esquema objetivo (por defecto 'public')")
    target_table: str = Field(default="tb_direccion", description="Tabla objetivo (por defecto 'tb_direccion')")
    source_mode: str = Field(default="central_tb_direccion", description="Modo de origen ('central_tb_direccion' o 'source_table')")
    filter_mode: str = Field(default="pending", description="Filtro de registros ('pending', 'all', 'observed')")
    require_ai: bool = Field(default=True, description="Requiere normalización con modelo de Inteligencia Artificial")
    last_run_at: Optional[str] = Field(default=None, description="Fecha y hora ISO del último disparo")
    last_run_status: Optional[str] = Field(default=None, description="Estado del último disparo (SUCCESS, RUNNING, ERROR, STOPPED, STOPPED_BY_SCHEDULE)")
    last_run_message: Optional[str] = Field(default=None, description="Detalle del último resultado")
    next_run_at: Optional[str] = Field(default=None, description="Próxima fecha y hora ISO programada para el disparo")


def get_device_timezone_info() -> Dict[str, str]:
    """Obtiene la información de zona horaria y hora local del dispositivo host."""
    now_local = datetime.now()
    tz_name = now_local.astimezone().tzname() or "Local"
    offset_str = now_local.astimezone().strftime("%z")
    if len(offset_str) == 5:
        offset_fmt = f"UTC{offset_str[:3]}:{offset_str[3:]}"
    else:
        offset_fmt = "UTC"
    return {
        "tz_name": tz_name,
        "offset": offset_fmt,
        "description": f"{tz_name} ({offset_fmt})",
        "current_local_time": now_local.strftime("%Y-%m-%d %H:%M:%S"),
        "current_time_hm": now_local.strftime("%H:%M"),
    }


class SchedulerService:
    """Servicio autónomo de monitoreo y disparo programado diario en segundo plano."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        on_trigger: Optional[Callable[[SchedulerConfig], Any]] = None,
        on_stop: Optional[Callable[[], Any]] = None,
    ):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.on_trigger = on_trigger
        self.on_stop = on_stop
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._active_cycle_id: Optional[str] = None
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
        """Calcula el próximo datetime exacto en que debe ejecutarse el disparo diario en la hora local del dispositivo."""
        now = datetime.now()
        try:
            parts = str(time_str).strip().split(":")
            hh = int(parts[0])
            mm = int(parts[1]) if len(parts) > 1 else 0
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                raise ValueError()
        except Exception:
            hh, mm = 23, 0

        target_today = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target_today > now:
            return target_today
        else:
            return target_today + timedelta(days=1)

    @staticmethod
    def is_in_time_window(
        start_hm: str,
        end_hm: Optional[str] = None,
        current_dt: Optional[datetime] = None,
    ) -> bool:
        """Evalúa si un momento dado se encuentra dentro del rango de horario configurado.
        
        Soporta:
        - Rango nocturno con cruce de medianoche: start='22:00', end='06:00'
          (Activo si current >= 22:00 o current < 06:00)
        - Rango diurno en el mismo día: start='08:00', end='16:00'
          (Activo si 08:00 <= current < 16:00)
        - Disparo puntual (sin hora fin): coincide exactamente el minuto HH:MM
        """
        now = current_dt or datetime.now()
        cur_hm = now.strftime("%H:%M")

        try:
            sp = start_hm.strip().split(":")
            s_val = f"{int(sp[0]):02d}:{int(sp[1]):02d}"
        except Exception:
            s_val = "23:00"

        if not end_hm or not str(end_hm).strip():
            return cur_hm == s_val

        try:
            ep = str(end_hm).strip().split(":")
            e_val = f"{int(ep[0]):02d}:{int(ep[1]):02d}"
        except Exception:
            return cur_hm == s_val

        if s_val < e_val:
            return s_val <= cur_hm < e_val
        elif s_val > e_val:
            return cur_hm >= s_val or cur_hm < e_val
        else:
            return True

    def is_currently_in_window(self, current_dt: Optional[datetime] = None) -> bool:
        """Indica si el momento actual se encuentra dentro de la ventana de ejecución configurada."""
        return self.is_in_time_window(
            start_hm=self.config.time_str,
            end_hm=self.config.end_time_str,
            current_dt=current_dt,
        )

    def get_current_window_cycle_id(self, current_dt: Optional[datetime] = None) -> Optional[str]:
        """Genera un identificador único para el ciclo actual de la ventana horaria (estable a través de la medianoche)."""
        now = current_dt or datetime.now()
        if not self.is_currently_in_window(now):
            return None
        s_val = self.config.time_str
        e_val = self.config.end_time_str
        if e_val and s_val > e_val:
            cur_hm = now.strftime("%H:%M")
            if cur_hm < e_val:
                cycle_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                cycle_date = now.strftime("%Y-%m-%d")
        else:
            cycle_date = now.strftime("%Y-%m-%d")
        return f"cycle_{cycle_date}_{s_val}"

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

            if end_time_str is not None and str(end_time_str).strip():
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
                self._active_cycle_id = None

            try:
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self.config.model_dump(), f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.error("Error al persistir scheduler: %s", e)

            return self.config

    def get_status_dict(self) -> Dict[str, Any]:
        """Retorna el estado completo del scheduler para consumo de la UI y validación de inicio manual."""
        data = self.config.model_dump()
        next_dt_str = self.config.next_run_at
        countdown_human = "Programación inactiva"
        seconds_remaining = None
        in_window = self.is_currently_in_window()

        if self.config.enabled:
            if in_window:
                countdown_human = "En ventana activa de ejecución"
                seconds_remaining = 0
            elif next_dt_str:
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
                        countdown_human = "Por iniciarse en breve"
                except Exception:
                    pass

        range_desc = self.config.time_str
        if self.config.end_time_str:
            range_desc += f" a {self.config.end_time_str}"

        data["scheduled_time"] = self.config.time_str
        data["end_time"] = self.config.end_time_str
        data["next_run"] = self.config.next_run_at
        data["seconds_remaining"] = seconds_remaining
        data["countdown_human"] = countdown_human
        data["is_monitoring"] = bool(self._monitor_thread and self._monitor_thread.is_alive())
        data["is_in_window"] = in_window
        data["range_human"] = range_desc
        data["manual_start_blocked"] = bool(self.config.enabled)
        data["timezone"] = get_device_timezone_info()
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
        tz_inf = get_device_timezone_info()
        logger.info(
            "Scheduler de ejecuciones diarias iniciado 24/7. Horario: %s - %s (%s). Activo: %s.",
            self.config.time_str,
            self.config.end_time_str or "sin límite",
            tz_inf["description"],
            self.config.enabled,
        )

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
        """Bucle de evaluación continua en segundo plano cada 10 segundos."""
        while not self._stop_event.is_set():
            try:
                if self.config.enabled:
                    now = datetime.now()
                    in_window = self.is_currently_in_window(now)
                    cycle_id = self.get_current_window_cycle_id(now)

                    if in_window:
                        if self._active_cycle_id != cycle_id:
                            self._active_cycle_id = cycle_id
                            logger.info(
                                "[SCHEDULER] 🌙 Ventana de horario diario alcanzada (%s a %s). Iniciando disparo automático...",
                                self.config.time_str,
                                self.config.end_time_str or "sin límite",
                            )
                            self.config.last_run_at = now.isoformat()
                            self.config.last_run_status = "RUNNING"
                            self.config.last_run_message = (
                                f"Disparo automático iniciado dentro de la ventana {self.config.time_str} - {self.config.end_time_str or ''}."
                            )
                            self.save_config(self.config)

                            if self.on_trigger:
                                t = threading.Thread(
                                    target=self._execute_trigger,
                                    name="SchedulerDailyExecutionThread",
                                    daemon=True,
                                )
                                t.start()
                    else:
                        if self._active_cycle_id is not None:
                            logger.info(
                                "[SCHEDULER] ☀️ Fin del rango horario programado alcanzado (%s). Solicitando detención automática...",
                                self.config.end_time_str or self.config.time_str,
                            )
                            self._active_cycle_id = None
                            if self.on_stop:
                                try:
                                    self.on_stop()
                                except Exception as ex_stop:
                                    logger.error("[SCHEDULER] Error al ejecutar callback on_stop: %s", ex_stop)
                            self.config.last_run_status = "STOPPED_BY_SCHEDULE"
                            self.config.last_run_message = (
                                f"Proceso detenido automáticamente al alcanzar fin de ventana ({self.config.end_time_str})."
                            )
                            self.save_config(self.config)

                        next_dt = self.compute_next_run(self.config.time_str)
                        if self.config.next_run_at != next_dt.isoformat():
                            self.config.next_run_at = next_dt.isoformat()
                            self.save_config(self.config)

                self._stop_event.wait(10.0)

            except Exception as e:
                logger.error("[SCHEDULER] Error inesperado en monitor loop: %s", e)
                self._stop_event.wait(15.0)
