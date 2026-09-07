"""
사용량 과금 시스템 - DB 스키마 및 초기화

테이블 2개:
1. hospitals      : 병원별 계약 정보 (단가, 계약시작일)
2. usage_logs     : 분석 요청 1건마다 기록되는 사용량 로그

실제 서비스에서는 SQLite 대신 PostgreSQL(RDS 등)을 쓰면 되지만,
로직 검증 단계에서는 SQLite로 충분합니다 (파일 하나로 관리됨).
"""
import sqlite3
from contextlib import contextmanager

DB_PATH = "billing.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hospitals (
                hospital_id   TEXT PRIMARY KEY,
                hospital_name TEXT NOT NULL,
                unit_price    INTEGER NOT NULL,      -- 건당 단가 (원)
                contract_start TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_logs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                hospital_id   TEXT NOT NULL,
                request_time  TEXT NOT NULL,          -- ISO 8601
                result_id     TEXT NOT NULL,
                status        TEXT NOT NULL,          -- success / failed
                FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id)
            )
        """)


def upsert_hospital(hospital_id: str, hospital_name: str, unit_price: int, contract_start: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO hospitals (hospital_id, hospital_name, unit_price, contract_start)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(hospital_id) DO UPDATE SET
                hospital_name=excluded.hospital_name,
                unit_price=excluded.unit_price,
                contract_start=excluded.contract_start
        """, (hospital_id, hospital_name, unit_price, contract_start))


def log_usage(hospital_id: str, request_time: str, result_id: str, status: str = "success"):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO usage_logs (hospital_id, request_time, result_id, status)
            VALUES (?, ?, ?, ?)
        """, (hospital_id, request_time, result_id, status))


if __name__ == "__main__":
    init_db()
    print(f"DB initialized at {DB_PATH}")
