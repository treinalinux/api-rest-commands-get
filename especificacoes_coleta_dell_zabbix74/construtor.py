"""Constrói um JSON com todos os ACTIVE_HANDLERS por equipamento.

Entrada: objeto, lista de objetos ou {"events": [...]} com os campos do CSV
anterior e listas opcionais de discos/fans afetados. Usa apenas a biblioteca
padrão e é compatível com Python 3.6+.
"""

import argparse
import json
import math
import os
import re
import stat
import sys
import tempfile


BASE_PATH = "."
CONSTRUCTOR_VERSION = "2026.10.14-seguranca-logs"

# ==========================================
# CONTRATOS E LIMITES DE HARDWARE E SERVIÇOS
# ==========================================

TEMP_THRESHOLDS_BY_FAMILY = {
    "unity": {"warning": 37.0, "critical": 40.0},
    "isilon": {"warning": 45.0, "critical": 50.0},
    "me4": {"warning": 40.0, "critical": 43.0},
    "default": {"warning": 37.0, "critical": 40.0}
}

DISK_REDUNDANCY_BY_FAMILY = {
    "unity": 1,
    "isilon": 2,
    "me4": 1,
    "default": 1
}

CAPACITY_THRESHOLDS_BY_FAMILY = {
    "unity": {"volume_usage": 80.0, "pool_usage": 90.0, "pool_full": 95.0},
    "isilon": {"volume_usage": 80.0, "pool_usage": 90.0, "pool_full": 95.0},
    "me4": {"volume_usage": 80.0, "pool_usage": 90.0, "pool_full": 95.0},
    "default": {"volume_usage": 80.0, "pool_usage": 90.0, "pool_full": 95.0}
}

CPU_THRESHOLDS = {
    "warning": 85.0,
    "critical": 95.0
}

PERFORMANCE_THRESHOLDS = {
    "smb_latency_ms": 20.0,
    "nfs_latency_ms": 20.0,
    "nfs_retransmissions_pct": 1.0,
    "cpu_utilization_pct": 80.0,
    "storage_utilization_pct": 85.0,
    "network_utilization_pct": 80.0,
    "packet_loss_pct": 0.1
}

SECURITY_THRESHOLDS = {
    "cert_expiry_days_warning": 30,
    "cert_expiry_days_critical": 0
}


# ==========================================
# UTILITÁRIOS PARA MANIPULAÇÃO DE JSON
# ==========================================

