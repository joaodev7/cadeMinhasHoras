import os
import logging
from datetime import datetime, time, timedelta
import zoneinfo
import threading
import uvicorn
from fastapi import FastAPI
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

from functools import wraps

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

def restrito_para_dono(func):
    """Decorator de segurança: bloqueia a execução caso o usuário não esteja autorizado."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or not eh_usuario_autorizado(user.id):
            logger.warning(f"Acesso negado para usuário não autorizado ID: {user.id if user else 'desconhecido'}")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

async def safe_reply_text(message_or_update, text: str, reply_markup=None):
    """Envia mensagem tentando Markdown primeiro; se a IA gerar entidades inválidas, reenvia em texto puro sem quebrar."""
    target = message_or_update.message if hasattr(message_or_update, "message") and message_or_update.message else message_or_update
    try:
        return await target.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"Falha ao renderizar Markdown ({e}). Reenviando em texto plano...")
        return await target.reply_text(text, reply_markup=reply_markup)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start de boas-vindas do CadêMinhasHoras."""
    user = update.effective_user
    if not user:
        return
    user_id = user.id

    # Segurança: só ativa alarmes se for o usuário autorizado (ou se ainda não foi configurado)
    if eh_usuario_autorizado(user_id):
        database.registrar_usuario_ativo(user_id)

    msg = (
        f"👋 Olá, *{user.first_name}*! Sou o *CadêMinhasHoras*, seu assistente pessoal de rotina e ponto.\n\n"
        f"🔑 *Seu ID no Telegram:* `{user_id}`\n\n"
        "✨ *O que eu faço por você:*\n"
        "• **Conversar & Tirar Dúvidas:** Me mande um áudio ou texto perguntando qualquer coisa geral ou sobre o trabalho (ex: _'Quando foi a última vez que mexi na SA do refin?'_ ou _'Como tá o tempo?'_).\n"
        "• **Lançar Horas em SAs:** _'Fiz 3h no refin ajustando layout'_ ➡️ Lanço na SA com memória de apelidos!\n"
        "• **Bloco de Notas Diário:** _'Participei da daily e ajudei no deploy'_ ➡️ Salvo no seu rastro de hoje.\n"
        "• **Capturar To-Dos automaticamente:** Se você disser _'preciso falar com fulano'_, eu crio uma pendência.\n"
        "• **Daily Meeting:** Use `/daily` para eu montar o que você deve falar na reunião matinal.\n\n"
        "📌 *Comandos Principais:*\n"
        "• `/daily` - Gera sua fala pronta para a Daily Meeting de hoje\n"
        "• `/tarefas` - Lista suas pendências com botões para concluir\n"
        "• `/hoje` ou `/dia ontem` - Resumo completo do dia (SAs + Notas)\n"
        "• `/escrever <ideia>` - Redige um e-mail ou mensagem corporativa formal\n"
        "• `/mes` - Relatório consolidado e planilha Excel\n"
        "• `/apelidos` - Lista apelidos das suas SAs\n"
        "• `/alarmes` - Ativar/pausar alarmes de ponto"
    )
    await safe_reply_text(update, msg)

