import os
import logging
from datetime import datetime, time
import zoneinfo
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import threading
import uvicorn
from fastapi import FastAPI

import database
import ai_extractor
import reports

# Configurações de Logs
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Fuso horário do Brasil
TIMEZONE_BR = zoneinfo.ZoneInfo("America/Sao_Paulo")

# Carregar variáveis do .env
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = os.getenv("ALLOWED_TELEGRAM_USER_ID")
ALLOWED_USER_ID = int(ALLOWED_USER_ID) if ALLOWED_USER_ID and ALLOWED_USER_ID.strip() else None

def eh_usuario_autorizado(user_id: int) -> bool:
    """Verifica se o usuário tem permissão para usar o bot (caso configurado)."""
    if ALLOWED_USER_ID is None:
        return True
    return user_id == ALLOWED_USER_ID

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start de boas-vindas e exibição do ID do usuário."""
    user = update.effective_user
    user_id = user.id

    database.registrar_usuario_ativo(user_id)

    msg = (
        f"👋 Olá, *{user.first_name}*!\n\n"
        f"Sou seu assistente de ponto, lançamento de SAs e bloco de notas diário.\n\n"
        f"🔑 *Seu ID no Telegram:* `{user_id}`\n\n"
        "⏰ *Seus Alarmes Automáticos de Ponto estão ATIVOS (Seg a Sex):*\n"
        "• `08:00` - 🟢 Início do expediente (Bater ponto)\n"
        "• `12:00` - 🍽️ Saída para almoço (O que você fez de manhã?)\n"
        "• `12:30` - 🍽️ Lembrete flexível de almoço\n"
        "• `13:30` - 💻 Retorno do almoço (Bater ponto e retomar)\n"
        "• `17:00` - 🔴 Fim do expediente (Fechamento do dia e horas das SAs)\n\n"
        "💡 *Como interagir (Áudio ou Texto):*\n"
        "• **Com SA:** `Fiz 4h no refin ajustando a tela` ➡️ Lança as horas na SA vinculada!\n"
        "• **Sem SA (Bloco de Notas):** `Participei da daily com o time e tirei dúvidas de homologação` ➡️ Salva automaticamente como anotação do dia para seu rastro!\n\n"
        "📌 *Comandos:*\n"
        "• `/hoje` - Relatório do dia (Horas nas SAs + Anotações do Bloco de Notas)\n"
        "• `/notas` - Lista apenas as anotações do bloco de notas de hoje\n"
        "• `/mes` - Relatório mensal consolidado e planilha Excel\n"
        "• `/apelidos` - Lista apelidos das suas SAs\n"
        "• `/alarmes` - Ativar/pausar alarmes automáticos\n"
        "• `/desfazer` - Apaga o último lançamento"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def alarmes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Permite ligar ou desligar os alarmes automáticos."""
    user_id = update.effective_user.id
    if not eh_usuario_autorizado(user_id):
        return

    args = context.args
    if args and args[0].lower() in ["off", "desligar", "pausar"]:
        database.alternar_alarmes(user_id, False)
        await update.message.reply_text("⏸️ *Alarmes automáticos de ponto pausados!*", parse_mode=ParseMode.MARKDOWN)
        return
    elif args and args[0].lower() in ["on", "ligar", "ativar"]:
        database.alternar_alarmes(user_id, True)
        await update.message.reply_text("▶️ *Alarmes automáticos ativados com sucesso!*", parse_mode=ParseMode.MARKDOWN)
        return

    keyboard = [
        [
            InlineKeyboardButton("🔔 Ativar Alarmes", callback_data="alarmes_on"),
            InlineKeyboardButton("🔕 Pausar Alarmes", callback_data="alarmes_off"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = (
        "⏰ *Gerenciamento de Alarmes de Ponto:*\n\n"
        "Os alarmes disparam de **segunda a sexta-feira** nos horários:\n"
        "• `08:00` - Início do expediente\n"
        "• `12:00` - Saída para almoço + Lembrete de horas da manhã\n"
        "• `12:30` - Alarme de reforço/flexível de almoço\n"
        "• `13:30` - Retorno do almoço\n"
        "• `17:00` - Fim de expediente + Fechamento do dia\n\n"
        "Escolha abaixo ou use `/alarmes on` ou `/alarmes off`:"
    )
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def apelidos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista todos os apelidos e SAs cadastrados."""
    user_id = update.effective_user.id
    if not eh_usuario_autorizado(user_id):
        return

    itens = database.obter_apelidos(user_id)
    if not itens:
        await update.message.reply_text(
            "🧠 *Memória de Apelidos Vazia*\n\n"
            "Você pode cadastrar apelidos falando naturalmente (ex: _'A SA 96569 é o refin'_)\n"
            "ou pelo comando:\n`/apelido refin 96569`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    por_sa = {}
    for item in itens:
        sa = item["sa_id"]
        if sa not in por_sa:
            por_sa[sa] = []
        por_sa[sa].append(f"`{item['apelido']}`")

    linhas = ["🧠 *SAs e Apelidos Cadastrados:*\n"]
    for sa, apelidos_list in por_sa.items():
        linhas.append(f"📌 *SA {sa}:* {', '.join(apelidos_list)}")

    linhas.append("\n💡 _Para adicionar mais um apelido:_ `/apelido <novo_apelido> <sa>`")
    await update.message.reply_text("\n".join(linhas), parse_mode=ParseMode.MARKDOWN)

async def cadastrar_apelido_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Permite cadastrar ou associar um apelido a uma SA: /apelido <termo> <numero_sa>"""
    user_id = update.effective_user.id
    if not eh_usuario_autorizado(user_id):
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "ℹ️ *Uso correto:*\n`/apelido <termo_ou_apelido> <numero_sa>`\n\n_Exemplo:_ `/apelido refin 96569`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    apelido = " ".join(args[:-1]).strip().lower()
    sa_id = args[-1].strip()

    database.salvar_apelido(user_id, apelido, sa_id)
    await update.message.reply_text(
        f"✅ *Apelido salvo com sucesso!*\n"
        f"Quando você falar `{apelido}`, saberei que é a *SA {sa_id}*.",
        parse_mode=ParseMode.MARKDOWN
    )

async def hoje_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe o resumo das atividades registradas hoje ou em uma data específica (SAs + Bloco de Notas)."""
    user_id = update.effective_user.id
    if not eh_usuario_autorizado(user_id):
        return

    data_consulta = datetime.now(TIMEZONE_BR)
    titulo_data = data_consulta.strftime('%d/%m/%Y')
    hoje_str = data_consulta.strftime("%Y-%m-%d")

    # Suporte a argumentos: /hoje ontem ou /hoje 14/10/2026
    args = context.args
    if args:
        param = args[0].lower().strip()
        if param == "ontem":
            from datetime import timedelta
            data_consulta = data_consulta - timedelta(days=1)
            hoje_str = data_consulta.strftime("%Y-%m-%d")
            titulo_data = f"Ontem ({data_consulta.strftime('%d/%m/%Y')})"
        else:
            try:
                # Tenta parsear formato DD/MM ou DD/MM/AAAA
                partes = param.split("/")
                if len(partes) == 2:
                    ano = data_consulta.year
                    d_parsed = datetime.strptime(f"{param}/{ano}", "%d/%m/%Y")
                else:
                    d_parsed = datetime.strptime(param, "%d/%m/%Y")
                hoje_str = d_parsed.strftime("%Y-%m-%d")
                titulo_data = d_parsed.strftime("%d/%m/%Y")
            except Exception:
                await update.message.reply_text("⚠️ Formato de data inválido! Use `/hoje`, `/hoje ontem` ou `/hoje DD/MM/AAAA`.", parse_mode=ParseMode.MARKDOWN)
                return

    registros = database.obter_registros_dia(user_id, hoje_str)
    notas = database.obter_notas_dia(user_id, hoje_str)

    texto = reports.formatar_relatorio_texto(
        registros=registros, 
        titulo=f"Rastro Diário ({titulo_data})",
        notas=notas
    )
    await update.message.reply_text(texto, parse_mode=ParseMode.MARKDOWN)

async def notas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe apenas as anotações do bloco de notas do dia."""
    user_id = update.effective_user.id
    if not eh_usuario_autorizado(user_id):
        return

    hoje_str = datetime.now(TIMEZONE_BR).strftime("%Y-%m-%d")
    notas = database.obter_notas_dia(user_id, hoje_str)
    texto = reports.formatar_notas_texto(notas, datetime.now(TIMEZONE_BR).strftime("%d/%m/%Y"))
    await update.message.reply_text(texto, parse_mode=ParseMode.MARKDOWN)

async def mes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gera o relatório do mês e anexa o arquivo Excel."""
    user_id = update.effective_user.id
    if not eh_usuario_autorizado(user_id):
        return

    ano_mes = datetime.now(TIMEZONE_BR).strftime("%Y-%m")
    registros = database.obter_registros_mes(user_id, ano_mes)

    if not registros:
        await update.message.reply_text(f"Nenhum registro de SA encontrado para o mês {ano_mes}.")
        return

    texto = reports.formatar_relatorio_texto(registros, titulo=f"Consolidado Mensal ({datetime.now(TIMEZONE_BR).strftime('%m/%Y')})")
    await update.message.reply_text(texto, parse_mode=ParseMode.MARKDOWN)

    nome_arquivo = f"Horas_{ano_mes}_{user_id}.xlsx"
    reports.gerar_planilha_excel(registros, nome_arquivo)

    with open(nome_arquivo, "rb") as doc:
        await update.message.reply_document(
            document=doc,
            filename=nome_arquivo,
            caption=f"📁 Planilha consolidada de {datetime.now(TIMEZONE_BR).strftime('%m/%Y')} para facilitar o preenchimento no sistema oficial."
        )

    try:
        os.remove(nome_arquivo)
    except Exception:
        pass

async def desfazer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Desfaz o último registro de SA do usuário."""
    user_id = update.effective_user.id
    if not eh_usuario_autorizado(user_id):
        return

    ultimo = database.obter_ultimo_registro(user_id)
    if not ultimo:
        await update.message.reply_text("Nenhum registro para desfazer.")
        return

    database.deletar_registro(ultimo["id"], user_id)
    await update.message.reply_text(
        f"🗑️ *Registro removido:*\n"
        f"• SA: `{ultimo['sa_id']}`\n"
        f"• Horas: `{ultimo['horas']}h`\n"
        f"• Descrição: {ultimo['descricao']}",
        parse_mode=ParseMode.MARKDOWN
    )

async def callback_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trata cliques nos botões de confirmação/desfazer e toggle de alarmes."""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = update.effective_user.id

    if data.startswith("desfazer_"):
        reg_id = int(data.split("_")[1])
        sucesso = database.deletar_registro(reg_id, user_id)
        if sucesso:
            await query.edit_message_text(f"❌ *Registro #{reg_id} desfeito e removido com sucesso.*", parse_mode=ParseMode.MARKDOWN)
        else:
            await query.edit_message_text("Não foi possível remover o registro (já havia sido deletado).")
    elif data.startswith("desfazernota_"):
        nota_id = int(data.split("_")[1])
        sucesso = database.deletar_nota(nota_id, user_id)
        if sucesso:
            await query.edit_message_text(f"❌ *Nota #{nota_id} removida do bloco de notas.*", parse_mode=ParseMode.MARKDOWN)
        else:
            await query.edit_message_text("Não foi possível remover a anotação.")
    elif data == "alarmes_on":
        database.alternar_alarmes(user_id, True)
        await query.edit_message_text("🔔 *Alarmes automáticos de ponto ativados!*", parse_mode=ParseMode.MARKDOWN)
    elif data == "alarmes_off":
        database.alternar_alarmes(user_id, False)
        await query.edit_message_text("🔕 *Alarmes automáticos de ponto pausados!*", parse_mode=ParseMode.MARKDOWN)

async def processar_mensagem_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe mensagens de texto livre e aciona o Gemini com memória de apelidos e bloco de notas."""
    user_id = update.effective_user.id
    if not eh_usuario_autorizado(user_id):
        return

    database.registrar_usuario_ativo(user_id)
    texto_usuario = update.message.text
    status_msg = await update.message.reply_text("⏳ _Processando com IA..._", parse_mode=ParseMode.MARKDOWN)

    try:
        apelidos_existentes = database.obter_apelidos(user_id)
        data_ref = datetime.now(TIMEZONE_BR).strftime("%Y-%m-%d")
        resultado = ai_extractor.processar_texto(
            texto=texto_usuario, 
            data_referencia=data_ref,
            apelidos_existentes=apelidos_existentes
        )
        await status_msg.delete()

        # 1. Se identificou novos apelidos na mensagem
        if resultado.novos_apelidos:
            for item in resultado.novos_apelidos:
                database.salvar_apelido(user_id, item.apelido, item.sa)
                await update.message.reply_text(
                    f"🧠 *Novo apelido aprendido!*\n"
                    f"Associei `{item.apelido}` ➡️ *SA {item.sa}*. Pode usar esse nome nas próximas mensagens!",
                    parse_mode=ParseMode.MARKDOWN
                )

        # 2. Se houver dúvidas específicas
        if resultado.duvidas_sa:
            for duvida in resultado.duvidas_sa:
                await update.message.reply_text(f"❓ *Dúvida sobre a SA:*\n{duvida}", parse_mode=ParseMode.MARKDOWN)

        # 3. Registra os lançamentos de SAs
        for item in resultado.registros:
            data_reg = item.data or data_ref
            reg_id = database.inserir_registro(
                telegram_user_id=user_id,
                data=data_reg,
                sa_id=item.sa,
                horas=item.horas,
                descricao=item.descricao,
                raw_message=texto_usuario
            )

            keyboard = [[InlineKeyboardButton("🗑️ Desfazer", callback_data=f"desfazer_{reg_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            msg_confirmacao = (
                f"✅ *Lançamento Registrado na SA!*\n\n"
                f"📅 *Data:* `{data_reg}`\n"
                f"📌 *SA:* `{item.sa}`\n"
                f"⏱️ *Horas:* `{item.horas}h`\n"
                f"📝 *Descrição:* {item.descricao}"
            )
            await update.message.reply_text(msg_confirmacao, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        # 4. Modo Bloco de Notas: Registra tarefas sem SA
        if resultado.notas_gerais:
            hora_atual = datetime.now(TIMEZONE_BR).strftime("%H:%M")
            for nota in resultado.notas_gerais:
                nota_id = database.inserir_nota(user_id, data_ref, nota, hora_atual)
                keyboard = [[InlineKeyboardButton("🗑️ Remover Nota", callback_data=f"desfazernota_{nota_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                msg_nota = (
                    f"📝 *Bloco de Notas (Sem SA)*\n\n"
                    f"⏰ *Horário:* `{hora_atual}`\n"
                    f"📌 *Anotação:* {nota}\n\n"
                    f"_(Ficou salvo no seu rastro de hoje! Você pode consultar com `/hoje` ou `/notas`)_"
                )
                await update.message.reply_text(msg_nota, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        if resultado.observacoes:
            await update.message.reply_text(f"ℹ️ *Nota:* {resultado.observacoes}", parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Erro ao processar mensagem de texto: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Ocorreu um erro ao processar: {str(e)}")

async def processar_mensagem_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe mensagens de voz/áudio, baixa e aciona o Gemini multimodal com bloco de notas."""
    user_id = update.effective_user.id
    if not eh_usuario_autorizado(user_id):
        return

    database.registrar_usuario_ativo(user_id)
    voice = update.message.voice or update.message.audio
    if not voice:
        return

    status_msg = await update.message.reply_text("🎙️ _Baixando áudio e interpretando com IA..._", parse_mode=ParseMode.MARKDOWN)

    temp_audio_path = f"temp_voice_{user_id}_{voice.file_id}.ogg"
    try:
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(temp_audio_path)

        apelidos_existentes = database.obter_apelidos(user_id)
        data_ref = datetime.now(TIMEZONE_BR).strftime("%Y-%m-%d")
        resultado = ai_extractor.processar_audio(
            caminho_arquivo_audio=temp_audio_path,
            data_referencia=data_ref,
            apelidos_existentes=apelidos_existentes
        )
        await status_msg.delete()

        # 1. Novos apelidos
        if resultado.novos_apelidos:
            for item in resultado.novos_apelidos:
                database.salvar_apelido(user_id, item.apelido, item.sa)
                await update.message.reply_text(
                    f"🧠 *Novo apelido aprendido!*\n"
                    f"Associei `{item.apelido}` ➡️ *SA {item.sa}*. Pode usar esse nome nas próximas mensagens!",
                    parse_mode=ParseMode.MARKDOWN
                )

        # 2. Dúvidas
        if resultado.duvidas_sa:
            for duvida in resultado.duvidas_sa:
                await update.message.reply_text(f"❓ *Dúvida sobre a SA:*\n{duvida}", parse_mode=ParseMode.MARKDOWN)

        # 3. Lançamentos de SAs
        for item in resultado.registros:
            data_reg = item.data or data_ref
            reg_id = database.inserir_registro(
                telegram_user_id=user_id,
                data=data_reg,
                sa_id=item.sa,
                horas=item.horas,
                descricao=item.descricao,
                raw_message="[Mensagem de Áudio]"
            )

            keyboard = [[InlineKeyboardButton("🗑️ Desfazer", callback_data=f"desfazer_{reg_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            msg_confirmacao = (
                f"✅ *Lançamento Registrado na SA (via Áudio)!*\n\n"
                f"📅 *Data:* `{data_reg}`\n"
                f"📌 *SA:* `{item.sa}`\n"
                f"⏱️ *Horas:* `{item.horas}h`\n"
                f"📝 *Descrição:* {item.descricao}"
            )
            await update.message.reply_text(msg_confirmacao, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        # 4. Modo Bloco de Notas: Registra tarefas sem SA
        if resultado.notas_gerais:
            hora_atual = datetime.now(TIMEZONE_BR).strftime("%H:%M")
            for nota in resultado.notas_gerais:
                nota_id = database.inserir_nota(user_id, data_ref, nota, hora_atual)
                keyboard = [[InlineKeyboardButton("🗑️ Remover Nota", callback_data=f"desfazernota_{nota_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                msg_nota = (
                    f"📝 *Bloco de Notas (via Áudio - Sem SA)*\n\n"
                    f"⏰ *Horário:* `{hora_atual}`\n"
                    f"📌 *Anotação:* {nota}\n\n"
                    f"_(Ficou salvo no seu rastro de hoje! Você pode consultar com `/hoje` ou `/notas`)_"
                )
                await update.message.reply_text(msg_nota, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        if resultado.observacoes:
            await update.message.reply_text(f"ℹ️ *Nota:* {resultado.observacoes}", parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Erro ao processar áudio: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Ocorreu um erro ao processar o áudio: {str(e)}")
    finally:
        if os.path.exists(temp_audio_path):
            try:
                os.remove(temp_audio_path)
            except Exception:
                pass

# ==========================================
# ROTINAS DE ALARMES AUTOMÁTICOS
# ==========================================
async def disparar_alarme(context: ContextTypes.DEFAULT_TYPE, mensagem: str, incluir_resumo_hoje: bool = False):
    """Envia uma notificação de alarme para todos os usuários cadastrados e ativos."""
    usuarios = database.obter_usuarios_para_alarme()
    hoje_str = datetime.now(TIMEZONE_BR).strftime("%Y-%m-%d")

    for user_id in usuarios:
        if not eh_usuario_autorizado(user_id):
            continue

        texto_final = mensagem
        if incluir_resumo_hoje:
            regs = database.obter_registros_dia(user_id, hoje_str)
            notas = database.obter_notas_dia(user_id, hoje_str)
            total_horas = sum(r["horas"] for r in regs)

            if regs:
                texto_final += f"\n\n📊 *Horas nas SAs hoje:* `{total_horas:.2f}h`\n"
                for r in regs:
                    texto_final += f"• SA `{r['sa_id']}`: {r['horas']}h ({r['descricao']})\n"
            else:
                texto_final += "\n\n⚠️ *Atenção:* Nenhuma hora apontada em SA hoje ainda!"

            if notas:
                texto_final += "\n📝 *Bloco de notas de hoje:*\n"
                for n in notas:
                    texto_final += f"• `[{n['hora']}]` {n['conteudo']}\n"

        try:
            await context.bot.send_message(chat_id=user_id, text=texto_final, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Falha ao enviar alarme para usuário {user_id}: {e}")

async def job_alarme_0800(context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "⏰ *08:00 - Bom dia!*\n\n"
        "🟢 Hora de **bater o ponto de entrada** no sistema oficial!\n"
        "Tenha um ótimo expediente. Ao longo do dia, mande áudio ou texto do que for produzindo."
    )
    await disparar_alarme(context, msg, incluir_resumo_hoje=False)

async def job_alarme_1200(context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🍽️ *12:00 - Pausa para o Almoço!*\n\n"
        "Se for sair para almoçar agora, lembre de **bater o ponto de saída**!\n\n"
        "💬 *O que você fez nesta manhã?*\n"
        "Mande um áudio ou texto rápido me contando a SA ou apenas as atividades que você executou até aqui."
    )
    await disparar_alarme(context, msg, incluir_resumo_hoje=True)

async def job_alarme_1230(context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🍲 *12:30 - Lembrete de Almoço!*\n\n"
        "Se você saiu às 12h, lembre que seu retorno é às 13h.\n"
        "Se está saindo agora (ou até 13h), lembre-se de registrar seu ponto de saída e me mandar um áudio com o que produziu na manhã!"
    )
    await disparar_alarme(context, msg, incluir_resumo_hoje=False)

async def job_alarme_1330(context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💻 *13:30 - Retorno do Almoço!*\n\n"
        "🟢 Hora de **bater o ponto de retorno** e retomar as atividades da tarde!"
    )
    await disparar_alarme(context, msg, incluir_resumo_hoje=False)

async def job_alarme_1700(context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🏁 *17:00 - Fim de Expediente!*\n\n"
        "🔴 Hora de **bater o ponto de saída** no sistema oficial!\n\n"
        "💬 *Fechamento do Dia:*\n"
        "O que você fez na parte da tarde? Me mande um áudio ou texto para fechar o rastro de hoje (com ou sem SA)."
    )
    await disparar_alarme(context, msg, incluir_resumo_hoje=True)

def configurar_alarmes(app: Application):
    """Configura a fila de agendamentos (JobQueue) de segunda a sexta."""
    jq = app.job_queue
    if jq is None:
        logger.warning("JobQueue não está disponível. Alarmes não foram agendados.")
        return

    dias_uteis = (0, 1, 2, 3, 4)

    # 08:00
    jq.run_daily(job_alarme_0800, time=time(8, 0, tzinfo=TIMEZONE_BR), days=dias_uteis, name="alarme_0800")
    # 12:00
    jq.run_daily(job_alarme_1200, time=time(12, 0, tzinfo=TIMEZONE_BR), days=dias_uteis, name="alarme_1200")
    # 12:30
    jq.run_daily(job_alarme_1230, time=time(12, 30, tzinfo=TIMEZONE_BR), days=dias_uteis, name="alarme_1230")
    # 13:30
    jq.run_daily(job_alarme_1330, time=time(13, 30, tzinfo=TIMEZONE_BR), days=dias_uteis, name="alarme_1330")
    # 17:00
    jq.run_daily(job_alarme_1700, time=time(17, 0, tzinfo=TIMEZONE_BR), days=dias_uteis, name="alarme_1700")
    logger.info("Alarmes de ponto agendados com sucesso para os horários 08:00, 12:00, 12:30, 13:30 e 17:00 (Seg-Sex).")

# ==========================================
# SERVIDOR WEB PARA HEALTH-CHECK NO RENDER
# ==========================================
web_app = FastAPI()

@web_app.get("/")
def health_check():
    return {"status": "ok", "bot": "online"}

def rodar_servidor_web():
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Iniciando servidor web na porta {port} para o Render...")
    uvicorn.run(web_app, host="0.0.0.0", port=port, log_level="warning")

def main():
    """Ponto de entrada do Bot."""
    database.init_db()

    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "seu_telegram_bot_token_aqui":
        print("\n❌ ERRO: O TELEGRAM_BOT_TOKEN não foi configurado!")
        print("Por favor, crie um arquivo .env na raiz do projeto contendo:")
        print("TELEGRAM_BOT_TOKEN=seu_token_do_botfather")
        print("GEMINI_API_KEY=sua_chave_do_google_ai_studio\n")
        return

    # Inicia o servidor web em uma thread separada para o Render e UptimeRobot
    thread_web = threading.Thread(target=rodar_servidor_web, daemon=True)
    thread_web.start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Handlers de comandos
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("hoje", hoje_command))
    app.add_handler(CommandHandler("dia", hoje_command))
    app.add_handler(CommandHandler("notas", notas_command))
    app.add_handler(CommandHandler("mes", mes_command))
    app.add_handler(CommandHandler("desfazer", desfazer_command))
    app.add_handler(CommandHandler("apelidos", apelidos_command))
    app.add_handler(CommandHandler("apelido", cadastrar_apelido_command))
    app.add_handler(CommandHandler("alarmes", alarmes_command))

    # Handler para botões inline
    app.add_handler(CallbackQueryHandler(callback_button_handler))

    # Handlers para mensagens de texto e áudio
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, processar_mensagem_texto))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, processar_mensagem_audio))

    # Inicia os alarmes de ponto no JobQueue
    configurar_alarmes(app)

    print("🤖 Bot iniciado com sucesso com suporte a Bloco de Notas e Alarmes! Pressione Ctrl+C para encerrar.")
    app.run_polling()

if __name__ == "__main__":
    main()

