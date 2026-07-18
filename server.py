"""Servidor local do Orbita HRM, com persistência SQLite. Não usar como base de produção."""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import threading
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import db

ROOT = Path(__file__).resolve().parent
SSO_CONFIG = {"enabled": True, "provider": "corporate-oidc", "protocol": "OIDC", "issuer": "https://id.orbita.local/mock"}

REQUEST_EVENT_TYPES = ["Entrada", "Início do intervalo", "Fim do intervalo", "Saída"]
REQUEST_TYPES = ("Ajuste de ponto", "Solicitação de férias", "Hora extra", "Alteração cadastral")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CPF_RE = re.compile(r"^\d{3}\.\d{3}\.\d{3}-\d{2}$")

LOGIN_ATTEMPT_LIMIT = 5
LOGIN_ATTEMPT_WINDOW_SECONDS = 300
DAILY_TARGET_MINUTES = 8 * 60

db.get_database().close()
SECRET = db.load_or_create_secret()

_login_attempts_lock = threading.Lock()
_login_attempts: dict[str, list[float]] = {}
_revoked_tokens_lock = threading.Lock()
_revoked_tokens: dict[str, float] = {}


def is_login_locked(email: str) -> bool:
    now = time.time()
    with _login_attempts_lock:
        attempts = [t for t in _login_attempts.get(email, []) if now - t < LOGIN_ATTEMPT_WINDOW_SECONDS]
        _login_attempts[email] = attempts
        return len(attempts) >= LOGIN_ATTEMPT_LIMIT


def register_failed_login(email: str) -> None:
    with _login_attempts_lock:
        _login_attempts.setdefault(email, []).append(time.time())


def clear_login_attempts(email: str) -> None:
    with _login_attempts_lock:
        _login_attempts.pop(email, None)


def revoke_token(token: str, exp: float) -> None:
    with _revoked_tokens_lock:
        now = time.time()
        for existing, existing_exp in list(_revoked_tokens.items()):
            if existing_exp < now:
                del _revoked_tokens[existing]
        _revoked_tokens[token] = exp


def is_token_revoked(token: str) -> bool:
    with _revoked_tokens_lock:
        return token in _revoked_tokens


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def user_dict(row) -> dict:
    d = dict(row)
    d["workCard"] = d.pop("work_card")
    d["motherName"] = d.pop("mother_name")
    d["managerId"] = d.pop("manager_id")
    d["jobTitle"] = d.pop("job_title") or d["role"]
    d["birthDate"] = d.pop("birth_date")
    d["admissionDate"] = d.pop("admission_date")
    d["vacationBalance"] = d.pop("vacation_balance")
    d.pop("password_hash", None)
    d.pop("password_salt", None)
    return d


def public_user(user: dict) -> dict:
    return {key: user[key] for key in ("id", "email", "name", "role", "jobTitle", "department", "enrollment", "status", "photo")}


def document_dict(row) -> dict:
    d = dict(row)
    d["userId"] = d.pop("user_id")
    d["updatedAt"] = d.pop("updated_at")
    d["signedBy"] = d.pop("signed_by")
    d["signedAt"] = d.pop("signed_at")
    d["signed"] = bool(d["signed"])
    d["hasFile"] = bool(d.get("file_data"))
    d.pop("file_data", None)
    d.pop("file_type", None)
    return d


def point_event_dict(row) -> dict:
    return {"id": row["id"], "type": row["type"], "at": row["at"], "date": row["date"]}


def salary_request_dict(row) -> dict:
    d = dict(row)
    d["employeeId"] = d.pop("employee_id")
    d["employeeName"] = d.pop("employee_name")
    d["oldSalary"] = d.pop("old_salary")
    d["newSalary"] = d.pop("new_salary")
    d["effectiveDate"] = d.pop("effective_date")
    d["managerApprovedBy"] = d.pop("manager_approved_by")
    d["cfoApprovedBy"] = d.pop("cfo_approved_by")
    return d


def request_dict(row) -> dict:
    d = dict(row)
    d["employeeId"] = d.pop("employee_id")
    d["employeeName"] = d.pop("employee_name")
    d["decidedBy"] = d.pop("decided_by")
    d["decisionReason"] = d.pop("decision_reason")
    return d


def schedule_dict(row) -> dict:
    return {"competence": row["competence"], "scheduledAt": row["scheduled_at"], "scheduledBy": row["scheduled_by"], "status": row["status"]}


def notification_dict(row) -> dict:
    return {"id": row["id"], "title": row["title"], "text": row["text"], "read": bool(row["is_read"])}


def benefit_dict(row) -> dict:
    return {"id": row["id"], "employeeId": row["employee_id"], "name": row["name"], "value": row["value"]}


