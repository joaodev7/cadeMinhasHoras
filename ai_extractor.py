import os
import json
import time
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from google.genai.errors import APIError

logger = logging.getLogger(__name__)

MODELS_TO_TRY = [
    'gemini-3.8-flash',
    'gemini-3.8-flash-lite',
    'gemini-3.5-flash',
    'gemini-3.1-flash-lite',
]

class NovoApelidoSugerido(BaseModel):
    apelido: str = Field(description="O termo ou apelido usado pelo usuário (ex: 'refin', 'portal')")
    sa: str = Field(description="O código da SA correspondente detectado")

class ItemRegistro(BaseModel):
    sa: str = Field(description="Código, número ou identificador da SA/Demanda (ex: '96569', '1234')")
    horas: float = Field(description="Quantidade de horas dedicadas à atividade em formato decimal (ex: 2.5 para 2 horas e meia, 0.5 para 30 minutos)")
    descricao: str = Field(description="Resumo claro e profissional da atividade realizada")
    data: Optional[str] = Field(default=None, description="Data da atividade no formato YYYY-MM-DD. Se a mensagem não especificar dia anterior, use a data de hoje.")

class ExtracaoGeralResponse(BaseModel):
    eh_pergunta_ou_conversa: bool = Field(default=False, description="True se a mensagem do usuário for uma pergunta, dúvida geral, pedido de conselho/tempo ou consulta sobre seu trabalho. False se for um registro/relato de tarefas feitas.")
    resposta_conversacional: Optional[str] = Field(default=None, description="Se for uma pergunta/conversa, responda de forma prestativa, direta e natural como um assistente pessoal.")
    registros: List[ItemRegistro] = Field(default_factory=list, description="Lista de apontamentos com SA identificada")
    notas_gerais: List[str] = Field(default_factory=list, description="Resumos de atividades realizadas onde NENHUMA SA foi mencionada (bloco de notas)")
    pendencias_futuras: List[str] = Field(default_factory=list, description="Tarefas que o usuário precisa fazer no futuro, promessas ou to-dos identificados (ex: 'preciso cobrar o Matheus', 'tenho que testar o deploy amanhã')")
    novos_apelidos: List[NovoApelidoSugerido] = Field(default_factory=list, description="Associações explícitas de nome/apelido com código de SA")
    duvidas_sa: List[str] = Field(default_factory=list, description="Perguntas quando houver dúvida se um termo é uma SA existente")
    observacoes: Optional[str] = Field(default=None, description="Avisos gerais ou esclarecimentos")

def get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY não foi encontrada nas variáveis de ambiente.")
    return genai.Client(api_key=api_key)

def _montar_contexto_apelidos(apelidos: Optional[List[Dict[str, Any]]] = None) -> str:
    if not apelidos:
        return "Nenhum apelido cadastrado ainda."
    
    por_sa: Dict[str, List[str]] = {}
    for item in apelidos:
        sa = item["sa_id"]
        if sa not in por_sa:
            por_sa[sa] = []
        por_sa[sa].append(item["apelido"])

    linhas = []
    for sa, nomes in por_sa.items():
        linhas.append(f"- SA {sa}: apelidos conhecidos = [{', '.join(nomes)}]")
    return "\n".join(linhas)

def _montar_contexto_historico(historico: Optional[Dict[str, Any]] = None) -> str:
    """Formata os últimos registros e notas de trabalho para permitir que o bot responda sobre o trabalho."""
    if not historico:
        return "Nenhum histórico recente disponível."

    linhas = ["HISTÓRICO RECENTE DE TRABALHO DO USUÁRIO:"]
    
    regs = historico.get("registros", [])
    if regs:
        linhas.append("Horas em SAs recentes:")
        for r in regs[:15]:
            linhas.append(f"  • {r['data']} - SA {r['sa_id']} ({r['horas']}h): {r['descricao']}")
    
    notas = historico.get("notas", [])
    if notas:
        linhas.append("Anotações recentes do bloco de notas:")
        for n in notas[:10]:
            linhas.append(f"  • {n['data']} às {n['hora']}: {n['conteudo']}")

    tarefas = historico.get("tarefas_pendentes", [])
    if tarefas:
        linhas.append("Tarefas pendentes atuais:")
        for t in tarefas:
            linhas.append(f"  • [Pendente desde {t['data_criacao']}]: {t['descricao']}")

    return "\n".join(linhas)

