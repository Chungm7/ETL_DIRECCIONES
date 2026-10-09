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
