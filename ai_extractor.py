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

# Modelos em ordem de preferência (fallback automático se um der 503/sobrecarga)
MODELS_TO_TRY = [
    'gemini-3.8-flash',
    'gemini-3.8-flash-lite',
    'gemini-2.0-flash',
]

class NovoApelidoSugerido(BaseModel):
    apelido: str = Field(description="O termo ou apelido usado pelo usuário (ex: 'refin', 'portal')")
    sa: str = Field(description="O código da SA correspondente detectado")

class ItemRegistro(BaseModel):
    sa: str = Field(description="Código, número ou identificador da SA/Demanda (ex: '96569', '1234')")
    horas: float = Field(description="Quantidade de horas dedicadas à atividade em formato decimal (ex: 2.5 para 2 horas e meia, 0.5 para 30 minutos)")
    descricao: str = Field(description="Resumo claro e profissional da atividade realizada")
    data: Optional[str] = Field(default=None, description="Data da atividade no formato YYYY-MM-DD. Se a mensagem não especificar dia anterior, use a data de hoje.")

class ExtracaoHorasResponse(BaseModel):
    registros: List[ItemRegistro] = Field(default_factory=list, description="Lista de apontamentos com SA identificada")
    notas_gerais: List[str] = Field(default_factory=list, description="Resumos de atividades, anotações ou tarefas descritas onde NENHUMA SA foi mencionada ou identificada (atuando como bloco de notas)")
    novos_apelidos: List[NovoApelidoSugerido] = Field(default_factory=list, description="Associações explícitas de nome/apelido com código de SA que o usuário fez na mensagem")
    duvidas_sa: List[str] = Field(default_factory=list, description="Apenas quando o usuário menciona um termo que parece ser um código ou projeto específico e você precisa esclarecer se é uma SA já existente")
    observacoes: Optional[str] = Field(default=None, description="Avisos gerais ou esclarecimentos")

def get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY não foi encontrada nas variáveis de ambiente.")
    return genai.Client(api_key=api_key)

def _montar_contexto_apelidos(apelidos: Optional[List[Dict[str, Any]]] = None) -> str:
    """Formata os apelidos já conhecidos do usuário para incluir no prompt."""
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

def _chamar_gemini_com_retry(contents, response_schema=ExtracaoHorasResponse) -> str:
    """Executa a chamada no Gemini com retries exponenciais e fallback de modelos em caso de 503 (alta demanda)."""
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
                        temperature=0.1
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
    apelidos_existentes: Optional[List[Dict[str, Any]]] = None
) -> ExtracaoHorasResponse:
    """Extrai informações de SAs ou notas de bloco de notas a partir de um texto livre."""
    if not data_referencia:
        data_referencia = datetime.now().strftime("%Y-%m-%d")
        
    contexto_apelidos = _montar_contexto_apelidos(apelidos_existentes)

    prompt = f"""
Você é um assistente de produtividade e diário de trabalho diário.
A data de referência de 'hoje' é: {data_referencia}.

MEMÓRIA DE APELIDOS E PROJETOS CONHECIDOS DO USUÁRIO:
{contexto_apelidos}

COMPORTAMENTO ESPERADO:
1. COM SA OU APELIDO: Se o usuário mencionar uma SA ou um dos apelidos conhecidos (ou definir explicitamente uma nova SA), extraia em `registros` com 'sa', 'horas', 'descricao' e 'data'.
2. SEM SA (MODO BLOCO DE NOTAS): Se o usuário falar sobre o que fez no dia MAS NÃO citar nenhuma SA e nenhum apelido cadastrado (ex: 'Participei da daily e conversei com o PO sobre a sprint', 'Fiquei revisando código e documentação a tarde toda', 'Estudei a arquitetura nova'), NÃO tente inventar uma SA e NÃO trate como erro! Em vez disso, guarde cada atividade resumida no campo `notas_gerais`.
3. APELIDOS NOVOS: Se o usuário associar explicitamente um nome a um número (ex: 'SA 96569 do refin'), adicione em `novos_apelidos`.
4. DÚVIDAS: Se o usuário citar um termo ou número ambíguo que possa ser uma SA existente, coloque uma pergunta amigável em `duvidas_sa`.

Mensagem do usuário:
"{texto}"
"""
    json_text = _chamar_gemini_com_retry(contents=prompt)
    return ExtracaoHorasResponse.model_validate_json(json_text)

def processar_audio(
    caminho_arquivo_audio: str, 
    data_referencia: Optional[str] = None,
    apelidos_existentes: Optional[List[Dict[str, Any]]] = None
) -> ExtracaoHorasResponse:
    """Extrai informações de SAs ou anotações livres em áudio."""
    if not data_referencia:
        data_referencia = datetime.now().strftime("%Y-%m-%d")

    contexto_apelidos = _montar_contexto_apelidos(apelidos_existentes)

    prompt = f"""
Você é um assistente de produtividade e diário de trabalho diário.
A data de referência de 'hoje' é: {data_referencia}.

MEMÓRIA DE APELIDOS E PROJETOS CONHECIDOS DO USUÁRIO:
{contexto_apelidos}

COMPORTAMENTO ESPERADO:
1. COM SA: Se o usuário citar uma SA ou apelido conhecido, extraia em `registros` (sa, horas, descricao, data).
2. SEM SA (MODO BLOCO DE NOTAS): Se o usuário falar do que fez no expediente mas NÃO citar nenhuma SA e nenhum apelido cadastrado (ex: 'Fiquei alinhando com o time na daily, depois ajudei o colega na homologação'), salve as tarefas no campo `notas_gerais` para servir como diário/bloco de notas.
3. Se associar novo apelido a uma SA, inclua em `novos_apelidos`.
4. Se houver dúvida real se um termo novo é uma SA existente, inclua em `duvidas_sa`.
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
    return ExtracaoHorasResponse.model_validate_json(json_text)