def _chamar_gemini_com_retry(contents, response_schema=ExtracaoGeralResponse) -> str:
    client = get_client()
    last_error = None

    for model_name in MODELS_TO_TRY:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=response_schema,
                        temperature=0.2
                    )
                )
                return response.text
            except APIError as e:
                last_error = e
                if e.code in [503, 429]:
                    espera = (2 ** attempt) * 1.5
                    logger.warning(
                        f"Modelo {model_name} ocupado (status {e.code}). Tentativa {attempt + 1}/3. Aguardando {espera}s..."
                    )
                    time.sleep(espera)
                else:
                    logger.warning(f"Erro {e.code} ao tentar {model_name}: {e.message}. Tentando próximo modelo...")
                    break
            except Exception as e:
                last_error = e
                logger.warning(f"Erro inesperado em {model_name}: {e}. Tentando próximo modelo...")
                break

    raise last_error or RuntimeError("Não foi possível obter resposta de nenhum modelo Gemini.")

def processar_texto(
    texto: str, 
    data_referencia: Optional[str] = None, 
    apelidos_existentes: Optional[List[Dict[str, Any]]] = None,
    historico_recente: Optional[Dict[str, Any]] = None
) -> ExtracaoGeralResponse:
    """Processa texto do usuário classificando entre pergunta/conversa ou registro de SAs/tarefas."""
    if not data_referencia:
        data_referencia = datetime.now().strftime("%Y-%m-%d")
        
    contexto_apelidos = _montar_contexto_apelidos(apelidos_existentes)
    contexto_historico = _montar_contexto_historico(historico_recente)

    prompt = f"""
Você é o 'CadêMinhasHoras', o assistente pessoal de trabalho do usuário.
A data de referência de 'hoje' é: {data_referencia}.

{contexto_apelidos}

{contexto_historico}

DIRETRIZES DE ATUAÇÃO:
1. SE FOR UMA PERGUNTA OU CONVERSA:
   - Se o usuário perguntar sobre o trabalho (ex: 'quando mexi na SA do refin?', 'quantas horas fiz ontem?', 'qual SA usei no login?'), use o HISTÓRICO RECENTE para responder com exatidão em `resposta_conversacional` e defina `eh_pergunta_ou_conversa: true`.
   - Se for uma pergunta geral (ex: 'como tá o clima?', 'o que é tal tecnologia?', 'resume isso pra mim'), responda de forma prestativa, direta e simpática em `resposta_conversacional` com `eh_pergunta_ou_conversa: true`.
2. SE FOR UM REGISTRO OU RELATO DE TAREFAS:
   - Defina `eh_pergunta_ou_conversa: false`.
   - Extraia as SAs conhecidas em `registros` (sa, horas, descricao, data).
   - Se relatar trabalho sem SA, coloque em `notas_gerais`.
   - SE CITAR TAREFAS QUE PRECISA FAZER NO FUTURO (ex: 'preciso falar com fulano', 'amanhã tenho que testar x'), adicione essas pendências em `pendencias_futuras`.
   - Se associar novo apelido a um número de SA, coloque em `novos_apelidos`.

Mensagem do usuário:
"{texto}"
"""
    json_text = _chamar_gemini_com_retry(contents=prompt)
    return ExtracaoGeralResponse.model_validate_json(json_text)

