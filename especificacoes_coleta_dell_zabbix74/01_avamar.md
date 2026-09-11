# Avamar — especificação de coleta

## 1. Decisão

**Mínimo recomendado:** SNMPv3 `authPriv`, usando a `AVAMAR-MCS-MIB`, mais traps SNMPv3 para eventos.  
**Extensão:** Avamar REST API para detalhamento de atividades, clientes e jobs quando o mínimo por SNMP não atender ao SLA de proteção.

Essa divisão entrega saúde, capacidade e eventos com baixa complexidade. A API REST moderna do Avamar exige o fluxo de autenticação suportado pela versão, normalmente com cliente OAuth2 e token; portanto, ela deve entrar depois que o mínimo SNMP estiver estável.

## 2. Escopo mínimo

| Critério | Entrega mínima |
|---|---|
| Disponibilidade | Alcance SNMP, uptime, estado do servidor/grid, serviços essenciais e eventos críticos ativos. |
| Capacidade | Capacidade total, usada, livre e percentual de utilização expostos pela MIB. |
| Performance | Utilização/carga exposta pela MIB e volume/duração/taxa das atividades disponíveis. |
| Proteção | Última atividade, resultado das atividades, falhas de backup/restore/replicação e idade do último sucesso quando expostos. |
| Segurança observável | Versão, validade do HTTPS e eventos de autenticação/segurança que a MIB ou API realmente exponha. |

Não confundir o estado do Avamar com o estado de um Data Domain integrado. Se houver Data Domain, ele deve ter coleta própria conforme `03_powerprotect_data_domain.md`.

## 3. Pré-requisitos

- Modelo do Avamar, versão exata e tipo de implantação: appliance, grid ou Avamar Virtual Edition.
- `AVAMAR-MCS-MIB.txt` correspondente à versão instalada.
- Conta/usuário SNMPv3 exclusivo e somente leitura, preferencialmente com autenticação e privacidade.
- UDP 161 do coletor para o Avamar.
- UDP 162 do Avamar para o receptor de traps, se habilitado.
- Perfil de eventos do Avamar configurado para enviar somente categorias e severidades aprovadas.
- NTP consistente.
- Para REST: HTTPS, CA confiável, cliente OAuth2 autorizado e documentação Swagger da própria versão.

## 4. Como habilitar e validar o SNMP

O guia de administração fornece o utilitário `avsetup_snmp` para configurar o agente Net-SNMP e o subagente Avamar. A alteração deve ser executada pelo administrador do produto, em janela aprovada.

No lado do coletor RHEL, instalar as ferramentas:

```bash
sudo dnf install net-snmp-utils
```

Copiar a MIB da versão para um diretório controlado, por exemplo:

```text
/usr/local/share/snmp/mibs-avamar/AVAMAR-MCS-MIB.txt
```

Primeiro validar um objeto padrão. Os valores abaixo são marcadores, não credenciais reais:

```bash
snmpget -v3 -l authPriv \
  -u 'USUARIO_SNMP' \
  -a SHA-256 -A 'SEGREDO_AUTH' \
  -x AES -X 'SEGREDO_PRIV' \
  AVAMAR_FQDN \
  SNMPv2-MIB::sysUpTime.0
```

Depois listar os símbolos da MIB instalada:

```bash
snmptranslate \
  -M +/usr/local/share/snmp/mibs-avamar \
  -m +AVAMAR-MCS-MIB \
  -Tz | sort > avamar_mib_symbols.txt
```

Gerar a árvore, com tipos e relações:

```bash
snmptranslate \
  -M +/usr/local/share/snmp/mibs-avamar \
  -m +AVAMAR-MCS-MIB \
  -Tp > avamar_mib_tree.txt
```

O nome do nó raiz deve ser obtido do arquivo da MIB, não presumido. Convertê-lo para OID numérico e executar um walk controlado:

```bash
snmptranslate \
  -M +/usr/local/share/snmp/mibs-avamar \
  -m +AVAMAR-MCS-MIB \
  -On 'AVAMAR-MCS-MIB::SIMBOLO_RAIZ'
```

