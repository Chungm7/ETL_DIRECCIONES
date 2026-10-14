"""Cargador de datos hacia PostgreSQL para la arquitectura relacional V2 y método In-Place."""

import logging
from typing import Any, Dict, List, Optional, Set

from src.loaders.base_loader import BaseLoader
from src.models.direccion_destino import DireccionDestino
from src.services.db_service import DatabaseService
from src.config.settings import get_settings

logger = logging.getLogger("etl_mpch.db_loader")

try:
    from sqlalchemy import text
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False


class DatabaseLoader(BaseLoader):
    """Carga y actualiza registros normalizados en PostgreSQL.
    
    Soporta:
    1. Arquitectura Relacional V2 (3NF): Inserta en tb_direccion, tb_direccion_via (multi-vía),
       tb_contenido_componente_direccion y tb_direccion_tipo_modulo, y vincula dire_id
       en la tabla de origen (tb_xxx / tabla seleccionada).
    2. Retrocompatibilidad In-Place (Legacy): Actualiza columnas planas id_via, id_zona, num_via, etc.
    """

    def __init__(
        self,
        db_service: Optional[DatabaseService] = None,
        schema: Optional[str] = None,
        table: Optional[str] = None,
        mode: str = "in_place",
        source_mode: str = "source_table",
        target_catalog_schema: str = "public",
        db_settings: Optional[Any] = None,
    ):
        self.db = db_service or DatabaseService()
        self.settings = db_settings or getattr(self.db, "settings", None) or get_settings().db
        self.mode = mode
        self.source_mode = source_mode  # "source_table" o "central_tb_direccion"
        self.target_catalog_schema = target_catalog_schema
        self.schema = schema or self.settings.schema
        self.table = table or self.settings.table

        # Mapeo de nombres dinámicos de columnas
        self.col_id = getattr(self.settings, "id_col", "id_licencia")
        self.col_id_via = getattr(self.settings, "col_id_via", "id_via")
        self.col_num_via = getattr(self.settings, "col_num_via", "num_via")
        self.col_id_zona = getattr(self.settings, "col_id_zona", "id_zona")
        self.col_mz = getattr(self.settings, "col_manzana", "manzana")
        self.col_lt = getattr(self.settings, "col_lote", "lote")
        self.col_slt = getattr(self.settings, "col_slote", "slote")
        self.col_referencia = getattr(self.settings, "col_referencia", "referencia")
        self.col_es_procesado = getattr(self.settings, "col_es_procesado", "es_procesado")
        self.col_observacion = getattr(self.settings, "col_observacion", "observacion")

        self._target_cols: Optional[Set[str]] = None
        self._has_tb_direccion: Optional[bool] = None

    def _inspect_structure(self) -> None:
        """Detecta las columnas de la tabla origen y la presencia de tb_direccion."""
        if not SQLALCHEMY_AVAILABLE or not self.db._engine:
            return
        try:
            with self.db.get_session() as session:
                # Comprobar si existe tb_direccion en el esquema activo
                res_tb_dir = session.execute(text("""
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = :schema AND table_name = 'tb_direccion';
                """), {"schema": self.schema}).scalar()
                self._has_tb_direccion = bool(res_tb_dir and res_tb_dir > 0)
                if self._has_tb_direccion and hasattr(self.db, "ensure_modulo_pk_constraint"):
                    try:
                        self.db.ensure_modulo_pk_constraint(self.schema)
                    except Exception as ex_mig:
                        logger.debug("Aviso al asegurar PK de tb_direccion_tipo_modulo: %s", ex_mig)

                # Inspeccionar columnas de la tabla de origen seleccionada
                col_rows = session.execute(text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = :schema AND table_name = :table;
                """), {"schema": self.schema, "table": self.table}).fetchall()
                self._target_cols = {r[0].lower() for r in col_rows}
                cols_map = {r[0].lower(): r[0] for r in col_rows}

                # Alinear columna ID si es diferente (ej. xxxx_id, id_licencia, id)
                for cand in [self.col_id, "xxxx_id", "id_licencia", "id", "id_direccion", "codigo"]:
                    if cand and cand.lower() in self._target_cols:
                        self.col_id = cols_map[cand.lower()]
                        break

                # Alinear columna es_procesado (ej. xxxx_es_procesado, es_procesado)
                for cand in [self.col_es_procesado, "xxxx_es_procesado", "es_procesado"]:
                    if cand and cand.lower() in self._target_cols:
                        self.col_es_procesado = cols_map[cand.lower()]
                        break

                # Alinear columna observacion (ej. xxxx_observacion_ia, observacion)
                for cand in [self.col_observacion, "xxxx_observacion_ia", "observacion_ia", "observacion"]:
                    if cand and cand.lower() in self._target_cols:
                        self.col_observacion = cols_map[cand.lower()]
                        break
        except Exception as e:
            logger.debug("Aviso al inspeccionar estructura en %s.%s: %s", self.schema, self.table, e)

    def load_batch(self, records: List[DireccionDestino]) -> int:
        """Actualiza y/o persiste un lote de registros normalizados conservando IDs originales."""
        if not records:
            return 0

        if not SQLALCHEMY_AVAILABLE or not self.db._engine:
            logger.warning("Base de datos no disponible. Omitiendo persistencia.")
            return 0

        if self.source_mode == "central_tb_direccion":
            return self._load_central_tb_direccion(records)

        if self._target_cols is None:
            self._inspect_structure()

        if self._has_tb_direccion:
            return self._load_v2(records)
        else:
            return self._load_in_place_legacy(records)

    def _load_central_tb_direccion(self, records: List[DireccionDestino]) -> int:
        """Persistencia sobre public.tb_direccion para el flujo desacoplado.
        No modifica la tabla fuente emisora pues ya está enlazada por FK.
        """
        is_sqlite = False
        try:
            if self.db._engine and hasattr(self.db._engine, "dialect"):
                is_sqlite = (self.db._engine.dialect.name == "sqlite")
        except Exception:
            pass

        cat_schema = self.target_catalog_schema or ""
        pfx = "" if (is_sqlite or not cat_schema or cat_schema.lower() in ("", "main")) else f'"{cat_schema}".'

        try:
            with self.db.get_session() as session:
                for rec in records:
                    dire_id = rec.dire_id or rec.id_licencia
                    clean_estado = "A" if (rec.dire_estado in ("A", "ACT") or not rec.dire_estado) else ("I" if rec.dire_estado in ("I", "INA") else "A")

                    if rec.es_procesado:
                        # 1. Actualizar tb_direccion como normalizado exitoso
                        try:
                            with session.begin_nested():
                                session.execute(text(f"""
                                    UPDATE {pfx}"tb_direccion" SET
                                        zona_id = :zona_id,
                                        dire_referencia = :dire_referencia,
                                        dire_estado = :dire_estado,
                                        dire_es_procesado = TRUE,
                                        update_at = CURRENT_TIMESTAMP
                                    WHERE dire_id = :dire_id;
                                """), {
                                    "zona_id": rec.zona_id,
                                    "dire_referencia": rec.dire_referencia,
                                    "dire_estado": clean_estado,
                                    "dire_id": dire_id,
                                    "update_at": None,
                                } if False else {
                                    "zona_id": rec.zona_id,
                                    "dire_referencia": rec.dire_referencia,
                                    "dire_estado": clean_estado,
                                    "dire_id": dire_id,
                                })
                        except Exception:
                            session.execute(text(f"""
                                    UPDATE {pfx}"tb_direccion" SET
                                        zona_id = :zona_id,
                                        dire_referencia = :dire_referencia,
                                        dire_estado = :dire_estado,
                                        dire_es_procesado = TRUE,
                                        update_at = CURRENT_TIMESTAMP
                                    WHERE dire_id = :dire_id;
                            """), {
                                "zona_id": rec.zona_id,
                                "dire_referencia": rec.dire_referencia,
                                "dire_estado": clean_estado,
                                "dire_id": dire_id,
                            })

                        # 2. Insertar vías asociadas
                        if rec.vias:
                            ins_via_sql = text(f"""
                                INSERT INTO {pfx}"tb_direccion_via" (
                                    dire_id, via_id, divi_numero, divi_cuadra, divi_orden, divi_es_principal, divi_estado
                                ) VALUES (
                                    :dire_id, :via_id, :divi_numero, :divi_cuadra, :divi_orden, :divi_es_principal, :divi_estado
                                )
                                ON CONFLICT (dire_id, via_id) DO UPDATE SET
                                    divi_numero = EXCLUDED.divi_numero,
                                    divi_cuadra = EXCLUDED.divi_cuadra,
                                    divi_orden = EXCLUDED.divi_orden,
                                    divi_es_principal = EXCLUDED.divi_es_principal,
                                    divi_estado = EXCLUDED.divi_estado;
                            """)
                            for idx, v in enumerate(rec.vias, start=1):
                                via_id = v.get("via_id")
                                if via_id is not None:
                                    via_ord = v.get("divi_orden", idx)
                                    via_params = {
                                        "dire_id": dire_id,
                                        "via_id": via_id,
                                        "divi_numero": str(v.get("divi_numero") or "").strip() or None,
                                        "divi_cuadra": str(v.get("divi_cuadra") or "").strip() or None,
                                        "divi_orden": via_ord,
                                        "divi_es_principal": (via_ord == 1 or idx == 1),
                                        "divi_estado": "A",
                                    }
                                    try:
                                        with session.begin_nested():
                                            session.execute(ins_via_sql, via_params)
                                    except Exception:
                                        # Fallback si faltase alguna columna en esquemas no migrados
                                        try:
                                            with session.begin_nested():
                                                session.execute(text(f"""
                                                    INSERT INTO {pfx}"tb_direccion_via" (
                                                        dire_id, via_id, divi_numero, divi_estado
                                                    ) VALUES (
                                                        :dire_id, :via_id, :divi_numero, :divi_estado
                                                    )
                                                    ON CONFLICT (dire_id, via_id) DO UPDATE SET
                                                        divi_numero = EXCLUDED.divi_numero;
                                                """), {
                                                    "dire_id": dire_id,
                                                    "via_id": via_id,
                                                    "divi_numero": str(v.get("divi_numero") or "").strip() or None,
                                                    "divi_estado": "A",
                                                })
                                        except Exception as ex_fb:
                                             logger.debug("Aviso al insertar vía con fallback en central: %s", ex_fb)

                        # 3. Insertar componentes catastrales
                        if rec.componentes:
                            ins_comp_sql = text(f"""
                                INSERT INTO {pfx}"tb_contenido_componente_direccion" (
                                    dire_id, codi_id, diti_valor, diti_orden, diti_estado
                                ) VALUES (
                                    :dire_id, :codi_id, :diti_valor, :diti_orden, :diti_estado
                                )
                                ON CONFLICT (dire_id, codi_id) DO UPDATE SET
                                    diti_valor = EXCLUDED.diti_valor,
                                    diti_orden = EXCLUDED.diti_orden,
                                    diti_estado = EXCLUDED.diti_estado;
                            """)
                            for idx, c in enumerate(rec.componentes, start=1):
                                codi_id = c.get("codi_id")
                                val = c.get("diti_valor") or c.get("diti_nombre")
                                comp_ord = c.get("diti_orden") or c.get("orden") or idx
                                if codi_id is not None and val:
                                    clean_val = str(val).strip().upper()
                                    try:
                                        with session.begin_nested():
                                            session.execute(ins_comp_sql, {
                                                "dire_id": dire_id,
                                                "codi_id": codi_id,
                                                "diti_valor": clean_val,
                                                "diti_orden": comp_ord,
                                                "diti_estado": "A",
                                            })
                                    except Exception:
                                        # Fallback legacy si la columna aún se llama diti_nombre
                                        try:
                                            with session.begin_nested():
                                                session.execute(text(f"""
                                                    INSERT INTO {pfx}"tb_contenido_componente_direccion" (
                                                        dire_id, codi_id, diti_nombre, diti_orden, diti_estado
                                                    ) VALUES (
                                                        :dire_id, :codi_id, :diti_nombre, :diti_orden, :diti_estado
                                                    )
                                                    ON CONFLICT (dire_id, codi_id) DO UPDATE SET
                                                        diti_nombre = EXCLUDED.diti_nombre,
                                                        diti_orden = EXCLUDED.diti_orden;
                                                """), {
                                                    "dire_id": dire_id,
                                                    "codi_id": codi_id,
                                                    "diti_nombre": clean_val,
                                                    "diti_orden": comp_ord,
                                                    "diti_estado": "A",
                                                })
                                        except Exception as ex_cfb:
                                             logger.debug("Aviso al insertar componente con fallback en central: %s", ex_cfb)

                        # 4. Insertar módulos inmobiliarios
                        if rec.modulos:
                            ins_mod_sql = text(f"""
                                INSERT INTO {pfx}"tb_direccion_tipo_modulo" (
                                    dire_id, timo_id, ditm_nombre, ditm_orden, ditm_estado
                                ) VALUES (
                                    :dire_id, :timo_id, :ditm_nombre, :ditm_orden, :ditm_estado
                                )
                                ON CONFLICT (dire_id, timo_id, ditm_nombre) DO UPDATE SET
                                    ditm_orden = EXCLUDED.ditm_orden,
                                    ditm_estado = EXCLUDED.ditm_estado;
                            """)
                            for idx, m in enumerate(rec.modulos, start=1):
                                timo_id = m.get("timo_id")
                                ditm_nombre = m.get("ditm_nombre")
                                mod_ord = m.get("ditm_orden") or m.get("orden") or idx
                                if timo_id is not None and ditm_nombre:
                                    clean_ditm = str(ditm_nombre).strip().upper()
                                    try:
                                        with session.begin_nested():
                                            session.execute(ins_mod_sql, {
                                                "dire_id": dire_id,
                                                "timo_id": timo_id,
                                                "ditm_nombre": clean_ditm,
                                                "ditm_orden": mod_ord,
                                                "ditm_estado": "A",
                                            })
                                    except Exception as ex_mod:
                                        # Fallback si ditm_orden no existe en esquemas previos
                                        fb_mod_sql = text(f"""
                                            INSERT INTO {pfx}"tb_direccion_tipo_modulo" (
                                                dire_id, timo_id, ditm_nombre, ditm_estado
                                            ) VALUES (
                                                :dire_id, :timo_id, :ditm_nombre, :ditm_estado
                                            )
                                            ON CONFLICT (dire_id, timo_id, ditm_nombre) DO UPDATE SET
                                                ditm_estado = EXCLUDED.ditm_estado;
                                        """)
                                        try:
                                            with session.begin_nested():
                                                session.execute(fb_mod_sql, {
                                                    "dire_id": dire_id,
                                                    "timo_id": timo_id,
                                                    "ditm_nombre": clean_ditm,
                                                    "ditm_estado": "A",
                                                })
                                        except Exception as ex_fb:
                                            err_str = str(ex_fb)
                                            if ("ON CONFLICT" in err_str or "InvalidColumnReference" in err_str) and not is_sqlite:
                                                logger.warning(
                                                    "Restricción única ausente en %s.tb_direccion_tipo_modulo. Migrando en caliente...",
                                                    self.target_catalog_schema,
                                                )
                                                if hasattr(self.db, "ensure_modulo_pk_constraint"):
                                                    self.db.ensure_modulo_pk_constraint(self.target_catalog_schema)
                                                try:
                                                    with session.begin_nested():
                                                        session.execute(fb_mod_sql, {
                                                            "dire_id": dire_id,
                                                            "timo_id": timo_id,
                                                            "ditm_nombre": clean_ditm,
                                                            "ditm_estado": "A",
                                                        })
                                                except Exception as ex_mfb:
                                                    logger.debug("Aviso al reintentar inserción de modulo en central: %s", ex_mfb)
                                            else:
                                                logger.debug("Aviso al insertar modulo inmobiliario en central: %s", ex_fb)
                    else:
                        # Rechazado / Incoherente: dire_es_procesado = FALSE, update_at = NOW(), sin componentes
                        try:
                            with session.begin_nested():
                                session.execute(text(f"""
                                    UPDATE {pfx}"tb_direccion" SET
                                        zona_id = NULL,
                                        dire_referencia = NULL,
                                        dire_es_procesado = FALSE,
                                        update_at = CURRENT_TIMESTAMP
                                    WHERE dire_id = :dire_id;
                                """), {"dire_id": dire_id})
                        except Exception:
                            session.execute(text(f"""
                                UPDATE {pfx}"tb_direccion" SET
                                    zona_id = NULL,
                                    dire_referencia = NULL,
                                    dire_es_procesado = FALSE,
                                    update_at = CURRENT_TIMESTAMP
                                WHERE dire_id = :dire_id;
                            """), {"dire_id": dire_id})

            logger.debug(
                "Lote de %d registros normalizados persistido directamente en %s.tb_direccion",
                len(records), self.target_catalog_schema
            )
            return len(records)
        except Exception as e:
            logger.error("Error en persistencia central sobre tb_direccion: %s", e)
            return 0

    def _load_v2(self, records: List[DireccionDestino]) -> int:
        """Persistencia relacional V2 atómica en tb_direccion, tb_direccion_via,
        tb_contenido_componente_direccion, tb_direccion_tipo_modulo y actualización en tabla origen."""
        has_dire_id_col = "dire_id" in (self._target_cols or {})

        try:
            with self.db.get_session() as session:
                for rec in records:
                    if rec.es_procesado:
                        # 1. Insertar o recuperar en tb_direccion
                        ins_dir_sql = text(f"""
                            INSERT INTO "{self.schema}"."tb_direccion" (
                                zona_id, dire_referencia, dire_estado
                            ) VALUES (
                                :zona_id, :dire_referencia, :dire_estado
                            ) RETURNING dire_id;
                        """)
                        clean_estado = "A" if (rec.dire_estado in ("A", "ACT") or not rec.dire_estado) else ("I" if rec.dire_estado in ("I", "INA") else "A")
                        dire_id = session.execute(ins_dir_sql, {
                            "zona_id": rec.zona_id,
                            "dire_referencia": rec.dire_referencia,
                            "dire_estado": clean_estado,
                        }).scalar()
                        rec.dire_id = dire_id

                        # 2. Insertar vías en tb_direccion_via (soporta esquinas / multi-vía)
                        if rec.vias:
                            ins_via_sql = text(f"""
                                INSERT INTO "{self.schema}"."tb_direccion_via" (
                                    dire_id, via_id, divi_numero, divi_cuadra, divi_orden, divi_es_principal, divi_estado
                                ) VALUES (
                                    :dire_id, :via_id, :divi_numero, :divi_cuadra, :divi_orden, :divi_es_principal, :divi_estado
                                )
                                ON CONFLICT (dire_id, via_id) DO UPDATE SET
                                    divi_numero = EXCLUDED.divi_numero,
                                    divi_cuadra = EXCLUDED.divi_cuadra,
                                    divi_orden = EXCLUDED.divi_orden,
                                    divi_es_principal = EXCLUDED.divi_es_principal,
                                    divi_estado = EXCLUDED.divi_estado;
                            """)
                            for idx, v in enumerate(rec.vias, start=1):
                                via_id = v.get("via_id")
                                if via_id is not None:
                                    via_ord = v.get("divi_orden", idx)
                                    via_params = {
                                        "dire_id": dire_id,
                                        "via_id": via_id,
                                        "divi_numero": str(v.get("divi_numero") or "").strip() or None,
                                        "divi_cuadra": str(v.get("divi_cuadra") or "").strip() or None,
                                        "divi_orden": via_ord,
                                        "divi_es_principal": (via_ord == 1 or idx == 1),
                                        "divi_estado": "A",
                                    }
                                    try:
                                        with session.begin_nested():
                                            session.execute(ins_via_sql, via_params)
                                    except Exception:
                                        try:
                                            with session.begin_nested():
                                                session.execute(text(f"""
                                                    INSERT INTO "{self.schema}"."tb_direccion_via" (
                                                        dire_id, via_id, divi_numero, divi_orden, divi_estado
                                                    ) VALUES (
                                                        :dire_id, :via_id, :divi_numero, :divi_orden, :divi_estado
                                                    )
                                                    ON CONFLICT (dire_id, via_id) DO UPDATE SET
                                                        divi_numero = EXCLUDED.divi_numero,
                                                        divi_orden = EXCLUDED.divi_orden;
                                                """), {
                                                    "dire_id": dire_id,
                                                    "via_id": via_id,
                                                    "divi_numero": str(v.get("divi_numero") or "").strip() or None,
                                                    "divi_orden": via_ord,
                                                    "divi_estado": "A",
                                                })
                                        except Exception as ex_vfb:
                                            logger.debug("Aviso al insertar vía con fallback en _load_v2: %s", ex_vfb)

                        # 3. Insertar componentes catastrales en tb_contenido_componente_direccion
                        if rec.componentes:
                            ins_comp_sql = text(f"""
                                INSERT INTO "{self.schema}"."tb_contenido_componente_direccion" (
                                    dire_id, codi_id, diti_valor, diti_orden, diti_estado
                                ) VALUES (
                                    :dire_id, :codi_id, :diti_valor, :diti_orden, :diti_estado
                                )
                                ON CONFLICT (dire_id, codi_id) DO UPDATE SET
                                    diti_valor = EXCLUDED.diti_valor,
                                    diti_orden = EXCLUDED.diti_orden,
                                    diti_estado = EXCLUDED.diti_estado;
                            """)
                            for idx, c in enumerate(rec.componentes, start=1):
                                codi_id = c.get("codi_id")
                                val = c.get("diti_valor") or c.get("diti_nombre")
                                comp_ord = c.get("diti_orden") or c.get("orden") or idx
                                if codi_id is not None and val:
                                    clean_val = str(val).strip().upper()
                                    try:
                                        with session.begin_nested():
                                            session.execute(ins_comp_sql, {
                                                "dire_id": dire_id,
                                                "codi_id": codi_id,
                                                "diti_valor": clean_val,
                                                "diti_orden": comp_ord,
                                                "diti_estado": "A",
                                            })
                                    except Exception:
                                        try:
                                            with session.begin_nested():
                                                session.execute(text(f"""
                                                    INSERT INTO "{self.schema}"."tb_contenido_componente_direccion" (
                                                        dire_id, codi_id, diti_nombre, diti_orden, diti_estado
                                                    ) VALUES (
                                                        :dire_id, :codi_id, :diti_nombre, :diti_orden, :diti_estado
                                                    )
                                                    ON CONFLICT (dire_id, codi_id) DO UPDATE SET
                                                        diti_nombre = EXCLUDED.diti_nombre,
                                                        diti_orden = EXCLUDED.diti_orden;
                                                """), {
                                                    "dire_id": dire_id,
                                                    "codi_id": codi_id,
                                                    "diti_nombre": clean_val,
                                                    "diti_orden": comp_ord,
                                                    "diti_estado": "A",
                                                })
                                        except Exception as ex_cfb:
                                            logger.debug("Aviso al insertar componente con fallback en _load_v2: %s", ex_cfb)

                        # 4. Insertar módulos inmobiliarios en tb_direccion_tipo_modulo
                        if rec.modulos:
                            ins_mod_sql = text(f"""
                                INSERT INTO "{self.schema}"."tb_direccion_tipo_modulo" (
                                    dire_id, timo_id, ditm_nombre, ditm_orden, ditm_estado
                                ) VALUES (
                                    :dire_id, :timo_id, :ditm_nombre, :ditm_orden, :ditm_estado
                                )
                                ON CONFLICT (dire_id, timo_id, ditm_nombre) DO UPDATE SET
                                    ditm_orden = EXCLUDED.ditm_orden,
                                    ditm_estado = EXCLUDED.ditm_estado;
                            """)
                            for idx, m in enumerate(rec.modulos, start=1):
                                timo_id = m.get("timo_id")
                                ditm_nombre = m.get("ditm_nombre")
                                mod_ord = m.get("ditm_orden") or m.get("orden") or idx
                                if timo_id is not None and ditm_nombre:
                                    clean_ditm = str(ditm_nombre).strip().upper()
                                    try:
                                        with session.begin_nested():
                                            session.execute(ins_mod_sql, {
                                                "dire_id": dire_id,
                                                "timo_id": timo_id,
                                                "ditm_nombre": clean_ditm,
                                                "ditm_orden": mod_ord,
                                                "ditm_estado": "A",
                                            })
                                    except Exception as ex_mod:
                                        # Fallback si ditm_orden no existe en esquemas previos
                                        fb_mod_sql = text(f"""
                                            INSERT INTO "{self.schema}"."tb_direccion_tipo_modulo" (
                                                dire_id, timo_id, ditm_nombre, ditm_estado
                                            ) VALUES (
                                                :dire_id, :timo_id, :ditm_nombre, :ditm_estado
                                            )
                                            ON CONFLICT (dire_id, timo_id, ditm_nombre) DO UPDATE SET
                                                ditm_estado = EXCLUDED.ditm_estado;
                                        """)
                                        try:
                                            with session.begin_nested():
                                                session.execute(fb_mod_sql, {
                                                    "dire_id": dire_id,
                                                    "timo_id": timo_id,
                                                    "ditm_nombre": clean_ditm,
                                                    "ditm_estado": "A",
                                                })
                                        except Exception as ex_fb:
                                            err_str = str(ex_fb)
                                            if ("ON CONFLICT" in err_str or "InvalidColumnReference" in err_str) and not is_sqlite:
                                                logger.warning(
                                                    "Restricción única ausente en %s.tb_direccion_tipo_modulo. Migrando en caliente...",
                                                    self.schema,
                                                )
                                                if hasattr(self.db, "ensure_modulo_pk_constraint"):
                                                    self.db.ensure_modulo_pk_constraint(self.schema)
                                                try:
                                                    with session.begin_nested():
                                                        session.execute(fb_mod_sql, {
                                                            "dire_id": dire_id,
                                                            "timo_id": timo_id,
                                                            "ditm_nombre": clean_ditm,
                                                            "ditm_estado": "A",
                                                        })
                                                except Exception as ex_mfb:
                                                    logger.debug("Aviso al reintentar modulo en _load_v2: %s", ex_mfb)
                                            else:
                                                logger.debug("Aviso al insertar modulo en _load_v2: %s", ex_fb)

                        # 5. Actualizar la tabla origen vinculando dire_id
                        upd_params: Dict[str, Any] = {
                            "id": rec.id_licencia,
                            "es_proc": True,
                            "obs": rec.observacion,
                        }
                        set_parts = [
                            f'"{self.col_es_procesado}" = :es_proc',
                            f'"{self.col_observacion}" = :obs',
                        ]
                        if has_dire_id_col:
                            set_parts.append('"dire_id" = :dire_id')
                            upd_params["dire_id"] = dire_id

                        # Enriquecer columnas planas si aún existen en la tabla origen
                        if self._target_cols:
                            if self.col_id_via.lower() in self._target_cols:
                                set_parts.append(f'"{self.col_id_via}" = :id_via')
                                upd_params["id_via"] = rec.id_via
                            if self.col_num_via.lower() in self._target_cols:
                                set_parts.append(f'"{self.col_num_via}" = :num_via')
                                upd_params["num_via"] = rec.num_via
                            if self.col_id_zona.lower() in self._target_cols:
                                set_parts.append(f'"{self.col_id_zona}" = :id_zona')
                                upd_params["id_zona"] = rec.id_zona
                            if self.col_mz.lower() in self._target_cols:
                                set_parts.append(f'"{self.col_mz}" = :manzana')
                                upd_params["manzana"] = rec.manzana
                            if self.col_lt.lower() in self._target_cols:
                                set_parts.append(f'"{self.col_lt}" = :lote')
                                upd_params["lote"] = rec.lote
                            if self.col_slt.lower() in self._target_cols:
                                set_parts.append(f'"{self.col_slt}" = :slote')
                                upd_params["slote"] = str(rec.slote)[:100].strip() if rec.slote else None
                            if self.col_referencia.lower() in self._target_cols:
                                set_parts.append(f'"{self.col_referencia}" = :referencia')
                                upd_params["referencia"] = rec.dire_referencia

                        upd_sql = text(f"""
                            UPDATE "{self.schema}"."{self.table}" SET
                                {", ".join(set_parts)}
                            WHERE "{self.col_id}" = :id;
                        """)
                        session.execute(upd_sql, upd_params)

                    else:
                        # Registro observado / no procesado: dire_id queda en NULL
                        upd_params = {
                            "id": rec.id_licencia,
                            "es_proc": False,
                            "obs": rec.observacion,
                        }
                        set_parts = [
                            f'"{self.col_es_procesado}" = :es_proc',
                            f'"{self.col_observacion}" = :obs',
                        ]
                        if has_dire_id_col:
                            set_parts.append('"dire_id" = NULL')

                        # Si tiene columnas planas, resetearlas a NULL
                        if self._target_cols:
                            for col_name in [
                                self.col_id_via, self.col_num_via, self.col_id_zona,
                                self.col_mz, self.col_lt, self.col_slt, self.col_referencia
                            ]:
                                if col_name.lower() in self._target_cols:
                                    set_parts.append(f'"{col_name}" = NULL')

                        upd_sql = text(f"""
                            UPDATE "{self.schema}"."{self.table}" SET
                                {", ".join(set_parts)}
                            WHERE "{self.col_id}" = :id;
                        """)
                        session.execute(upd_sql, upd_params)

            logger.debug(
                "Lote V2 de %d registros persistido atómicamente en %s.%s",
                len(records),
                self.schema,
                self.table,
            )
            return len(records)
        except Exception as e:
            logger.error("Error en persistencia V2 en %s.%s: %s", self.schema, self.table, e)
            return 0

    def _load_in_place_legacy(self, records: List[DireccionDestino]) -> int:
        """Actualiza in-place las columnas normalizadas planas en la tabla existente conservando IDs."""
        query = text(f"""
            UPDATE "{self.schema}"."{self.table}" SET
                "{self.col_id_via}"      = :id_via,
                "{self.col_num_via}"     = :num_via,
                "{self.col_id_zona}"     = :id_zona,
                "{self.col_mz}"          = :manzana,
                "{self.col_lt}"          = :lote,
                "{self.col_slt}"         = :slote,
                "{self.col_referencia}"  = :referencia,
                "{self.col_es_procesado}"= :es_procesado,
                "{self.col_observacion}" = :observacion
            WHERE "{self.col_id}" = :id_licencia;
        """)

        payload = [
            {
                "id_licencia": rec.id_licencia,
                "id_via": rec.id_via,
                "num_via": rec.num_via,
                "id_zona": rec.id_zona,
                "manzana": rec.manzana,
                "lote": rec.lote,
                "slote": str(rec.slote)[:100].strip() if rec.slote else None,
                "referencia": rec.dire_referencia,
                "es_procesado": rec.es_procesado,
                "observacion": rec.observacion,
            }
            for rec in records
        ]
        try:
            with self.db.get_session() as session:
                session.execute(query, payload)
            logger.debug(
                "Lote legacy de %d registros actualizado in-place en %s.%s",
                len(records),
                self.schema,
                self.table,
            )
            return len(records)
        except Exception as e:
            logger.error(
                "Error en actualización legacy in-place en %s.%s: %s", self.schema, self.table, e
            )
            return 0
