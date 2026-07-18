"""Camada de persistência SQLite do Orbita HRM. Stdlib apenas, sem dependências externas."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "orbita_hrm.db"
SECRET_KEY_PATH = ROOT / ".secret_key"

DEFAULT_VACATION_BALANCE = 30
DEFAULT_SCHEDULE = "08:00 – 17:00 (seg. a sex.)"

SEED_USERS = [
    {"id": "usr-001", "email": "admin@orbita.com", "name": "André David", "role": "Admin", "jobTitle": "Administrador de Sistemas", "department": "Administração", "cpf": "123.456.789-09", "workCard": "CTPS 0012345 / Série 0001", "address": "Av. Paulista, 1000, Bela Vista, São Paulo - SP", "enrollment": "MAT-000001", "motherName": "Cláudia David", "managerId": None, "salary": 18000, "birthDate": "1985-03-12", "admissionDate": "2021-02-01"},
    {"id": "usr-002", "email": "manager@orbita.com", "name": "Mariana Costa", "role": "Manager", "jobTitle": "Gerente de Pessoas & Cultura", "department": "Pessoas & Cultura", "cpf": "987.654.321-00", "workCard": "CTPS 0034521 / Série 0001", "address": "Rua das Flores, 88, Pinheiros, São Paulo - SP", "enrollment": "MAT-000002", "motherName": "Lúcia Costa", "managerId": None, "salary": 11500, "birthDate": "1990-07-22", "admissionDate": "2022-05-16"},
    {"id": "usr-003", "email": "cfo@orbita.com", "name": "Camila Rocha", "role": "CFO", "jobTitle": "Diretora Financeira", "department": "Financeiro", "cpf": "456.789.123-00", "workCard": "CTPS 0088954 / Série 0002", "address": "Rua Oscar Freire, 620, Jardins, São Paulo - SP", "enrollment": "MAT-000003", "motherName": "Regina Rocha", "managerId": None, "salary": 22000, "birthDate": "1982-11-30", "admissionDate": "2020-09-01"},
    {"id": "usr-004", "email": "employee@orbita.com", "name": "Lucas Mendes", "role": "Funcionário", "jobTitle": "Engenheiro de Software", "department": "Tecnologia", "cpf": "321.654.987-00", "workCard": "CTPS 0067892 / Série 0001", "address": "Rua Harmonia, 120, Vila Madalena, São Paulo - SP", "enrollment": "MAT-000004", "motherName": "Sônia Mendes", "managerId": "usr-002", "salary": 7800, "birthDate": "1996-07-05", "admissionDate": "2023-01-10"},
    {"id": "usr-005", "email": "treasury@orbita.com", "name": "Beatriz Nunes", "role": "Tesouraria", "jobTitle": "Analista de Tesouraria", "department": "Tesouraria", "cpf": "741.852.963-00", "workCard": "CTPS 0091123 / Série 0001", "address": "Rua Vergueiro, 440, São Paulo - SP", "enrollment": "MAT-000005", "motherName": "Elisa Nunes", "managerId": None, "salary": 9800, "birthDate": "1993-01-18", "admissionDate": "2022-11-07"},
    {"id": "usr-006", "email": "rh@orbita.com", "name": "Renata Alves", "role": "RH", "jobTitle": "Analista de RH", "department": "Pessoas & Cultura", "cpf": "852.963.741-00", "workCard": "CTPS 0075310 / Série 0001", "address": "Rua Augusta, 900, Consolação, São Paulo - SP", "enrollment": "MAT-000006", "motherName": "Iara Alves", "managerId": None, "salary": 9200, "birthDate": "1988-07-29", "admissionDate": "2021-08-23"},
]
SEED_PASSWORD = "123456"

SEED_DOCUMENTS = [
    {"id": "doc-001", "userId": "usr-002", "name": "Contrato de trabalho.pdf", "category": "Contrato", "version": "1.0", "updatedAt": "2026-06-02", "access": "RH e Admin"},
    {"id": "doc-002", "userId": "usr-002", "name": "Termo de confidencialidade.pdf", "category": "Termo", "version": "1.1", "updatedAt": "2026-06-02", "access": "RH, Admin e Gestor"},
    {"id": "doc-003", "userId": "usr-004", "name": "Certificado AWS.pdf", "category": "Certificado", "version": "1.0", "updatedAt": "2026-05-11", "access": "RH e Admin"},
]
REQUIRED_DOCUMENTS = ["Contrato de trabalho", "Documento de identificação", "CPF", "Carteira de trabalho", "Termo de confidencialidade"]

SEED_NOTIFICATIONS = [
    {"id": "ntf-001", "title": "Competência de julho disponível", "text": "A folha está pronta para programação pela Tesouraria.", "read": False},
    {"id": "ntf-002", "title": "Documentos pendentes", "text": "Há documentos obrigatórios para revisão.", "read": False},
]

SEED_BENEFITS = [
    {"id": "ben-001", "employeeId": "usr-004", "name": "Vale-refeição", "value": 800},
    {"id": "ben-002", "employeeId": "usr-004", "name": "Plano de saúde", "value": 450},
    {"id": "ben-003", "employeeId": "usr-002", "name": "Vale-refeição", "value": 800},
    {"id": "ben-003b", "employeeId": "usr-002", "name": "Plano de saúde", "value": 450},
]

PASSWORD_ITERATIONS = 200_000


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return digest.hex(), salt.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    digest, _ = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(digest, hash_hex)


def load_or_create_secret() -> bytes:
    env_secret = os.environ.get("ORBITA_HRM_SECRET")
    if env_secret:
        return env_secret.encode()
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_bytes()
    generated = secrets.token_hex(32).encode()
    SECRET_KEY_PATH.write_bytes(generated)
    return generated


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path | None = None) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            job_title TEXT,
            department TEXT NOT NULL,
            cpf TEXT NOT NULL,
            work_card TEXT NOT NULL,
            address TEXT NOT NULL,
            enrollment TEXT NOT NULL,
            mother_name TEXT NOT NULL,
            manager_id TEXT,
            salary REAL NOT NULL DEFAULT 0,
            birth_date TEXT,
            admission_date TEXT,
            status TEXT NOT NULL DEFAULT 'Ativo',
            photo TEXT,
            schedule TEXT,
            vacation_balance INTEGER NOT NULL DEFAULT 30
        );
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            version TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            access TEXT NOT NULL,
            file_data TEXT,
            file_type TEXT,
            signed INTEGER NOT NULL DEFAULT 0,
            signed_by TEXT,
            signed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS point_events (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            type TEXT NOT NULL,
            at TEXT NOT NULL,
            date TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS salary_requests (
            id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL REFERENCES users(id),
            employee_name TEXT NOT NULL,
            old_salary REAL NOT NULL,
            new_salary REAL NOT NULL,
            reason TEXT NOT NULL,
            effective_date TEXT NOT NULL,
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            requester TEXT NOT NULL,
            manager_approved_by TEXT,
            cfo_approved_by TEXT
        );
        CREATE TABLE IF NOT EXISTS requests (
            id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL REFERENCES users(id),
            employee_name TEXT NOT NULL,
            type TEXT NOT NULL,
            detail TEXT NOT NULL,
            days INTEGER,
            status TEXT NOT NULL,
            decided_by TEXT,
            decision_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS payroll_schedule (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            competence TEXT NOT NULL,
            scheduled_at TEXT,
            scheduled_by TEXT,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS payroll_history (
            id TEXT PRIMARY KEY,
            competence TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            scheduled_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            user_id TEXT REFERENCES users(id),
            title TEXT NOT NULL,
            text TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS benefits (
            id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            value REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id TEXT,
            actor_name TEXT NOT NULL,
            action TEXT NOT NULL,
            detail TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    return conn


def seed_if_empty(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        return
    for user in SEED_USERS:
        password_hash, password_salt = hash_password(SEED_PASSWORD)
        conn.execute(
            "INSERT INTO users (id, email, password_hash, password_salt, name, role, job_title, department, cpf, work_card, address, enrollment, mother_name, manager_id, salary, birth_date, admission_date, status, schedule, vacation_balance) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user["id"], user["email"], password_hash, password_salt, user["name"], user["role"], user["jobTitle"], user["department"], user["cpf"], user["workCard"], user["address"], user["enrollment"], user["motherName"], user["managerId"], user["salary"], user["birthDate"], user["admissionDate"], "Ativo", DEFAULT_SCHEDULE, DEFAULT_VACATION_BALANCE),
        )
    for document in SEED_DOCUMENTS:
        conn.execute(
            "INSERT INTO documents (id, user_id, name, category, version, updated_at, access) VALUES (?,?,?,?,?,?,?)",
            (document["id"], document["userId"], document["name"], document["category"], document["version"], document["updatedAt"], document["access"]),
        )
    conn.execute(
        "INSERT INTO payroll_schedule (id, competence, scheduled_at, scheduled_by, status) VALUES (1,?,?,?,?)",
        ("07/2026", None, None, "Não programado"),
    )
    for notification in SEED_NOTIFICATIONS:
        conn.execute(
            "INSERT INTO notifications (id, user_id, title, text, is_read, created_at) VALUES (?,NULL,?,?,?,?)",
            (notification["id"], notification["title"], notification["text"], int(notification["read"]), "2026-07-15T09:00:00"),
        )
    for benefit in SEED_BENEFITS:
        conn.execute(
            "INSERT INTO benefits (id, employee_id, name, value) VALUES (?,?,?,?)",
            (benefit["id"], benefit["employeeId"], benefit["name"], benefit["value"]),
        )
    conn.commit()


def get_database(path: Path | None = None) -> sqlite3.Connection:
    conn = init_db(path)
    seed_if_empty(conn)
    return conn