def processar_audio(
    caminho_arquivo_audio: str, 
    data_referencia: Optional[str] = None,
    apelidos_existentes: Optional[List[Dict[str, Any]]] = None,
    historico_recente: Optional[Dict[str, Any]] = None
) -> ExtracaoGeralResponse:
    """Processa áudio do usuário classificando entre pergunta/conversa ou registro."""
    if not data_referencia:
        data_referencia = datetime.now().strftime("%Y-%m-%d")

    contexto_apelidos = _montar_contexto_apelidos(apelidos_existentes)
    contexto_historico = _montar_contexto_historico(historico_recente)

    prompt = f"""
Você é o 'CadêMinhasHoras', o assistente pessoal de trabalho do usuário.
A data de referência de 'hoje' é: {data_referencia}.

{contexto_apelidos}

{contexto_historico}

Ouça com atenção o áudio do usuário e decida:
1. É uma PERGUNTA OU CONVERSA?
   - Sobre trabalho (pesquise no HISTÓRICO RECENTE fornecido) ou sobre assuntos gerais: defina `eh_pergunta_ou_conversa: true` e forneça a resposta completa em `resposta_conversacional`.
2. É um REGISTRO DE TRABALHO?
   - Defina `eh_pergunta_ou_conversa: false`.
   - Extraia SAs em `registros` (sa, horas, descricao, data).
   - Tarefas feitas sem SA em `notas_gerais`.
   - Tarefas/promessas a fazer no futuro em `pendencias_futuras`.
   - Novos apelidos em `novos_apelidos`.
"""

    with open(caminho_arquivo_audio, "rb") as f:
        audio_bytes = f.read()

    contents = [
        types.Part.from_bytes(
            data=audio_bytes,
            mime_type='audio/ogg'
        ),
        prompt
    ]

    json_text = _chamar_gemini_com_retry(contents=contents)
    return ExtracaoGeralResponse.model_validate_json(json_text)

def gerar_script_daily(
    dia_anterior_str: str, 
    registros_ontem: List[Dict[str, Any]], 
    notas_ontem: List[Dict[str, Any]],
    tarefas_pendentes: List[Dict[str, Any]]
) -> str:
    """Gera um texto pronto e polido para falar na Daily Meeting matinal."""
    client = get_client()

    prompt = f"""
Você é o assistente pessoal CadêMinhasHoras. 
Crie uma fala pronta e objetiva para o usuário usar na reunião de DAILY MEETING matinal.

DADOS DE ONTEM ({dia_anterior_str}):
- Horas e SAs: {json.dumps(registros_ontem, ensure_ascii=False)}
- Notas/Daily notes: {json.dumps(notas_ontem, ensure_ascii=False)}

PENDÊNCIAS / TO-DOS EM ABERTO:
- {json.dumps(tarefas_pendentes, ensure_ascii=False)}

Gere uma resposta em Markdown dividida estritamente em:
🎙️ **Sugestão para sua Daily de Hoje:**
• **Ontem eu fiz:** (resumo claro das tarefas e SAs trabalhadas)
• **Hoje vou focar em:** (sugestão com base nas pendências em aberto ou continuidade)
• **Impedimentos:** (se houver menção a bloqueios, caso contrário: 'Nenhum impedimento')
"""

    for model_name in MODELS_TO_TRY:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.3)
            )
            return response.text
        except Exception as e:
            logger.warning(f"Erro ao gerar script daily no modelo {model_name}: {e}")

    return "Não foi possível gerar a sugestão de daily hoje."

def redigir_mensagem_corporativa(intencao: str) -> str:
    """Transforma um pedido bruto em um texto corporativo elegante e polido."""
    client = get_client()

    prompt = f"""
Você é um especialista em comunicação corporativa e produtividade.
O usuário quer mandar uma mensagem profissional no Teams/Slack/E-mail sobre:
"{intencao}"

Escreva uma mensagem clara, educada, concisa e altamente profissional em português.
Forneça 2 opções: uma mais direta (curta) e uma mais formal (detalhada).
"""

    for model_name in MODELS_TO_TRY:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.4)
            )
            return response.text
        except Exception as e:
            logger.warning(f"Erro ao redigir mensagem com modelo {model_name}: {e}")

    return "Não foi possível redigir a mensagem no momento."
