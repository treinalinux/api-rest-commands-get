#!/usr/bin/env python3
"""Coleta Unity XT 380F/480F e publica input_events.json sem interação.

Fluxo: inventário -> identidade -> COLLECTION_HANDLERS -> validação -> publicação.
Cada handler tem uma função collect_* e retorna exatamente um registro de entrada.
CollectionContext compartilha consultas dentro de um equipamento, sem novo login.
O JSON v2 publicado contém um objeto por unidade, com device_info e 25 events.

Autenticação e sessão pertencem ao storage_api_manager do usuário. Linux/RHEL
8 ou 9, Python 3.6+. Consulte README_Coletor_Unity.md para operação e
MANUTENCAO_Coletor_Unity.md para alterar handlers e diagnosticar falhas.
"""

import argparse
import fcntl
import inspect
import json
import logging
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, unquote_plus, urlencode, urljoin, urlsplit


LOG = logging.getLogger("unity.collector")
INPUT_FIELDS = (
    "family", "type", "name", "serial_number", "service_tag", "software_version",
    "health_status", "uptime_seconds", "datetime", "manufacturer_division",
    "manufacturer_severity", "manufacturer_category", "event_name", "impact",
    "recommended_action", "priority", "custom_description", "total_fans", "failed_fans",
    "current_temperature", "total_disks", "failed_disks", "usage_percentage", "total_psus",
    "failed_psus", "total_controllers", "failed_controllers", "controller_cpu_percentage",
    "smb_latency_ms", "nfs_latency_ms", "nfs_retransmissions_pct", "cpu_utilization_pct",
    "storage_utilization_pct", "network_utilization_pct", "packet_loss_pct", "lag_minutes",
    "rpo_minutes", "days_to_expire", "is_replication_configured", "is_nfs_configured",
    "is_smb_configured", "is_ransomware_suspected", "is_audit_disabled", "has_unauthorized_admin",
)
DEVICE_FIELDS = (
    "family", "type", "name", "serial_number", "service_tag", "software_version",
    "uptime_seconds", "datetime", "manufacturer_division",
)
# Consultas básicas próximas dos exemplos executados no Unity. Metadados físicos
# são enriquecidos separadamente: um campo opcional inválido não apaga a saúde.
RESOURCES = {
    "installedSoftwareVersion": "id,version,fullVersion",
    "storageProcessor": "id,name,health,isRescueMode,needsReplacement",
    "disk": "id,name,health",
    "fan": "id,name,health",
    "powerSupply": "id,name,health",
    "dpe": "id,name,health,currentTemperature",
    "dae": "id,name,health,currentTemperature",
    "pool": "id,name,sizeUsed,sizeTotal",
    "filesystem": "id,name,health,sizeTotal,sizeUsed",
    "lun": "id,name,health,sizeTotal,sizeAllocated",
    "nasServer": "id,name,nfsServer,cifsServer,health",
    "nfsServer": "id,hostName,nasServer,nfsv3Enabled,nfsv4Enabled",
    "cifsServer": "id,name,health,nasServer",
    "replicationSession": "id,name,health,status,syncState,networkStatus",
    "alert": "id,timestamp,state,severity,messageId,message,description,resolution,component",
    "virusChecker": "id,isEnabled,nasServer",
    "metric": "id,name,path,type,unitDisplayString,isRealtimeAvailable,isHistoricalAvailable",
    "metricService": "id,isHistoricalEnabled",
}
RESOURCE_DETAILS = {
    "storageProcessor": "slotNumber,emcSerialNumber,parentDpe",
    "disk": "needsReplacement,slotNumber,emcSerialNumber,parentDpe,parentDae,pool,isInUse",
    "fan": "needsReplacement,slotNumber,emcSerialNumber,vendorSerialNumber,parentDpe,parentDae,storageProcessor",
    "powerSupply": "needsReplacement,slotNumber,emcSerialNumber,parentDpe,parentDae,storageProcessor",
    "pool": "health,sizeFree,sizePreallocated",
    "replicationSession": "srcStatus,dstStatus,maxTimeOutOfSync,lastSyncTime,localRole",
    "metric": "description",
}
CPU_BUSY = "sp.*.cpu.summary.busyTicks"
CPU_IDLE = "sp.*.cpu.summary.idleTicks"
PERFORMANCE = {
    "SMB latency": "smb_latency_ms", "NFS latency": "nfs_latency_ms",
    "NFS retransmissions": "nfs_retransmissions_pct",
    "Network utilization": "network_utilization_pct", "Packet loss": "packet_loss_pct",
}
SECURITY = {
    "Audit Disabled": "is_audit_disabled", "Unauthorized Admin": "has_unauthorized_admin",
    "Ransomware Pattern": "is_ransomware_suspected",
}
COLLECTION_STATUSES = frozenset(("collected", "partial", "unavailable", "unsupported", "not_applicable"))


class CollectionError(RuntimeError):
    """Falha com mensagem controlada, que pode aparecer no log sem credenciais."""


class RESTError(CollectionError):
    """Erro HTTP controlado; status permite fallback apenas para seleção inválida."""

    def __init__(self, status, endpoint):
        """Registra código e caminho, sem corpo, headers ou credenciais."""
        self.status = status
        super().__init__("HTTP {} em {}".format(status, endpoint))


def utc_now():
    """Retorna o horário atual com fuso UTC explícito."""
    return datetime.now(timezone.utc)


def iso(value):
    """Formata um datetime com fuso como ISO 8601 UTC, com segundos e sufixo Z."""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def timestamp(value):
    """Lê ISO 8601 com fuso no Python 3.6; rejeita horários ambíguos/sem fuso."""
    if not isinstance(value, str):
        raise ValueError("Timestamp ausente")
    # Python 3.6 (RHEL 8) não fornece datetime.fromisoformat e seu %z
    # requer offsets sem ':'. Aceita ISO 8601 com segundos e fuso explícito.
    normalized = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", value.strip())
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+0000"
    for pattern in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(normalized, pattern).astimezone(timezone.utc)
        except ValueError:
            pass
    raise ValueError("Timestamp inválido; use ISO 8601 com segundos e fuso horário.")


