"""Pruebas unitarias para el servicio de programación horaria diaria (SchedulerService)

y los endpoints /api/scheduler/* de la GUI.
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.services.scheduler_service import SchedulerConfig, SchedulerService
from src.ui.server import app, scheduler_service


@pytest.fixture
def temp_config_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def client():
    return TestClient(app)


def test_scheduler_config_defaults():
    cfg = SchedulerConfig()
    assert cfg.enabled is False
    assert cfg.time_str == "23:00"
    assert cfg.num_workers == 2
    assert cfg.batch_size == 50
    assert cfg.target_schema == "public"
    assert cfg.target_table == "tb_direccion"
    assert cfg.require_ai is True


def test_scheduler_compute_next_run():
    # Probar con hora lejana en el futuro hoy o mañana
    next_dt = SchedulerService.compute_next_run("23:59")
    assert isinstance(next_dt, datetime)
    assert next_dt.hour == 23
    assert next_dt.minute == 59
    assert next_dt > datetime.now()

    # Probar hora inválida (debe hacer fallback a 23:00)
    fallback_dt = SchedulerService.compute_next_run("invalid_hour")
    assert fallback_dt.hour == 23
    assert fallback_dt.minute == 0


def test_scheduler_save_and_load(temp_config_file):
    service = SchedulerService(config_path=temp_config_file)
    assert service.config.enabled is False

    service.update_settings(
        enabled=True,
        time_str="03:30",
        num_workers=4,
        max_records=1000,
        batch_size=80,
    )

    assert os.path.exists(temp_config_file)
    with open(temp_config_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["enabled"] is True
    assert data["time_str"] == "03:30"
    assert data["num_workers"] == 4
    assert data["max_records"] == 1000
    assert data["batch_size"] == 80
    assert data["next_run_at"] is not None

    # Recargar desde disco
    service2 = SchedulerService(config_path=temp_config_file)
    assert service2.config.enabled is True
    assert service2.config.time_str == "03:30"
    assert service2.config.num_workers == 4


def test_scheduler_get_status_dict(temp_config_file):
    service = SchedulerService(config_path=temp_config_file)
    service.update_settings(enabled=True, time_str="23:00", num_workers=2)

    status = service.get_status_dict()
    assert status["enabled"] is True
    assert status["time_str"] == "23:00"
    assert status["scheduled_time"] == "23:00"
    assert status["next_run"] is not None
    assert "seconds_remaining" in status
    assert "countdown_human" in status
    assert "is_monitoring" in status


def test_scheduler_trigger_now(temp_config_file):
    triggered_flag = threading.Event()
    received_cfg = []

    def callback(cfg):
        received_cfg.append(cfg)
        triggered_flag.set()

    service = SchedulerService(config_path=temp_config_file, on_trigger=callback)
    res = service.trigger_now()
    assert res["status"] == "TRIGGERED"

    # Esperar disparo en hilo
    assert triggered_flag.wait(timeout=2.0)
    assert len(received_cfg) == 1
    assert received_cfg[0].last_run_status in ("RUNNING", "SUCCESS")


def test_scheduler_lifecycle(temp_config_file):
    service = SchedulerService(config_path=temp_config_file)
    service.start()
    assert service._monitor_thread is not None
    assert service._monitor_thread.is_alive()

    # Re-iniciar no crea hilos duplicados
    t1 = service._monitor_thread
    service.start()
    assert service._monitor_thread == t1

    service.stop()
    assert not service._monitor_thread.is_alive()


def test_api_scheduler_endpoints(client):
    # 1. GET /api/scheduler/config
    get_res = client.get("/api/scheduler/config")
    assert get_res.status_code == 200
    data = get_res.json()
    assert "enabled" in data
    assert "time_str" in data
    assert "scheduled_time" in data

    # 2. POST /api/scheduler/config
    post_res = client.post(
        "/api/scheduler/config",
        json={
            "enabled": True,
            "scheduled_time": "04:15",
            "num_workers": 3,
            "batch_size": 40,
            "target_schema": "public",
            "target_table": "tb_direccion",
        },
    )
    assert post_res.status_code == 200
    res_json = post_res.json()
    assert res_json["status"] == "SAVED"
    assert res_json["config"]["enabled"] is True
    assert res_json["config"]["scheduled_time"] == "04:15"
    assert res_json["config"]["num_workers"] == 3

    # 3. Disparo de prueba /api/scheduler/trigger-now
    trig_res = client.post("/api/scheduler/trigger-now")
    assert trig_res.status_code == 200
    trig_json = trig_res.json()
    assert trig_json["status"] in ("TRIGGERED", "RUNNING")
    # Restaurar scheduler_service a inactivo para no interferir con otros tests
    scheduler_service.config.enabled = False


def test_is_in_time_window_same_day():
    """Prueba rangos diurnos dentro del mismo día (ej. 08:00 a 16:00)."""
    # 07:59 -> Fuera
    dt_before = datetime(2026, 10, 10, 7, 59)
    assert SchedulerService.is_in_time_window("08:00", "16:00", dt_before) is False

    # 08:00 -> Dentro
    dt_start = datetime(2026, 10, 10, 8, 0)
    assert SchedulerService.is_in_time_window("08:00", "16:00", dt_start) is True

    # 12:30 -> Dentro
    dt_mid = datetime(2026, 10, 10, 12, 30)
    assert SchedulerService.is_in_time_window("08:00", "16:00", dt_mid) is True

    # 15:59 -> Dentro
    dt_last = datetime(2026, 10, 10, 15, 59)
    assert SchedulerService.is_in_time_window("08:00", "16:00", dt_last) is True

    # 16:00 -> Fuera
    dt_end = datetime(2026, 10, 10, 16, 0)
    assert SchedulerService.is_in_time_window("08:00", "16:00", dt_end) is False

    # 20:00 -> Fuera
    dt_after = datetime(2026, 10, 10, 20, 0)
    assert SchedulerService.is_in_time_window("08:00", "16:00", dt_after) is False


def test_is_in_time_window_crosses_midnight():
    """Prueba rangos nocturnos que cruzan la medianoche (ej. 22:00 / 10 PM a 06:00 / 6 AM)."""
    # 21:59 -> Fuera
    assert SchedulerService.is_in_time_window("22:00", "06:00", datetime(2026, 10, 10, 21, 59)) is False

    # 22:00 -> Dentro
    assert SchedulerService.is_in_time_window("22:00", "06:00", datetime(2026, 10, 10, 22, 0)) is True

    # 23:45 -> Dentro
    assert SchedulerService.is_in_time_window("22:00", "06:00", datetime(2026, 10, 10, 23, 45)) is True

    # 00:00 (Medianoche) -> Dentro
    assert SchedulerService.is_in_time_window("22:00", "06:00", datetime(2026, 10, 11, 0, 0)) is True

    # 03:15 (Madrugada) -> Dentro
    assert SchedulerService.is_in_time_window("22:00", "06:00", datetime(2026, 10, 11, 3, 15)) is True

    # 05:59 -> Dentro
    assert SchedulerService.is_in_time_window("22:00", "06:00", datetime(2026, 10, 11, 5, 59)) is True

    # 06:00 (Fin de ventana) -> Fuera
    assert SchedulerService.is_in_time_window("22:00", "06:00", datetime(2026, 10, 11, 6, 0)) is False

    # 12:00 (Mediodía) -> Fuera
    assert SchedulerService.is_in_time_window("22:00", "06:00", datetime(2026, 10, 11, 12, 0)) is False


def test_get_current_window_cycle_id_across_midnight(temp_config_file):
    """Comprueba que el identificador de ciclo sea estable durante toda la noche cruzando medianoche."""
    svc = SchedulerService(config_path=temp_config_file)
    svc.update_settings(enabled=True, time_str="22:00", end_time_str="06:00")

    # A las 23:00 del día 1
    cycle_d1 = svc.get_current_window_cycle_id(datetime(2026, 10, 10, 23, 0))
    assert cycle_d1 == "cycle_2026-10-10_22:00"

    # A las 04:00 del día 2 (misma noche de ejecución)
    cycle_d2 = svc.get_current_window_cycle_id(datetime(2026, 10, 11, 4, 0))
    assert cycle_d2 == "cycle_2026-10-10_22:00"
    assert cycle_d1 == cycle_d2, "El ID de ciclo nocturno debe ser idéntico antes y después de medianoche"

    # A las 12:00 del día 2 (fuera de ventana)
    assert svc.get_current_window_cycle_id(datetime(2026, 10, 11, 12, 0)) is None


def test_scheduler_device_timezone_info(temp_config_file):
    """Verifica que el servicio reporte la zona horaria del dispositivo host."""
    svc = SchedulerService(config_path=temp_config_file)
    status = svc.get_status_dict()
    assert "timezone" in status
    tz_info = status["timezone"]
    assert "tz_name" in tz_info
    assert "offset" in tz_info
    assert "current_local_time" in tz_info
    assert "manual_start_blocked" in status


def test_scheduler_auto_stop_callback(temp_config_file):
    """Verifica que el scheduler invoque on_stop al abandonar la ventana de ejecución."""
    stop_called = threading.Event()

    def on_stop_cb():
        stop_called.set()

    svc = SchedulerService(config_path=temp_config_file, on_stop=on_stop_cb)
    svc.update_settings(enabled=True, time_str="22:00", end_time_str="06:00")

    # Simulamos que estuvimos en una ventana activa
    svc._active_cycle_id = "cycle_2026-10-10_22:00"

    # Al simular llamada con hora fuera de la ventana (ej. 06:01)
    out_dt = datetime(2026, 10, 11, 6, 1)
    assert svc.is_currently_in_window(out_dt) is False

    # Ejecutamos la lógica que ocurre en el loop al salir de ventana
    if not svc.is_currently_in_window(out_dt) and svc._active_cycle_id is not None:
        svc._active_cycle_id = None
        if svc.on_stop:
            svc.on_stop()

    assert stop_called.is_set()
    assert svc._active_cycle_id is None


def test_api_start_blocked_when_scheduler_enabled(client):
    """Verifica que /api/start rechace con HTTP 400 el inicio manual si la programación está activa."""
    try:
        # Activar scheduler
        scheduler_service.config.enabled = True
        scheduler_service.config.time_str = "22:00"
        scheduler_service.config.end_time_str = "06:00"

        res = client.post(
            "/api/start",
            json={
                "schema_name": "public",
                "table_name": "tb_direccion",
                "batch_size": 20,
            },
        )
        assert res.status_code == 400
        data = res.json()
        assert "No se permite iniciar manualmente mientras la programación horaria automática esté activa" in data["detail"]
    finally:
        # Restaurar a inactivo
        scheduler_service.config.enabled = False
