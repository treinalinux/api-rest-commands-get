# Checklist de entrega da coleta para a equipe Zabbix

Use uma cópia deste checklist para cada família e, quando necessário, para cada combinação de modelo e firmware.

## 1. Identificação

- [ ] Família e modelo exatos registrados.
- [ ] Firmware/SO registrado.
- [ ] Versão da API, Redfish ou MIB registrada.
- [ ] Licenças que alteram a telemetria registradas.
- [ ] Topologia de nós/controladores/membros registrada.
- [ ] Recursos não aplicáveis identificados explicitamente.

## 2. Acesso

- [ ] Conta de serviço exclusiva criada.
- [ ] Privilégio mínimo de leitura validado.
- [ ] Senha/token armazenado fora dos documentos e amostras.
- [ ] Origem do Zabbix Server/Proxy autorizada.
- [ ] Portas e firewalls validados nos dois sentidos necessários.
- [ ] Cadeia TLS confiável instalada no coletor.
- [ ] NTP consistente entre equipamento e monitoração.

## 3. Descoberta

- [ ] Catálogo da API, `?describe`, Redfish ServiceRoot ou árvore MIB salvo.
- [ ] IDs nativos e estáveis dos objetos identificados.
- [ ] Paginação testada.
- [ ] Campos opcionais, `null` e coleções vazias testados.
- [ ] Enumerações de saúde/estado copiadas da versão instalada.

## 4. Critérios mínimos

| Critério | Disponível | Não disponível | Não aplicável | Evidência |
|---|:---:|:---:|:---:|---|
| Disponibilidade | [ ] | [ ] | [ ] | |
| Capacidade | [ ] | [ ] | [ ] | |
| Performance | [ ] | [ ] | [ ] | |
| Proteção | [ ] | [ ] | [ ] | |
| Segurança observável | [ ] | [ ] | [ ] | |

## 5. Para cada métrica aprovada

- [ ] Nome funcional.
- [ ] Critério e escopo.
- [ ] Endpoint/OID e método.
- [ ] Caminho exato no payload ou objeto MIB.
- [ ] Identificador estável do recurso.
- [ ] Tipo e unidade.
- [ ] Gauge, contador cumulativo, estado ou texto.
- [ ] Enumeração oficial, quando for estado.
- [ ] Frequência máxima aceita pelo responsável do produto.
- [ ] Amostra saudável sanitizada.
- [ ] Amostra degradada ou evento de teste sanitizado.
- [ ] Comportamento de ausência do recurso.

## 6. Falhas de coleta

- [ ] DNS inválido distinguido de timeout.
- [ ] Conexão recusada distinguida de timeout.
- [ ] Certificado inválido/expirado distinguido de falha da API.
- [ ] Credencial inválida distinguida de falta de permissão.
- [ ] Limite de requisição ou sessão expirada identificado.
- [ ] HTTP `200` com payload inválido é detectável.
- [ ] Resposta SNMP `noSuchObject/noSuchInstance` é distinguida de timeout.
- [ ] Reinicialização é detectada antes de calcular delta de contadores.

## 7. Arquivos a entregar

- [ ] `inventario.md` ou planilha com modelo, versão, site e recursos.
- [ ] `descoberta.*` com catálogo/API/MIB.
- [ ] `healthy.*` com resposta normal.
- [ ] `degraded.*` com resposta de problema ou teste oficial.
- [ ] `empty.*` com coleção vazia válida, se aplicável.
- [ ] `auth_error.*` sem dados sensíveis.
- [ ] `timeout.txt` com evidência do comportamento de indisponibilidade.
- [ ] `mapping.md` preenchendo o contrato de métricas.
- [ ] Referência oficial correspondente à versão instalada.

## 8. Aprovações

- [ ] Dono técnico do equipamento aprovou método e frequência.
- [ ] Segurança aprovou conta, TLS e armazenamento de segredos.
- [ ] Rede aprovou fluxos e portas.
- [ ] Equipe Zabbix confirmou que as amostras bastam para implementar e testar o template.