```bash
snmpwalk -v3 -l authPriv \
  -u 'USUARIO_SNMP' \
  -a SHA-256 -A 'SEGREDO_AUTH' \
  -x AES -X 'SEGREDO_PRIV' \
  -M +/usr/local/share/snmp/mibs-avamar \
  -m +AVAMAR-MCS-MIB \
  AVAMAR_FQDN \
  'AVAMAR-MCS-MIB::SIMBOLO_RAIZ' > avamar_vendor_walk.txt
```

Não manter senhas na linha de comando em produção. O exemplo serve para validação em ambiente protegido; a implementação deve usar o mecanismo de segredo aprovado pela equipe Zabbix.

## 5. Como escolher os OIDs

Pesquisar as descrições da MIB e confrontar cada resultado com Avamar Administrator:

```bash
rg -i 'capacity|utilization|status|activity|backup|restore|replication|event|severity|error|failed|version' \
  avamar_mib_symbols.txt avamar_mib_tree.txt
```

Para cada símbolo candidato:

```bash
snmptranslate \
  -M +/usr/local/share/snmp/mibs-avamar \
  -m +AVAMAR-MCS-MIB \
  -Td 'AVAMAR-MCS-MIB::SIMBOLO'
```

A saída `-Td` é obrigatória para descobrir sintaxe, unidade, enumeração e se o objeto é escalar ou tabela. O número do OID só deve ser fixado depois dessa validação.

## 6. Mapeamento a levantar

| Critério | Objeto funcional | Fonte | Extração e interpretação |
|---|---|---|---|
| Disponibilidade | Uptime do agente | `SNMPv2-MIB::sysUpTime.0` | TimeTicks; queda seguida de valor baixo indica reinicialização. |
| Disponibilidade | Estado consolidado do Avamar/grid | `AVAMAR-MCS-MIB` da versão | Selecionar símbolo cuja descrição represente saúde atual; preservar enumeração original. |
| Disponibilidade | Serviços/processos essenciais | MIB e eventos | Descobrir todos os objetos/índices; não usar apenas a primeira linha. |
| Disponibilidade | Eventos críticos/erro | Traps e tabela de eventos | Guardar ID, código, severidade, timestamp, mensagem e identidade do servidor. |
| Capacidade | Total/usado/livre | MIB | Preferir bytes ou unidade explicitada pela MIB; calcular percentual somente com grandezas da mesma base. |
| Capacidade | Utilização máxima do grid | MIB/Server Monitor | Confirmar se o valor representa o nó mais utilizado, o grid ou backend Data Domain. |
| Performance | Carga/atividade | MIB | Determinar se o valor é gauge ou contador e qual intervalo representa. |
| Proteção | Resultado da última atividade | MIB de atividades | Descobrir por ID estável; registrar tipo, início, fim, resultado e domínio/cliente apenas se permitido. |
| Proteção | Falhas por tipo | MIB/traps | Não tratar evento histórico resolvido como problema ainda ativo. |
| Proteção | Replicação | MIB, eventos e REST opcional | Separar estado do job, último sucesso e atraso. |
| Segurança | Versão | MIB ou inventário REST | Texto de inventário; coleta diária é suficiente. |
| Segurança | Certificado HTTPS | Handshake TLS externo | Coletar validade e cadeia sem desabilitar validação TLS. |

### Regras para atividades

- Usar o ID nativo da atividade como identidade.
- Separar estado em andamento do resultado final.
- Não deduzir sucesso pela ausência de evento de erro.
- Definir qual timezone aparece no payload.
- Calcular idade do último sucesso a partir do timestamp do produto, não da hora de chegada ao Zabbix.
- Filtrar ou anonimizar nome de cliente, dataset e caminho se forem dados sensíveis.

## 7. Traps

No Avamar Administrator, criar um perfil de eventos que envie traps ao receptor aprovado. O teste deve usar a função oficial de teste ou um evento não destrutivo.

No receptor, confirmar:

- IP de origem real;
- versão e nível de segurança SNMPv3;
- enterprise OID;
- código e ID do evento;
- severidade;
- texto;
- timestamp e timezone;
- evento de recuperação, quando existir.

Traps podem ser perdidas. Manter polling periódico do estado e das atividades para reconciliar o cenário atual.

## 8. Extensão REST para atividades

A documentação do Avamar 19.x expõe atividades em:

```http
GET https://AVAMAR_FQDN/api/v1/activities?
Authorization: Bearer TOKEN
Accept: application/json
```

