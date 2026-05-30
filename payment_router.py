import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Session
import httpx  # 💡 운영 서버 성능 병목 방지를 위해 비동기 HTTP 클라이언트 도입

from database import get_db, Base

class PaymentRecord(Base):
    __tablename__ = "payment_records"
    __table_args__ = {'extend_existing': True}  # 중복 정의 방지
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    merchant_uid = Column(String, unique=True, nullable=False)  
    imp_uid = Column(String, nullable=True)       
    amount = Column(Integer, nullable=False)       
    status = Column(String, default="ready")       
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

# 🛠️ 안전한 환경변수 매핑 (.env 파일 혹은 AWS 시스템 환경변수에서 주입받음)
PORTONE_API_KEY = os.getenv("PORTONE_API_KEY", "")
PORTONE_API_SECRET = os.getenv("PORTONE_API_SECRET", "")

payment_router = APIRouter(prefix="/payments", tags=["Payment"])

@payment_router.post("/checkout")
async def create_checkout_session(data: dict, db: Session = Depends(get_db)):
    customer_id = data.get("customer_id")
    amount = data.get("amount")
    
    if not customer_id or not amount:
        raise HTTPException(status_code=400, detail="필수 정보(customer_id, amount)가 누락되었습니다.")
        
    # 고유 주문번호 생성 (중복 방지를 위한 타임스탬프 결합)
    merchant_uid = f"pay_{datetime.now().strftime('%Y%m%d%H%M%S')}_{customer_id}"
    
    new_record = PaymentRecord(
        customer_id=customer_id,
        merchant_uid=merchant_uid,
        amount=int(amount),
        status="ready"
    )
    db.add(new_record)
    db.commit()
    
    return {"status": "success", "merchant_uid": merchant_uid, "amount": amount}

@payment_router.post("/webhook")
async def payment_webhook(data: dict, db: Session = Depends(get_db)):
    imp_uid = data.get("imp_uid")          
    merchant_uid = data.get("merchant_uid")  
    
    if not imp_uid or not merchant_uid:
        raise HTTPException(status_code=400, detail="필수 인자(imp_uid, merchant_uid)가 누락되었습니다.")

    record = db.query(PaymentRecord).filter(PaymentRecord.merchant_uid == merchant_uid).first()
    if not record:
        raise HTTPException(status_code=404, detail="시스템에 등록되지 않은 주문 내역입니다.")

    # 외부 API 호출 도중 트랜잭션이 블로킹되는 것을 방지하기 위해 비동기 세션으로 토큰 및 검증 획득
    async with httpx.AsyncClient() as client:
        try:
            # 1. 포트원 인증 토큰 발급 요청
            token_req = await client.post(
                "https://api.iamport.kr/users/getToken", 
                json={"imp_key": PORTONE_API_KEY, "imp_secret": PORTONE_API_SECRET},
                timeout=5.0
            )
            token_res = token_req.json()
            access_token = token_res.get("response", {}).get("access_token")
            
            if not access_token:
                raise HTTPException(status_code=500, detail="포트원 API 토큰 인증에 실패했습니다. 키 설정을 확인하세요.")

            # 2. 포트원 서버에서 실제 결제 단건 내역 조회
            payment_req = await client.get(
                f"https://api.iamport.kr/payments/{imp_uid}",
                headers={"Authorization": access_token},
                timeout=5.0
            )
            payment_res = payment_req.json()
            payment_data = payment_res.get("response")
            
            if not payment_data:
                raise HTTPException(status_code=404, detail="포트원 서버에 해당 결제 이력이 존재하지 않습니다.")

            actual_amount = payment_data.get("amount")
            status = payment_data.get("status")

            # 3. 데이터베이스 위변조 최종 검증 후 상태 업데이트
            if actual_amount == record.amount and status == "paid":
                record.status = "paid"
                record.imp_uid = imp_uid
                db.commit()
                return {"status": "success", "message": "결제 검증 및 데이터 동기화 완료"}
            else:
                record.status = "failed"
                db.commit()
                raise HTTPException(status_code=400, detail="결제 금액 또는 결제 상태가 일치하지 않는 위변조 위험 거래입니다.")
                
        except httpx.HTTPError as he:
            db.rollback()
            raise HTTPException(status_code=502, detail=f"포트원 통신 모듈 외부망 에러: {str(he)}")
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"결제 내부 검증 처리 중 예외 발생: {str(e)}")