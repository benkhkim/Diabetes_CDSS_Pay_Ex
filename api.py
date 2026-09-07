"""
당뇨병 위험 예측 API + 사용량 자동 로깅

병원은 hospital_id를 헤더(X-Hospital-Id)로 넣어서 호출합니다.
분석 요청이 들어올 때마다 성공/실패 여부와 함께 usage_logs에 기록됩니다.
이 로그가 나중에 월별 청구서 생성의 기반 데이터가 됩니다.
"""
import math
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import db

app = FastAPI(title="Diabetes Risk API (with usage billing)")

# HF Static Space(다른 도메인)에서 이 API를 호출할 수 있도록 CORS 허용
# 실서비스에서는 allow_origins를 실제 프론트엔드 도메인으로 제한해야 함
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 모델 계수 (기존 diabetes-cdss와 동일)
WEIGHTS = {"age": 0.035, "family_history": 0.8, "fpg": 0.05, "hba1c": 1.5}
BIAS = -18.0


class PredictRequest(BaseModel):
    age: float
    family_history: int  # 0 or 1
    fpg: float
    hba1c: float


class PredictResponse(BaseModel):
    result_id: str
    risk_probability: float
    is_diabetic: bool
    is_prediabetes: bool


@app.on_event("startup")
def startup():
    db.init_db()
    # 정적 사이트(index.html)가 별도 회원가입 절차 없이 바로 테스트 호출할 수 있도록
    # 데모용 병원 계정을 하나 자동 등록해둠 (실서비스에서는 실제 병원별로 발급해야 함)
    db.upsert_hospital("DEMO_HOSPITAL", "데모 병원", unit_price=10000,
                        contract_start=datetime.now(timezone.utc).date().isoformat())


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze", response_model=PredictResponse)
def analyze(req: PredictRequest, x_hospital_id: str = Header(...)):
    # 1. 병원이 등록되어 있는지 확인 (계약 안 된 병원은 거절)
    with db.get_conn() as conn:
        hospital = conn.execute(
            "SELECT * FROM hospitals WHERE hospital_id = ?", (x_hospital_id,)
        ).fetchone()

    if hospital is None:
        raise HTTPException(status_code=403, detail=f"등록되지 않은 병원 ID: {x_hospital_id}")

    result_id = str(uuid.uuid4())
    request_time = datetime.now(timezone.utc).isoformat()

    try:
        # 2. 실제 추론
        score = (
            WEIGHTS["age"] * req.age
            + WEIGHTS["family_history"] * req.family_history
            + WEIGHTS["fpg"] * req.fpg
            + WEIGHTS["hba1c"] * req.hba1c
            + BIAS
        )
        prob = 1 / (1 + math.exp(-score))
        is_diabetic = req.fpg >= 126 or req.hba1c >= 6.5
        is_prediabetes = (100 <= req.fpg < 126) or (5.7 <= req.hba1c < 6.5)

        # 3. 성공 로그 기록 <- 과금의 기반 데이터
        db.log_usage(x_hospital_id, request_time, result_id, status="success")

        return PredictResponse(
            result_id=result_id,
            risk_probability=round(prob, 6),
            is_diabetic=is_diabetic,
            is_prediabetes=is_prediabetes,
        )

    except Exception as e:
        # 실패도 기록 (단, 과금 대상에서는 제외할지는 정책에 따라 결정)
        db.log_usage(x_hospital_id, request_time, result_id, status="failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/usage/{hospital_id}")
def get_usage(hospital_id: str, year_month: str):
    """관리자용: 특정 병원의 특정 월(YYYY-MM) 사용 건수 확인"""
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT COUNT(*) as cnt FROM usage_logs
            WHERE hospital_id = ? AND request_time LIKE ? AND status = 'success'
            """,
            (hospital_id, f"{year_month}%"),
        ).fetchone()
    return {"hospital_id": hospital_id, "year_month": year_month, "billable_count": rows["cnt"]}