Antes de implementar:

1. Abrir o Swagger da versão instalada.
2. Criar um cliente OAuth2 conforme o guia dessa versão.
3. Obter token pelo endpoint documentado pela instalação.
4. Executar somente chamadas de leitura durante a homologação.
5. Definir filtros de janela de tempo e paginação.
6. Capturar uma atividade concluída com sucesso, uma falha e uma em execução.

Não copiar payload de criação de cliente nem fluxo de token de outra release. Em versões recentes há integração com OAuth2/JWT e detalhes que mudam conforme a configuração. O coletor deve renovar o token antes de expirar e repetir a autenticação apenas quando necessário.

Da resposta de atividades, a equipe deverá localizar, usando o Swagger e as amostras reais:

- ID da atividade;
- tipo: backup, restore, replication etc.;
- estado atual;
- resultado final;
- início e fim;
- bytes processados, se disponível;
- duração;
- cliente/dataset ou escopo;
- mensagem/código de erro;
- paginação e total de registros.

## 9. Frequência inicial

| Coleta | Frequência |
|---|---:|
| Uptime e saúde | 1 a 2 minutos |
| Capacidade | 15 minutos |
| Tabelas de atividade SNMP | 5 minutos |
| REST de atividades em execução | 5 minutos |
| Inventário/versão | 12 a 24 horas |
| Traps | contínuo |

## 10. Tratamento de falhas

- Timeout SNMP é falha de coleta, não estado ruim do Avamar.
- `noSuchObject` indica MIB/OID incompatível; `noSuchInstance` pode indicar recurso inexistente.
- Uma tabela vazia pode significar ausência legítima de atividades no filtro.
- HTTP `401`/`403` deve ser separado de API fora do ar.
- Token expirado exige renovação; não deve abrir problema de backup.
- Se o Avamar reiniciar, descartar deltas negativos de contadores.

## 11. Evidências obrigatórias

- `avamar_inventory.txt`: modelo e versão.
- `AVAMAR-MCS-MIB.txt`: arquivo da instalação, com checksum.
- `avamar_mib_symbols.txt` e `avamar_mib_tree.txt`.
- `avamar_vendor_walk.txt` sanitizado.
- uma trap de teste sanitizada.
- capturas da tela que confirmem capacidade e saúde na mesma hora do walk.
- se REST entrar no escopo: Swagger/versão, headers sem token e três respostas de atividades sanitizadas.
- tabela final com símbolo, OID numérico, índice, tipo, unidade e significado.

## 12. Testes de aceitação

- [ ] `sysUpTime.0` responde por SNMPv3.
- [ ] A MIB carrega sem erro de dependência.
- [ ] Saúde e capacidade conferem com a interface do Avamar.
- [ ] Uma trap oficial chega e é decodificada pela MIB.
- [ ] Uma falha histórica não permanece como estado atual sem evidência.
- [ ] Indisponibilidade SNMP é distinguida de problema do produto.
- [ ] Se REST for usado, token expira/renova sem perder atividades.
- [ ] Dados de clientes foram sanitizados nas evidências.

## 13. Referências oficiais

- [Dell Avamar 19.12 — configurar monitoração do servidor com SNMP](https://www.dell.com/support/manuals/en-us/avamar-server/avamar_administration_guide_19.12/configure-server-monitoring-with-snmp?guid=guid-83d3a36e-b975-43c2-8811-b05a018abe38&lang=en-us)
- [Dell Avamar — monitorar servidores com SNMP](https://www.dell.com/support/manuals/en-us/avamar-server/avamar_administration_guide_19.12/monitor-servers-with-snmp?guid=guid-2a16003a-d08c-4288-9508-dae656ce0a7c&lang=en-us)
- [Dell Avamar 19.12 — consumir serviços REST](https://www.dell.com/support/manuals/en-us/avamar-server/avamar_administration_guide_19.12/consume-rest-api-services?guid=guid-8356895d-ca05-4987-bc11-4608a4dbc2bb&lang=en-us)
- [Dell Avamar 19.12 — testar a REST API](https://www.dell.com/support/manuals/en-us/avamar-server/avamar_administration_guide_19.12/Test-the-Avamar-REST-API?guid=guid-fe72480f-7dd6-494f-92aa-1306826b1084&lang=en-us)