def write_temp_json(tmp_filepath, payload):
    with open(tmp_filepath, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=4, ensure_ascii=False, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def validate_and_move_json(tmp_filepath, final_filepath, verbose=False):
    with open(tmp_filepath, 'r', encoding='utf-8') as f:
        data = json.load(f, parse_constant=_reject_json_constant)

    # O temporário fica no mesmo diretório: a substituição é atômica por arquivo.
    os.replace(tmp_filepath, final_filepath)

    if verbose:
        print(f"\n[SUCESSO] JSON gerado e salvo em: {final_filepath}")
        print(json.dumps(data, indent=4, ensure_ascii=False))


# ==========================================
# CONSTRUTORES BASE (Inputs já tipados pelo JSON)
# ==========================================

def _build_device_info(row):
    return {
        "family": row.get("family", "").strip(),
        "type": row.get("type", "").strip(),
        "name": row.get("name", "").strip(),
        "serial_number": row.get("serial_number", "").strip(),
        "service_tag": row.get("service_tag", "").strip()
    }


def _build_base_event(row):
    status = row.get("health_status", "").strip().upper()

    if status in ["OK", "HEALTHY", "NORMAL"]:
        status = "OK"
        severity = "Info"
        impact = "None"
        action = "None required"
        priority = "P4"
        custom_desc = f"{row.get('event_name')} status is OK. System operating normally."
    else:
        severity = row.get("manufacturer_severity", "Unknown")
        impact = row.get("impact", "Unknown")
        action = row.get("recommended_action", "Check logs")
        priority = row.get("priority", "P3")
        custom_desc = f"{priority} - {severity}: {action} | Impact: {impact}"

    return {
        "component_health_status": status,
        "event_metadata": {
            "timestamp": row.get("datetime", "").strip(),
            "division": row.get("manufacturer_division", "").strip(),
            "category": row.get("manufacturer_category", "").strip(),
            "name": row.get("event_name", "").strip()
        },
        "event_details": {
            "severity": severity,
            "impact": impact,
            "recommended_action": action,
            "priority": priority,
            "custom_description": custom_desc
        }
    }


def _create_healthy_mock_row(base_row, missing_event_name):
    mock = base_row.copy()

    # Neutraliza o status, mas PRESERVA os valores numéricos reais para os gráficos do Zabbix
    mock["event_name"] = missing_event_name
    mock["health_status"] = "OK"
    mock["manufacturer_severity"] = "Info"
    mock["priority"] = "P4"
    mock["impact"] = "None"
    mock["recommended_action"] = "None required"

    return mock


# ==========================================
# 1. FUNÇÕES ATIVAS
# ==========================================

def handle_cluster_down(row):
    event = _build_base_event(row)
    details = event["event_details"]

    if event["component_health_status"] in ["OK", "HEALTHY"]:
        details["custom_description"] = "Status OK. Quorum do Cluster operando normalmente."
    else:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P1"
        details["custom_description"] = "CRÍTICO (P1): Cluster DOWN! Possível perda de Quorum ou shutdown."

    return event


def handle_controller_down(row):
    event = _build_base_event(row)
    details = event["event_details"]

    total_ctrls = row.get("total_controllers", 0)
    failed_ctrls = row.get("failed_controllers", 0)

    if failed_ctrls == 0:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = f"Status OK. Todas as {total_ctrls} controladoras ativas."
    elif failed_ctrls < total_ctrls:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P2"
        details["custom_description"] = f"CRÍTICO (P2): {failed_ctrls} controladora(s) falhou. Operacional via redundância."
    else:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P1"
        details["custom_description"] = "CRÍTICO (P1): TODAS as controladoras falharam! Storage inoperante."

    details["metrics"] = {
        "total_controllers": total_ctrls,
        "failed_controllers": failed_ctrls,
        "healthy_controllers": max(0, total_ctrls - failed_ctrls)
    }

    return event


def handle_multiple_disk_failure(row):
    event = _build_base_event(row)
    details = event["event_details"]
    family = row.get("family", "").strip().lower()

    total_disks = row.get("total_disks", 0)
    failed_disks = row.get("failed_disks", 0)

    allowed_failures = DISK_REDUNDANCY_BY_FAMILY.get(family, DISK_REDUNDANCY_BY_FAMILY["default"])

    if failed_disks == 0:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = "Status OK. Discos saudáveis."
    elif failed_disks <= allowed_failures:
        event["component_health_status"] = "OPERATIONAL"
        details["severity"] = "Warning"
        details["priority"] = "P3"
        details["custom_description"] = f"AVISO: {failed_disks} disco(s) falho(s). Operacional via redundância."
    else:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P1"
        details["custom_description"] = f"CRÍTICO: {failed_disks} discos falharam! Risco de perda de dados!"

    details["metrics"] = {
        "total_disks": total_disks,
        "failed_disks": failed_disks,
        "allowed_failures": allowed_failures
    }

    return event


def handle_power_supply_failure(row):
    event = _build_base_event(row)
    details = event["event_details"]

    total_psus = row.get("total_psus", 0)
    failed_psus = row.get("failed_psus", 0)

    if failed_psus == 0:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = "Status OK. PSUs saudáveis."
    elif failed_psus == 1 and total_psus > 1:
        event["component_health_status"] = "OPERATIONAL"
        details["severity"] = "Warning"
        details["priority"] = "P2"
        details["custom_description"] = "ALERTA: 1 PSU falhou. Redundância elétrica perdida."
    else:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P1"
        details["custom_description"] = "CRÍTICO: Fontes de energia falharam! Risco de shutdown."

    details["metrics"] = {
        "total_psus": total_psus,
        "failed_psus": failed_psus
    }

    return event


def handle_fan_failure(row):
    event = _build_base_event(row)
    details = event["event_details"]

    total = row.get("total_fans", 0)
    failed = row.get("failed_fans", 0)

    if failed == 0:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = f"Status OK. Todas as {total} fans saudáveis."
    elif failed == 1:
        event["component_health_status"] = "OPERATIONAL"
        details["severity"] = "Warning"
        details["priority"] = "P3"
        details["custom_description"] = "AVISO: 1 fan falha. Operacional via redundância."
    else:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P1"
        details["custom_description"] = f"CRÍTICO: {failed} fans falharam. Redundância perdida!"

    details["metrics"] = {
        "total_fans": total,
        "failed_fans": failed,
        "healthy_fans": max(0, total - failed)
    }

    return event


def handle_high_temp(row):
    event = _build_base_event(row)
    details = event["event_details"]
    family = row.get("family", "").strip().lower()

    temp = row.get("current_temperature", 0.0)
    failed = row.get("failed_fans", 0)

    warn_limit = TEMP_THRESHOLDS_BY_FAMILY.get(family, TEMP_THRESHOLDS_BY_FAMILY["default"])["warning"]
    crit_limit = TEMP_THRESHOLDS_BY_FAMILY.get(family, TEMP_THRESHOLDS_BY_FAMILY["default"])["critical"]
    root_cause = "Falha de refrigeração." if failed > 0 else "Falha no Ar-Condicionado."

    if temp >= crit_limit:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P1"
        details["custom_description"] = f"CRÍTICO: Temp ({temp}°C) excedeu {crit_limit}°C. {root_cause}"
    elif temp >= warn_limit:
        event["component_health_status"] = "WARNING"
        details["severity"] = "Warning"
        details["priority"] = "P3"
        details["custom_description"] = f"AVISO: Temp ({temp}°C) próxima ao limite. {root_cause}"
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = "Status OK. Temperatura Normal."

    details["metrics"] = {
        "current_temperature_celsius": temp,
        "warning_threshold": warn_limit,
        "critical_threshold": crit_limit,
        "failed_fans": failed
    }

    return event


def handle_smb_latency(row):
    event = _build_base_event(row)
    details = event["event_details"]

    val = row.get("smb_latency_ms", 0.0)
    limit = PERFORMANCE_THRESHOLDS["smb_latency_ms"]

    if val > limit:
        event["component_health_status"] = "WARNING"
        details["severity"] = "Warning"
        details["priority"] = "P3"
        details["custom_description"] = f"AVISO: Latência SMB alta ({val} ms). Excedeu o limite de {limit} ms."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = f"Status OK. Latência SMB normal ({val} ms)."

    details["metrics"] = {
        "smb_latency_ms": val,
        "threshold_limit": limit
    }

    return event


def handle_nfs_latency(row):
    event = _build_base_event(row)
    details = event["event_details"]

    val = row.get("nfs_latency_ms", 0.0)
    limit = PERFORMANCE_THRESHOLDS["nfs_latency_ms"]

    if val > limit:
        event["component_health_status"] = "WARNING"
        details["severity"] = "Warning"
        details["priority"] = "P3"
        details["custom_description"] = f"AVISO: Latência NFS alta ({val} ms). Excedeu o limite de {limit} ms."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = f"Status OK. Latência NFS normal ({val} ms)."

    details["metrics"] = {
        "nfs_latency_ms": val,
        "threshold_limit": limit
    }

    return event


def handle_nfs_retransmissions(row):
    event = _build_base_event(row)
    details = event["event_details"]

    val = row.get("nfs_retransmissions_pct", 0.0)
    limit = PERFORMANCE_THRESHOLDS["nfs_retransmissions_pct"]

    if val > limit:
        event["component_health_status"] = "WARNING"
        details["severity"] = "Warning"
        details["priority"] = "P3"
        details["custom_description"] = f"AVISO: Retransmissões NFS altas ({val}%). Excedeu o limite de {limit}%."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = f"Status OK. Retransmissões NFS normais ({val}%)."

    details["metrics"] = {
        "nfs_retransmissions_pct": val,
        "threshold_limit": limit
    }

    return event


def handle_cpu_utilization(row):
    event = _build_base_event(row)
    details = event["event_details"]

    val = row.get("cpu_utilization_pct", 0.0)
    limit = PERFORMANCE_THRESHOLDS["cpu_utilization_pct"]

    if val > limit:
        event["component_health_status"] = "WARNING"
        details["severity"] = "Warning"
        details["priority"] = "P3"
        details["custom_description"] = f"AVISO: Uso Geral de CPU atingiu {val}%. Excedeu {limit}%."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = f"Status OK. Uso de CPU normal ({val}%)."

    details["metrics"] = {
        "cpu_utilization_pct": val,
        "threshold_limit": limit
    }

    return event


def handle_storage_utilization(row):
    event = _build_base_event(row)
    details = event["event_details"]

    val = row.get("storage_utilization_pct", 0.0)
    limit = PERFORMANCE_THRESHOLDS["storage_utilization_pct"]

    if val > limit:
        event["component_health_status"] = "WARNING"
        details["severity"] = "Warning"
        details["priority"] = "P3"
        details["custom_description"] = f"AVISO: Uso Geral de Armazenamento atingiu {val}%. Excedeu {limit}%."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = f"Status OK. Uso de Armazenamento em {val}%."

    details["metrics"] = {
        "storage_utilization_pct": val,
        "threshold_limit": limit
    }

    return event


def handle_network_utilization(row):
    event = _build_base_event(row)
    details = event["event_details"]

    val = row.get("network_utilization_pct", 0.0)
    limit = PERFORMANCE_THRESHOLDS["network_utilization_pct"]

    if val > limit:
        event["component_health_status"] = "WARNING"
        details["severity"] = "Warning"
        details["priority"] = "P3"
        details["custom_description"] = f"AVISO: Utilização do Link de Rede atingiu {val}%. Excedeu {limit}%."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = f"Status OK. Utilização do link normal ({val}%)."

    details["metrics"] = {
        "network_utilization_pct": val,
        "threshold_limit": limit
    }

    return event


def handle_packet_loss(row):
    event = _build_base_event(row)
    details = event["event_details"]

    val = row.get("packet_loss_pct", 0.0)
    limit = PERFORMANCE_THRESHOLDS["packet_loss_pct"]

    if val > limit:
        event["component_health_status"] = "WARNING"
        details["severity"] = "Warning"
        details["priority"] = "P2"
        details["custom_description"] = f"ALERTA: Perda de pacotes na interface ({val}%). Acima de {limit}%."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = f"Status OK. Qualidade da rede excelente ({val}% perda)."

    details["metrics"] = {
        "packet_loss_pct": val,
        "threshold_limit": limit
    }

    return event


def handle_controller_cpu(row):
    event = _build_base_event(row)
    details = event["event_details"]

    cpu_usage = row.get("controller_cpu_percentage", 0.0)
    warn_limit = CPU_THRESHOLDS["warning"]
    crit_limit = CPU_THRESHOLDS["critical"]

    if cpu_usage >= crit_limit:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P1"
        details["custom_description"] = f"CRÍTICO: CPU da Controladora em {cpu_usage}% (Fila de I/O saturada)."
    elif cpu_usage >= warn_limit:
        event["component_health_status"] = "WARNING"
        details["severity"] = "Warning"
        details["priority"] = "P3"
        details["custom_description"] = f"AVISO: CPU da Controladora atingiu {cpu_usage}%."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = f"Status OK. Uso de CPU normal ({cpu_usage}%)."

    details["metrics"] = {
        "controller_cpu_percentage": cpu_usage,
        "warning_threshold": warn_limit,
        "critical_threshold": crit_limit
    }

    return event


def handle_volume_usage(row):
    event = _build_base_event(row)
    details = event["event_details"]

    usage_pct = row.get("usage_percentage", 0.0)
    family = row.get("family", "").strip().lower()
    limit = CAPACITY_THRESHOLDS_BY_FAMILY.get(family, CAPACITY_THRESHOLDS_BY_FAMILY["default"])["volume_usage"]

    if usage_pct >= limit:
        event["component_health_status"] = "WARNING"
        details["severity"] = "Warning"
        details["priority"] = "P3"
        details["custom_description"] = f"AVISO: Volume atingiu {usage_pct}% (Limite: {limit}%)."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = f"Status OK. Volume em {usage_pct}%."

    details["metrics"] = {
        "usage_percentage": usage_pct,
        "threshold_limit": limit
    }

    return event


def handle_pool_usage(row):
    event = _build_base_event(row)
    details = event["event_details"]

    usage_pct = row.get("usage_percentage", 0.0)
    family = row.get("family", "").strip().lower()
    limit = CAPACITY_THRESHOLDS_BY_FAMILY.get(family, CAPACITY_THRESHOLDS_BY_FAMILY["default"])["pool_usage"]

    if usage_pct >= limit:
        event["component_health_status"] = "WARNING"
        details["severity"] = "Warning"
        details["priority"] = "P2"
        details["custom_description"] = f"ALERTA: Pool atingiu {usage_pct}% (Limite: {limit}%)."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = f"Status OK. Pool em {usage_pct}%."

    details["metrics"] = {
        "usage_percentage": usage_pct,
        "threshold_limit": limit
    }

    return event


def handle_pool_full(row):
    event = _build_base_event(row)
    details = event["event_details"]

    usage_pct = row.get("usage_percentage", 0.0)
    family = row.get("family", "").strip().lower()
    limit = CAPACITY_THRESHOLDS_BY_FAMILY.get(family, CAPACITY_THRESHOLDS_BY_FAMILY["default"])["pool_full"]

    if usage_pct >= limit:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P1"
        details["custom_description"] = f"CRÍTICO: Pool quase cheio! ({usage_pct}%, Limite: {limit}%)."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = f"Status OK. Pool possui espaço ({usage_pct}%)."

    details["metrics"] = {
        "usage_percentage": usage_pct,
        "threshold_limit": limit
    }

    return event


def handle_replication_failed(row):
    event = _build_base_event(row)
    details = event["event_details"]

    is_configured = row.get("is_replication_configured", False)

    if not is_configured:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = "Status OK. Replicação não configurada (Não exigido)."
    elif event["component_health_status"] in ["OK", "HEALTHY"]:
        details["custom_description"] = "Status OK. Replicação configurada e sincronizada."
    else:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P1"
        details["custom_description"] = "CRÍTICO: Replicação falhou! Disaster Recovery (DR) comprometido."

    details["metrics"] = {"is_configured": is_configured}

    return event


def handle_replication_lag(row):
    event = _build_base_event(row)
    details = event["event_details"]

    is_configured = row.get("is_replication_configured", False)
    lag_mins = row.get("lag_minutes", 0.0)
    rpo_mins = row.get("rpo_minutes", 60.0)

    if not is_configured:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = "Status OK. Replicação não configurada."
    elif lag_mins > rpo_mins:
        event["component_health_status"] = "WARNING"
        details["severity"] = "Warning"
        details["priority"] = "P2"
        details["custom_description"] = f"ALERTA: Atraso de replicação ({lag_mins}m) excedeu o RPO ({rpo_mins}m)."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = f"Status OK. Replicação dentro da meta (Atraso: {lag_mins}m)."

    details["metrics"] = {
        "is_configured": is_configured,
        "lag_minutes": lag_mins,
        "rpo_minutes": rpo_mins
    }

    return event


def handle_nfs_service(row):
    event = _build_base_event(row)
    details = event["event_details"]

    is_configured = row.get("is_nfs_configured", False)

    if not is_configured:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = "Status OK. NFS não configurado (Não exigido)."
    elif event["component_health_status"] in ["OK", "HEALTHY"]:
        details["custom_description"] = "Status OK. NFS operando normalmente."
    else:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P1"
        details["custom_description"] = "CRÍTICO: Serviço NFS parou de responder!"

    details["metrics"] = {"is_configured": is_configured}

    return event


def handle_smb_service(row):
    event = _build_base_event(row)
    details = event["event_details"]

    is_configured = row.get("is_smb_configured", False)

    if not is_configured:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = "Status OK. SMB/CIFS não configurado (Não exigido)."
    elif event["component_health_status"] in ["OK", "HEALTHY"]:
        details["custom_description"] = "Status OK. SMB/CIFS operando normalmente."
    else:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P1"
        details["custom_description"] = "CRÍTICO: Serviço SMB parou de responder!"

    details["metrics"] = {"is_configured": is_configured}

    return event


def handle_audit_disabled(row):
    event = _build_base_event(row)
    details = event["event_details"]

    is_disabled = row.get("is_audit_disabled", False)

    if is_disabled:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P1"
        details["custom_description"] = "CRÍTICO (P1): O Log de Auditoria do Storage foi DESATIVADO. Rastro perdido."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = "Status OK. Logs de auditoria estão ativos e gravando."

    details["metrics"] = {"is_audit_disabled": is_disabled}

    return event


def _security_observations(row):
    """Lê metadados opcionais sem exigir um formato novo da entrada legada."""
    source = row.get("source_details")
    observations = source.get("observations") if isinstance(source, dict) else None
    return observations if isinstance(observations, dict) else {}


def handle_unauthorized_admin(row):
    event = _build_base_event(row)
    details = event["event_details"]

    has_unauth = row.get("has_unauthorized_admin", False)

    if has_unauth:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P1"
        details["custom_description"] = "CRÍTICO (P1): Detectada tentativa de Acesso Administrativo Não Autorizado."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = "Status OK. Sem tentativas de acesso não autorizado registradas."

    details["metrics"] = {"has_unauthorized_admin": has_unauth}

    observations = _security_observations(row)
    if observations.get("security_scope") == "active_unity_alerts":
        if has_unauth:
            details["custom_description"] = (
                "alerta ativo de acesso nao autorizado ou falha de autenticacao no unity; "
                "verificar a descricao e a origem da tentativa"
            )
        else:
            details["custom_description"] = (
                "nenhum alerta ativo com descricao unauthorized ou login failed no unity"
            )

    return event


def handle_certificate_expiring(row):
    event = _build_base_event(row)
    details = event["event_details"]

    days = row.get("days_to_expire", 90)
    warn_limit = SECURITY_THRESHOLDS["cert_expiry_days_warning"]
    crit_limit = SECURITY_THRESHOLDS["cert_expiry_days_critical"]

    if days <= crit_limit:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P1"
        details["custom_description"] = f"CRÍTICO: Certificado expirado há {abs(days)} dia(s)! APIs podem falhar."
    elif days <= warn_limit:
        event["component_health_status"] = "WARNING"
        details["severity"] = "Warning"
        details["priority"] = "P3"
        details["custom_description"] = f"AVISO: Certificado expira em {days} dia(s)."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = f"Status OK. Certificado válido por mais {days} dia(s)."

    details["metrics"] = {
        "days_to_expire": days,
        "warning_threshold": warn_limit
    }

    return event


def _antivirus_problem_names(antivirus):
    """Identifica até 20 NAS com proteção ausente/desabilitada para a mensagem."""
    servers = []
    for key in ("disabled_servers", "unconfigured_servers"):
        items = antivirus.get(key)
        if isinstance(items, list):
            servers.extend(item for item in items if isinstance(item, dict))
    names = [str(item.get("nas_server_name") or item.get("nas_server_id") or "nas desconhecido")
             for item in servers]
    if not names:
        return "identificacao indisponivel"
    return "; ".join(names[:20]) + (f"; mais {len(names) - 20} nas" if len(names) > 20 else "")


def _handle_antivirus_configuration(row, antivirus):
    """Avalia CAVA sem converter sua habilitação em detecção de ransomware.

    Preserva a chave legada is_ransomware_suspected com null. Contagens adicionais
    pertencem somente à configuração informada em source_details.observations.
    A avaliação de qualidade posterior conserva falta de dados como UNKNOWN.
    """
    event = _build_base_event(row)
    details = event["event_details"]
    disabled = antivirus.get("disabled_count")
    missing = antivirus.get("unconfigured_nas_count")
    problems = any(isinstance(value, int) and not isinstance(value, bool) and value > 0
                   for value in (disabled, missing))
    status = antivirus.get("collection_status")
    if problems:
        event["component_health_status"] = "WARNING"
        details.update(severity="Warning", priority="P3", impact="antivirus protection disabled or unconfigured",
                       recommended_action="check the antivirus configuration on the affected nas servers",
                       custom_description="protecao antivirus cava desabilitada ou sem configuracao nos nas: "
                                          + _antivirus_problem_names(antivirus))
    elif (status == "collected" and antivirus.get("coverage_available") is True
          and antivirus.get("unknown_count") == 0 and missing == 0
          and isinstance(antivirus.get("enabled_count"), int)
          and not isinstance(antivirus.get("enabled_count"), bool) and antivirus["enabled_count"] > 0):
        event["component_health_status"] = "OK"
        details.update(severity="Info", priority="P4", impact="None", recommended_action="None required",
                       custom_description="protecao antivirus cava habilitada nos nas consultados; "
                                          "deteccao de ransomware nao consultada")
    else:
        event["component_health_status"] = "NOT_APPLICABLE" if status == "not_applicable" else "UNKNOWN"
        details.update(severity="Info" if status == "not_applicable" else "Unknown",
                       priority="P4" if status == "not_applicable" else "P3",
                       custom_description=row.get("collection_reason", "configuracao antivirus indisponivel"))
    details["metrics"] = {
        "is_ransomware_suspected": None,
        "antivirus_enabled_count": antivirus.get("enabled_count"),
        "antivirus_disabled_count": disabled,
        "antivirus_unknown_count": antivirus.get("unknown_count"),
        "antivirus_unconfigured_nas_count": missing,
    }
    return event


def handle_ransomware_pattern(row):
    """Usa detecção real quando informada; caso contrário avalia o escopo CAVA."""
    observations = _security_observations(row)
    if (observations.get("security_scope") == "antivirus_configuration"
            and row.get("is_ransomware_suspected") is None):
        antivirus = observations.get("antivirus")
        if isinstance(antivirus, dict):
            return _handle_antivirus_configuration(row, antivirus)
    event = _build_base_event(row)
    details = event["event_details"]

    is_suspected = row.get("is_ransomware_suspected", False)

    if is_suspected:
        event["component_health_status"] = "CRITICAL"
        details["severity"] = "Critical"
        details["priority"] = "P1"
        details["custom_description"] = "CRÍTICO (P1): Detecção de alta entropia/Ransomware Pattern no I/O do Storage! Risco iminente."
    else:
        event["component_health_status"] = "OK"
        details["severity"] = "Info"
        details["priority"] = "P4"
        details["custom_description"] = "Status OK. Nenhuma anomalia de entropia detectada."

    details["metrics"] = {"is_ransomware_suspected": is_suspected}

    return event


# ==========================================
# DICIONÁRIOS DE ROTEAMENTO
# ==========================================

ACTIVE_HANDLERS = {
    "Cluster Down": handle_cluster_down,
    "Controller Down": handle_controller_down,
    "Multiple Disk Failure": handle_multiple_disk_failure,
    "Power Supply Failure": handle_power_supply_failure,
    "Fan Failure": handle_fan_failure,
    "High Temp": handle_high_temp,
    "SMB latency": handle_smb_latency,
    "NFS latency": handle_nfs_latency,
    "NFS retransmissions": handle_nfs_retransmissions,
    "CPU utilization": handle_cpu_utilization,
    "Storage utilization": handle_storage_utilization,
    "Network utilization": handle_network_utilization,
    "Packet loss": handle_packet_loss,
    "Controller CPU": handle_controller_cpu,
    "Volume Usage": handle_volume_usage,
    "Pool Usage": handle_pool_usage,
    "Pool Full": handle_pool_full,
    "Replication Failed": handle_replication_failed,
    "Replication Lag": handle_replication_lag,
    "NFS Service": handle_nfs_service,
    "SMB Service": handle_smb_service,
    "Audit Disabled": handle_audit_disabled,
    "Unauthorized Admin": handle_unauthorized_admin,
    "Certificate Expiring": handle_certificate_expiring,
    "Ransomware Pattern": handle_ransomware_pattern
}


# ==========================================
# FLUXO PRINCIPAL DE INGESTÃO DE JSON
# ==========================================

INPUT_FIELDS = (
    "family", "type", "name", "serial_number", "service_tag",
    "software_version", "health_status", "uptime_seconds", "datetime",
    "manufacturer_division", "manufacturer_severity", "manufacturer_category",
    "event_name", "impact", "recommended_action", "priority", "custom_description",
    "total_fans", "failed_fans", "current_temperature", "total_disks", "failed_disks",
    "usage_percentage", "total_psus", "failed_psus", "total_controllers",
    "failed_controllers", "controller_cpu_percentage", "smb_latency_ms",
    "nfs_latency_ms", "nfs_retransmissions_pct", "cpu_utilization_pct",
    "storage_utilization_pct", "network_utilization_pct", "packet_loss_pct",
    "lag_minutes", "rpo_minutes", "days_to_expire", "is_replication_configured",
    "is_nfs_configured", "is_smb_configured", "is_ransomware_suspected",
    "is_audit_disabled", "has_unauthorized_admin"
)

INTEGER_FIELDS = {
    "uptime_seconds", "total_fans", "failed_fans", "total_disks", "failed_disks",
    "total_psus", "failed_psus", "total_controllers", "failed_controllers",
    "days_to_expire"
}

FLOAT_FIELDS = {
    "current_temperature", "usage_percentage", "controller_cpu_percentage",
    "smb_latency_ms", "nfs_latency_ms", "nfs_retransmissions_pct",
    "cpu_utilization_pct", "storage_utilization_pct", "network_utilization_pct",
    "packet_loss_pct", "lag_minutes", "rpo_minutes"
}

BOOLEAN_FIELDS = {
    "is_replication_configured", "is_nfs_configured", "is_smb_configured",
    "is_ransomware_suspected", "is_audit_disabled", "has_unauthorized_admin"
}

COMPONENT_DETAILS_FIELDS = {
    "failed_disks_details": "failed_disks",
    "failed_fans_details": "failed_fans"
}

COLLECTION_STATUSES = {"collected", "partial", "unavailable", "unsupported", "not_applicable"}
DEVICE_INPUT_FIELDS = {
    "family", "type", "name", "serial_number", "service_tag", "software_version",
    "uptime_seconds", "datetime", "manufacturer_division",
}


class InputValidationError(ValueError):
    """A entrada não atende ao contrato; nenhuma saída deve ser substituída."""


def _reject_json_constant(value):
    raise InputValidationError(f"Constante JSON inválida: {value}. Use números finitos.")


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputValidationError(f"Chave JSON duplicada: '{key}'.")
        result[key] = value
    return result


def _device_segment(value, field):
    # Mantém a nomenclatura anterior, impedindo que a entrada altere o diretório.
    segment = value.strip().lower()
    if not segment or segment in (".", "..") or any(
        char in segment for char in ("/", "\\", "\x00", "\n", "\r")
    ):
        raise InputValidationError(f"Campo '{field}' inválido para identificar o equipamento.")
    return segment


def _event_token(value):
    return re.sub(r"[\s_]+", " ", value.strip()).casefold()


def _number(value, field, index):
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError()
        # Preserva inteiros grandes; não os converte desnecessariamente a float.
        if field in INTEGER_FIELDS and isinstance(value, int):
            number = value
        elif field in INTEGER_FIELDS and isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
            number = int(value)
        else:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError()
            if field in INTEGER_FIELDS:
                if not number.is_integer():
                    raise ValueError()
                number = int(number)
        if field not in ("current_temperature", "days_to_expire") and number < 0:
            raise ValueError()
        return number
    except (ValueError, TypeError, OverflowError):
        kind = "inteiro" if field in INTEGER_FIELDS else "número finito"
        raise InputValidationError(f"Registro {index}: '{field}' precisa ser um {kind} válido.")


def _boolean(value, field, index):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in ("true", "1"):
            return True
        if normalized in ("false", "0"):
            return False
    raise InputValidationError(f"Registro {index}: '{field}' precisa ser true ou false.")


def _normalize_component_details(value, field, index):
    if not isinstance(value, list):
        raise InputValidationError(f"Registro {index}: '{field}' precisa ser uma lista de objetos.")
    components = []
    identifiers = set()
    for position, raw in enumerate(value, 1):
        label = f"{field}[{position}]"
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"].strip():
            raise InputValidationError(f"Registro {index}: '{label}' precisa ter um 'id' textual não vazio.")
        component = dict(raw)
        component["id"] = raw["id"].strip()
        identifier = component["id"].casefold()
        if identifier in identifiers:
            raise InputValidationError(f"Registro {index}: ID duplicado em '{field}': '{component['id']}'.")
        identifiers.add(identifier)
        for name in ("enclosure", "location", "controller", "serial_number", "health_status", "reason", "role"):
            if name not in component:
                continue
            if component[name] is None:
                component.pop(name)
            elif not isinstance(component[name], str):
                raise InputValidationError(f"Registro {index}: '{label}.{name}' precisa ser texto.")
            else:
                component[name] = component[name].strip()
        if "slot" in component:
            slot = component["slot"]
            if slot is None:
                component.pop("slot")
            elif isinstance(slot, str) and slot.strip():
                component["slot"] = slot.strip()
            elif isinstance(slot, int) and not isinstance(slot, bool) and slot >= 0:
                pass
            else:
                raise InputValidationError(f"Registro {index}: '{label}.slot' precisa ser inteiro não negativo ou texto.")
        if "is_spare" in component:
            if component["is_spare"] is None:
                component.pop("is_spare")
            else:
                component["is_spare"] = _boolean(component["is_spare"], f"{label}.is_spare", index)
        if "rpm" in component:
            if component["rpm"] is None:
                component.pop("rpm")
            else:
                component["rpm"] = _number(component["rpm"], f"{label}.rpm", index)
        components.append(component)
    return components


def normalize_row(raw, index=1):
    if not isinstance(raw, dict):
        raise InputValidationError(f"Registro {index}: cada registro precisa ser um objeto JSON.")

    row = {}
    for field in INPUT_FIELDS:
        value = raw.get(field)
        # Ausência não pode apagar uma medição válida recebida em outro registro.
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if field in INTEGER_FIELDS or field in FLOAT_FIELDS:
            row[field] = _number(value, field, index)
        elif field in BOOLEAN_FIELDS:
            row[field] = _boolean(value, field, index)
        else:
            if field in ("serial_number", "service_tag") and isinstance(value, int) and not isinstance(value, bool):
                value = str(value)
            if not isinstance(value, str):
                raise InputValidationError(f"Registro {index}: '{field}' precisa ser texto.")
            row[field] = value.strip()

    if "collection_status" in raw:
        status = raw["collection_status"]
        if not isinstance(status, str) or status not in COLLECTION_STATUSES:
            raise InputValidationError(f"Registro {index}: collection_status inválido.")
        row["collection_status"] = status
        reason = raw.get("collection_reason", "")
        if not isinstance(reason, str):
            raise InputValidationError(f"Registro {index}: collection_reason precisa ser texto.")
        row["collection_reason"] = reason
    if "source_details" in raw:
        if not isinstance(raw["source_details"], dict):
            raise InputValidationError(f"Registro {index}: source_details precisa ser um objeto.")
        try:
            json.dumps(raw["source_details"], allow_nan=False)
        except (TypeError, ValueError):
            raise InputValidationError(f"Registro {index}: source_details precisa conter JSON finito.")
        row["source_details"] = raw["source_details"]

    for field, counter in COMPONENT_DETAILS_FIELDS.items():
        if field in raw and raw[field] is not None:
            row[field] = _normalize_component_details(raw[field], field, index)
            if counter not in row:
                row[counter] = len(row[field])
            if len(row[field]) > row[counter]:
                raise InputValidationError(
                    f"Registro {index}: '{field}' identifica mais componentes do que '{counter}'."
                )

    for field in ("family", "name"):
        if field not in row:
            raise InputValidationError(f"Registro {index}: campo obrigatório '{field}' ausente.")
        _device_segment(row[field], field)

    if "event_name" in row:
        names = {_event_token(name): name for name in ACTIVE_HANDLERS}
        canonical = names.get(_event_token(row["event_name"]))
        if canonical is None:
            raise InputValidationError(
                f"Registro {index}: event_name '{row['event_name']}' não existe em ACTIVE_HANDLERS."
            )
        row["event_name"] = canonical
    elif "collection_status" in row:
        raise InputValidationError(f"Registro {index}: collection_status requer event_name para definir seu escopo.")

    for component in ("fans", "disks", "psus", "controllers"):
        total, failed = "total_" + component, "failed_" + component
        if total in row and failed in row and row[failed] > row[total]:
            raise InputValidationError(f"Registro {index}: '{failed}' não pode exceder '{total}'.")
    return row


def expand_device_input(device, index=1):
    """Expande uma entrada v2 por equipamento sem alterar as regras ACTIVE_HANDLERS.

    Identidade é compartilhada em device_info; cada chave de events identifica
    uma medição. Não aceita JSON de saída como entrada nem evento incompleto.
    A expansão é somente em memória; o input_events.json mantém uma unidade por
    objeto, e todos os handlers ainda executam uma vez por unidade.
    """
    if (device.get("schema_version") != 2 or not isinstance(device.get("device_info"), dict)
            or not isinstance(device.get("events"), dict)):
        raise InputValidationError(f"Equipamento {index}: formato device_info/events requer schema_version 2.")
    info = device["device_info"]
    if set(info) - DEVICE_INPUT_FIELDS:
        raise InputValidationError(f"Equipamento {index}: device_info contém campos fora da identidade.")
    if set(device["events"]) != set(ACTIVE_HANDLERS):
        raise InputValidationError(f"Equipamento {index}: events deve conter exatamente todos os ACTIVE_HANDLERS.")
    rows = []
    for event in ACTIVE_HANDLERS:
        values = device["events"][event]
        if (not isinstance(values, dict) or set(values) & (DEVICE_INPUT_FIELDS | {"event_name"})
                or "collection_status" not in values):
            raise InputValidationError(f"Equipamento {index}: evento '{event}' inválido ou sem qualidade de coleta.")
        row = dict(info)
        row.update(values)
        row["event_name"] = event
        rows.append(row)
    return rows


def load_json_rows(json_filepath):
    try:
        with open(json_filepath, 'r', encoding='utf-8-sig') as file:
            payload = json.load(
                file, parse_constant=_reject_json_constant,
                object_pairs_hook=_unique_json_object
            )
    except json.JSONDecodeError as error:
        raise InputValidationError(f"Arquivo '{json_filepath}' vazio ou JSON inválido: {error}")

    if isinstance(payload, dict):
        if "device_info" in payload:
            payload = [payload]
        elif "events" in payload:
            payload = payload["events"]
            if not isinstance(payload, list):
                raise InputValidationError(
                    "'events' na entrada precisa ser uma lista de registros brutos. "
                    "O JSON de saída não é um input_events.json."
                )
        else:
            payload = [payload]
    if not isinstance(payload, list) or not payload:
        raise InputValidationError("A entrada precisa conter um objeto ou uma lista não vazia de registros.")
    rows = []
    for index, raw in enumerate(payload, 1):
        if isinstance(raw, dict) and "device_info" in raw:
            rows.extend(expand_device_input(raw, index))
        else:
            rows.append(raw)
    return [normalize_row(raw, index) for index, raw in enumerate(rows, 1)]


def group_device_rows(rows):
    groups = {}
    for row in rows:
        key = (_device_segment(row["family"], "family"), _device_segment(row["name"], "name"))
        if key not in groups:
            groups[key] = {"context": {}, "events": {}, "rows": [], "detail_timestamps": {}}
        group = groups[key]
        for field in ("serial_number", "service_tag"):
            previous = group["context"].get(field)
            if previous and field in row and previous != row[field]:
                raise InputValidationError(
                    f"Equipamento '{row['name']}': valores conflitantes de '{field}'."
                )
        for field, counter in COMPONENT_DETAILS_FIELDS.items():
            if counter in row and field not in row:
                changed_count = row[counter] != group["context"].get(counter)
                old_time = group["detail_timestamps"].get(field)
                new_time = row.get("datetime")
                if changed_count or (old_time and new_time and old_time != new_time):
                    # Quantidade ou coleta mudou: a lista antiga não identifica a nova falha.
                    group["context"].pop(field, None)
                    group["detail_timestamps"].pop(field, None)
            if field in row:
                group["detail_timestamps"][field] = row.get("datetime")
        group["context"].update(row)
        group["rows"].append(row)
        if "event_name" in row:
            # O último registro do MESMO evento substitui o anterior; os demais ficam.
            group["events"][row["event_name"]] = row
    return groups


def _finalize_event(event, event_name):
    details = event["event_details"]
    if event["component_health_status"] in ("OK", "HEALTHY", "NORMAL"):
        event["component_health_status"] = "OK"
        details.update({
            "severity": "Info", "impact": "None",
            "recommended_action": "None required", "priority": "P4"
        })
    else:
        # Uma métrica pode gerar um alerta mesmo quando o status de entrada é OK.
        if details.get("impact") in (None, "", "None", "Unknown"):
            details["impact"] = "Potential service degradation"
        if details.get("recommended_action") in (None, "", "None required", "None", "Unknown"):
            details["recommended_action"] = f"Investigate {event_name} and check device logs."
    return event


def _component_label(component):
    parts = [component["id"]]
    for field in ("enclosure", "slot", "controller", "location"):
        if field in component and component[field] != "":
            parts.append(f"{field}: {component[field]}")
    if "is_spare" in component:
        parts.append("spare" if component["is_spare"] else "não spare")
    return " / ".join(parts)


def _attach_affected_components(event, row, field, counter, component_type, source):
    details = event["event_details"]
    failures = row.get(counter, 0)
    components = row.get(field, []) if failures else []
    details["affected_components"] = [dict(component, component_type=component_type) for component in components]
    identified = len(components)
    status = "not_required" if not failures else (
        "complete" if identified == failures else "partial" if identified else "not_provided"
    )
    details["component_identification"] = {
        "status": status,
        "reported_failures": failures,
        "identified_failures": identified,
        "unidentified_failures": max(0, failures - identified)
    }
    if failures:
        if components:
            labels = "; ".join(_component_label(component) for component in components)
            details["custom_description"] += f" Componentes afetados: {labels}."
        if failures > identified:
            details["custom_description"] += (
                f" Identificação não informada pelo coletor para {failures - identified} componente(s)."
            )
    if source is not None and source.get("custom_description"):
        details["source_description"] = source["custom_description"]
    return event


def _attach_collection_quality(event, source, event_name):
    """Mantém as chamadas dos handlers; corrige seus defaults sem evidência."""
    if source is None or "collection_status" not in source:
        return event
    status = source["collection_status"]
    details = event["event_details"]
    details["collection"] = {
        "status": status,
        "reason": source.get("collection_reason", ""),
    }
    details["source_details"] = source.get("source_details", {})
    if source.get("custom_description"):
        details["source_description"] = source["custom_description"]

    aliases = {"current_temperature_celsius": "current_temperature"}
    if event_name.startswith("Replication"):
        aliases["is_configured"] = "is_replication_configured"
    elif event_name == "NFS Service":
        aliases["is_configured"] = "is_nfs_configured"
    elif event_name == "SMB Service":
        aliases["is_configured"] = "is_smb_configured"
    constants = {"warning_threshold", "critical_threshold", "threshold_limit", "allowed_failures"}
    metrics = details.get("metrics", {})
    observations = _security_observations(source)
    antivirus_metrics = {"antivirus_enabled_count", "antivirus_disabled_count", "antivirus_unknown_count",
                         "antivirus_unconfigured_nas_count"}
    for key in metrics:
        field = aliases.get(key, key)
        if key in constants:
            continue
        if (event_name == "Ransomware Pattern" and key in antivirus_metrics
                and observations.get("security_scope") == "antivirus_configuration"):
            continue  # Derivados pelo handler da configuração CAVA, não dos campos do CSV.
        if field in source:
            metrics[key] = source[field]
        elif key.startswith("healthy_") and status == "collected":
            pass
        else:
            metrics[key] = None

    incomplete = status in ("unavailable", "unsupported") or (
        status == "partial" and event["component_health_status"] == "OK"
    )
    if incomplete or status == "not_applicable":
        event["component_health_status"] = "NOT_APPLICABLE" if status == "not_applicable" else "UNKNOWN"
        details.update({
            "severity": "Info" if status == "not_applicable" else "Unknown",
            "priority": "P4" if status == "not_applicable" else "P3",
            "impact": "None" if status == "not_applicable" else "Monitoring data unavailable",
            "recommended_action": "None required" if status == "not_applicable" else
                "Restore or configure the data source before assessing this event.",
            "custom_description": source.get("collection_reason") or "Medição indisponível.",
        })
        if "component_identification" in details:
            details["component_identification"]["status"] = (
                "not_required" if status == "not_applicable" else "unknown"
            )
            if "failed_disks" not in source and "failed_fans" not in source:
                for key in ("reported_failures", "unidentified_failures"):
                    details["component_identification"][key] = None
    return event


def build_device_payload(group):
    context = group["context"]
    events = {}
    for event_name, handler in ACTIVE_HANDLERS.items():
        row = _create_healthy_mock_row(context, event_name)
        source = group["events"].get(event_name)
        if source is not None:
            row.update(source)
            # O status de outro componente não é evidência sobre este evento.
            row["health_status"] = source.get("health_status", "UNKNOWN")
            for field, counter in COMPONENT_DETAILS_FIELDS.items():
                if counter in source and field not in source:
                    changed_count = source[counter] != context.get(counter)
                    detail_time = group["detail_timestamps"].get(field)
                    source_time = source.get("datetime")
                    if changed_count or (detail_time and source_time and detail_time != source_time):
                        row.pop(field, None)

        if event_name in ("Volume Usage", "Pool Usage", "Pool Full"):
            scope = ("Volume Usage",) if event_name == "Volume Usage" else ("Pool Usage", "Pool Full")
            capacity_rows = [
                item for item in group["rows"]
                if item.get("event_name") in scope and "usage_percentage" in item
            ]
            if capacity_rows:
                row["usage_percentage"] = capacity_rows[-1]["usage_percentage"]
            else:
                # usage_percentage de um volume não é a ocupação do pool, e vice-versa.
                shared_rows = [
                    item for item in group["rows"]
                    if item.get("event_name") not in ("Volume Usage", "Pool Usage", "Pool Full")
                    and "usage_percentage" in item
                ]
                if shared_rows:
                    row["usage_percentage"] = shared_rows[-1]["usage_percentage"]
                else:
                    row.pop("usage_percentage", None)

        # Verifica também as contagens após combinar medições parciais.
        row = normalize_row(row)

        # Chamada mandatória: executada para CADA entrada de ACTIVE_HANDLERS.
        event = handler(row)
        key = event_name.lower().replace(" ", "_")
        event = _finalize_event(event, event_name)
        if event_name == "Multiple Disk Failure":
            event = _attach_affected_components(event, row, "failed_disks_details", "failed_disks", "disk", source)
        elif event_name == "Fan Failure":
            event = _attach_affected_components(event, row, "failed_fans_details", "failed_fans", "fan", source)
        event = _attach_collection_quality(event, source, event_name)
        events[key] = event

    return {"device_info": _build_device_info(context), "events": events}


def process_json_events(json_filepath, verbose=False, base_path=None):
    """Valida toda a entrada, chama todos os handlers e retorna as saídas geradas.

    Erros de entrada levantam InputValidationError antes de substituir arquivos.
    Registros devem estar em ordem de coleta; para um evento repetido, vence o último.
    """
    groups = group_device_rows(load_json_rows(json_filepath))
    output_root = os.path.abspath(BASE_PATH if base_path is None else base_path)
    outputs = []
    for (family, name), group in groups.items():
        payload = build_device_payload(group)
        # Valida a serialização de todas as saídas antes de iniciar a gravação.
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
        final_path = os.path.join(output_root, family, name, "public", f"done-{name}.json")
        if os.path.realpath(final_path) == os.path.realpath(json_filepath):
            raise InputValidationError("O arquivo de entrada não pode ser o arquivo de saída.")
        outputs.append((final_path, payload))

    staged = []
    try:
        for final_path, payload in outputs:
            target_dir = os.path.dirname(final_path)
            os.makedirs(target_dir, exist_ok=True)
            descriptor, temp_path = tempfile.mkstemp(prefix=".events-", suffix=".json.tmp", dir=target_dir)
            os.close(descriptor)
            staged.append((temp_path, final_path))
            output_mode = stat.S_IMODE(os.stat(final_path).st_mode) if os.path.exists(final_path) else 0o644
            os.chmod(temp_path, output_mode)
            write_temp_json(temp_path, payload)
        for temp_path, final_path in staged:
            validate_and_move_json(temp_path, final_path, verbose=verbose)
    finally:
        for temp_path, _ in staged:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    print(f"[SUCESSO] {len(outputs)} equipamento(s); {len(ACTIVE_HANDLERS)} handlers executados por equipamento.")
    return [final_path for final_path, _ in outputs]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="%(prog)s " + CONSTRUCTOR_VERSION,
                        help="Mostra a versão sem processar arquivos.")
    parser.add_argument("--input", default="input_events.json", help="Arquivo JSON de entrada (padrão: input_events.json).")
    parser.add_argument("--output-dir", default=BASE_PATH, help="Diretório base das saídas (padrão: diretório atual).")
    parser.add_argument("--verbose", action="store_true", help="Exibe os caminhos e os JSONs gerados.")
    args = parser.parse_args(argv)
    try:
        process_json_events(args.input, verbose=args.verbose, base_path=args.output_dir)
    except (InputValidationError, OSError) as error:
        print(f"[ERRO] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
