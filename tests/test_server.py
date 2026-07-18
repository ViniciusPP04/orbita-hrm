import base64
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["ORBITA_HRM_SECRET"] = "test-secret-not-for-production"

import db  # noqa: E402

_tmpdir = tempfile.TemporaryDirectory()
db.DB_PATH = Path(_tmpdir.name) / "test.db"

import server  # noqa: E402


class ServerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        _tmpdir.cleanup()

    def request(self, method, path, body=None, token=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def request_raw(self, method, path, token=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers)

    def login(self, email, password="123456"):
        status, data = self.request("POST", "/api/auth/login", {"email": email, "password": password})
        self.assertEqual(status, 200, data)
        return data["accessToken"]

    def test_login_success(self):
        token = self.login("admin@orbita.com")
        self.assertTrue(token)

    def test_login_wrong_password(self):
        status, _ = self.request("POST", "/api/auth/login", {"email": "admin@orbita.com", "password": "wrong"})
        self.assertEqual(status, 401)

    def test_login_unknown_user(self):
        status, _ = self.request("POST", "/api/auth/login", {"email": "nobody@orbita.com", "password": "123456"})
        self.assertEqual(status, 401)

    def test_protected_route_without_token(self):
        status, _ = self.request("GET", "/api/auth/me")
        self.assertEqual(status, 401)

    def test_protected_route_invalid_token(self):
        status, _ = self.request("GET", "/api/auth/me", token="not-a-valid-token")
        self.assertEqual(status, 401)

    def test_rbac_users_requires_admin_or_rh(self):
        employee_token = self.login("employee@orbita.com")
        status, _ = self.request("GET", "/api/users", token=employee_token)
        self.assertEqual(status, 403)

    def test_rbac_rh_can_access_users(self):
        rh_token = self.login("rh@orbita.com")
        status, data = self.request("GET", "/api/users", token=rh_token)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(data["users"]), 5)

    def test_create_employee_missing_fields(self):
        admin_token = self.login("admin@orbita.com")
        status, _ = self.request("POST", "/api/employees", {"name": "Sem CPF"}, token=admin_token)
        self.assertEqual(status, 400)

    def test_create_employee_duplicate_email(self):
        admin_token = self.login("admin@orbita.com")
        status, _ = self.request(
            "POST", "/api/employees",
            {"name": "Dup", "email": "admin@orbita.com", "cpf": "111.111.111-11", "workCard": "1", "address": "1", "motherName": "1"},
            token=admin_token,
        )
        self.assertEqual(status, 409)

    def test_new_employee_can_log_in_with_default_password(self):
        admin_token = self.login("admin@orbita.com")
        status, data = self.request(
            "POST", "/api/employees",
            {"name": "Nova Pessoa", "email": "nova.pessoa@orbita.com", "cpf": "222.222.222-22", "workCard": "1", "address": "1", "motherName": "1"},
            token=admin_token,
        )
        self.assertEqual(status, 201, data)
        token = self.login("nova.pessoa@orbita.com")
        self.assertTrue(token)

    def test_salary_request_two_stage_approval(self):
        manager_token = self.login("manager@orbita.com")
        cfo_token = self.login("cfo@orbita.com")
        status, data = self.request(
            "POST", "/api/salary-requests",
            {"employeeId": "usr-004", "newSalary": 9500, "reason": "merito", "effectiveDate": "2026-08-01"},
            token=manager_token,
        )
        self.assertEqual(status, 201, data)
        request_id = data["request"]["id"]

        status, data = self.request("POST", f"/api/salary-requests/{request_id}/approve", {}, token=manager_token)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["request"]["stage"], "cfo")

        admin_token = self.login("admin@orbita.com")
        _, data = self.request("GET", "/api/users", token=admin_token)
        employee = next(u for u in data["users"] if u["id"] == "usr-004")
        self.assertNotEqual(employee["salary"], 9500)

        status, data = self.request("POST", f"/api/salary-requests/{request_id}/approve", {}, token=cfo_token)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["request"]["status"], "Aprovado")

        _, data = self.request("GET", "/api/users", token=admin_token)
        employee = next(u for u in data["users"] if u["id"] == "usr-004")
        self.assertEqual(employee["salary"], 9500)

    def test_generic_request_create_and_decide(self):
        employee_token = self.login("employee@orbita.com")
        manager_token = self.login("manager@orbita.com")
        status, data = self.request("POST", "/api/requests", {"type": "Hora extra", "detail": "2h"}, token=employee_token)
        self.assertEqual(status, 201, data)
        request_id = data["request"]["id"]

        status, data = self.request("POST", f"/api/requests/{request_id}/decide", {"status": "Aprovado"}, token=manager_token)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["request"]["status"], "Aprovado")

    def test_search_scoped_by_role(self):
        employee_token = self.login("employee@orbita.com")
        status, data = self.request("GET", "/api/search?q=Rocha", token=employee_token)
        self.assertEqual(status, 200)
        self.assertEqual(data["results"], [])

    def test_create_employee_invalid_email_format(self):
        admin_token = self.login("admin@orbita.com")
        status, _ = self.request(
            "POST", "/api/employees",
            {"name": "X", "email": "not-an-email", "cpf": "111.111.111-11", "workCard": "1", "address": "1", "motherName": "1"},
            token=admin_token,
        )
        self.assertEqual(status, 400)

    def test_create_employee_invalid_cpf_format(self):
        admin_token = self.login("admin@orbita.com")
        status, _ = self.request(
            "POST", "/api/employees",
            {"name": "X", "email": "formatvalid@orbita.com", "cpf": "12345", "workCard": "1", "address": "1", "motherName": "1"},
            token=admin_token,
        )
        self.assertEqual(status, 400)

    def test_login_rate_limiting(self):
        email = "ratelimit-test@orbita.com"
        for _ in range(server.LOGIN_ATTEMPT_LIMIT):
            status, _ = self.request("POST", "/api/auth/login", {"email": email, "password": "wrong"})
            self.assertEqual(status, 401)
        status, data = self.request("POST", "/api/auth/login", {"email": email, "password": "wrong"})
        self.assertEqual(status, 429, data)

    def test_logout_revokes_token(self):
        token = self.login("employee@orbita.com")
        status, _ = self.request("GET", "/api/auth/me", token=token)
        self.assertEqual(status, 200)
        status, _ = self.request("POST", "/api/auth/logout", {}, token=token)
        self.assertEqual(status, 200)
        status, _ = self.request("GET", "/api/auth/me", token=token)
        self.assertEqual(status, 401)

    def test_documents_list_scoped_by_role(self):
        admin_token = self.login("admin@orbita.com")
        status, data = self.request("GET", "/api/documents", token=admin_token)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(data["documents"]), 1)

        employee_token = self.login("employee@orbita.com")
        status, data = self.request("GET", "/api/documents", token=employee_token)
        self.assertEqual(status, 200)
        for doc in data["documents"]:
            self.assertEqual(doc["userId"], "usr-004")

    def test_create_document_requires_admin_or_rh(self):
        employee_token = self.login("employee@orbita.com")
        status, _ = self.request("POST", "/api/documents", {"name": "x.pdf", "userId": "usr-004"}, token=employee_token)
        self.assertEqual(status, 403)

        admin_token = self.login("admin@orbita.com")
        status, data = self.request("POST", "/api/documents", {"name": "Novo.pdf", "userId": "usr-004"}, token=admin_token)
        self.assertEqual(status, 201, data)

    def test_user_documents_endpoint_permission(self):
        manager_token = self.login("manager@orbita.com")
        status, data = self.request("GET", "/api/users/usr-004/documents", token=manager_token)
        self.assertEqual(status, 200, data)
        cfo_token = self.login("cfo@orbita.com")
        status, _ = self.request("GET", "/api/users/usr-004/documents", token=cfo_token)
        self.assertEqual(status, 403)

    def test_time_punch_and_me(self):
        employee_token = self.login("employee@orbita.com")
        status, data = self.request("GET", "/api/time/me", token=employee_token)
        self.assertEqual(status, 200)
        before = len(data["events"])
        status, data = self.request("POST", "/api/time/punch", {}, token=employee_token)
        self.assertEqual(status, 201, data)
        self.assertEqual(len(data["events"]), before + 1)

    def test_notifications_list_and_mark_read(self):
        admin_token = self.login("admin@orbita.com")
        status, data = self.request("GET", "/api/notifications", token=admin_token)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(data["notifications"]), 1)
        status, _ = self.request("POST", "/api/notifications/read", {}, token=admin_token)
        self.assertEqual(status, 200)
        status, data = self.request("GET", "/api/notifications", token=admin_token)
        self.assertTrue(all(n["read"] for n in data["notifications"]))

    def test_portal_endpoint(self):
        employee_token = self.login("employee@orbita.com")
        status, data = self.request("GET", "/api/portal", token=employee_token)
        self.assertEqual(status, 200)
        self.assertIn("payroll", data)
        self.assertIn("time", data)

    def test_admin_overview_requires_admin(self):
        rh_token = self.login("rh@orbita.com")
        status, _ = self.request("GET", "/api/admin/overview", token=rh_token)
        self.assertEqual(status, 403)
        admin_token = self.login("admin@orbita.com")
        status, data = self.request("GET", "/api/admin/overview", token=admin_token)
        self.assertEqual(status, 200)
        self.assertIn("users", data)

    def test_payroll_schedule_get_and_treasury_can_schedule(self):
        employee_token = self.login("employee@orbita.com")
        status, data = self.request("GET", "/api/payroll/close-schedule", token=employee_token)
        self.assertEqual(status, 200)
        self.assertFalse(data["canSchedule"])

        treasury_token = self.login("treasury@orbita.com")
        status, data = self.request(
            "POST", "/api/payroll/close-schedule",
            {"competence": "08/2026", "scheduledAt": "2026-08-31T18:00"},
            token=treasury_token,
        )
        self.assertEqual(status, 200, data)
        self.assertEqual(data["schedule"]["status"], "Programado")

        status, _ = self.request("POST", "/api/payroll/close-schedule", {"scheduledAt": "2026-08-31T18:00"}, token=employee_token)
        self.assertEqual(status, 403)

    # --- edição, status, filtros e CSV de colaboradores ---

    def test_patch_employee_updates_fields(self):
        admin_token = self.login("admin@orbita.com")
        status, data = self.request("PATCH", "/api/employees/usr-004", {"department": "Produto"}, token=admin_token)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["user"]["department"], "Produto")

    def test_patch_employee_requires_admin_or_rh(self):
        employee_token = self.login("employee@orbita.com")
        status, _ = self.request("PATCH", "/api/employees/usr-004", {"department": "Produto"}, token=employee_token)
        self.assertEqual(status, 403)

    def test_employee_status_toggle_and_login_blocked_when_inactive(self):
        admin_token = self.login("admin@orbita.com")
        status, data = self.request("POST", "/api/employees/usr-005/status", {"status": "Inativo"}, token=admin_token)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["user"]["status"], "Inativo")
        status, data = self.request("POST", "/api/auth/login", {"email": "treasury@orbita.com", "password": "123456"})
        self.assertEqual(status, 403, data)
        status, data = self.request("POST", "/api/employees/usr-005/status", {"status": "Ativo"}, token=admin_token)
        self.assertEqual(status, 200, data)
        token = self.login("treasury@orbita.com")
        self.assertTrue(token)

    def test_users_filtered_by_department(self):
        admin_token = self.login("admin@orbita.com")
        status, data = self.request("GET", "/api/users?department=Financeiro", token=admin_token)
        self.assertEqual(status, 200, data)
        self.assertTrue(all(u["department"] == "Financeiro" for u in data["users"]))
        self.assertGreaterEqual(len(data["users"]), 1)

    def test_employees_export_csv(self):
        admin_token = self.login("admin@orbita.com")
        status, body, headers = self.request_raw("GET", "/api/employees/export", token=admin_token)
        self.assertEqual(status, 200)
        self.assertIn("csv", headers.get("Content-Type", ""))
        text = body.decode("utf-8-sig")
        self.assertIn("Matrícula", text)
        self.assertIn("admin@orbita.com", text)

    def test_employee_photo_upload_self_and_forbidden_for_others(self):
        employee_token = self.login("employee@orbita.com")
        status, data = self.request("POST", "/api/employees/usr-004/photo", {"photo": "data:image/png;base64,AAAA"}, token=employee_token)
        self.assertEqual(status, 200, data)
        status, _ = self.request("POST", "/api/employees/usr-002/photo", {"photo": "data:image/png;base64,AAAA"}, token=employee_token)
        self.assertEqual(status, 403)

    # --- documentos: upload, download, versionamento, assinatura ---

    def test_document_upload_and_download_roundtrip(self):
        admin_token = self.login("admin@orbita.com")
        file_data = base64.b64encode(b"conteudo do arquivo").decode()
        status, data = self.request(
            "POST", "/api/documents",
            {"name": "Aditivo.pdf", "userId": "usr-004", "category": "Contrato", "fileData": file_data, "fileType": "application/pdf"},
            token=admin_token,
        )
        self.assertEqual(status, 201, data)
        document_id = data["document"]["id"]
        status, body, headers = self.request_raw("GET", f"/api/documents/{document_id}/download", token=admin_token)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"conteudo do arquivo")
        self.assertIn("application/pdf", headers.get("Content-Type", ""))

    def test_document_version_bumps_on_reupload(self):
        admin_token = self.login("admin@orbita.com")
        status, data = self.request("POST", "/api/documents", {"name": "Recorrente.pdf", "userId": "usr-004"}, token=admin_token)
        self.assertEqual(data["document"]["version"], "1.0")
        status, data = self.request("POST", "/api/documents", {"name": "Recorrente.pdf", "userId": "usr-004"}, token=admin_token)
        self.assertEqual(data["document"]["version"], "1.1")

    def test_document_sign(self):
        admin_token = self.login("admin@orbita.com")
        status, data = self.request("POST", "/api/documents", {"name": "ParaAssinar.pdf", "userId": "usr-004"}, token=admin_token)
        document_id = data["document"]["id"]
        employee_token = self.login("employee@orbita.com")
        status, data = self.request("POST", f"/api/documents/{document_id}/sign", {}, token=employee_token)
        self.assertEqual(status, 200, data)
        self.assertTrue(data["document"]["signed"])
        self.assertEqual(data["document"]["signedBy"], "Lucas Mendes")

    def test_document_download_forbidden_for_unrelated_employee(self):
        admin_token = self.login("admin@orbita.com")
        status, data = self.request("POST", "/api/documents", {"name": "Sigiloso.pdf", "userId": "usr-004"}, token=admin_token)
        document_id = data["document"]["id"]
        cfo_token = self.login("cfo@orbita.com")
        status, _, _ = self.request_raw("GET", f"/api/documents/{document_id}/download", token=cfo_token)
        self.assertEqual(status, 403)

    # --- ponto: histórico e banco de horas ---

    def test_time_history_groups_by_date_and_computes_bank(self):
        employee_token = self.login("employee@orbita.com")
        for _ in range(4):
            status, data = self.request("POST", "/api/time/punch", {}, token=employee_token)
            self.assertEqual(status, 201, data)
        status, data = self.request("GET", "/api/users/usr-004/time", token=employee_token)
        self.assertEqual(status, 200, data)
        self.assertGreaterEqual(len(data["days"]), 1)
        self.assertIn("bank", data)

    def test_time_correct_by_admin(self):
        admin_token = self.login("admin@orbita.com")
        status, data = self.request(
            "POST", "/api/employees/usr-004/time/correct",
            {"type": "Entrada", "at": "08:00", "date": "2026-06-01"},
            token=admin_token,
        )
        self.assertEqual(status, 201, data)
        status, data = self.request("GET", "/api/users/usr-004/time", token=admin_token)
        dates = [day["date"] for day in data["days"]]
        self.assertIn("2026-06-01", dates)

    def test_time_correct_requires_admin_or_rh(self):
        employee_token = self.login("employee@orbita.com")
        status, _ = self.request("POST", "/api/employees/usr-004/time/correct", {"type": "Entrada", "at": "08:00", "date": "2026-06-01"}, token=employee_token)
        self.assertEqual(status, 403)

    # --- férias: saldo e solicitação estruturada ---

    def test_vacation_request_deducts_balance_on_approval(self):
        employee_token = self.login("employee@orbita.com")
        manager_token = self.login("manager@orbita.com")
        status, data = self.request("GET", "/api/portal", token=employee_token)
        balance_before = data["vacationBalance"]
        status, data = self.request("POST", "/api/requests", {"type": "Solicitação de férias", "detail": "Férias de inverno", "days": 10}, token=employee_token)
        self.assertEqual(status, 201, data)
        request_id = data["request"]["id"]
        status, data = self.request("POST", f"/api/requests/{request_id}/decide", {"status": "Aprovado"}, token=manager_token)
        self.assertEqual(status, 200, data)
        status, data = self.request("GET", "/api/portal", token=employee_token)
        self.assertEqual(data["vacationBalance"], balance_before - 10)

    def test_vacation_request_rejects_insufficient_balance(self):
        employee_token = self.login("employee@orbita.com")
        status, data = self.request("POST", "/api/requests", {"type": "Solicitação de férias", "detail": "Férias longas demais", "days": 999}, token=employee_token)
        self.assertEqual(status, 400, data)

    def test_reject_generic_request_requires_reason(self):
        employee_token = self.login("employee@orbita.com")
        manager_token = self.login("manager@orbita.com")
        status, data = self.request("POST", "/api/requests", {"type": "Hora extra", "detail": "3h extras"}, token=employee_token)
        request_id = data["request"]["id"]
        status, data = self.request("POST", f"/api/requests/{request_id}/decide", {"status": "Rejeitado"}, token=manager_token)
        self.assertEqual(status, 400, data)
        status, data = self.request("POST", f"/api/requests/{request_id}/decide", {"status": "Rejeitado", "reason": "Sem cobertura de equipe"}, token=manager_token)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["request"]["decisionReason"], "Sem cobertura de equipe")

    # --- benefícios ---

    def test_benefit_create_list_delete(self):
        admin_token = self.login("admin@orbita.com")
        status, data = self.request("POST", "/api/benefits", {"employeeId": "usr-004", "name": "Vale-transporte", "value": 220}, token=admin_token)
        self.assertEqual(status, 201, data)
        benefit_id = data["benefit"]["id"]
        status, data = self.request("GET", "/api/users/usr-004/benefits", token=admin_token)
        self.assertEqual(status, 200, data)
        self.assertTrue(any(b["id"] == benefit_id for b in data["benefits"]))
        status, data = self.request("DELETE", f"/api/benefits/{benefit_id}", token=admin_token)
        self.assertEqual(status, 200, data)
        status, data = self.request("GET", "/api/users/usr-004/benefits", token=admin_token)
        self.assertFalse(any(b["id"] == benefit_id for b in data["benefits"]))

    # --- notificações por evento e log de auditoria ---

    def test_new_employee_receives_welcome_notification(self):
        admin_token = self.login("admin@orbita.com")
        status, data = self.request(
            "POST", "/api/employees",
            {"name": "Notif Teste", "email": "notif.teste@orbita.com", "cpf": "333.333.333-33", "workCard": "1", "address": "1", "motherName": "1"},
            token=admin_token,
        )
        self.assertEqual(status, 201, data)
        new_token = self.login("notif.teste@orbita.com")
        status, data = self.request("GET", "/api/notifications", token=new_token)
        self.assertEqual(status, 200)
        self.assertTrue(any("Bem-vindo" in n["title"] for n in data["notifications"]))

    def test_audit_log_requires_admin_and_records_actions(self):
        rh_token = self.login("rh@orbita.com")
        status, _ = self.request("GET", "/api/audit-log", token=rh_token)
        self.assertEqual(status, 403)
        admin_token = self.login("admin@orbita.com")
        status, data = self.request("POST", "/api/documents", {"name": "ParaAuditoria.pdf", "userId": "usr-004"}, token=admin_token)
        self.assertEqual(status, 201, data)
        status, data = self.request("GET", "/api/audit-log", token=admin_token)
        self.assertEqual(status, 200, data)
        self.assertGreater(len(data["entries"]), 0)
        self.assertTrue(any(entry["action"] == "document.create" for entry in data["entries"]))

    def test_payroll_history_grows_after_scheduling(self):
        treasury_token = self.login("treasury@orbita.com")
        status, data = self.request("GET", "/api/payroll/history", token=treasury_token)
        count_before = len(data["history"])
        self.request("POST", "/api/payroll/close-schedule", {"competence": "09/2026", "scheduledAt": "2026-09-30T18:00"}, token=treasury_token)
        status, data = self.request("GET", "/api/payroll/history", token=treasury_token)
        self.assertEqual(len(data["history"]), count_before + 1)


if __name__ == "__main__":
    unittest.main()
