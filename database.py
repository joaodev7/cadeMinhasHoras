import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_PATH = os.getenv("DB_PATH", "horas.db")

@contextmanager
def get_db(db_path: str = DB_PATH):
    """Gerenciador de contexto seguro para conexões SQLite com WAL e timeout."""
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db(db_path: str = DB_PATH):
    """Inicializa as tabelas necessárias no SQLite com pragmas de segurança e alta concorrência."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS registros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                data TEXT NOT NULL,          -- Formato YYYY-MM-DD
                sa_id TEXT NOT NULL,         -- Código/Identificador da SA
                horas REAL NOT NULL,         -- Duração em horas (ex: 1.5, 4.0)
                descricao TEXT NOT NULL,     -- Descrição da atividade
                raw_message TEXT,            -- Mensagem original que gerou o registro
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sa_apelidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                apelido TEXT NOT NULL,       -- Ex: 'refin', 'refinanciamento', 'portal'
                sa_id TEXT NOT NULL,         -- Ex: '96569'
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(telegram_user_id, apelido)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS configuracoes_usuario (
                telegram_user_id INTEGER PRIMARY KEY,
                alarmes_ativos INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notas_diarias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                data TEXT NOT NULL,          -- Formato YYYY-MM-DD
                conteudo TEXT NOT NULL,      -- Texto da anotação
                hora TEXT NOT NULL,          -- Formato HH:MM
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tarefas_pendentes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                descricao TEXT NOT NULL,
                status TEXT DEFAULT 'pendente', -- 'pendente' ou 'concluida'
                data_criacao TEXT NOT NULL,     -- Formato YYYY-MM-DD
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

def salvar_apelido(telegram_user_id: int, apelido: str, sa_id: str, db_path: str = DB_PATH):
    """Salva ou atualiza um apelido associado a uma SA."""
    apelido_limpo = apelido.strip().lower()
    sa_limpa = sa_id.strip()
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO sa_apelidos (telegram_user_id, apelido, sa_id)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_user_id, apelido) DO UPDATE SET sa_id = excluded.sa_id
        """, (telegram_user_id, apelido_limpo, sa_limpa))

def remover_apelido(telegram_user_id: int, apelido: str, db_path: str = DB_PATH) -> bool:
    """Remove um apelido específico."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM sa_apelidos WHERE telegram_user_id = ? AND apelido = ?
        """, (telegram_user_id, apelido.strip().lower()))
        return cursor.rowcount > 0

def obter_apelidos(telegram_user_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Retorna todos os apelidos cadastrados pelo usuário."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT apelido, sa_id FROM sa_apelidos
            WHERE telegram_user_id = ?
            ORDER BY sa_id ASC, apelido ASC
        """, (telegram_user_id,))
        return [dict(row) for row in cursor.fetchall()]

def inserir_registro(telegram_user_id: int, data: str, sa_id: str, horas: float, descricao: str, raw_message: str = "", db_path: str = DB_PATH) -> int:
    """Insere um novo apontamento de horas."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO registros (telegram_user_id, data, sa_id, horas, descricao, raw_message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (telegram_user_id, data, sa_id, horas, descricao, raw_message))
        return cursor.lastrowid

def deletar_registro(registro_id: int, telegram_user_id: int, db_path: str = DB_PATH) -> bool:
    """Deleta um registro (para função de desfazer)."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM registros WHERE id = ? AND telegram_user_id = ?
        """, (registro_id, telegram_user_id))
        return cursor.rowcount > 0

def obter_ultimo_registro(telegram_user_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Busca o último registro inserido pelo usuário."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM registros 
            WHERE telegram_user_id = ? 
            ORDER BY id DESC LIMIT 1
        """, (telegram_user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def obter_registros_dia(telegram_user_id: int, data_str: str, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Busca registros de uma data específica (YYYY-MM-DD)."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM registros 
            WHERE telegram_user_id = ? AND data = ?
            ORDER BY id ASC
        """, (telegram_user_id, data_str))
        return [dict(row) for row in cursor.fetchall()]