def number(value):
    """Retorna float finito ou None; booleanos nunca representam uma medição."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def health_value(item):
    """Lê health.value; retorna 0 (desconhecido) se a resposta não for válida."""
    health = item.get("health")
    value = health.get("value") if isinstance(health, dict) else health
    value = number(value)
    return int(value) if value is not None and value.is_integer() else 0


def health_text(item):
    """Extrai as descrições de saúde para explicar a condição de um componente."""
    health = item.get("health", {})
    if isinstance(health, dict):
        descriptions = health.get("descriptions", health.get("description", []))
        if isinstance(descriptions, list):
            return "; ".join(str(part) for part in descriptions)
        return str(descriptions)
    return str(health)


def reference(value):
    """Lê o ID de uma relação REST, aceitando objeto {id: ...} ou ID direto."""
    return value.get("id") if isinstance(value, dict) else value


def error_text(error):
    """Expõe mensagens próprias ou apenas o tipo de erro vindo do motor externo."""
    # Não copia corpos, headers, credenciais ou URLs gerados pelo motor.
    return str(error) if isinstance(error, CollectionError) else type(error).__name__


def error_location(error):
    """Mostra arquivo, linha e função da falha, sem mensagem externa ou variáveis."""
    frames = traceback.extract_tb(error.__traceback__)
    return " > ".join("{}:{}:{}".format(Path(frame.filename).name, frame.lineno, frame.name)
                      for frame in frames[-3:]) or "local indisponível"


def supports_json_body(storage):
    """Verifica a interface pública do motor antes de enviar um corpo JSON."""
    try:
        parameters = inspect.signature(storage.make_request).parameters
    except (TypeError, ValueError):
        return False
    return "json" in parameters or any(parameter.kind == inspect.Parameter.VAR_KEYWORD
                                       for parameter in parameters.values())


def redact_diagnostic(value):
    """Oculta campos de autenticação e segredos nomeados nos corpos de debug.

    Preserva telemetria, IDs e demais valores. Não altera a resposta usada pelos
    handlers; cria outra estrutura somente para o log. Headers não são lidos.
    """
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            sensitive = (normalized in ("authorization", "credentials", "setcookie", "sessionid")
                         or normalized.endswith(("password", "passwd", "secret", "token", "cookie")))
            result[key] = "[REDACTED]" if sensitive else redact_diagnostic(item)
        return result
    if isinstance(value, list):
        return [redact_diagnostic(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", r"\1 [REDACTED]", value)
        return re.sub(r"(?i)(\b(?:password|passwd|secret|token|cookie|authorization)\s*[:=]\s*)"
                      r"(?:\"[^\"]*\"|'[^']*'|[^\s,;<>]+)", r"\1[REDACTED]", value)
    return value


class UnityAPI:
    """Adapta make_request e valida REST/paginação usando a sessão existente."""

    def __init__(self, storage, address, max_pages=500, verbosity=0):
        """Recebe sessão, limite de páginas e nível 0/1/2 do diagnóstico."""
        self.storage = storage
        base = address if "://" in address else "https://" + address
        self.origin = urlsplit(base)
        self.max_pages = max_pages
        self.verbosity = verbosity
        self.device_name = "não informado"
        self.handler = "identificação"

    def endpoint(self, path):
        """Mostra URL HTTPS e query legível, sem userinfo nem segredos nomeados."""
        host = self.origin.hostname or "host-desconhecido"
        host = "[{}]".format(host) if ":" in host else host
        if self.origin.port is not None:
            host += ":{}".format(self.origin.port)
        parsed = urlsplit(path)
        query = unquote_plus(parsed.query)
        value = "{}://{}{}{}".format(self.origin.scheme, host, parsed.path,
                                     "?" + query if query else "")
        return redact_diagnostic(value)

    def log_response(self, response, status, payload, is_json):
        """Em nível 2 mostra corpo JSON/texto recebido, inclusive erro HTTP."""
        if self.verbosity < 2:
            return
        value = payload if is_json else getattr(response, "text", "")
        LOG.debug("etapa=resposta equipamento=%s handler=%r http_status=%s formato=%s corpo=%s",
                  self.device_name, self.handler, status, "json" if is_json else "texto",
                  json.dumps(redact_diagnostic(value), ensure_ascii=False, indent=2, default=str))

    def request(self, method, path, body=None):
        """Executa REST; -v mostra query completa, -vv também os corpos sem segredos."""
        LOG.debug("etapa=consulta equipamento=%s handler=%r metodo=%s endpoint=%s",
                  self.device_name, self.handler, method, self.endpoint(path))
        if body is not None and self.verbosity >= 2:
            LOG.debug("etapa=envio equipamento=%s handler=%r corpo=%s", self.device_name,
                      self.handler, json.dumps(redact_diagnostic(body), ensure_ascii=False, indent=2))
        if body is None:
            response = self.storage.make_request(method, path)
        else:
            # Mantém make_request; não abre sessão paralela nem refaz o login.
            if not supports_json_body(self.storage):
                raise CollectionError("make_request não aceita json=; usando somente consultas GET.")
            response = self.storage.make_request(method, path, json=body)
        if response is None:
            raise CollectionError("O motor retornou uma resposta vazia.")
        status = getattr(response, "status_code", 200)
        # Lê o JSON uma vez. Em -vv erros HTTP também mostram o corpo recebido.
        payload, is_json = None, False
        if self.verbosity >= 2 or (200 <= status < 300 and method != "DELETE"):
            try:
                payload, is_json = response.json(), True
            except (AttributeError, TypeError, ValueError):
                pass
        self.log_response(response, status, payload, is_json)
        if status < 200 or status >= 300:
            raise RESTError(status, urlsplit(path).path)
        if method == "DELETE":
            return {}
        if not is_json:
            raise CollectionError("Resposta REST não contém JSON válido.")
        if not isinstance(payload, dict) or "error" in payload:
            raise CollectionError("Resposta REST inválida ou contém erro.")
        return payload

    def _next_path(self, base, href, resource_path):
        """Resolve o link next sem permitir mudar a origem ou a coleção REST."""
        if not isinstance(base, str) or not isinstance(href, str):
            raise CollectionError("Link de paginação inválido.")
        if href.startswith("&"):
            parsed = urlsplit(base)
            parameters = dict(parse_qsl(parsed.query, keep_blank_values=True))
            parameters.update(parse_qsl(href[1:], keep_blank_values=True))
            target = parsed._replace(query=urlencode(parameters)).geturl()
        else:
            target = urljoin(base, href)
        parsed = urlsplit(target)
        if parsed.netloc:
            if (parsed.scheme != "https" or parsed.hostname != self.origin.hostname
                    or (parsed.port or 443) != (self.origin.port or 443)
                    or parsed.username or parsed.password):
                raise CollectionError("Link de paginação aponta para outra origem.")
        if parsed.path != resource_path or parsed.fragment:
            raise CollectionError("Link de paginação alterou o recurso consultado.")
        return parsed.path + ("?" + parsed.query if parsed.query else "")

    def collection(self, resource, fields=None, filter_expression=None, compact=True):
        """Retorna content de todas as páginas; resposta incompleta gera erro."""
        resource_path = "/api/types/{}/instances".format(resource)
        parameters = {}
        if fields:
            parameters["fields"] = fields
        if compact:
            parameters["compact"] = "true"
        if filter_expression:
            parameters["filter"] = filter_expression
        path = resource_path + "?" + urlencode(parameters)
        result, seen = [], set()
        for _ in range(self.max_pages):
            if path in seen:
                raise CollectionError("Paginação circular em {}.".format(resource))
            seen.add(path)
            payload = self.request("GET", path)
            entries = payload.get("entries")
            if not isinstance(entries, list):
                raise CollectionError("Coleção {} sem entries válidas.".format(resource))
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("content"), dict):
                    raise CollectionError("Item inválido em {}.".format(resource))
                result.append(entry["content"])
            links = payload.get("links", [])
            if not isinstance(links, list):
                raise CollectionError("Paginação inválida em {}.".format(resource))
            next_links = [link for link in links if isinstance(link, dict) and link.get("rel") == "next"]
            if not next_links:
                return result
            if len(next_links) != 1:
                raise CollectionError("Múltiplos links next em {}.".format(resource))
            path = self._next_path(payload.get("@base", payload.get("base", path)),
                                   next_links[0].get("href"), resource_path)
        raise CollectionError("Limite de páginas excedido em {}.".format(resource))


def flatten_values(value, prefix=""):
    """Achata valores de métricas por caminho de instância, mantendo só números."""
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            result.update(flatten_values(child, prefix + "/" + str(key)))
        return result
    value = number(value)
    return {prefix.lstrip("/"): value} if value is not None else {}


def metric_samples(entries, path, now, max_age):
    """Agrupa amostras recentes por timestamp; ignora antigas e futuras incoerentes."""
    result = {}
    for item in entries:
        if item.get("path") != path:
            continue
        try:
            when = timestamp(item.get("timestamp"))
        except ValueError:
            continue
        age = (now - when).total_seconds()
        if -5 <= age <= max_age:
            result[when] = flatten_values(item.get("values"))
    return result


def counter_ratio(entries, numerator, denominator, now, max_age, cpu=False):
    """Calcula percentuais por delta de duas amostras comuns e sincronizadas.

    Para CPU, o denominador é delta(busy) + delta(idle). Nos outros casos,
    é delta(denominator). Reset, ausência de tráfego e amostras insuficientes
    não produzem zero: retornam valores vazios e uma razão para diagnóstico.
    """
    first = metric_samples(entries, numerator, now, max_age)
    second = metric_samples(entries, denominator, now, max_age)
    times = sorted(set(first) & set(second))
    if len(times) < 2:
        return {}, "São necessárias duas amostras sincronizadas dos contadores."
    before, after = times[-2:]
    keys = set(first[before]) & set(first[after]) & set(second[before]) & set(second[after])
    result = {}
    for key in keys:
        increment = first[after][key] - first[before][key]
        other = second[after][key] - second[before][key]
        total = increment + other if cpu else other
        if increment < 0 or other < 0 or total <= 0:
            continue  # Reinício/wrap/ausência de tráfego não significam 0%.
        value = 100.0 * increment / total
        if 0 <= value <= 100:
            result[key] = round(value, 4)
    return result, "Contadores sem delta válido; possível reinício ou ausência de tráfego."


def unit_factor(unit, field):
    """Valida unidade e retorna o fator para milissegundos ou percentual."""
    unit = str(unit).strip().casefold()
    if field.endswith("_ms"):
        return {"ms": 1, "millisecond": 1, "milliseconds": 1, "milissegundos": 1,
                "us": .001, "µs": .001, "microseconds": .001, "microssegundos": .001,
                "microsecond": .001, "μs": .001, "usec": .001,
                "s": 1000, "second": 1000, "seconds": 1000, "segundos": 1000}.get(unit)
    return 1 if unit in ("%", "percent", "percentage", "pct", "porcentagem", "percentual") else None


def metric_candidates(catalog, field):
    """Identifica caminhos relacionados em memória; publica somente sua contagem."""
    results = []
    for item in catalog:
        text = " ".join(str(item.get(key, "")) for key in ("path", "name", "description")).casefold()
        related = ((field.startswith("smb_") and ("cifs" in text or "smb" in text))
                   or (field.startswith("nfs_") and "nfs" in text)
                   or (field in ("network_utilization_pct", "packet_loss_pct") and ".net." in text))
        if related:
            results.append({key: item.get(key) for key in ("path", "name", "type", "unitDisplayString",
                                                         "isRealtimeAvailable", "isHistoricalAvailable")})
    return results


def choose_bindings(catalog, config):
    """Descobre só gauges com unidade e significado inequívocos; admite override."""
    result = dict(config.get("bindings", {}))
    for event, field in PERFORMANCE.items():
        if field in result:
            continue
        candidates = []
        for metric in catalog:
            text = " ".join(str(metric.get(key, "")) for key in ("path", "name", "description")).casefold()
            factor = unit_factor(metric.get("unitDisplayString", ""), field)
            if factor is None or metric.get("type") not in (4, 5):
                continue
            matches = (
                (field == "smb_latency_ms" and ("cifs" in text or "smb" in text)
                 and ("latency" in text or "response time" in text or "responsetime" in text))
                or (field == "nfs_latency_ms" and "nfs" in text
                    and ("latency" in text or "response time" in text or "responsetime" in text))
                or (field == "nfs_retransmissions_pct" and "nfs" in text and "retrans" in text)
                or (field == "network_utilization_pct" and ".net." in text and "utilization" in text)
                or (field == "packet_loss_pct" and ".net." in text and "packet loss" in text)
            )
            if matches and metric.get("path"):
                candidates.append({"path": metric["path"], "unit": metric["unitDisplayString"]})
        if len(candidates) == 1:
            result[field] = candidates[0]
    return result


def read_metrics(api, catalog, bindings, now, mode, interval, max_age, sleep=time.sleep):
    """Busca uma única série compartilhada pelos handlers de desempenho.

    auto tenta tempo real e histórico; historical usa apenas GET; realtime
    usa uma consulta temporária. Remove somente a consulta que criou, mesmo
    em erro. Retorna (amostras, razão), sem inventar valores ausentes.
    sleep é injetável para testar a amostragem sem aguardar os intervalos.
    """
    known = {item.get("path"): item for item in catalog if item.get("path")}
    paths = {path for path in (CPU_BUSY, CPU_IDLE) if path in known}
    for binding in bindings.values():
        for key in ("path", "numerator_path", "denominator_path"):
            if binding.get(key) in known:
                paths.add(binding[key])
    if not paths:
        return [], "Nenhum caminho de métrica compatível foi encontrado no catálogo."
    collected, reasons = [], []
    realtime = sorted(path for path in paths if known[path].get("isRealtimeAvailable") is True)
    if mode != "historical" and realtime:
        query_id = None
        try:
            payload = api.request("POST", "/api/types/metricRealTimeQuery/instances",
                                  {"paths": realtime, "interval": interval})
            query_id = payload.get("content", {}).get("id")
            if not isinstance(query_id, int) or isinstance(query_id, bool) or query_id < 0:
                query_id = None
                raise CollectionError("Consulta de métricas não retornou um ID numérico.")
            # Três intervalos dão margem para duas amostras de contadores.
            for _ in range(3):
                sleep(interval)
                collected.extend(api.collection("metricQueryResult", "queryId,path,timestamp,values",
                                                "queryId eq {}".format(query_id)))
        except Exception as error:
            reasons.append("Métricas em tempo real: " + error_text(error))
            LOG.warning("etapa=metricas equipamento=%s modo=realtime erro=%s local=%s",
                        api.device_name, error_text(error), error_location(error))
        finally:
            if query_id is not None:
                try:
                    api.request("DELETE", "/api/instances/metricRealTimeQuery/" + str(query_id))
                except Exception as error:
                    reasons.append("Consulta temporária expirará automaticamente: " + error_text(error))
                    LOG.warning("etapa=limpeza_metricas equipamento=%s query_id=%s erro=%s local=%s",
                                api.device_name, query_id, error_text(error), error_location(error))
    if mode != "realtime":
        historical = sorted(path for path in paths if known[path].get("isHistoricalAvailable") is True)
        if historical:
            path_filter = " or ".join('path eq "{}"'.format(path.replace('"', '\\"')) for path in historical)
            expression = '({}) and timestamp gt "{}"'.format(path_filter, iso(now - timedelta(seconds=max_age)))
            try:
                collected.extend(api.collection("metricValue", "path,timestamp,interval,values", expression))
            except Exception as error:
                reasons.append("Métricas históricas: " + error_text(error))
                LOG.warning("etapa=metricas equipamento=%s modo=historical erro=%s local=%s",
                            api.device_name, error_text(error), error_location(error))
    return collected, "; ".join(reasons) or "Amostras não disponíveis ou antigas."


def component_details(item, enclosures):
    """Identifica componente físico por ID, enclosure, slot, serial e motivo."""
    result = {"id": str(item["id"]), "name": str(item.get("name", item["id"])),
              "health_status": str(health_value(item)), "reason": health_text(item)}
    for field in ("parentDpe", "parentDae"):
        parent_id = reference(item.get(field))
        if parent_id:
            result["enclosure"] = enclosures.get(parent_id, str(parent_id))
    if item.get("slotNumber") is not None:
        result["slot"] = item["slotNumber"]
    serial = item.get("emcSerialNumber") or item.get("vendorSerialNumber")
    if serial:
        result["serial_number"] = str(serial)
    controller = reference(item.get("storageProcessor"))
    if controller:
        result["controller"] = str(controller)
    # isInUse=false NÃO identifica um spare. A API documentada não fornece isSpare.
    if isinstance(item.get("isSpare"), bool):
        result["is_spare"] = item["isSpare"]
    return result


def read_resource(api, resource, fields, filter_expression=None):
    """Lê saúde básica e enriquece por ID, sem perder dados se um extra falhar.

    HTTP 400/422 na seleção básica permite uma única tentativa sem fields/compact.
    Falhas de autenticação, transporte ou recurso inexistente não são repetidas.
    O enriquecimento é opcional; sua falha fica no log e nos detalhes da fonte.
    """
    diagnostics = {"fields": fields}
    try:
        items = api.collection(resource, fields, filter_expression)
    except RESTError as error:
        if error.status not in (400, 422):
            raise
        LOG.warning("etapa=campos equipamento=%s recurso=%s selecao_rejeitada=true tentativa=campos_padrao",
                    api.device_name, resource)
        diagnostics["fields_error"] = error_text(error)
        diagnostics["default_fields"] = True
        items = api.collection(resource, None, filter_expression, compact=False)
    extras = RESOURCE_DETAILS.get(resource)
    # Coleção vazia já é uma resposta válida. Não faz uma segunda consulta vazia.
    if extras and items:
        diagnostics["enrichment_fields"] = extras
        try:
            detailed = api.collection(resource, "id," + extras, filter_expression)
            by_id = {item.get("id"): item for item in detailed if item.get("id") is not None}
            items = [dict(item, **by_id.get(item.get("id"), {})) for item in items]
        except Exception as error:
            diagnostics["enrichment_error"] = error_text(error)
            LOG.warning("etapa=enriquecimento equipamento=%s handler=%r recurso=%s erro=%s dados_basicos=preservados local=%s",
                        api.device_name, api.handler, resource, error_text(error), error_location(error))
    return items, diagnostics


def openssl_timestamp(value):
    """Converte data GMT do OpenSSL sem depender do locale configurado no Python."""
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    try:
        month, day, clock, year, zone = value.split()
        if zone != "GMT":
            raise ValueError()
        hour, minute, second = (int(part) for part in clock.split(":"))
        return datetime(int(year), months.index(month) + 1, int(day), hour, minute, second, tzinfo=timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise CollectionError("OpenSSL retornou uma data de certificado inválida.")


def run_openssl(arguments, input_text, timeout):
    """Executa OpenSSL com stdin fechado por input, timeout e sem shell/credenciais."""
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    try:
        return subprocess.run(["openssl"] + arguments, input=input_text, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout,
                              env=environment, check=False)
    except FileNotFoundError:
        raise CollectionError("OpenSSL não encontrado no PATH do serviço.")
    except subprocess.TimeoutExpired:
        raise CollectionError("OpenSSL excedeu o timeout de {} segundos.".format(timeout))


def probe_https_certificate(address, now, timeout=15, server_name=None):
    """Lê o certificado folha HTTPS com s_client e seus dados com x509.

    Conexão TLS anônima, sem autenticação REST. Mede a validade do certificado
    realmente apresentado pela gestão; não declara confiança de CA/hostname.
    Certificado autoassinado ainda pode ter sua validade medida.
    """
    parsed = urlsplit(address if "://" in address else "https://" + address)
    host = parsed.hostname
    try:
        port = parsed.port or 443
    except ValueError:
        raise CollectionError("Porta HTTPS inválida para consultar o certificado.")
    name = server_name or host
    if (parsed.scheme != "https" or not host or parsed.username or parsed.password
            or not 1 <= port <= 65535 or not isinstance(name, str)
            or any(character.isspace() for character in host + name)):
        raise CollectionError("Endereço HTTPS/SNI inválido para consultar o certificado.")
    target = "[{}]:{}".format(host, port) if ":" in host else "{}:{}".format(host, port)
    connection = run_openssl(["s_client", "-connect", target, "-servername", name,
                              "-showcerts", "-no_ign_eof"], "", timeout)
    match = re.search(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", connection.stdout, re.DOTALL)
    if not match:
        raise CollectionError("A conexão TLS não retornou um certificado; OpenSSL exit={}.".format(connection.returncode))
    decoded = run_openssl(["x509", "-noout", "-startdate", "-enddate", "-subject", "-issuer",
                          "-serial", "-fingerprint", "-sha256", "-nameopt", "RFC2253"], match.group() + "\n", timeout)
    if decoded.returncode:
        raise CollectionError("OpenSSL x509 não conseguiu interpretar o certificado.")
    fields = dict(line.split("=", 1) for line in decoded.stdout.splitlines() if "=" in line)
    if "notAfter" not in fields or "notBefore" not in fields:
        raise CollectionError("OpenSSL não retornou as datas de validade do certificado.")
    valid_from, valid_to = openssl_timestamp(fields["notBefore"]), openssl_timestamp(fields["notAfter"])
    verification = re.findall(r"Verify return code:\s*(\d+)", connection.stdout)
    return {"scope": "management_https", "method": "openssl_s_client_x509", "host": host, "port": port,
            "server_name": name, "subject": fields.get("subject"), "issuer": fields.get("issuer"),
            "serial_number": fields.get("serial"), "sha256_fingerprint": fields.get("sha256 Fingerprint", fields.get("SHA256 Fingerprint")),
            "valid_from": iso(valid_from), "valid_to": iso(valid_to),
            "days_to_expire": math.floor((valid_to - now).total_seconds() / 86400),
            "openssl_verify_return_code": int(verification[-1]) if verification else None,
            "hostname_verification_performed": False}


class CollectionContext:
    """Estado de uma unidade durante uma coleta; nunca compartilhado entre arrays.

    resource() consulta cada coleção uma vez, incluindo falhas: None significa
    indisponível; [] significa consulta concluída sem itens. event() cria o
    contrato de entrada. metrics() compartilha catálogo e amostras de desempenho.
    results contém apenas registros já retornados pelos handlers executados.
    """

    def __init__(self, device, api, system, config, signals, started, fixed_now, sleep):
        """Recebe identidade validada, sessão existente e dependências do ciclo."""
        self.device = device
        self.api = api
        self.system = system
        self.config = config
        self.signals = signals
        self.started = started
        self.fixed_now = fixed_now
        self.sleep = sleep
        self.results = OrderedDict()
        self._resources = {"system": [system]}
        self.resource_errors = {}
        self.resource_details = {}
        self.handler_resources = set()
        self._metrics = None
        self.common = build_common_fields(self)

    def resource(self, resource):
        """Consulta REST opcional com cache; registra o local de falhas no log.

        Campos e recursos ficam em RESOURCES. Um nome não registrado é erro de
        programação e cancela o ciclo. Falha da consulta de um recurso conhecido
        fica em resource_errors e retorna None, sem repetir a requisição.
        """
        self.handler_resources.add(resource)
        if resource not in self._resources:
            fields = RESOURCES[resource]
            expression = "state eq 0 or state eq 1" if resource == "alert" else None
            try:
                items, diagnostics = read_resource(self.api, resource, fields, expression)
                self._resources[resource] = items
                self.resource_details[resource] = diagnostics
            except Exception as error:
                self._resources[resource] = None
                self.resource_errors[resource] = error_text(error)
                LOG.warning("etapa=recurso equipamento=%s handler=%r recurso=%s erro=%s local=%s",
                            self.device["name"], self.api.handler, resource,
                            error_text(error), error_location(error))
        else:
            LOG.debug("etapa=cache equipamento=%s handler=%r recurso=%s",
                      self.device["name"], self.api.handler, resource)
        return self._resources[resource]

    def event(self, event, status="collected", reason="Consulta REST concluída.", details=None, **values):
        """Cria um registro com 44 campos, qualidade e origem, sem valores fictícios.

        O handler retorna este registro; execute_handlers verifica o event_name.
        Valores não medidos permanecem None. Somente collected começa com
        health_status OK; values pode indicar uma falha realmente confirmada.
        """
        row = dict(self.common)
        row.update(event_name=event, health_status="OK" if status == "collected" else "UNKNOWN",
                   manufacturer_category="Monitoring", collection_status=status,
                   collection_reason=reason, custom_description=reason,
                   source_details={"system_id": self.system["id"], "system_name": self.system.get("name"),
                                   "model": str(self.system["model"]), "observations": details or {}})
        row.update(values)
        query_issues = {}
        for resource in sorted(self.handler_resources):
            info = self.resource_details.get(resource, {})
            errors = {key: info[key] for key in ("fields_error", "enrichment_error") if info.get(key)}
            if errors:
                query_issues[resource] = errors
        if query_issues:
            row["source_details"]["query_issues"] = query_issues
        return row

    def unavailable(self, event, resources):
        """Retorna um registro unavailable se alguma consulta falhou; senão None."""
        absent = [resource for resource in resources if self.resource(resource) is None]
        if absent:
            reason = "; ".join(resource + ": " + self.resource_errors[resource] for resource in absent)
            return self.event(event, "unavailable", reason, {"resources": resources})
        return None

    def enclosures(self):
        """Resolve IDs DPE/DAE para nomes; IDs continuam úteis se a consulta falhar."""
        return {item["id"]: item.get("name", item["id"]) for resource in ("dpe", "dae")
                for item in (self.resource(resource) or []) if item.get("id")}

    def metrics(self):
        """Carrega catálogo/amostras uma vez e calcula CPU usando o mesmo intervalo."""
        # Dependências continuam relevantes quando as amostras vêm do cache.
        self.handler_resources.update(("metric", "metricService"))
        if self._metrics is None:
            catalog, entries, bindings, reason = [], [], {}, ""
            LOG.info("etapa=metricas equipamento=%s status=iniciado", self.device["name"])
            try:
                catalog = self.resource("metric")
                if catalog is None:
                    catalog = []
                    raise CollectionError(self.resource_errors["metric"])
                bindings = choose_bindings(catalog, self.config)
                entries, reason = read_metrics(
                    self.api, catalog, bindings, self.started,
                    self.config.get("metrics_mode", "auto"),
                    self.config.get("sample_interval_seconds", 5),
                    self.config.get("metrics_max_age_seconds", 300), self.sleep)
            except Exception as error:
                reason = error_text(error)
                LOG.warning("etapa=metricas equipamento=%s erro=%s local=%s",
                            self.device["name"], reason, error_location(error))
            finished = self.started if self.fixed_now else utc_now()
            max_age = self.config.get("metrics_max_age_seconds", 300)
            cpu, cpu_reason = counter_ratio(entries, CPU_BUSY, CPU_IDLE, finished, max_age, cpu=True)
            self._metrics = {"catalog": catalog, "entries": entries, "bindings": bindings,
                             "reason": reason, "finished": finished, "max_age": max_age,
                             "cpu": cpu, "cpu_reason": cpu_reason}
            service = self.resource("metricService")
            self._metrics["service"] = service
            self._metrics["catalog_error"] = self.resource_errors.get("metric")
            if not entries and service and any(item.get("isHistoricalEnabled") is False for item in service):
                self._metrics["reason"] = (reason + " Histórico de métricas desabilitado; "
                                           "tempo real requer suporte a json= no make_request.").strip()
        return self._metrics


def build_common_fields(context):
    """Monta identidade e horário comuns; firmware ausente permanece None."""
    versions = context.resource("installedSoftwareVersion") or []
    version = next((item.get("fullVersion") or item.get("version") for item in versions
                    if item.get("fullVersion") or item.get("version")), None)
    row = dict.fromkeys(INPUT_FIELDS)
    row.update(family="unity", type=str(context.system["model"]), name=context.device["name"],
               serial_number=str(context.system["serialNumber"]), service_tag=context.device.get("service_tag"),
               software_version=version, datetime=iso(context.started),
               manufacturer_division="Dell Unity", manufacturer_severity="Info", priority="P4")
    return row


def collect_hardware(context, event, resource, kind):
    """Compartilha contagem/identificação de hardware sem confundir falha e dúvida.

    Controllers: modo de serviço ou saúde 30 confirma falha. Outros componentes:
    needsReplacement ou saúde 20/25/30 confirma falha. Estados restantes não OK
    geram partial. Inventário vazio/incompleto gera unavailable, nunca zero.
    """
    unavailable = context.unavailable(event, [resource])
    if unavailable is not None:
        return unavailable
    items = context.resource(resource)
    if not items or any(not item.get("id") for item in items):
        return context.event(event, "unavailable", "Inventário de {} vazio ou incompleto.".format(resource))
    if kind == "controllers":
        failed = [item for item in items if item.get("isRescueMode") is True or health_value(item) == 30]
    else:
        failed = [item for item in items if item.get("needsReplacement") is True or health_value(item) in (20, 25, 30)]
    unknown = [item for item in items if item not in failed and health_value(item) != 5]
    enclosures = context.enclosures()
    identified = [component_details(item, enclosures) for item in failed]
    values = {"total_" + kind: len(items), "failed_" + kind: len(failed)}
    if kind in ("disks", "fans"):
        values["failed_" + kind + "_details"] = identified
    return context.event(
        event, "partial" if unknown else "collected",
        "{} componente(s) com falha confirmada; {} com estado inconclusivo.".format(len(failed), len(unknown)),
        {"resource": resource, "affected_components": identified,
         "unknown_component_ids": [item["id"] for item in unknown],
         "inconclusive_components": [component_details(item, enclosures) for item in unknown]}, **values)


def collect_capacity(context, event, resource, pool=False):
    """Mede a maior ocupação; LUN alocada não representa uso dos arquivos do host.

    pool=True usa (sizeTotal-sizeFree)/sizeTotal; sem sizeFree usa sizeUsed
    com qualidade partial, pois a cobertura de pré-alocação é desconhecida.
    filesystem usa sizeUsed.
    Itens com números incoerentes não entram no cálculo e tornam a coleta partial.
    """
    unavailable = context.unavailable(event, [resource])
    if unavailable is not None:
        return unavailable
    entries = context.resource(resource)
    if not entries:
        status, reason, details = "not_applicable", "Nenhum {} configurado.".format(resource), {}
        if resource == "filesystem":
            luns = context.resource("lun")
            details = {"luns": luns}
            if luns is None or luns:
                status = "unavailable"
                reason = "A Unity não expõe uso do filesystem do host em LUNs; alocação não é uso real."
        return context.event(event, status, reason, details)
    measurements = []
    used_fallback = False
    for item in entries:
        total = number(item.get("sizeTotal"))
        free_or_used = number(item.get("sizeFree" if pool else "sizeUsed"))
        method = "total_minus_free" if pool else "filesystem_used"
        if pool and free_or_used is None:
            # Os comandos do ambiente retornam sizeUsed/sizeTotal. Não inventa
            # sizeFree; registra que esse valor não inclui pré-alocação conhecida.
            free_or_used = number(item.get("sizeUsed"))
            method = "pool_used"
            used_fallback = True
        if total is None or total <= 0 or free_or_used is None or not 0 <= free_or_used <= total:
            continue
        occupied = total - free_or_used if pool and method == "total_minus_free" else free_or_used
        measurements.append({"id": item.get("id"), "name": item.get("name"),
                             "size_total_bytes": total, "size_occupied_bytes": occupied,
                             "usage_percentage": round(100 * occupied / total, 4), "measurement": method})
    if not measurements:
        return context.event(event, "unavailable", "Coleção sem capacidade utilizável.")
    worst = max(measurements, key=lambda item: item["usage_percentage"])
    return context.event(event, "partial" if used_fallback or len(measurements) != len(entries) else "collected",
                         "Maior ocupação entre os {}s consultados.".format(resource),
                         {"resource": resource, "measurement": worst["measurement"],
                          "preallocation_coverage": "unknown" if used_fallback else "included" if pool else "not_applicable",
                          "worst_resource_id": worst["id"], "resources": measurements},
                         usage_percentage=worst["usage_percentage"])


def collect_service(context, event, resource, field):
    """Confirma configuração e saúde de gestão; não simula um teste de cliente."""
    nas_servers = context.resource("nasServer")
    relation = "nfsServer" if resource == "nfsServer" else "cifsServer"
    if nas_servers is not None and all(relation in item for item in nas_servers):
        configured = [item for item in nas_servers if reference(item.get(relation)) is not None]
        if not configured:
            return context.event(event, "not_applicable", "Serviço não configurado nos NAS servers consultados.", **{field: False})
        healths = [health_value(item) for item in configured]
        status = "collected" if all(value == 5 for value in healths) else "unavailable"
        reason = ("Saúde de gestão do NAS server OK; não é teste de acesso de clientes." if status == "collected"
                  else "Saúde do NAS server degradada ou desconhecida; não prova indisponibilidade de protocolo.")
        return context.event(event, status, reason,
                             {"resource": "nasServer", "relation": relation, "servers": configured,
                              "health_values": healths, "probe": "management_health"}, **{field: True})
    unavailable = context.unavailable(event, [resource])
    if unavailable is not None:
        return unavailable
    services = context.resource(resource)
    if not services:
        return context.event(event, "not_applicable", "Serviço não configurado (coleção REST vazia).", **{field: False})
    if resource == "nfsServer":
        nas = {item.get("id"): item for item in (context.resource("nasServer") or [])}
        healths = [health_value(nas.get(reference(item.get("nasServer")), {})) for item in services]
    else:
        healths = [health_value(item) for item in services]
    if all(value == 5 for value in healths):
        return context.event(event, reason="Saúde de gestão do serviço/NAS server OK; não é teste de acesso de clientes.",
                             details={"servers": services, "health_values": healths, "probe": "management_health"},
                             **{field: True})
    return context.event(event, "unavailable",
                         "Saúde do serviço/NAS server degradada ou desconhecida; não prova indisponibilidade de protocolo.",
                         {"servers": services, "health_values": healths}, **{field: True})


def collect_security(context, event, field):
    """Aceita booleano externo recente ou alerta ativo com messageId validado.

    Ausência de alerta não estabelece False. Falta de evidência retorna
    unsupported. O sinal pertence ao nome lógico do equipamento atual.
    """
    alerts = [item for item in (context.resource("alert") or []) if item.get("state") in (0, 1)]
    signal = context.signals.get(context.device["name"], {})
    fresh = False
    if signal:
        try:
            age = (context.started - timestamp(signal.get("datetime"))).total_seconds()
            fresh = 0 <= age <= context.config.get("signal_max_age_seconds", 300)
        except ValueError:
            pass
    rules = context.config.get("alert_rules", {}).get(event, [])
    matches = [alert for alert in alerts if alert.get("messageId") in rules]
    if fresh and isinstance(signal.get(field), bool):
        return context.event(event, reason="Sinal externo recente fornecido pelo operador.",
                             details={"source": signal.get("source", "external_signal"), "datetime": signal["datetime"]},
                             **{field: signal[field]})
    if matches:
        return context.event(event, reason="Alerta ativo corresponde a messageId explicitamente configurado.",
                             details={"alerts": matches}, **{field: True})
    return context.event(event, "unsupported",
                         "Sem sinal de segurança verificável; ausência de alerta não comprova estado saudável.",
                         {"configured_message_ids": rules, "active_alerts_query_error": context.resource_errors.get("alert"),
                          "external_signal_present": bool(signal), "external_signal_fresh": fresh})


def collect_performance(context, event, field):
    """Lê gauge ou fórmula validada e retorna o maior valor por instância.

    Sem binding inequívoco retorna unsupported. Binding incompatível ou amostra
    ausente retorna unavailable. Contadores brutos nunca viram percentuais.
    """
    metrics = context.metrics()
    binding = metrics["bindings"].get(field)
    if not binding:
        candidates = metric_candidates(metrics["catalog"], field)
        unavailable = bool(metrics["catalog_error"])
        reason = (metrics["catalog_error"] if unavailable else
                  "Catálogo sem uma métrica inequívoca; configure bindings com caminho e unidade validados.")
        details = {"field": field, "candidate_metric_count": len(candidates)}
        if unavailable:
            details["catalog_query_error"] = metrics["catalog_error"]
        return context.event(event, "unavailable" if unavailable else "unsupported", reason, details)
    known = {item.get("path"): item for item in metrics["catalog"]}
    entries, finished, max_age = metrics["entries"], metrics["finished"], metrics["max_age"]
    values, sample_time = {}, None
    if binding.get("mode") == "counter_ratio":
        paths = (binding.get("numerator_path"), binding.get("denominator_path"))
        if all(known.get(path, {}).get("type") in (2, 3, 7, 8) for path in paths):
            values, reason = counter_ratio(entries, paths[0], paths[1], finished, max_age)
        else:
            reason = "A fórmula counter_ratio requer dois caminhos classificados como contadores."
    else:
        path = binding.get("path")
        metric = known.get(path, {})
        factor = unit_factor(binding.get("unit", metric.get("unitDisplayString", "")), field)
        samples = metric_samples(entries, path, finished, max_age)
        reason = "Caminho/unidade incompatível, contador sem fórmula, ou amostra ausente/antiga."
        if metric.get("type") in (4, 5) and factor is not None and samples:
            sample_time = max(samples)
            values = {key: round(value * factor, 4) for key, value in samples[sample_time].items()
                      if value >= 0 and (field.endswith("_ms") or value * factor <= 100)}
    if values:
        return context.event(event, reason="Maior valor medido entre as instâncias da métrica.",
                             details={"binding": binding, "per_instance": values,
                                      "sample_time": iso(sample_time) if sample_time else None},
                             **{field: max(values.values())})
    return context.event(event, "unavailable", metrics["reason"] or reason, {"binding": binding})


def collect_cpu(context, event, field, average=False):
    """Compartilha CPU por SP; distingue média do array e maior controladora."""
    metrics = context.metrics()
    cpu = metrics["cpu"]
    if not cpu:
        return context.event(event, "unavailable", metrics["reason"] or metrics["cpu_reason"],
                             {"required_paths": [CPU_BUSY, CPU_IDLE], "metrics_service": metrics["service"],
                              "available_cpu_metrics": [item.get("path") for item in metrics["catalog"]
                                                        if item.get("path") in (CPU_BUSY, CPU_IDLE)]})
    expected = len(context.resource("storageProcessor") or [])
    status = "partial" if not expected or len(cpu) < expected else "collected"
    value = round(sum(cpu.values()) / len(cpu), 4) if average else max(cpu.values())
    reason = ("Média das CPUs por delta de busyTicks e idleTicks." if average else
              "Maior CPU entre as controladoras por delta de contadores.")
    return context.event(event, status, reason,
                         {"paths": [CPU_BUSY, CPU_IDLE], "per_controller_percent": cpu}, **{field: value})


def collect_cluster_down(context):
    """Cluster Down: consulta storageProcessor e usa a identidade/saúde de system.

    Degradação global não comprova array DOWN; a sondagem é a API de gestão.
    """
    processors = context.resource("storageProcessor")
    system = context.system
    if health_value(system) == 5 or any(health_value(sp) == 5 for sp in (processors or [])):
        return context.event("Cluster Down", reason="API de gestão respondeu e há evidência de operação do array.",
                             details={"system_health": system.get("health"), "probe": "management_api"})
    if processors and all(sp.get("isRescueMode") is True for sp in processors):
        return context.event("Cluster Down", reason="Todas as controladoras consultadas estão em modo de serviço.",
                             details={"processors": processors}, health_status="CRITICAL")
    return context.event("Cluster Down", "unavailable", "Saúde global degradada/indefinida; não confirma Cluster DOWN.",
                         {"system_health": system.get("health"), "probe": "management_api"})


def collect_controller_down(context):
    """Controller Down: storageProcessor -> total_controllers/failed_controllers."""
    return collect_hardware(context, "Controller Down", "storageProcessor", "controllers")


def collect_multiple_disk_failure(context):
    """Multiple Disk Failure: disk -> contagens e failed_disks_details com localização."""
    return collect_hardware(context, "Multiple Disk Failure", "disk", "disks")


def collect_power_supply_failure(context):
    """Power Supply Failure: powerSupply -> contagens e componentes nas observações."""
    return collect_hardware(context, "Power Supply Failure", "powerSupply", "psus")


def collect_fan_failure(context):
    """Fan Failure: fan -> contagens e failed_fans_details com localização física."""
    return collect_hardware(context, "Fan Failure", "fan", "fans")


def collect_high_temp(context):
    """High Temp: dpe/dae -> maior current_temperature em Celsius.

    Reutiliza failed_fans do registro Fan Failure, executado antes no registro
    COLLECTION_HANDLERS. Enclosures sem temperatura tornam a medição partial.
    """
    temperatures = []
    incomplete = False
    for resource in ("dpe", "dae"):
        items = context.resource(resource)
        if items is None:
            incomplete = True
        for item in items or []:
            value = number(item.get("currentTemperature"))
            if value is None:
                incomplete = True
            else:
                temperatures.append({"id": item.get("id"), "name": item.get("name"), "celsius": value})
    if not temperatures:
        return context.event("High Temp", "unavailable", "Nenhum enclosure retornou temperatura válida.")
    return context.event("High Temp", "partial" if incomplete else "collected",
                         "Maior temperatura medida nos enclosures; unidade Celsius.", {"enclosures": temperatures},
                         current_temperature=max(item["celsius"] for item in temperatures),
                         failed_fans=context.results["Fan Failure"].get("failed_fans"))


def collect_smb_latency(context):
    """SMB latency: catálogo/amostras metric -> smb_latency_ms, com unidade validada."""
    return collect_performance(context, "SMB latency", "smb_latency_ms")


def collect_nfs_latency(context):
    """NFS latency: catálogo/amostras metric -> nfs_latency_ms, com unidade validada."""
    return collect_performance(context, "NFS latency", "nfs_latency_ms")


def collect_nfs_retransmissions(context):
    """NFS retransmissions: métrica percentual/fórmula -> nfs_retransmissions_pct."""
    return collect_performance(context, "NFS retransmissions", "nfs_retransmissions_pct")


def collect_cpu_utilization(context):
    """CPU utilization: busyTicks/idleTicks -> média cpu_utilization_pct dos SPs."""
    return collect_cpu(context, "CPU utilization", "cpu_utilization_pct", average=True)


def collect_storage_utilization(context):
    """Storage utilization: pool -> storage_utilization_pct; mede ocupação de espaço."""
    pool = collect_capacity(context, "Pool Usage", "pool", pool=True)
    if pool["usage_percentage"] is None:
        return context.event("Storage utilization", pool["collection_status"], pool["collection_reason"])
    included = pool["source_details"]["observations"].get("preallocation_coverage") == "included"
    reason = ("Ocupação do pool mais utilizado; inclui pré-alocação." if included else
              "Uso medido por sizeUsed/sizeTotal; cobertura de pré-alocação desconhecida.")
    return context.event("Storage utilization", pool["collection_status"], reason,
                         pool["source_details"]["observations"], storage_utilization_pct=pool["usage_percentage"])


def collect_network_utilization(context):
    """Network utilization: catálogo/amostras metric -> network_utilization_pct."""
    return collect_performance(context, "Network utilization", "network_utilization_pct")


def collect_packet_loss(context):
    """Packet loss: métrica de perda explicitamente validada -> packet_loss_pct."""
    return collect_performance(context, "Packet loss", "packet_loss_pct")


def collect_controller_cpu(context):
    """Controller CPU: busyTicks/idleTicks -> maior controller_cpu_percentage dos SPs."""
    return collect_cpu(context, "Controller CPU", "controller_cpu_percentage")


def collect_volume_usage(context):
    """Volume Usage: filesystem.sizeUsed/sizeTotal -> usage_percentage; LUN é auxiliar."""
    return collect_capacity(context, "Volume Usage", "filesystem")


def collect_pool_usage(context):
    """Pool Usage: ocupação do pool; fallback sizeUsed/sizeTotal tem qualidade partial."""
    return collect_capacity(context, "Pool Usage", "pool", pool=True)


def collect_pool_full(context):
    """Pool Full: mesma medição de pool; o construtor aplica seu limite específico."""
    return collect_capacity(context, "Pool Full", "pool", pool=True)


def collect_replication_failed(context):
    """Replication Failed: replicationSession -> estados explícitos de erro da sessão."""
    event = "Replication Failed"
    unavailable = context.unavailable(event, ["replicationSession"])
    if unavailable is not None:
        return unavailable
    sessions = context.resource("replicationSession")
    if not sessions:
        return context.event(event, "not_applicable", "Nenhuma sessão de replicação configurada.",
                             is_replication_configured=False)
    bad = [session for session in sessions if session.get("status") in (7, 13, 33803, 33806, 33807)
           or session.get("networkStatus") in (5, 10, 18)
           or session.get("srcStatus") in (4, 5, 8, 10, 11) or session.get("dstStatus") in (4, 5, 8, 10, 11)]
    good = all(session.get("status") in (2, 33794, 33796, 33797, 33805, 33809)
               and health_value(session) == 5 for session in sessions)
    return context.event(event, "collected" if bad or good else "unavailable",
                         "Falha confirmada por estado da sessão." if bad else "Estado das sessões de replicação consultado.",
                         {"sessions": sessions, "failed_session_ids": [session.get("id") for session in bad]},
                         is_replication_configured=True, health_status="CRITICAL" if bad else "OK" if good else "UNKNOWN")


def collect_replication_lag(context):
    """Replication Lag: expõe RPO/lastSyncTime de replicationSession para diagnóstico.

    Idade da última sincronização concluída não mede lag real. Sem fonte validada,
    retorna unsupported e mantém lag_minutes/rpo_minutes ausentes nas medições.
    """
    event = "Replication Lag"
    unavailable = context.unavailable(event, ["replicationSession"])
    if unavailable is not None:
        return unavailable
    sessions = context.resource("replicationSession")
    if not sessions:
        return context.event(event, "not_applicable", "Nenhuma sessão de replicação configurada.",
                             is_replication_configured=False)
    observations = []
    for session in sessions:
        record = {"id": session.get("id"), "rpo_minutes": session.get("maxTimeOutOfSync"),
                  "last_sync_time": session.get("lastSyncTime")}
        try:
            age = (context.started - timestamp(session.get("lastSyncTime"))).total_seconds() / 60
            record["last_completed_sync_age_minutes"] = max(0, age)
        except ValueError:
            pass
        observations.append(record)
    return context.event(event, "unsupported",
                         "lastSyncTime não mede atraso real/RPO atual; requer uma métrica de lag validada.",
                         {"sessions": observations}, is_replication_configured=True)


def collect_nfs_service(context):
    """NFS Service: nfsServer + saúde de nasServer -> is_nfs_configured."""
    return collect_service(context, "NFS Service", "nfsServer", "is_nfs_configured")


def collect_smb_service(context):
    """SMB Service: cifsServer + sua saúde de gestão -> is_smb_configured."""
    return collect_service(context, "SMB Service", "cifsServer", "is_smb_configured")


def collect_audit_disabled(context):
    """Audit Disabled: alerta ativo/sinal externo recente -> is_audit_disabled."""
    return collect_security(context, "Audit Disabled", "is_audit_disabled")


def collect_unauthorized_admin(context):
    """Unauthorized Admin: alerta/sinal externo validado -> has_unauthorized_admin."""
    return collect_security(context, "Unauthorized Admin", "has_unauthorized_admin")


def collect_certificate_expiring(context):
    """Certificate Expiring: OpenSSL no HTTPS da gestão -> validade e days_to_expire.

    Expõe subject, issuer, serial, fingerprint e datas UTC do certificado folha.
    Falha/timeout do OpenSSL gera unavailable; não usa outro certificado da API
    como substituto silencioso do certificado HTTPS solicitado.
    """
    try:
        details = probe_https_certificate(
            context.device["ip"], context.started,
            context.config.get("certificate_timeout_seconds", 15), context.device.get("tls_server_name"))
    except Exception as error:
        LOG.warning("etapa=certificado equipamento=%s erro=%s local=%s",
                    context.device["name"], error_text(error), error_location(error))
        return context.event("Certificate Expiring", "unavailable", error_text(error),
                             {"scope": "management_https", "method": "openssl_s_client_x509"})
    return context.event("Certificate Expiring", reason="Validade do certificado HTTPS apresentado pela gestão, medida com OpenSSL.",
                         details=details, days_to_expire=details["days_to_expire"])


def antivirus_configuration(context):
    """Resume virusChecker como configuração CAVA, sem inferir infecção/ransomware.

    isEnabled indica habilitação por NAS server. O resumo evita copiar uma
    coleção inteira ao evento; o corpo completo está disponível em -vv.
    """
    checkers = context.resource("virusChecker")
    result = {"resource": "virusChecker", "scope": "nas_antivirus_configuration"}
    if checkers is None:
        result.update(collection_status="unavailable", query_error=context.resource_errors["virusChecker"])
        return result
    enabled = sum(item.get("isEnabled") is True for item in checkers)
    disabled = sum(item.get("isEnabled") is False for item in checkers)
    unknown = len(checkers) - enabled - disabled
    status = "not_applicable" if not checkers else "partial" if unknown else "collected"
    result.update(collection_status=status, checker_count=len(checkers), enabled_count=enabled,
                  disabled_count=disabled, unknown_count=unknown)
    return result


def collect_ransomware_pattern(context):
    """Ransomware Pattern: alerta/sinal validado; virusChecker fornece contexto CAVA."""
    antivirus = antivirus_configuration(context)
    row = collect_security(context, "Ransomware Pattern", "is_ransomware_suspected")
    row["source_details"]["observations"]["antivirus"] = antivirus
    if row["collection_status"] == "unsupported":
        reason = ("Sem evidência verificável de ransomware; virusChecker informa configuração "
                  "do antivírus CAVA, não suspeita de ransomware.")
        row.update(collection_reason=reason, custom_description=reason)
    return row


# Registro único: um nome de evento, uma função, uma chamada por equipamento.
# A ordem acompanha ACTIVE_HANDLERS do construtor. Fan Failure precede High Temp.
COLLECTION_HANDLERS = OrderedDict([
    ("Cluster Down", collect_cluster_down),
    ("Controller Down", collect_controller_down),
    ("Multiple Disk Failure", collect_multiple_disk_failure),
    ("Power Supply Failure", collect_power_supply_failure),
    ("Fan Failure", collect_fan_failure),
    ("High Temp", collect_high_temp),
    ("SMB latency", collect_smb_latency),
    ("NFS latency", collect_nfs_latency),
    ("NFS retransmissions", collect_nfs_retransmissions),
    ("CPU utilization", collect_cpu_utilization),
    ("Storage utilization", collect_storage_utilization),
    ("Network utilization", collect_network_utilization),
    ("Packet loss", collect_packet_loss),
    ("Controller CPU", collect_controller_cpu),
    ("Volume Usage", collect_volume_usage),
    ("Pool Usage", collect_pool_usage),
    ("Pool Full", collect_pool_full),
    ("Replication Failed", collect_replication_failed),
    ("Replication Lag", collect_replication_lag),
    ("NFS Service", collect_nfs_service),
    ("SMB Service", collect_smb_service),
    ("Audit Disabled", collect_audit_disabled),
    ("Unauthorized Admin", collect_unauthorized_admin),
    ("Certificate Expiring", collect_certificate_expiring),
    ("Ransomware Pattern", collect_ransomware_pattern),
])
HANDLERS = tuple(COLLECTION_HANDLERS)


def identify_system(api, device):
    """Consulta system e valida identidade obrigatória; None indica modelo fora do escopo."""
    systems = api.collection("system", "id,name,model,serialNumber,health")
    if len(systems) != 1 or not systems[0].get("model") or not systems[0].get("serialNumber"):
        raise CollectionError("Identidade do equipamento incompleta; publicação cancelada.")
    system = systems[0]
    if not re.search(r"(?<!\d)(380F|480F)(?!\w)", str(system["model"]), re.IGNORECASE):
        LOG.info("etapa=identidade equipamento=%s modelo=%s status=fora_do_escopo",
                 device["name"], system["model"])
        return None
    LOG.info("etapa=identidade equipamento=%s modelo=%s status=identificado", device["name"], system["model"])
    return system


def execute_handlers(context):
    """Executa o registro completo; erro de código cancela o ciclo com contexto.

    Qualidade unavailable/unsupported/partial é um resultado operacional válido,
    não uma exceção. Exceção inesperada informa equipamento, evento, função e
    localização e impede publicar um JSON com um handler faltando.
    """
    for event, handler in COLLECTION_HANDLERS.items():
        context.api.handler = event
        context.handler_resources.clear()
        started = time.monotonic()
        LOG.debug("etapa=handler equipamento=%s handler=%r funcao=%s status=iniciado",
                  context.device["name"], event, handler.__name__)
        try:
            row = handler(context)
            if not isinstance(row, dict) or row.get("event_name") != event:
                raise CollectionError("Handler não retornou o registro do evento esperado.")
        except Exception as error:
            raise CollectionError("etapa=handler equipamento={} handler={!r} funcao={} erro={} local={}".format(
                context.device["name"], event, handler.__name__, error_text(error), error_location(error))) from error
        context.results[event] = row
        LOG.info("etapa=handler equipamento=%s handler=%r funcao=%s qualidade=%s duracao_ms=%.1f",
                 context.device["name"], event, handler.__name__, row.get("collection_status"),
                 (time.monotonic() - started) * 1000)
        if row.get("collection_status") != "collected":
            LOG.info("etapa=qualidade equipamento=%s handler=%r motivo=%s",
                      context.device["name"], event, row.get("collection_reason"))
    return list(context.results.values())


def collect_device(device, storage, config=None, signals=None, now=None, sleep=time.sleep, verbosity=0):
    """Coleta uma Unity elegível usando uma única sessão e todos os handlers.

    Retorna um registro por COLLECTION_HANDLERS, na ordem do construtor; retorna
    [] para outro modelo Unity. Falha da identidade essencial levanta exceção.
    now/sleep permitem reproduzir o ciclo em testes sem conexões/esperas reais.
    verbosity=1 registra endpoints; 2 registra também corpos de respostas.
    """
    api = UnityAPI(storage, device["ip"], verbosity=verbosity)
    api.device_name = device["name"]
    started = now or utc_now()
    system = identify_system(api, device)
    if system is None:
        return []
    context = CollectionContext(device, api, system, config or {}, signals or {}, started, now is not None, sleep)
    return execute_handlers(context)


def load_object(path):
    """Lê objeto JSON UTF-8/BOM; arquivo omitido retorna {}; NaN/Infinity são rejeitados."""
    if not path:
        return {}
    def reject(value):
        """Recusa constantes não permitidas pelo padrão JSON."""
        raise ValueError("Constante JSON inválida: " + value)
    with open(path, "r", encoding="utf-8-sig") as source:
        payload = json.load(source, parse_constant=reject)
    if not isinstance(payload, dict):
        raise CollectionError("Arquivo de configuração/sinais precisa conter um objeto JSON.")
    return payload


def validate_config(config):
    """Valida modos, intervalos, caminhos e regras antes de autenticar/coletar."""
    if config.get("metrics_mode", "auto") not in ("auto", "historical", "realtime"):
        raise CollectionError("metrics_mode deve ser auto, historical ou realtime.")
    interval = config.get("sample_interval_seconds", 5)
    if not isinstance(interval, int) or isinstance(interval, bool) or not 5 <= interval <= 15:
        raise CollectionError("sample_interval_seconds deve estar entre 5 e 15.")
    certificate_timeout = config.get("certificate_timeout_seconds", 15)
    if (not isinstance(certificate_timeout, int) or isinstance(certificate_timeout, bool)
            or not 1 <= certificate_timeout <= 60):
        raise CollectionError("certificate_timeout_seconds deve estar entre 1 e 60.")
    for key in ("metrics_max_age_seconds", "signal_max_age_seconds"):
        value = config.get(key, 300)
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 3600:
            raise CollectionError(key + " deve estar entre 1 e 3600.")
    bindings = config.get("bindings", {})
    if not isinstance(bindings, dict) or any(field not in PERFORMANCE.values() for field in bindings):
        raise CollectionError("bindings contém campos de desempenho inválidos.")
    for field, binding in bindings.items():
        if not isinstance(binding, dict):
            raise CollectionError("Cada binding deve conter um objeto.")
        keys = ("numerator_path", "denominator_path") if binding.get("mode") == "counter_ratio" else ("path",)
        if binding.get("mode", "direct") not in ("direct", "counter_ratio"):
            raise CollectionError("mode do binding deve ser direct ou counter_ratio.")
        if binding.get("mode") == "counter_ratio" and field.endswith("_ms"):
            raise CollectionError("counter_ratio não calcula latência em ms.")
        if any(not isinstance(binding.get(key), str) or not re.fullmatch(r"[A-Za-z0-9_.*:/-]+", binding[key]) for key in keys):
            raise CollectionError("Binding contém caminho de métrica inválido.")
    rules = config.get("alert_rules", {})
    if not isinstance(rules, dict) or any(event not in SECURITY for event in rules):
        raise CollectionError("alert_rules contém evento inválido.")
    if any(not isinstance(ids, list) or any(not isinstance(value, str) or not value for value in ids) for ids in rules.values()):
        raise CollectionError("alert_rules deve conter listas de messageIds textuais.")


@contextmanager
def snapshot_lock(output):
    """Lock oculto persistente; impede duas execuções publicando fora de ordem."""
    lock_path = output.parent / ("." + output.name + ".lock")
    try:
        handle = open(lock_path, "a+b")
    except OSError as error:
        LOG.error("etapa=bloqueio status=falha erro=%s local=%s", error_text(error), error_location(error))
        raise
    locked = False
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            LOG.error("etapa=bloqueio status=ocupado erro=%s local=%s", error_text(error), error_location(error))
            raise CollectionError("Já existe outra coleta em execução para este arquivo.") from error
        except OSError as error:
            LOG.error("etapa=bloqueio status=falha erro=%s local=%s", error_text(error), error_location(error))
            raise
        locked = True
        LOG.debug("etapa=bloqueio arquivo=%s status=adquirido", output)
        yield
    finally:
        if locked:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def validate_event_rows(rows):
    """Exige identidade consistente, campos finitos e um registro por handler/unidade."""
    if not rows:
        raise CollectionError("Nenhum Unity XT 380F/480F foi coletado; arquivo anterior preservado.")
    groups = {}
    serials = {}
    identities = {}
    for row in rows:
        if set(INPUT_FIELDS) - set(row) or row.get("event_name") not in HANDLERS:
            raise CollectionError("Registro não atende ao contrato dos handlers.")
        if (not isinstance(row.get("collection_status"), str)
                or row["collection_status"] not in COLLECTION_STATUSES
                or not isinstance(row.get("collection_reason"), str)
                or not isinstance(row.get("source_details"), dict)):
            raise CollectionError("Registro sem qualidade/origem de coleta válida.")
        name = row["name"]
        if not isinstance(name, str) or not name.strip() or name.strip() in (".", "..") or any(c in name for c in "/\\\0\n\r"):
            raise CollectionError("Nome lógico inválido para o construtor.")
        serial = row["serial_number"]
        key = name.strip().casefold()
        identity = (row["family"], row["type"], serial)
        if key in identities and identities[key] != identity:
            raise CollectionError("Um equipamento tem identidade divergente entre handlers.")
        identities[key] = identity
        if serial in serials and serials[serial] != key:
            raise CollectionError("Um mesmo serial foi associado a nomes lógicos diferentes.")
        serials[serial] = key
        groups.setdefault(key, []).append(row["event_name"])
        for kind in ("disks", "fans", "psus", "controllers"):
            total, failed = row.get("total_" + kind), row.get("failed_" + kind)
            if total is not None and failed is not None and not 0 <= failed <= total:
                raise CollectionError("Contagem de componentes inconsistente.")
            details = row.get("failed_" + kind + "_details", [])
            identifiers = [component.get("id") for component in details]
            if (any(not isinstance(value, str) or not value.strip() for value in identifiers)
                    or len(set(value.casefold() for value in identifiers)) != len(identifiers)
                    or (failed is not None and len(identifiers) > failed)):
                raise CollectionError("Identificação de componentes inconsistente.")
    if any(len(events) != len(HANDLERS) or set(events) != set(HANDLERS) for events in groups.values()):
        raise CollectionError("Cada equipamento deve ter exatamente um registro por handler.")
    json.dumps(rows, ensure_ascii=False, allow_nan=False)


def group_snapshot(rows):
    """Agrupa registros internos: um objeto por unidade, com todos os eventos dentro.

    O formato externo v2 não repete 25 equipamentos. Identidade fica em
    device_info; events é um mapa do nome de handler para seu registro de entrada.
    Campos sem medição são omitidos nos eventos e voltam a None na validação.
    """
    validate_event_rows(rows)
    devices = OrderedDict()
    for row in rows:
        key = (row["family"].casefold(), row["name"].strip().casefold())
        if key not in devices:
            devices[key] = {"schema_version": 2,
                            "device_info": {field: row.get(field) for field in DEVICE_FIELDS},
                            "events": OrderedDict()}
        values = {field: value for field, value in row.items()
                  if field not in DEVICE_FIELDS and field != "event_name" and value is not None}
        devices[key]["events"][row["event_name"]] = values
    return list(devices.values())


def flatten_snapshot(snapshot):
    """Expande o v2 só em memória para conferir contrato; não publica linhas repetidas."""
    if not isinstance(snapshot, list) or not snapshot:
        raise CollectionError("Snapshot deve conter uma lista não vazia de equipamentos.")
    rows = []
    for device in snapshot:
        if (not isinstance(device, dict) or device.get("schema_version") != 2
                or not isinstance(device.get("device_info"), dict) or not isinstance(device.get("events"), dict)):
            raise CollectionError("Equipamento não atende ao formato device_info/events v2.")
        info, events = device["device_info"], device["events"]
        if set(info) - set(DEVICE_FIELDS) or set(events) != set(HANDLERS):
            raise CollectionError("Snapshot tem identidade inválida ou handlers ausentes/desconhecidos.")
        for event in HANDLERS:
            values = events[event]
            if not isinstance(values, dict) or set(values) & (set(DEVICE_FIELDS) | {"event_name"}):
                raise CollectionError("Evento não pode substituir a identidade ou seu nome de handler.")
            row = dict.fromkeys(INPUT_FIELDS)
            row.update(info)
            row.update(values)
            row["event_name"] = event
            rows.append(row)
    return rows


def validate_snapshot(snapshot):
    """Valida v2 por equipamento; aceita registros planos apenas para compatibilidade interna."""
    if snapshot and isinstance(snapshot[0], dict) and "device_info" in snapshot[0]:
        validate_event_rows(flatten_snapshot(snapshot))
    else:
        validate_event_rows(snapshot)


@contextmanager
def collection_stage(stage, published=False):
    """Identifica falhas do ciclo sem alterar o tipo de exceção nem expor segredos.

    published=True indica que os.replace já ocorreu: um erro de fsync posterior
    não significa que o arquivo anterior foi preservado.
    """
    LOG.debug("etapa=%s status=iniciado", stage)
    try:
        yield
    except Exception as error:
        LOG.error("etapa=%s status=falha publicado=%s erro=%s local=%s", stage,
                  str(published).lower(), error_text(error), error_location(error))
        raise
    LOG.debug("etapa=%s status=concluido", stage)


def prepare_output(output, config):
    """Valida configuração e prepara o diretório, sem alterar o arquivo final."""
    with collection_stage("preparacao"):
        validate_config(config)
        output = Path(output).absolute()
        output.parent.mkdir(parents=True, exist_ok=True)
        return output


@contextmanager
def temporary_snapshot(output):
    """Mantém um único temporário oculto 0600 no filesystem do arquivo final.

    Existe desde antes da consulta ao inventário. Remove o temporário ao sair,
    inclusive em falha. Após os.replace, o nome temporário já não existe.
    """
    with collection_stage("criacao_temporario"):
        descriptor, temporary = tempfile.mkstemp(
            prefix="." + output.name + ".", suffix=".tmp", dir=str(output.parent))
        os.close(descriptor)
    try:
        yield Path(temporary)
    finally:
        if os.path.exists(temporary):
            with collection_stage("limpeza_temporario"):
                os.unlink(temporary)


def select_unity_devices(devices):
    """Seleciona type=unity e valida nomes/IPs e duplicidade antes das consultas."""
    if not isinstance(devices, list) or any(not isinstance(device, dict) for device in devices):
        raise CollectionError("Inventário ativo precisa retornar uma lista de objetos.")
    selected = [device for device in devices if str(device.get("type", "")).lower() == "unity"]
    names = set()
    for device in selected:
        if not all(isinstance(device.get(key), str) and device[key].strip() for key in ("name", "ip")):
            raise CollectionError("Unity ativo sem nome ou IP válido.")
        name = device["name"].strip().casefold()
        if name in names:
            raise CollectionError("Inventário contém nomes lógicos Unity duplicados.")
        names.add(name)
    return selected


def resolve_single_host(devices, host):
    """Seleciona exatamente uma unidade pelo nome lógico, endereço ou hostname.

    Não resolve DNS nem aceita correspondência parcial. Zero/múltiplas unidades
    são erro, antes de abrir uma sessão. O inventário continua pertencendo ao motor.
    """
    if not isinstance(host, str) or not host.strip():
        raise CollectionError("Diagnóstico exige nome lógico, IP ou FQDN de um host.")
    target = host.strip().casefold()
    matched = []
    for device in devices:
        address = device["ip"].strip()
        parsed = urlsplit(address if "://" in address else "https://" + address)
        identifiers = (device["name"].strip().casefold(), address.casefold(),
                       (parsed.hostname or "").casefold())
        if target in identifiers:
            matched.append(device)
    if len(matched) != 1:
        raise CollectionError("--host precisa identificar exatamente um Unity ativo no inventário.")
    return matched


def load_inventory(manager=None, host=None):
    """Carrega o motor e chama get_credentials/get_active_devices uma vez.

    O import de storage_api_manager fica nesta fronteira operacional: importar
    o coletor, exibir --help/--list-handlers e testar não exige o motor real.
    Retorna (manager, credenciais, dispositivos Unity). Não abre sessão extra.
    """
    with collection_stage("inventario"):
        if manager is None:
            import storage_api_manager as manager
        credentials = manager.get_credentials()
        devices = select_unity_devices(manager.get_active_devices())
        if host is not None:
            devices = resolve_single_host(devices, host)
        if not isinstance(credentials, dict) or "unity" not in credentials:
            raise CollectionError("O motor não forneceu a configuração de credenciais Unity.")
        LOG.info("etapa=inventario equipamentos_unity=%d status=concluido", len(devices))
        return manager, credentials, devices


def collect_inventory(manager, credentials, devices, config, signals, now, sleep, verbosity=0):
    """Cria UnityXT uma vez por equipamento; uma falha essencial cancela o ciclo."""
    if verbosity >= 2 and len(devices) != 1:
        raise CollectionError("Respostas completas exigem diagnóstico de um único host.")
    rows = []
    for device in devices:
        try:
            LOG.debug("etapa=sessao equipamento=%s status=iniciado", device["name"])
            storage = manager.UnityXT(device["ip"], credentials["unity"])
            rows.extend(collect_device(device, storage, config, signals, now, sleep, verbosity))
        except Exception as error:
            message = "etapa=coleta equipamento={} erro={} local={}; publicação cancelada.".format(
                device["name"], error_text(error), error_location(error))
            LOG.error("%s", message)
            raise CollectionError(message) from error
    return rows


def collect_metric_catalog(manager=None, host=None, verbosity=0):
    """Consulta o catálogo real sem publicar input_events.json ou criar query POST.

    Usa o inventário e a sessão do motor. Retorna tipo, unidade e disponibilidade
    dos caminhos, serviço de histórico e capacidade json= da interface pública.
    Permite resolver bindings no firmware real sem inventar nomes de métricas.
    """
    if verbosity >= 2 and host is None:
        raise CollectionError("Respostas completas exigem --host no diagnóstico de catálogo.")
    manager, credentials, devices = load_inventory(manager, host)
    result = []
    for device in devices:
        try:
            storage = manager.UnityXT(device["ip"], credentials["unity"])
            api = UnityAPI(storage, device["ip"], verbosity=verbosity)
            api.device_name = device["name"]
            system = identify_system(api, device)
            if system is None:
                continue
            metrics, diagnostics = read_resource(api, "metric", RESOURCES["metric"])
            try:
                service, _ = read_resource(api, "metricService", RESOURCES["metricService"])
                service_error = None
            except Exception as error:
                service, service_error = None, error_text(error)
            result.append({"device_info": {"name": device["name"], "type": system["model"],
                                           "serial_number": system["serialNumber"]},
                           "make_request_accepts_json": supports_json_body(storage), "metrics": metrics,
                           "metrics_service": service, "metrics_service_error": service_error,
                           "query_details": diagnostics})
        except Exception as error:
            raise CollectionError("Catálogo de {} falhou: {}.".format(device["name"], error_text(error))) from error
    if not result:
        raise CollectionError("Nenhum Unity XT 380F/480F elegível para consultar catálogo.")
    return result


def collect_diagnostic_host(host, manager=None, config=None, signals=None, verbosity=1,
                            now=None, sleep=time.sleep):
    """Executa os 25 handlers de uma unidade e retorna snapshot, sem publicar.

    Seleciona o host no inventário existente. Não cria lock/temporário nem
    substitui input_events.json. Corpos em nível 2 ficam somente nos logs; o
    snapshot retornado conserva o mesmo formato resumido do ciclo normal.
    """
    if not isinstance(host, str) or not host.strip():
        raise CollectionError("Diagnóstico exige nome lógico, IP ou FQDN de um host.")
    config, signals = config or {}, signals or {}
    validate_config(config)
    manager, credentials, devices = load_inventory(manager, host)
    rows = collect_inventory(manager, credentials, devices, config, signals, now, sleep, verbosity)
    snapshot = group_snapshot(rows)
    validate_snapshot(snapshot)
    LOG.info("etapa=diagnostico status=concluido equipamento=%s eventos=%d publicado=false",
             devices[0]["name"], len(rows))
    return snapshot


def write_snapshot(temporary, rows):
    """Grava, sincroniza e relê o temporário para validar os bytes publicados."""
    with collection_stage("gravacao_temporaria"):
        with open(temporary, "w", encoding="utf-8") as target:
            json.dump(rows, target, ensure_ascii=False, indent=2, allow_nan=False)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
    with collection_stage("validacao_temporaria"):
        with open(temporary, "r", encoding="utf-8") as source:
            validate_snapshot(json.load(source))


def sync_directory(directory):
    """Sincroniza a entrada do diretório no Linux depois da substituição do JSON."""
    descriptor = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_snapshot(temporary, output):
    """Preserva permissões e publica em uma única substituição atômica.

    Este é o único ponto que muda o arquivo final. Novo arquivo recebe 0644.
    Uma falha anterior a os.replace preserva a entrada existente. Se apenas a
    sincronização posterior falhar, o JSON já foi substituído e o log registra
    publicado=true; não existe promessa de rollback após a publicação.
    """
    with collection_stage("publicacao"):
        mode = stat.S_IMODE(output.stat().st_mode) if output.exists() else 0o644
        os.chmod(temporary, mode)
        os.replace(temporary, output)
    LOG.info("etapa=publicacao arquivo=%s publicado=true", output)
    with collection_stage("sincronizacao_diretorio", published=True):
        sync_directory(output.parent)


def run_collection(output, manager=None, config=None, signals=None, now=None, sleep=time.sleep, verbosity=0):
    """Executa um ciclo sem interação; retorna lista com um objeto por equipamento.

    Args:
        output: Caminho observado pela automação para input_events.json.
        manager: Motor de autenticação injetado; None usa storage_api_manager.
        config: Configuração opcional de métricas/regras, sem credenciais.
        signals: Sinais externos de segurança indexados pelo nome lógico.
        now: Horário UTC fixo para testes; None usa o relógio real.
        sleep: Espera de amostragem injetável; padrão time.sleep.
        verbosity: 0 para operação normal; 1 mostra endpoints completos. Para
            respostas completas use collect_diagnostic_host com nível 2.

    Raises:
        CollectionError: Inventário/identidade/handler/contrato inválido ou lock
            ocupado. Exceções de I/O também são propagadas com etapa no log.
            Qualidade de medição indisponível é registrada, não vira zero.

    O lock abrange coleta e publicação. Nenhum dado parcial muda o arquivo final;
    o temporário oculto existe até a substituição ou a limpeza em erro.
    """
    if verbosity >= 2:
        raise CollectionError("Use diagnóstico --host -vv para respostas completas, sem publicar a entrada.")
    config, signals = config or {}, signals or {}
    output = prepare_output(output, config)
    with snapshot_lock(output), temporary_snapshot(output) as temporary:
        manager, credentials, devices = load_inventory(manager)
        rows = collect_inventory(manager, credentials, devices, config, signals, now, sleep, verbosity)
        with collection_stage("validacao"):
            snapshot = group_snapshot(rows)
            validate_snapshot(snapshot)
        write_snapshot(temporary, snapshot)
        publish_snapshot(temporary, output)
    LOG.info("etapa=ciclo status=concluido arquivo=%s equipamentos=%d registros=%d",
             output, len(snapshot), len(rows))
    return snapshot


def main(argv=None):
    """CLI sem perguntas: retorna 0 em sucesso e 1 em erro operacional.

    --help e --list-handlers não importam o motor nem fazem consultas. --catalog-only
    consulta metadados e escreve JSON no stdout sem alterar o arquivo de entrada. Erros de
    argumentos são tratados pelo argparse com código 2. -v/--verbose mostra URLs
    e fields; -vv exige --host e inclui respostas. --host executa diagnóstico de
    uma unidade, sem publicar. Campos de autenticação são ocultados nos corpos.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exemplos:\n"
               "  python3 %(prog)s --output /dados/input_events.json --config config_unity.json\n"
               "  python3 %(prog)s --list-handlers\n"
               "  python3 %(prog)s --catalog-only > catalogo_unity.json\n"
               "  python3 %(prog)s --output /dados/input_events.json -v\n"
               "  python3 %(prog)s --host unity-prod -v\n"
               "  python3 %(prog)s --host unity-prod -vv 2> diagnostico_unity.log\n\n"
               "Saída: 0 = sucesso; 1 = falha operacional; 2 = argumentos inválidos.\n"
               "Guia: MANUTENCAO_Coletor_Unity.md")
    parser.add_argument("--output", default="input_events.json",
                        help="JSON final observado pela automação (padrão: %(default)s).")
    parser.add_argument("--config", help="JSON opcional de métricas e regras de messageId.")
    parser.add_argument("--signals", help="JSON de sinais recentes de segurança, por nome lógico.")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="-v: URLs/fields e etapas; -vv: também corpos, exige --host.")
    parser.add_argument("--host", help="Nome lógico/IP/FQDN de um Unity; diagnóstico sem publicar entrada.")
    parser.add_argument("--list-handlers", action="store_true",
                        help="Lista evento, função e fonte descrita na docstring; não coleta.")
    parser.add_argument("--catalog-only", action="store_true",
                        help="Consulta catálogo real de métricas e imprime JSON; não publica input_events.json.")
    args = parser.parse_args(argv)
    if args.list_handlers:
        for event, handler in COLLECTION_HANDLERS.items():
            print("{} -> {}\n  {}".format(event, handler.__name__, inspect.getdoc(handler).splitlines()[0]))
        return 0
    if args.verbose > 2:
        parser.error("Use no máximo -vv para o nível de diagnóstico.")
    if args.host is not None and not args.host.strip():
        parser.error("--host precisa conter um nome lógico, IP ou FQDN.")
    if args.verbose == 2 and not args.host:
        parser.error("-vv exige --host para mostrar respostas de apenas uma unidade.")
    if args.host and not args.verbose and not args.catalog_only:
        parser.error("Use --host com -v/-vv ou --catalog-only para diagnóstico.")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.catalog_only:
            print(json.dumps(collect_metric_catalog(host=args.host, verbosity=args.verbose),
                             ensure_ascii=False, indent=2, allow_nan=False))
            return 0
        with collection_stage("leitura_arquivos"):
            config, signals = load_object(args.config), load_object(args.signals)
        if args.host:
            collect_diagnostic_host(args.host, config=config, signals=signals, verbosity=args.verbose)
        else:
            run_collection(args.output, config=config, signals=signals, verbosity=args.verbose)
    except Exception as error:
        LOG.error("etapa=ciclo status=falha erro=%s local=%s", error_text(error), error_location(error))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