@restrito_para_dono
async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gera o script para a reunião de Daily Meeting com base no dia útil anterior e pendências."""
    user_id = update.effective_user.id
    status_msg = await update.message.reply_text("☕ _Montando sua fala para a Daily de hoje..._", parse_mode=ParseMode.MARKDOWN)

    hoje = datetime.now(TIMEZONE_BR)
    # Se for segunda (weekday 0), busca de sexta-feira (3 dias atrás)
    if hoje.weekday() == 0:
        dia_ant = hoje - timedelta(days=3)
    else:
        dia_ant = hoje - timedelta(days=1)
    
    dia_ant_str = dia_ant.strftime("%Y-%m-%d")
    registros_ontem = database.obter_registros_dia(user_id, dia_ant_str)
    notas_ontem = database.obter_notas_dia(user_id, dia_ant_str)
    tarefas_pendentes = database.obter_tarefas_pendentes(user_id)

    texto_daily = ai_extractor.gerar_script_daily(
        dia_anterior_str=dia_ant.strftime("%d/%m/%Y"),
        registros_ontem=registros_ontem,
        notas_ontem=notas_ontem,
        tarefas_pendentes=tarefas_pendentes
    )
    await status_msg.delete()
    await safe_reply_text(update, texto_daily)

@restrito_para_dono
async def tarefas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista as tarefas e pendências em aberto com botões interativos."""
    user_id = update.effective_user.id
    tarefas = database.obter_tarefas_pendentes(user_id)
    if not tarefas:
        await safe_reply_text(update, "🎉 *Nenhuma pendência em aberto!* Você está com tudo em dia.")
        return

    linhas = ["📋 *Suas Tarefas e Pendências em Aberto:*\n"]
    keyboard = []
    for t in tarefas:
        linhas.append(f"• `[#{t['id']}]` {t['descricao']} _(Criada em {t['data_criacao']})_")
        keyboard.append([InlineKeyboardButton(f"✅ Concluir #{t['id']}", callback_data=f"concluirtarefa_{t['id']}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_reply_text(update, "\n".join(linhas), reply_markup=reply_markup)

@restrito_para_dono
async def escrever_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Redige uma mensagem corporativa polida a partir de um texto informal."""
    args = context.args
    if not args:
        await safe_reply_text(
            update,
            "ℹ️ *Como usar:* `/escrever <o que você quer comunicar>`\n\n"
            "_Exemplo:_ `/escrever pede pro devops aprovar meu PR da SA 96569 pra liberar o deploy da sprint`"
        )
        return

    intencao = " ".join(args)
    status_msg = await update.message.reply_text("✍️ _Redigindo mensagem corporativa..._", parse_mode=ParseMode.MARKDOWN)
    texto_redigido = ai_extractor.redigir_mensagem_corporativa(intencao)
    await status_msg.delete()
    await safe_reply_text(update, texto_redigido)

@restrito_para_dono
async def alarmes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Permite ligar ou desligar os alarmes automáticos."""
    user_id = update.effective_user.id
    args = context.args
    if args and args[0].lower() in ["off", "desligar", "pausar"]:
        database.alternar_alarmes(user_id, False)
        await safe_reply_text(update, "⏸️ *Alarmes automáticos de ponto pausados!*")
        return
    elif args and args[0].lower() in ["on", "ligar", "ativar"]:
        database.alternar_alarmes(user_id, True)
        await safe_reply_text(update, "▶️ *Alarmes automáticos ativados com sucesso!*")
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
        "• `08:00` - Início do expediente (Bater ponto + Briefing da Daily)\n"
        "• `12:00` - Saída para almoço + Lembrete de horas da manhã\n"
        "• `12:30` - Alarme de reforço/flexível de almoço\n"
        "• `13:30` - Retorno do almoço\n"
        "• `17:00` - Fim de expediente + Fechamento e Pendências\n\n"
        "Escolha abaixo ou use `/alarmes on` ou `/alarmes off`:"
    )
    await safe_reply_text(update, msg, reply_markup=reply_markup)

@restrito_para_dono
async def apelidos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista todos os apelidos e SAs cadastrados."""
    user_id = update.effective_user.id
    itens = database.obter_apelidos(user_id)
    if not itens:
        await safe_reply_text(
            update,
            "🧠 *Memória de Apelidos Vazia*\n\n"
            "Você pode cadastrar apelidos falando naturalmente (ex: _'A SA 96569 é o refin'_)\n"
            "ou pelo comando:\n`/apelido refin 96569`"
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
    await safe_reply_text(update, "\n".join(linhas))

@restrito_para_dono
async def cadastrar_apelido_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Permite cadastrar ou associar um apelido a uma SA: /apelido <termo> <numero_sa>"""
    user_id = update.effective_user.id
    args = context.args
    if not args or len(args) < 2:
        await safe_reply_text(
            update,
            "ℹ️ *Uso correto:*\n`/apelido <termo_ou_apelido> <numero_sa>`\n\n_Exemplo:_ `/apelido refin 96569`"
        )
        return

    apelido = " ".join(args[:-1]).strip().lower()
    sa_id = args[-1].strip()

    database.salvar_apelido(user_id, apelido, sa_id)
    await safe_reply_text(
        update,
        f"✅ *Apelido salvo com sucesso!*\n"
        f"Quando você falar `{apelido}`, saberei que é a *SA {sa_id}*."
    )

@restrito_para_dono
async def hoje_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe o resumo das atividades registradas hoje ou em uma data específica (SAs + Bloco de Notas)."""
    user_id = update.effective_user.id
    data_consulta = datetime.now(TIMEZONE_BR)
    titulo_data = data_consulta.strftime('%d/%m/%Y')
    hoje_str = data_consulta.strftime("%Y-%m-%d")

    args = context.args
    if args:
        param = args[0].lower().strip()
        if param == "ontem":
            data_consulta = data_consulta - timedelta(days=1)
            hoje_str = data_consulta.strftime("%Y-%m-%d")
            titulo_data = f"Ontem ({data_consulta.strftime('%d/%m/%Y')})"
        else:
            try:
                partes = param.split("/")
                if len(partes) == 2:
                    ano = data_consulta.year
                    d_parsed = datetime.strptime(f"{param}/{ano}", "%d/%m/%Y")
                else:
                    d_parsed = datetime.strptime(param, "%d/%m/%Y")
                hoje_str = d_parsed.strftime("%Y-%m-%d")
                titulo_data = d_parsed.strftime("%d/%m/%Y")
            except Exception:
                await safe_reply_text(update, "⚠️ Formato de data inválido! Use `/hoje`, `/hoje ontem` ou `/hoje DD/MM/AAAA`.")
                return

    registros = database.obter_registros_dia(user_id, hoje_str)
    notas = database.obter_notas_dia(user_id, hoje_str)

    texto = reports.formatar_relatorio_texto(
        registros=registros, 
        titulo=f"Rastro Diário ({titulo_data})",
        notas=notas
    )
    await safe_reply_text(update, texto)

@restrito_para_dono
async def notas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe apenas as anotações do bloco de notas do dia."""
    user_id = update.effective_user.id
    hoje_str = datetime.now(TIMEZONE_BR).strftime("%Y-%m-%d")
    notas = database.obter_notas_dia(user_id, hoje_str)
    texto = reports.formatar_notas_texto(notas, datetime.now(TIMEZONE_BR).strftime("%d/%m/%Y"))
    await safe_reply_text(update, texto)

@restrito_para_dono
async def mes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gera o relatório do mês e anexa o arquivo Excel."""
    user_id = update.effective_user.id
    ano_mes = datetime.now(TIMEZONE_BR).strftime("%Y-%m")
    registros = database.obter_registros_mes(user_id, ano_mes)

    if not registros:
        await safe_reply_text(update, f"Nenhum registro de SA encontrado para o mês {ano_mes}.")
        return

    texto = reports.formatar_relatorio_texto(registros, titulo=f"Consolidado Mensal ({datetime.now(TIMEZONE_BR).strftime('%m/%Y')})")
    await safe_reply_text(update, texto)

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

@restrito_para_dono
async def desfazer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Desfaz o último registro de SA do usuário."""
    user_id = update.effective_user.id
    ultimo = database.obter_ultimo_registro(user_id)
    if not ultimo:
        await safe_reply_text(update, "Nenhum registro para desfazer.")
        return

    database.deletar_registro(ultimo["id"], user_id)
    await safe_reply_text(
        update,
        f"🗑️ *Registro removido:*\n"
        f"• SA: `{ultimo['sa_id']}`\n"
        f"• Horas: `{ultimo['horas']}h`\n"
        f"• Descrição: {ultimo['descricao']}"
    )

@restrito_para_dono
async def callback_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trata cliques nos botões inline."""
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
    elif data.startswith("concluirtarefa_"):
        tarefa_id = int(data.split("_")[1])
        sucesso = database.marcar_tarefa_concluida(tarefa_id, user_id)
        if sucesso:
            await query.edit_message_text(f"✅ *Tarefa #{tarefa_id} marcada como concluída!*", parse_mode=ParseMode.MARKDOWN)
        else:
            await query.edit_message_text("Não foi possível marcar a tarefa.")
    elif data == "alarmes_on":
        database.alternar_alarmes(user_id, True)
        await query.edit_message_text("🔔 *Alarmes automáticos de ponto ativados!*", parse_mode=ParseMode.MARKDOWN)
    elif data == "alarmes_off":
        database.alternar_alarmes(user_id, False)
        await query.edit_message_text("🔕 *Alarmes automáticos de ponto pausados!*", parse_mode=ParseMode.MARKDOWN)

@restrito_para_dono
async def processar_mensagem_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe mensagens de texto e atua como assistente pessoal ou registrador de horas/tarefas."""
    user_id = update.effective_user.id
    database.registrar_usuario_ativo(user_id)
    texto_usuario = update.message.text
    status_msg = await update.message.reply_text("⏳ _Pensando..._", parse_mode=ParseMode.MARKDOWN)

    try:
        apelidos_existentes = database.obter_apelidos(user_id)
        historico = database.buscar_historico_recente(user_id)
        data_ref = datetime.now(TIMEZONE_BR).strftime("%Y-%m-%d")

        resultado = ai_extractor.processar_texto(
            texto=texto_usuario, 
            data_referencia=data_ref,
            apelidos_existentes=apelidos_existentes,
            historico_recente=historico
        )
        await status_msg.delete()

        # 1. Se for uma pergunta ou conversa direta
        if resultado.eh_pergunta_ou_conversa and resultado.resposta_conversacional:
            await safe_reply_text(update, resultado.resposta_conversacional)
            return

        # 2. Se identificou novos apelidos
        if resultado.novos_apelidos:
            for item in resultado.novos_apelidos:
                database.salvar_apelido(user_id, item.apelido, item.sa)
                await safe_reply_text(
                    update,
                    f"🧠 *Novo apelido aprendido!*\nAssociei `{item.apelido}` ➡️ *SA {item.sa}*."
                )

        # 3. Se houver dúvidas específicas de SA
        if resultado.duvidas_sa:
            for duvida in resultado.duvidas_sa:
                await safe_reply_text(update, f"❓ *Dúvida sobre a SA:*\n{duvida}")

        # 4. Registros de SAs
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
            await safe_reply_text(update, msg_confirmacao, reply_markup=reply_markup)

        # 5. Modo Bloco de Notas: Tarefas sem SA
        if resultado.notas_gerais:
            hora_atual = datetime.now(TIMEZONE_BR).strftime("%H:%M")
            for nota in resultado.notas_gerais:
                nota_id = database.inserir_nota(user_id, data_ref, nota, hora_atual)
                keyboard = [[InlineKeyboardButton("🗑️ Remover Nota", callback_data=f"desfazernota_{nota_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                msg_nota = (
                    f"📝 *Bloco de Notas*\n\n"
                    f"⏰ *Horário:* `{hora_atual}`\n"
                    f"📌 *Anotação:* {nota}"
                )
                await safe_reply_text(update, msg_nota, reply_markup=reply_markup)

        # 6. Captura de Pendências / To-Dos futuros
        if resultado.pendencias_futuras:
            for p in resultado.pendencias_futuras:
                tarefa_id = database.inserir_tarefa(user_id, p, data_ref)
                keyboard = [[InlineKeyboardButton("✅ Concluir", callback_data=f"concluirtarefa_{tarefa_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await safe_reply_text(
                    update,
                    f"📌 *Nova Pendência Anotada:*\n{p}\n\n_(Use `/tarefas` para acompanhar)_",
                    reply_markup=reply_markup
                )

        if resultado.observacoes:
            await safe_reply_text(update, f"ℹ️ *Nota:* {resultado.observacoes}")

    except Exception as e:
        logger.error(f"Erro ao processar mensagem de texto: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Ocorreu um erro ao processar: {str(e)}")

@restrito_para_dono
async def processar_mensagem_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe mensagens de áudio e atua como assistente pessoal ou registrador."""
    user_id = update.effective_user.id
    database.registrar_usuario_ativo(user_id)
    voice = update.message.voice or update.message.audio
    if not voice:
        return

    status_msg = await update.message.reply_text("🎙️ _Ouvindo e pensando..._", parse_mode=ParseMode.MARKDOWN)

    temp_audio_path = f"temp_voice_{user_id}_{voice.file_id}.ogg"
    try:
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(temp_audio_path)

        apelidos_existentes = database.obter_apelidos(user_id)
        historico = database.buscar_historico_recente(user_id)
        data_ref = datetime.now(TIMEZONE_BR).strftime("%Y-%m-%d")

        resultado = ai_extractor.processar_audio(
            caminho_arquivo_audio=temp_audio_path,
            data_referencia=data_ref,
            apelidos_existentes=apelidos_existentes,
            historico_recente=historico
        )
        await status_msg.delete()

        # 1. Pergunta ou conversa respondida
        if resultado.eh_pergunta_ou_conversa and resultado.resposta_conversacional:
            await safe_reply_text(update, resultado.resposta_conversacional)
            return

        # 2. Novos apelidos
        if resultado.novos_apelidos:
            for item in resultado.novos_apelidos:
                database.salvar_apelido(user_id, item.apelido, item.sa)
                await safe_reply_text(
                    update,
                    f"🧠 *Novo apelido aprendido!*\nAssociei `{item.apelido}` ➡️ *SA {item.sa}*."
                )

        # 3. Dúvidas
        if resultado.duvidas_sa:
            for duvida in resultado.duvidas_sa:
                await safe_reply_text(update, f"❓ *Dúvida sobre a SA:*\n{duvida}")

        # 4. Lançamentos de SAs
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
            await safe_reply_text(update, msg_confirmacao, reply_markup=reply_markup)

        # 5. Modo Bloco de Notas: Tarefas sem SA
        if resultado.notas_gerais:
            hora_atual = datetime.now(TIMEZONE_BR).strftime("%H:%M")
            for nota in resultado.notas_gerais:
                nota_id = database.inserir_nota(user_id, data_ref, nota, hora_atual)
                keyboard = [[InlineKeyboardButton("🗑️ Remover Nota", callback_data=f"desfazernota_{nota_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                msg_nota = (
                    f"📝 *Bloco de Notas (via Áudio)*\n\n"
                    f"⏰ *Horário:* `{hora_atual}`\n"
                    f"📌 *Anotação:* {nota}"
                )
                await safe_reply_text(update, msg_nota, reply_markup=reply_markup)

        # 6. Pendências capturadas no áudio
        if resultado.pendencias_futuras:
            for p in resultado.pendencias_futuras:
                tarefa_id = database.inserir_tarefa(user_id, p, data_ref)
                keyboard = [[InlineKeyboardButton("✅ Concluir", callback_data=f"concluirtarefa_{tarefa_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await safe_reply_text(
                    update,
                    f"📌 *Nova Pendência Anotada (via Áudio):*\n{p}\n\n_(Use `/tarefas` para acompanhar)_",
                    reply_markup=reply_markup
                )

        if resultado.observacoes:
            await safe_reply_text(update, f"ℹ️ *Nota:* {resultado.observacoes}")

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
async def disparar_alarme(context: ContextTypes.DEFAULT_TYPE, mensagem: str, incluir_resumo_hoje: bool = False, incluir_pendencias: bool = False):
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

        if incluir_pendencias:
            pendencias = database.obter_tarefas_pendentes(user_id)
            if pendencias:
                texto_final += f"\n\n📋 *Você tem {len(pendencias)} pendência(s) em aberto:* (use `/tarefas` para ver)"

        try:
            await context.bot.send_message(chat_id=user_id, text=texto_final, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Falha ao enviar alarme para usuário {user_id}: {e}")

async def job_alarme_0800(context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "⏰ *08:00 - Bom dia!*\n\n"
        "🟢 Hora de **bater o ponto de entrada** no sistema oficial!\n\n"
        "💡 *Dica:* Digite `/daily` para ver sua sugestão de fala para a reunião diária de hoje!"
    )
    await disparar_alarme(context, msg, incluir_resumo_hoje=False, incluir_pendencias=True)

async def job_alarme_1200(context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🍽️ *12:00 - Pausa para o Almoço!*\n\n"
        "Se for sair para almoçar agora, lembre de **bater o ponto de saída**!\n\n"
        "💬 *O que você fez nesta manhã?*\n"
        "Mande um áudio rápido contando a SA ou o que você executou até aqui."
    )
    await disparar_alarme(context, msg, incluir_resumo_hoje=True)

async def job_alarme_1230(context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🍲 *12:30 - Lembrete de Almoço!*\n\n"
        "Se você saiu às 12h, seu retorno é às 13h.\n"
        "Se está saindo agora (ou até 13h), lembre-se de registrar o ponto e me mandar um áudio com o que produziu na manhã!"
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
        "Me mande um áudio ou texto para fechar o rastro de hoje (com ou sem SA)."
    )
    await disparar_alarme(context, msg, incluir_resumo_hoje=True, incluir_pendencias=True)

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
    return {"status": "ok", "bot": "CadêMinhasHoras Online"}

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

    thread_web = threading.Thread(target=rodar_servidor_web, daemon=True)
    thread_web.start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Handlers de comandos
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler("tarefas", tarefas_command))
    app.add_handler(CommandHandler("todo", tarefas_command))
    app.add_handler(CommandHandler("escrever", escrever_command))
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

    print("🤖 CadêMinhasHoras iniciado com sucesso! Pressione Ctrl+C para encerrar.")
    app.run_polling()

if __name__ == "__main__":
    main()