def obter_registros_mes(telegram_user_id: int, ano_mes: str, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Busca registros de um determinado mês (YYYY-MM)."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM registros 
            WHERE telegram_user_id = ? AND data LIKE ?
            ORDER BY data ASC, sa_id ASC
        """, (telegram_user_id, f"{ano_mes}%"))
        return [dict(row) for row in cursor.fetchall()]

# ==========================================
# BLOCO DE NOTAS DIÁRIO (SEM SA)
# ==========================================
def inserir_nota(telegram_user_id: int, data: str, conteudo: str, hora: str, db_path: str = DB_PATH) -> int:
    """Insere uma anotação de bloco de notas para o dia."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO notas_diarias (telegram_user_id, data, conteudo, hora)
            VALUES (?, ?, ?, ?)
        """, (telegram_user_id, data, conteudo, hora))
        return cursor.lastrowid

def deletar_nota(nota_id: int, telegram_user_id: int, db_path: str = DB_PATH) -> bool:
    """Deleta uma anotação do bloco de notas."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM notas_diarias WHERE id = ? AND telegram_user_id = ?
        """, (nota_id, telegram_user_id))
        return cursor.rowcount > 0

def obter_notas_dia(telegram_user_id: int, data_str: str, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Busca as anotações do bloco de notas de um dia específico."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM notas_diarias
            WHERE telegram_user_id = ? AND data = ?
            ORDER BY id ASC
        """, (telegram_user_id, data_str))
        return [dict(row) for row in cursor.fetchall()]

# ==========================================
# TAREFAS PENDENTES / TO-DOS
# ==========================================
def inserir_tarefa(telegram_user_id: int, descricao: str, data_criacao: str, db_path: str = DB_PATH) -> int:
    """Insere uma nova tarefa pendente."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO tarefas_pendentes (telegram_user_id, descricao, data_criacao, status)
            VALUES (?, ?, ?, 'pendente')
        """, (telegram_user_id, descricao, data_criacao))
        return cursor.lastrowid

def marcar_tarefa_concluida(tarefa_id: int, telegram_user_id: int, db_path: str = DB_PATH) -> bool:
    """Marca uma tarefa como concluída."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tarefas_pendentes SET status = 'concluida'
            WHERE id = ? AND telegram_user_id = ?
        """, (tarefa_id, telegram_user_id))
        return cursor.rowcount > 0

def obter_tarefas_pendentes(telegram_user_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Retorna todas as tarefas pendentes do usuário."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM tarefas_pendentes
            WHERE telegram_user_id = ? AND status = 'pendente'
            ORDER BY id ASC
        """, (telegram_user_id,))
        return [dict(row) for row in cursor.fetchall()]

# ==========================================
# BUSCA GERAL PARA O ASSISTENTE RESPONDER DÚVIDAS
# ==========================================
def buscar_historico_recente(telegram_user_id: int, limite_dias: int = 15, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Retorna os registros recentes de SAs, notas e apelidos para alimentar a memória do assistente."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT data, sa_id, horas, descricao FROM registros
            WHERE telegram_user_id = ?
            ORDER BY data DESC, id DESC
            LIMIT 40
        """, (telegram_user_id,))
        registros = [dict(r) for r in cursor.fetchall()]

        cursor.execute("""
            SELECT data, hora, conteudo FROM notas_diarias
            WHERE telegram_user_id = ?
            ORDER BY data DESC, id DESC
            LIMIT 30
        """, (telegram_user_id,))
        notas = [dict(r) for r in cursor.fetchall()]

        cursor.execute("""
            SELECT apelido, sa_id FROM sa_apelidos
            WHERE telegram_user_id = ?
        """, (telegram_user_id,))
        apelidos = [dict(r) for r in cursor.fetchall()]

        cursor.execute("""
            SELECT id, descricao, data_criacao, status FROM tarefas_pendentes
            WHERE telegram_user_id = ? AND status = 'pendente'
        """, (telegram_user_id,))
        tarefas = [dict(r) for r in cursor.fetchall()]

        return {
            "registros": registros,
            "notas": notas,
            "apelidos": apelidos,
            "tarefas_pendentes": tarefas
        }

# ==========================================
# CONFIGURAÇÕES DE USUÁRIO E ALARMES
# ==========================================
def registrar_usuario_ativo(telegram_user_id: int, db_path: str = DB_PATH):
    """Registra o usuário para recebimento de alarmes diários."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO configuracoes_usuario (telegram_user_id, alarmes_ativos)
            VALUES (?, 1)
            ON CONFLICT(telegram_user_id) DO NOTHING
        """, (telegram_user_id,))

def alternar_alarmes(telegram_user_id: int, ativo: bool, db_path: str = DB_PATH):
    """Ativa ou pausa os alarmes do usuário."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO configuracoes_usuario (telegram_user_id, alarmes_ativos)
            VALUES (?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET alarmes_ativos = excluded.alarmes_ativos
        """, (telegram_user_id, 1 if ativo else 0))

def obter_usuarios_para_alarme(db_path: str = DB_PATH) -> List[int]:
    """Retorna lista de IDs de usuários com alarmes ativos."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT telegram_user_id FROM configuracoes_usuario
            WHERE alarmes_ativos = 1
        """)
        return [row["telegram_user_id"] for row in cursor.fetchall()]
