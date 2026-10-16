import os
import pytest
import sqlite3
from database import (
    init_db,
    get_db,
    inserir_registro,
    obter_registros_dia,
    obter_registros_mes,
    obter_ultimo_registro,
    deletar_registro,
    salvar_apelido,
    obter_apelidos,
    remover_apelido,
    inserir_nota,
    obter_notas_dia,
    deletar_nota,
    inserir_tarefa,
    obter_tarefas_pendentes,
    marcar_tarefa_concluida,
    registrar_usuario_ativo,
    alternar_alarmes,
    obter_usuarios_para_alarme,
    buscar_historico_recente
)

@pytest.fixture
def temp_db(tmp_path):
    """Fixture que fornece um banco de dados SQLite isolado por teste."""
    db_file = str(tmp_path / "test_horas.db")
    init_db(db_file)
    return db_file

def test_init_db_and_pragmas(temp_db):
    """Valida se as tabelas foram criadas e os pragmas de WAL estão operacionais."""
    with get_db(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        journal_mode = cursor.fetchone()[0]
        assert journal_mode.lower() == "wal"

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        expected = {"registros", "sa_apelidos", "configuracoes_usuario", "notas_diarias", "tarefas_pendentes"}
        assert expected.issubset(tables)

def test_transacao_rollback_on_error(temp_db):
    """Garante que exceções disparam rollback seguro sem corromper o banco."""
    with pytest.raises(ValueError):
        with get_db(temp_db) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO configuracoes_usuario (telegram_user_id, alarmes_ativos) VALUES (?, ?)", (999, 1))
            raise ValueError("Erro intencional para forçar rollback")

    with get_db(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM configuracoes_usuario WHERE telegram_user_id = 999")
        assert cursor.fetchone() is None

def test_registros_fluxo_completo(temp_db):
    """Testa criação, consulta por dia, por mês, último registro e remoção."""
    user_id = 123456
    reg1_id = inserir_registro(user_id, "2026-10-16", "96569", 2.5, "Desenvolvimento de feature", db_path=temp_db)
    reg2_id = inserir_registro(user_id, "2026-10-16", "99888", 1.0, "Code review", db_path=temp_db)
    reg3_id = inserir_registro(user_id, "2026-10-15", "96569", 3.0, "Refatoração", db_path=temp_db)

    # Consulta do dia
    dia_regs = obter_registros_dia(user_id, "2026-10-16", db_path=temp_db)
    assert len(dia_regs) == 2
    assert dia_regs[0]["sa_id"] == "96569"
    assert dia_regs[1]["sa_id"] == "99888"

    # Consulta do mês
    mes_regs = obter_registros_mes(user_id, "2026-10", db_path=temp_db)
    assert len(mes_regs) == 3

    # Último registro inserido (maior ID)
    ultimo = obter_ultimo_registro(user_id, db_path=temp_db)
    assert ultimo is not None
    assert ultimo["id"] == reg3_id

    # Deletar registro
    sucesso = deletar_registro(reg3_id, user_id, db_path=temp_db)
    assert sucesso is True
    assert len(obter_registros_mes(user_id, "2026-10", db_path=temp_db)) == 2

def test_apelidos_crud_e_conflito(temp_db):
    """Testa associação de apelidos, listagem, atualização ON CONFLICT e deleção."""
    user_id = 123456
    salvar_apelido(user_id, "refin", "96569", db_path=temp_db)
    salvar_apelido(user_id, "portal", "11223", db_path=temp_db)

    # Atualização pelo mesmo apelido deve sobrescrever a SA
    salvar_apelido(user_id, "refin", "99999", db_path=temp_db)

    apelidos = obter_apelidos(user_id, db_path=temp_db)
    assert len(apelidos) == 2
    mapa = {a["apelido"]: a["sa_id"] for a in apelidos}
    assert mapa["refin"] == "99999"
    assert mapa["portal"] == "11223"

    # Remover apelido
    removido = remover_apelido(user_id, "portal", db_path=temp_db)
    assert removido is True
    assert len(obter_apelidos(user_id, db_path=temp_db)) == 1

def test_notas_diarias(temp_db):
    """Testa criação, listagem e remoção de anotações diárias."""
    user_id = 123456
    nota_id = inserir_nota(user_id, "2026-10-16", "Reunião de alinhamento com PO", "10:30", db_path=temp_db)
    
    notas = obter_notas_dia(user_id, "2026-10-16", db_path=temp_db)
    assert len(notas) == 1
    assert notas[0]["conteudo"] == "Reunião de alinhamento com PO"
    assert notas[0]["hora"] == "10:30"

    sucesso = deletar_nota(nota_id, user_id, db_path=temp_db)
    assert sucesso is True
    assert len(obter_notas_dia(user_id, "2026-10-16", db_path=temp_db)) == 0

def test_tarefas_pendentes(temp_db):
    """Testa inserção de pendências e marcação como concluída."""
    user_id = 123456
    t1_id = inserir_tarefa(user_id, "Enviar email de fechamento", "2026-10-16", db_path=temp_db)
    t2_id = inserir_tarefa(user_id, "Avisar o time sobre deploy", "2026-10-16", db_path=temp_db)

    pendentes = obter_tarefas_pendentes(user_id, db_path=temp_db)
    assert len(pendentes) == 2

    # Concluir t1
    sucesso = marcar_tarefa_concluida(t1_id, user_id, db_path=temp_db)
    assert sucesso is True

    pendentes_restantes = obter_tarefas_pendentes(user_id, db_path=temp_db)
    assert len(pendentes_restantes) == 1
    assert pendentes_restantes[0]["id"] == t2_id

def test_configuracoes_usuario_e_alarmes(temp_db):
    """Testa registro de usuário ativo e alternância de alarmes."""
    user_id = 777
    registrar_usuario_ativo(user_id, db_path=temp_db)
    
    usuarios_alarme = obter_usuarios_para_alarme(db_path=temp_db)
    assert user_id in usuarios_alarme

    # Pausar alarmes
    alternar_alarmes(user_id, False, db_path=temp_db)
    assert user_id not in obter_usuarios_para_alarme(db_path=temp_db)

    # Reativar alarmes
    alternar_alarmes(user_id, True, db_path=temp_db)
    assert user_id in obter_usuarios_para_alarme(db_path=temp_db)

def test_buscar_historico_recente(temp_db):
    """Testa consolidação da memória do assistente."""
    user_id = 123456
    inserir_registro(user_id, "2026-10-16", "96569", 2.0, "Ajustes de layout", db_path=temp_db)
    inserir_nota(user_id, "2026-10-16", "Ajudou colega com bug", "14:00", db_path=temp_db)
    salvar_apelido(user_id, "refin", "96569", db_path=temp_db)
    inserir_tarefa(user_id, "Revisar PR #42", "2026-10-16", db_path=temp_db)

    historico = buscar_historico_recente(user_id, db_path=temp_db)
    assert len(historico["registros"]) == 1
    assert len(historico["notas"]) == 1
    assert len(historico["apelidos"]) == 1
    assert len(historico["tarefas_pendentes"]) == 1