def find_user_by_id(conn, user_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return user_dict(row) if row else None


def find_user_by_email(conn, email: str) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    return dict(row) if row else None


def write_audit(conn, actor: dict | None, action: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO audit_log (actor_id, actor_name, action, detail, created_at) VALUES (?,?,?,?,?)",
        (actor["id"] if actor else None, actor["name"] if actor else "Sistema", action, detail, time.strftime("%Y-%m-%dT%H:%M:%S")),
    )


def create_notification(conn, user_id: str | None, title: str, text: str) -> None:
    conn.execute(
        "INSERT INTO notifications (id, user_id, title, text, is_read, created_at) VALUES (?,?,?,?,0,?)",
        (f"ntf-{uuid.uuid4().hex[:10]}", user_id, title, text, time.strftime("%Y-%m-%dT%H:%M:%S")),
    )


def _time_to_minutes(value: str) -> int:
    try:
        hours, minutes = value.split(":")
        return int(hours) * 60 + int(minutes)
    except Exception:
        return 0


def compute_worked_minutes(events: list[dict]) -> int:
    total = 0
    stack_start = None
    for event in events:
        minutes = _time_to_minutes(event["at"])
        if event["type"] in ("Entrada", "Fim do intervalo"):
            stack_start = minutes
        elif event["type"] in ("Início do intervalo", "Saída") and stack_start is not None:
            total += max(0, minutes - stack_start)
            stack_start = None
    return total


def group_point_events_by_date(rows) -> list[dict]:
    by_date: dict[str, list[dict]] = {}
    for row in rows:
        by_date.setdefault(row["date"], []).append(point_event_dict(row))
    days = []
    for date, events in sorted(by_date.items(), reverse=True):
        days.append({"date": date, "events": events, "workedMinutes": compute_worked_minutes(events)})
    return days


def compute_time_bank(conn, user_id: str) -> str:
    rows = conn.execute("SELECT * FROM point_events WHERE user_id=? ORDER BY date, id", (user_id,)).fetchall()
    by_date: dict[str, list[dict]] = {}
    for row in rows:
        by_date.setdefault(row["date"], []).append(point_event_dict(row))
    balance = sum(compute_worked_minutes(events) - DAILY_TARGET_MINUTES for events in by_date.values())
    sign = "+" if balance >= 0 else "-"
    balance = abs(balance)
    return f"{sign} {balance // 60:02d}:{balance % 60:02d}"


def issue_token(user: dict) -> str:
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = b64(json.dumps({"sub": user["id"], "email": user["email"], "role": user["role"], "iat": int(time.time()), "exp": int(time.time()) + 3600, "jti": uuid.uuid4().hex}, separators=(",", ":")).encode())
    signature = b64(hmac.new(SECRET, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def verify_token(conn, token: str) -> dict | None:
    try:
        if is_token_revoked(token):
            return None
        header, payload, signature = token.split(".")
        expected = b64(hmac.new(SECRET, f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            return None
        claims = json.loads(unb64(payload))
        if claims.get("exp", 0) < time.time():
            return None
        return find_user_by_id(conn, claims.get("sub"))
    except Exception:
        return None


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-App-Version", "0.3.0")
        super().end_headers()

    def json_response(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def file_response(self, status, content_type, filename, body_bytes, inline=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        disposition = "inline" if inline else "attachment"
        self.send_header("Content-Disposition", f'{disposition}; filename="{filename}"')
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def body(self):
        try:
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode() or "{}")
        except json.JSONDecodeError:
            self.json_response(HTTPStatus.BAD_REQUEST, {"error": "JSON inválido"})
            return None

    def current_user(self, conn):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self.json_response(HTTPStatus.UNAUTHORIZED, {"error": "Autenticação obrigatória"})
            return None
        user = verify_token(conn, auth[7:])
        if not user:
            self.json_response(HTTPStatus.UNAUTHORIZED, {"error": "Token inválido ou expirado"})
            return None
        return user

    def require(self, conn, *roles):
        user = self.current_user(conn)
        if user and user["role"] not in roles:
            self.json_response(HTTPStatus.FORBIDDEN, {"error": "Permissão insuficiente"})
            return None
        return user

    def do_POST(self):
        conn = db.connect()
        try:
            self.handle_post(conn)
        finally:
            conn.close()

    def do_GET(self):
        conn = db.connect()
        try:
            self.handle_get(conn)
        finally:
            conn.close()

    def do_PATCH(self):
        conn = db.connect()
        try:
            self.handle_patch(conn)
        finally:
            conn.close()

    def do_DELETE(self):
        conn = db.connect()
        try:
            self.handle_delete(conn)
        finally:
            conn.close()

    # ------------------------------------------------------------------ POST
    def handle_post(self, conn):
        path = urlparse(self.path).path
        data = self.body()
        if data is None:
            return

        if path in ("/api/auth/login", "/api/auth/sso"):
            return self._post_auth(conn, path, data)
        if path == "/api/auth/logout":
            return self._post_logout(conn)
        if path == "/api/employees":
            return self._post_employees(conn, data)
        if path.startswith("/api/employees/") and path.endswith("/status"):
            return self._post_employee_status(conn, path, data)
        if path.startswith("/api/employees/") and path.endswith("/photo"):
            return self._post_employee_photo(conn, path, data)
        if path.startswith("/api/employees/") and path.endswith("/time/correct"):
            return self._post_time_correct(conn, path, data)
        if path == "/api/documents":
            return self._post_documents(conn, data)
        if path.startswith("/api/documents/") and path.endswith("/sign"):
            return self._post_document_sign(conn, path)
        if path == "/api/time/punch":
            return self._post_time_punch(conn)
        if path == "/api/notifications/read":
            return self._post_notifications_read(conn)
        if path == "/api/payroll/close-schedule":
            return self._post_payroll_schedule(conn, data)
        if path == "/api/salary-requests":
            return self._post_salary_request(conn, data)
        if path.startswith("/api/salary-requests/") and path.endswith("/approve"):
            return self._post_salary_request_approve(conn, path)
        if path == "/api/requests":
            return self._post_generic_request(conn, data)
        if path.startswith("/api/requests/") and path.endswith("/decide"):
            return self._post_generic_request_decide(conn, path, data)
        if path == "/api/benefits":
            return self._post_benefit(conn, data)

        self.json_response(HTTPStatus.NOT_FOUND, {"error": "Rota não encontrada"})

    def _post_auth(self, conn, path, data):
        if path.endswith("sso") and (not SSO_CONFIG["enabled"] or data.get("provider") != SSO_CONFIG["provider"]):
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Provedor SSO indisponível"})
        email = data.get("email", "").strip().lower()
        if path.endswith("login"):
            if is_login_locked(email):
                return self.json_response(HTTPStatus.TOO_MANY_REQUESTS, {"error": "Muitas tentativas de login. Aguarde alguns minutos e tente novamente."})
            row = find_user_by_email(conn, email)
            if not row or not db.verify_password(data.get("password", ""), row["password_salt"], row["password_hash"]):
                register_failed_login(email)
                return self.json_response(HTTPStatus.UNAUTHORIZED, {"error": "Credenciais inválidas"})
            clear_login_attempts(email)
        else:
            row = find_user_by_email(conn, email)
            if not row:
                return self.json_response(HTTPStatus.UNAUTHORIZED, {"error": "Usuário não encontrado no provedor corporativo"})
        if row["status"] == "Inativo":
            return self.json_response(HTTPStatus.FORBIDDEN, {"error": "Este colaborador está desligado e não pode acessar a plataforma"})
        user = user_dict(row)
        return self.json_response(HTTPStatus.OK, {"accessToken": issue_token(user), "user": public_user(user)})

    def _post_logout(self, conn):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            try:
                _, payload, _ = token.split(".")
                exp = json.loads(unb64(payload)).get("exp", time.time() + 3600)
            except Exception:
                exp = time.time() + 3600
            revoke_token(token, exp)
        return self.json_response(HTTPStatus.OK, {"ok": True})

    def _post_employees(self, conn, data):
        user = self.require(conn, "Admin", "RH")
        if not user:
            return
        required = ("name", "email", "cpf", "workCard", "address", "motherName")
        missing = [key for key in required if not data.get(key)]
        if missing:
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Campos obrigatórios ausentes", "fields": missing})
        if not EMAIL_RE.match(data["email"]):
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "E-mail em formato inválido"})
        if not CPF_RE.match(data["cpf"]):
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "CPF deve seguir o formato 000.000.000-00"})
        if find_user_by_email(conn, data["email"].strip().lower()):
            return self.json_response(HTTPStatus.CONFLICT, {"error": "E-mail já cadastrado"})
        sequence = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] + 1
        password_hash, password_salt = db.hash_password(db.SEED_PASSWORD)
        new_user = {
            "id": f"usr-{sequence:03d}", "email": data["email"], "name": data["name"],
            "role": "Funcionário", "jobTitle": data.get("jobTitle") or "Funcionário", "department": data.get("department", "Operações"),
            "cpf": data["cpf"], "workCard": data["workCard"], "address": data["address"],
            "motherName": data["motherName"], "enrollment": f"MAT-{sequence:06d}", "managerId": data.get("managerId") or None,
            "salary": 3000, "birthDate": data.get("birthDate") or None, "admissionDate": data.get("admissionDate") or time.strftime("%Y-%m-%d"),
        }
        conn.execute(
            "INSERT INTO users (id, email, password_hash, password_salt, name, role, job_title, department, cpf, work_card, address, enrollment, mother_name, manager_id, salary, birth_date, admission_date, status, schedule, vacation_balance) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_user["id"], new_user["email"], password_hash, password_salt, new_user["name"], new_user["role"], new_user["jobTitle"], new_user["department"], new_user["cpf"], new_user["workCard"], new_user["address"], new_user["enrollment"], new_user["motherName"], new_user["managerId"], new_user["salary"], new_user["birthDate"], new_user["admissionDate"], "Ativo", db.DEFAULT_SCHEDULE, db.DEFAULT_VACATION_BALANCE),
        )
        write_audit(conn, user, "employee.create", f"Cadastrou {new_user['name']} ({new_user['enrollment']})")
        create_notification(conn, new_user["id"], "Bem-vindo(a) à Orbita", f"Sua conta foi criada. Use a senha inicial {db.SEED_PASSWORD} no primeiro acesso.")
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id=?", (new_user["id"],)).fetchone()
        return self.json_response(HTTPStatus.CREATED, {"user": public_user(user_dict(row)), "message": "Colaborador criado"})

    def _post_employee_status(self, conn, path, data):
        user = self.require(conn, "Admin", "RH")
        if not user:
            return
        employee_id = path.split("/")[3]
        target = find_user_by_id(conn, employee_id)
        if not target:
            return self.json_response(HTTPStatus.NOT_FOUND, {"error": "Colaborador não encontrado"})
        new_status = data.get("status")
        if new_status not in ("Ativo", "Inativo"):
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Status inválido"})
        conn.execute("UPDATE users SET status=? WHERE id=?", (new_status, employee_id))
        write_audit(conn, user, "employee.status", f"{target['name']} agora está {new_status}")
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id=?", (employee_id,)).fetchone()
        return self.json_response(HTTPStatus.OK, {"user": user_dict(row)})

    def _post_employee_photo(self, conn, path, data):
        user = self.current_user(conn)
        if not user:
            return
        employee_id = path.split("/")[3]
        if user["role"] not in ("Admin", "RH") and user["id"] != employee_id:
            return self.json_response(HTTPStatus.FORBIDDEN, {"error": "Sem permissão para alterar esta foto"})
        photo = data.get("photo")
        if not photo:
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Imagem obrigatória"})
        conn.execute("UPDATE users SET photo=? WHERE id=?", (photo, employee_id))
        conn.commit()
        return self.json_response(HTTPStatus.OK, {"ok": True})

    def _post_time_correct(self, conn, path, data):
        user = self.require(conn, "Admin", "RH")
        if not user:
            return
        employee_id = path.split("/")[3]
        target = find_user_by_id(conn, employee_id)
        if not target:
            return self.json_response(HTTPStatus.NOT_FOUND, {"error": "Colaborador não encontrado"})
        event_type, at, date = data.get("type"), data.get("at"), data.get("date")
        if event_type not in REQUEST_EVENT_TYPES or not at or not date:
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Tipo, horário e data são obrigatórios"})
        total_count = conn.execute("SELECT COUNT(*) FROM point_events WHERE user_id=?", (employee_id,)).fetchone()[0]
        conn.execute("INSERT INTO point_events (id, user_id, type, at, date) VALUES (?,?,?,?,?)", (f"pnt-{total_count + 1:03d}", employee_id, event_type, at, date))
        write_audit(conn, user, "time.correct", f"Registro manual para {target['name']}: {event_type} {at} em {date}")
        conn.commit()
        return self.json_response(HTTPStatus.CREATED, {"ok": True})

    def _post_documents(self, conn, data):
        user = self.require(conn, "Admin", "RH")
        if not user:
            return
        if not data.get("name") or not data.get("userId"):
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Nome e colaborador são obrigatórios"})
        existing = conn.execute("SELECT * FROM documents WHERE user_id=? AND name=? ORDER BY id DESC LIMIT 1", (data["userId"], data["name"])).fetchone()
        if existing:
            try:
                major, minor = existing["version"].split(".")
                version = f"{major}.{int(minor) + 1}"
            except Exception:
                version = "1.1"
        else:
            version = "1.0"
        sequence = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] + 1
        document = {"id": f"doc-{sequence:03d}", "userId": data["userId"], "name": data["name"], "category": data.get("category", "Outros"), "version": version, "updatedAt": time.strftime("%Y-%m-%d"), "access": data.get("access", "RH e Admin")}
        conn.execute(
            "INSERT INTO documents (id, user_id, name, category, version, updated_at, access, file_data, file_type) VALUES (?,?,?,?,?,?,?,?,?)",
            (document["id"], document["userId"], document["name"], document["category"], document["version"], document["updatedAt"], document["access"], data.get("fileData"), data.get("fileType")),
        )
        write_audit(conn, user, "document.create", f"Adicionou {document['name']} (v{version})")
        create_notification(conn, document["userId"], "Novo documento", f"{document['name']} foi adicionado ao seu perfil.")
        conn.commit()
        return self.json_response(HTTPStatus.CREATED, {"document": document})

    def _post_document_sign(self, conn, path):
        user = self.current_user(conn)
        if not user:
            return
        document_id = path.split("/")[3]
        row = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if not row:
            return self.json_response(HTTPStatus.NOT_FOUND, {"error": "Documento não encontrado"})
        allowed = user["role"] in ("Admin", "RH") or row["user_id"] == user["id"]
        if not allowed:
            return self.json_response(HTTPStatus.FORBIDDEN, {"error": "Sem permissão para assinar este documento"})
        conn.execute("UPDATE documents SET signed=1, signed_by=?, signed_at=? WHERE id=?", (user["name"], time.strftime("%Y-%m-%dT%H:%M:%S"), document_id))
        write_audit(conn, user, "document.sign", f"Assinou {row['name']}")
        conn.commit()
        row = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        return self.json_response(HTTPStatus.OK, {"document": document_dict(row)})

    def _post_time_punch(self, conn):
        user = self.current_user(conn)
        if not user:
            return
        today = time.strftime("%Y-%m-%d")
        total_count = conn.execute("SELECT COUNT(*) FROM point_events WHERE user_id=?", (user["id"],)).fetchone()[0]
        today_count = conn.execute("SELECT COUNT(*) FROM point_events WHERE user_id=? AND date=?", (user["id"], today)).fetchone()[0]
        event = {"id": f"pnt-{total_count + 1:03d}", "type": REQUEST_EVENT_TYPES[today_count % len(REQUEST_EVENT_TYPES)], "at": time.strftime("%H:%M"), "date": today}
        conn.execute("INSERT INTO point_events (id, user_id, type, at, date) VALUES (?,?,?,?,?)", (event["id"], user["id"], event["type"], event["at"], event["date"]))
        conn.commit()
        rows = conn.execute("SELECT * FROM point_events WHERE user_id=? AND date=? ORDER BY id", (user["id"], today)).fetchall()
        return self.json_response(HTTPStatus.CREATED, {"event": event, "events": [point_event_dict(row) for row in rows]})

    def _post_notifications_read(self, conn):
        user = self.current_user(conn)
        if not user:
            return
        conn.execute("UPDATE notifications SET is_read=1 WHERE user_id IS NULL OR user_id=?", (user["id"],))
        conn.commit()
        return self.json_response(HTTPStatus.OK, {"ok": True})

    def _post_payroll_schedule(self, conn, data):
        user = self.require(conn, "Tesouraria")
        if not user:
            return
        scheduled_at = data.get("scheduledAt")
        if not scheduled_at:
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Informe data e hora do fechamento"})
        competence = data.get("competence", "07/2026")
        conn.execute("UPDATE payroll_schedule SET competence=?, scheduled_at=?, scheduled_by=?, status=? WHERE id=1", (competence, scheduled_at, user["name"], "Programado"))
        conn.execute(
            "INSERT INTO payroll_history (id, competence, scheduled_at, scheduled_by, created_at) VALUES (?,?,?,?,?)",
            (f"ph-{uuid.uuid4().hex[:8]}", competence, scheduled_at, user["name"], time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
        write_audit(conn, user, "payroll.schedule", f"Programou fechamento de {competence} para {scheduled_at}")
        conn.commit()
        row = conn.execute("SELECT * FROM payroll_schedule WHERE id=1").fetchone()
        return self.json_response(HTTPStatus.OK, {"schedule": schedule_dict(row)})

    def _post_salary_request(self, conn, data):
        requester = self.require(conn, "Admin", "RH", "Manager")
        if not requester:
            return
        employee = find_user_by_id(conn, data.get("employeeId"))
        if not employee:
            return self.json_response(HTTPStatus.NOT_FOUND, {"error": "Colaborador não encontrado"})
        if requester["role"] == "Manager" and employee.get("managerId") != requester["id"]:
            return self.json_response(HTTPStatus.FORBIDDEN, {"error": "Manager só pode solicitar reajuste do próprio time"})
        new_salary = float(data.get("newSalary", 0))
        if new_salary <= 0 or new_salary == employee.get("salary"):
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Informe um novo salário válido"})
        sequence = conn.execute("SELECT COUNT(*) FROM salary_requests").fetchone()[0] + 1
        request_id = f"sal-{sequence:03d}"
        conn.execute(
            "INSERT INTO salary_requests (id, employee_id, employee_name, old_salary, new_salary, reason, effective_date, stage, status, requester, manager_approved_by, cfo_approved_by) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL)",
            (request_id, employee["id"], employee["name"], employee["salary"], new_salary, data.get("reason", "Não informado"), data.get("effectiveDate", ""), "manager", "Aguardando gerente", requester["name"]),
        )
        write_audit(conn, requester, "salary_request.create", f"Solicitou reajuste de {employee['name']} para {new_salary}")
        conn.commit()
        row = conn.execute("SELECT * FROM salary_requests WHERE id=?", (request_id,)).fetchone()
        return self.json_response(HTTPStatus.CREATED, {"request": salary_request_dict(row)})

    def _post_salary_request_approve(self, conn, path):
        user = self.current_user(conn)
        if not user:
            return
        request_id = path.split("/")[3]
        row = conn.execute("SELECT * FROM salary_requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            return self.json_response(HTTPStatus.NOT_FOUND, {"error": "Solicitação não encontrada"})
        request = dict(row)
        if request["stage"] == "manager" and user["role"] == "Manager":
            employee = find_user_by_id(conn, request["employee_id"])
            if employee.get("managerId") != user["id"]:
                return self.json_response(HTTPStatus.FORBIDDEN, {"error": "Manager só pode aprovar reajustes do próprio time"})
            conn.execute("UPDATE salary_requests SET stage=?, status=?, manager_approved_by=? WHERE id=?", ("cfo", "Aguardando CFO", user["name"], request_id))
            write_audit(conn, user, "salary_request.manager_approve", f"Aprovou (gerente) reajuste {request_id}")
        elif request["stage"] == "cfo" and user["role"] == "CFO":
            conn.execute("UPDATE users SET salary=? WHERE id=?", (request["new_salary"], request["employee_id"]))
            conn.execute("UPDATE salary_requests SET stage=?, status=?, cfo_approved_by=? WHERE id=?", ("complete", "Aprovado", user["name"], request_id))
            write_audit(conn, user, "salary_request.cfo_approve", f"Aprovou (CFO) reajuste {request_id}")
            create_notification(conn, request["employee_id"], "Reajuste salarial aprovado", f"Seu novo salário é {request['new_salary']:.2f}.")
        else:
            return self.json_response(HTTPStatus.FORBIDDEN, {"error": "Aprovação não permitida para este perfil ou etapa"})
        conn.commit()
        row = conn.execute("SELECT * FROM salary_requests WHERE id=?", (request_id,)).fetchone()
        return self.json_response(HTTPStatus.OK, {"request": salary_request_dict(row)})

    def _post_generic_request(self, conn, data):
        requester = self.current_user(conn)
        if not requester:
            return
        request_type = data.get("type")
        if request_type not in REQUEST_TYPES:
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Tipo de solicitação inválido"})
        if not data.get("detail"):
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Detalhe é obrigatório"})
        days = None
        if request_type == "Solicitação de férias":
            try:
                days = int(data.get("days", 0))
            except (TypeError, ValueError):
                days = 0
            if days <= 0:
                return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Informe a quantidade de dias de férias"})
            if days > requester.get("vacationBalance", 0):
                return self.json_response(HTTPStatus.BAD_REQUEST, {"error": f"Saldo de férias insuficiente ({requester.get('vacationBalance', 0)} dias disponíveis)"})
        sequence = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] + 1
        request_id = f"req-{sequence:03d}"
        conn.execute(
            "INSERT INTO requests (id, employee_id, employee_name, type, detail, days, status, decided_by, decision_reason) VALUES (?,?,?,?,?,?,?,NULL,NULL)",
            (request_id, requester["id"], requester["name"], request_type, data["detail"], days, "Pendente"),
        )
        write_audit(conn, requester, "request.create", f"{request_type}: {data['detail']}")
        conn.commit()
        row = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        return self.json_response(HTTPStatus.CREATED, {"request": request_dict(row)})

    def _post_generic_request_decide(self, conn, path, data):
        user = self.current_user(conn)
        if not user:
            return
        request_id = path.split("/")[3]
        row = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            return self.json_response(HTTPStatus.NOT_FOUND, {"error": "Solicitação não encontrada"})
        employee = find_user_by_id(conn, row["employee_id"])
        allowed = user["role"] in ("Admin", "RH") or (user["role"] == "Manager" and employee.get("managerId") == user["id"])
        if not allowed:
            return self.json_response(HTTPStatus.FORBIDDEN, {"error": "Sem permissão para decidir esta solicitação"})
        status = data.get("status")
        if status not in ("Aprovado", "Rejeitado"):
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Status inválido"})
        reason = (data.get("reason") or "").strip()
        if status == "Rejeitado" and not reason:
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Informe o motivo da recusa"})
        if status == "Aprovado" and row["type"] == "Solicitação de férias" and row["days"]:
            conn.execute("UPDATE users SET vacation_balance = MAX(0, vacation_balance - ?) WHERE id=?", (row["days"], row["employee_id"]))
        conn.execute("UPDATE requests SET status=?, decided_by=?, decision_reason=? WHERE id=?", (status, user["name"], reason or None, request_id))
        write_audit(conn, user, "request.decide", f"{status} solicitação {request_id} de {row['employee_name']}")
        create_notification(conn, row["employee_id"], f"Solicitação {status.lower()}", f"Sua solicitação de {row['type']} foi {status.lower()}." + (f" Motivo: {reason}" if reason else ""))
        conn.commit()
        row = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        return self.json_response(HTTPStatus.OK, {"request": request_dict(row)})

    def _post_benefit(self, conn, data):
        user = self.require(conn, "Admin", "RH")
        if not user:
            return
        if not data.get("employeeId") or not data.get("name") or data.get("value") is None:
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Colaborador, nome e valor são obrigatórios"})
        target = find_user_by_id(conn, data["employeeId"])
        if not target:
            return self.json_response(HTTPStatus.NOT_FOUND, {"error": "Colaborador não encontrado"})
        try:
            value = float(data["value"])
        except (TypeError, ValueError):
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Valor inválido"})
        sequence = conn.execute("SELECT COUNT(*) FROM benefits").fetchone()[0] + 1
        benefit_id = f"ben-{sequence:03d}"
        conn.execute("INSERT INTO benefits (id, employee_id, name, value) VALUES (?,?,?,?)", (benefit_id, data["employeeId"], data["name"], value))
        write_audit(conn, user, "benefit.create", f"{data['name']} para {target['name']}")
        conn.commit()
        return self.json_response(HTTPStatus.CREATED, {"benefit": {"id": benefit_id, "employeeId": data["employeeId"], "name": data["name"], "value": value}})

    # ------------------------------------------------------------------- GET
    def handle_get(self, conn):
        path = urlparse(self.path).path

        if path == "/api/auth/me":
            user = self.current_user(conn)
            if user:
                self.json_response(HTTPStatus.OK, {"user": public_user(user)})
            return
        if path == "/api/notifications":
            return self._get_notifications(conn)
        if path == "/api/time/me":
            return self._get_time_me(conn)
        if path == "/api/payroll/close-schedule":
            return self._get_payroll_schedule(conn)
        if path == "/api/payroll/history":
            return self._get_payroll_history(conn)
        if path == "/api/salary-requests":
            return self._get_salary_requests(conn)
        if path == "/api/requests":
            return self._get_generic_requests(conn)
        if path.startswith("/api/search"):
            return self._get_search(conn)
        if path == "/api/auth/sso/config":
            return self.json_response(HTTPStatus.OK, {key: SSO_CONFIG[key] for key in ("enabled", "provider", "protocol")})
        if path == "/api/employees/export":
            return self._get_employees_export(conn)
        if path == "/api/users":
            return self._get_users(conn)
        if path.startswith("/api/users/") and path.endswith("/documents"):
            return self._get_user_documents(conn, path)
        if path.startswith("/api/users/") and path.endswith("/time"):
            return self._get_user_time(conn, path)
        if path.startswith("/api/users/") and path.endswith("/benefits"):
            return self._get_user_benefits(conn, path)
        if path.startswith("/api/documents/") and path.endswith("/download"):
            return self._get_document_download(conn, path)
        if path == "/api/documents":
            return self._get_documents(conn)
        if path == "/api/portal":
            return self._get_portal(conn)
        if path == "/api/admin/overview":
            return self._get_admin_overview(conn)
        if path == "/api/audit-log":
            return self._get_audit_log(conn)

        super().do_GET()

    def _get_notifications(self, conn):
        user = self.current_user(conn)
        if not user:
            return
        rows = conn.execute("SELECT * FROM notifications WHERE user_id IS NULL OR user_id=? ORDER BY created_at DESC, id DESC", (user["id"],)).fetchall()
        return self.json_response(HTTPStatus.OK, {"notifications": [notification_dict(row) for row in rows]})

    def _get_time_me(self, conn):
        user = self.current_user(conn)
        if not user:
            return
        today = time.strftime("%Y-%m-%d")
        rows = conn.execute("SELECT * FROM point_events WHERE user_id=? AND date=? ORDER BY id", (user["id"], today)).fetchall()
        events = [point_event_dict(row) for row in rows]
        next_actions = ["Registrar entrada", "Iniciar intervalo", "Finalizar intervalo", "Registrar saída"]
        return self.json_response(HTTPStatus.OK, {"events": events, "nextAction": next_actions[len(events) % 4], "bank": compute_time_bank(conn, user["id"])})

    def _get_payroll_schedule(self, conn):
        user = self.current_user(conn)
        if not user:
            return
        row = conn.execute("SELECT * FROM payroll_schedule WHERE id=1").fetchone()
        return self.json_response(HTTPStatus.OK, {"schedule": schedule_dict(row), "canSchedule": user["role"] == "Tesouraria"})

    def _get_payroll_history(self, conn):
        if not self.current_user(conn):
            return
        rows = conn.execute("SELECT * FROM payroll_history ORDER BY created_at DESC").fetchall()
        return self.json_response(HTTPStatus.OK, {"history": [{"id": r["id"], "competence": r["competence"], "scheduledAt": r["scheduled_at"], "scheduledBy": r["scheduled_by"], "createdAt": r["created_at"]} for r in rows]})

    def _get_salary_requests(self, conn):
        user = self.current_user(conn)
        if not user:
            return
        if user["role"] in ("Admin", "RH", "CFO"):
            rows = conn.execute("SELECT * FROM salary_requests").fetchall()
        elif user["role"] == "Manager":
            rows = conn.execute("SELECT sr.* FROM salary_requests sr JOIN users u ON u.id = sr.employee_id WHERE u.manager_id=?", (user["id"],)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM salary_requests WHERE employee_id=?", (user["id"],)).fetchall()
        return self.json_response(HTTPStatus.OK, {"requests": [salary_request_dict(row) for row in rows]})

    def _get_generic_requests(self, conn):
        user = self.current_user(conn)
        if not user:
            return
        if user["role"] in ("Admin", "RH"):
            rows = conn.execute("SELECT * FROM requests").fetchall()
        elif user["role"] == "Manager":
            rows = conn.execute("SELECT r.* FROM requests r JOIN users u ON u.id = r.employee_id WHERE u.manager_id=? OR r.employee_id=?", (user["id"], user["id"])).fetchall()
        else:
            rows = conn.execute("SELECT * FROM requests WHERE employee_id=?", (user["id"],)).fetchall()
        return self.json_response(HTTPStatus.OK, {"requests": [request_dict(row) for row in rows]})

    def _get_search(self, conn):
        user = self.current_user(conn)
        if not user:
            return
        query = urlparse(self.path).query.lower()
        term = query.split("q=", 1)[-1].replace("+", " ") if "q=" in query else ""
        if user["role"] in ("Admin", "RH"):
            rows = conn.execute("SELECT * FROM users").fetchall()
        else:
            rows = conn.execute("SELECT * FROM users WHERE id=? OR manager_id=?", (user["id"], user["id"])).fetchall()
        results = [user_dict(row) for row in rows]
        return self.json_response(HTTPStatus.OK, {"results": [public_user(item) for item in results if term in item["name"].lower() or term in item["enrollment"].lower()]})

    def _get_employees_export(self, conn):
        if not self.require(conn, "Admin", "RH"):
            return
        rows = conn.execute("SELECT * FROM users ORDER BY enrollment").fetchall()
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Matrícula", "Nome", "E-mail", "Papel", "Departamento", "Status", "Salário", "Admissão"])
        for row in rows:
            u = user_dict(row)
            writer.writerow([u["enrollment"], u["name"], u["email"], u["role"], u["department"], u["status"], u["salary"], u["admissionDate"] or ""])
        return self.file_response(HTTPStatus.OK, "text/csv; charset=utf-8", "colaboradores.csv", buffer.getvalue().encode("utf-8-sig"))

    def _get_users(self, conn):
        if not self.require(conn, "Admin", "RH"):
            return
        query = parse_qs(urlparse(self.path).query)
        sql = "SELECT * FROM users WHERE 1=1"
        params: list[str] = []
        for key, column in (("department", "department"), ("role", "role"), ("status", "status")):
            if query.get(key) and query[key][0]:
                sql += f" AND {column}=?"
                params.append(query[key][0])
        rows = conn.execute(sql, params).fetchall()
        return self.json_response(HTTPStatus.OK, {"users": [user_dict(row) for row in rows]})

    def _get_user_documents(self, conn, path):
        requester = self.current_user(conn)
        if not requester:
            return
        user_id = path.split("/")[3]
        target = find_user_by_id(conn, user_id)
        if not target:
            return self.json_response(HTTPStatus.NOT_FOUND, {"error": "Colaborador não encontrado"})
        allowed = requester["role"] in ("Admin", "RH") or requester["id"] == user_id or target.get("managerId") == requester["id"]
        if not allowed:
            return self.json_response(HTTPStatus.FORBIDDEN, {"error": "Sem acesso aos documentos deste colaborador"})
        rows = conn.execute("SELECT * FROM documents WHERE user_id=?", (user_id,)).fetchall()
        documents = [document_dict(row) for row in rows]
        present = {doc["category"] for doc in documents} | {doc["name"].split(".")[0] for doc in documents}
        pending = [item for item in db.REQUIRED_DOCUMENTS if not any(item.lower() in value.lower() for value in present)]
        return self.json_response(HTTPStatus.OK, {"user": public_user(target), "documents": documents, "pending": pending})

    def _get_user_time(self, conn, path):
        requester = self.current_user(conn)
        if not requester:
            return
        user_id = path.split("/")[3]
        if requester["role"] not in ("Admin", "RH") and requester["id"] != user_id:
            return self.json_response(HTTPStatus.FORBIDDEN, {"error": "Sem acesso à jornada deste colaborador"})
        rows = conn.execute("SELECT * FROM point_events WHERE user_id=? ORDER BY date, id", (user_id,)).fetchall()
        return self.json_response(HTTPStatus.OK, {"days": group_point_events_by_date(rows), "bank": compute_time_bank(conn, user_id)})

    def _get_user_benefits(self, conn, path):
        requester = self.current_user(conn)
        if not requester:
            return
        user_id = path.split("/")[3]
        if requester["role"] not in ("Admin", "RH") and requester["id"] != user_id:
            return self.json_response(HTTPStatus.FORBIDDEN, {"error": "Sem acesso aos benefícios deste colaborador"})
        rows = conn.execute("SELECT * FROM benefits WHERE employee_id=?", (user_id,)).fetchall()
        return self.json_response(HTTPStatus.OK, {"benefits": [benefit_dict(row) for row in rows]})

    def _get_document_download(self, conn, path):
        user = self.current_user(conn)
        if not user:
            return
        document_id = path.split("/")[3]
        row = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if not row:
            return self.json_response(HTTPStatus.NOT_FOUND, {"error": "Documento não encontrado"})
        allowed = user["role"] in ("Admin", "RH") or row["user_id"] == user["id"]
        if not allowed:
            return self.json_response(HTTPStatus.FORBIDDEN, {"error": "Sem acesso a este documento"})
        if not row["file_data"]:
            return self.json_response(HTTPStatus.NOT_FOUND, {"error": "Nenhum arquivo foi enviado para este documento"})
        try:
            file_bytes = base64.b64decode(row["file_data"])
        except Exception:
            return self.json_response(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Arquivo corrompido"})
        return self.file_response(HTTPStatus.OK, row["file_type"] or "application/octet-stream", row["name"], file_bytes)

    def _get_documents(self, conn):
        user = self.current_user(conn)
        if not user:
            return
        if user["role"] in ("Admin", "RH"):
            rows = conn.execute("SELECT * FROM documents").fetchall()
        else:
            rows = conn.execute("SELECT * FROM documents WHERE user_id=?", (user["id"],)).fetchall()
        return self.json_response(HTTPStatus.OK, {"documents": [document_dict(row) for row in rows]})

    def _get_portal(self, conn):
        user = self.current_user(conn)
        if not user:
            return
        team_rows = conn.execute("SELECT * FROM users WHERE manager_id=?", (user["id"],)).fetchall()
        team = [public_user(user_dict(row)) for row in team_rows]
        own_documents = conn.execute("SELECT COUNT(*) FROM documents WHERE user_id=?", (user["id"],)).fetchone()[0]
        benefit_rows = conn.execute("SELECT * FROM benefits WHERE employee_id=?", (user["id"],)).fetchall()
        today = time.strftime("%Y-%m-%d")
        today_rows = conn.execute("SELECT * FROM point_events WHERE user_id=? AND date=?", (user["id"], today)).fetchall()
        worked_minutes = compute_worked_minutes([point_event_dict(row) for row in today_rows])
        return self.json_response(HTTPStatus.OK, {
            "user": public_user(user),
            "payroll": {"competence": "07/2026", "baseSalary": user.get("salary", 0), "earnings": 350, "discounts": round((user.get("salary", 0) + 350) * .17, 2)},
            "time": {"worked": f"{worked_minutes // 60:02d}:{worked_minutes % 60:02d}", "bank": compute_time_bank(conn, user["id"]), "status": "Jornada em andamento" if len(today_rows) % 4 != 0 else "Fora do expediente"},
            "team": team,
            "documents": {"sent": own_documents, "pending": len(db.REQUIRED_DOCUMENTS) - own_documents},
            "benefits": [{"name": r["name"], "value": r["value"]} for r in benefit_rows],
            "vacationBalance": user.get("vacationBalance", 0),
        })

    def _get_admin_overview(self, conn):
        if not self.require(conn, "Admin"):
            return
        users_count = conn.execute("SELECT COUNT(*) FROM users WHERE status='Ativo'").fetchone()[0]
        documents_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        return self.json_response(HTTPStatus.OK, {"users": users_count, "documents": documents_count, "securityEvents": 0, "ssoEnabled": True})

    def _get_audit_log(self, conn):
        if not self.require(conn, "Admin"):
            return
        rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200").fetchall()
        return self.json_response(HTTPStatus.OK, {"entries": [{"id": r["id"], "actorId": r["actor_id"], "actorName": r["actor_name"], "action": r["action"], "detail": r["detail"], "createdAt": r["created_at"]} for r in rows]})

    # ----------------------------------------------------------------- PATCH
    def handle_patch(self, conn):
        path = urlparse(self.path).path
        data = self.body()
        if data is None:
            return
        if path.startswith("/api/employees/"):
            return self._patch_employee(conn, path, data)
        self.json_response(HTTPStatus.NOT_FOUND, {"error": "Rota não encontrada"})

    def _patch_employee(self, conn, path, data):
        user = self.require(conn, "Admin", "RH")
        if not user:
            return
        employee_id = path.split("/")[3]
        target = find_user_by_id(conn, employee_id)
        if not target:
            return self.json_response(HTTPStatus.NOT_FOUND, {"error": "Colaborador não encontrado"})
        fields: dict[str, object] = {}
        for key, column in (("name", "name"), ("jobTitle", "job_title"), ("department", "department"), ("address", "address"), ("motherName", "mother_name"), ("schedule", "schedule"), ("birthDate", "birth_date"), ("managerId", "manager_id")):
            if key in data:
                fields[column] = data[key] or None
        if not fields:
            return self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Nada para atualizar"})
        set_clause = ", ".join(f"{col}=?" for col in fields)
        conn.execute(f"UPDATE users SET {set_clause} WHERE id=?", (*fields.values(), employee_id))
        write_audit(conn, user, "employee.update", f"Atualizou dados de {target['name']}")
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id=?", (employee_id,)).fetchone()
        return self.json_response(HTTPStatus.OK, {"user": user_dict(row)})

    # ---------------------------------------------------------------- DELETE
    def handle_delete(self, conn):
        path = urlparse(self.path).path
        if path.startswith("/api/benefits/"):
            return self._delete_benefit(conn, path)
        self.json_response(HTTPStatus.NOT_FOUND, {"error": "Rota não encontrada"})

    def _delete_benefit(self, conn, path):
        user = self.require(conn, "Admin", "RH")
        if not user:
            return
        benefit_id = path.split("/")[3]
        row = conn.execute("SELECT * FROM benefits WHERE id=?", (benefit_id,)).fetchone()
        if not row:
            return self.json_response(HTTPStatus.NOT_FOUND, {"error": "Benefício não encontrado"})
        conn.execute("DELETE FROM benefits WHERE id=?", (benefit_id,))
        write_audit(conn, user, "benefit.delete", f"Removeu {row['name']} de {row['employee_id']}")
        conn.commit()
        return self.json_response(HTTPStatus.OK, {"ok": True})

    def translate_path(self, path):
        path = urlparse(path).path.lstrip("/") or "index.html"
        target = (ROOT / path).resolve()
        return str(target if target.is_relative_to(ROOT) else ROOT / "index.html")


if __name__ == "__main__":
    host = os.environ.get("ORBITA_HRM_HOST", "127.0.0.1")
    print(f"Orbita HRM local em http://localhost:4173 (bind: {host})")
    ThreadingHTTPServer((host, 4173), Handler).serve_forever()
