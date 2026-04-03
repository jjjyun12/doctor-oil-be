from fastapi import FastAPI, HTTPException, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import (
    create_engine, Column, String, Integer, DateTime,
    ForeignKey, Boolean, Date, Time, Text, Float, func, JSON
)
from sqlalchemy.orm import sessionmaker, relationship, Session, declarative_base
from datetime import datetime, timezone, date, time
import os
import uvicorn
import requests 
import json
import urllib.parse

# ===============================
# 1. DB 설정 (환경변수)
# ===============================
DB_USER = os.getenv("DB_USER")
DB_PW = os.getenv("DB_PW")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")

DATABASE_URL = None

if all([DB_USER, DB_PW, DB_HOST, DB_NAME]):
    DATABASE_URL = (
        f"postgresql://{DB_USER}:{DB_PW}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
else:
    print("⚠️ DB 환경변수 누락 - DB 연결 없이 서버만 실행됩니다.")

engine = (
    create_engine(DATABASE_URL, pool_pre_ping=True)
    if DATABASE_URL
    else None
)

SessionLocal = (
    sessionmaker(bind=engine, autocommit=False, autoflush=False)
    if engine
    else None
)

Base = declarative_base()

# ===============================
# 2. 테이블 정의
# ===============================
class Partner(Base):
    __tablename__ = "partners"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    garage_code = Column(String, unique=True, index=True)
    garage_name = Column(String)
    zipcode = Column(String)
    address = Column(String)
    address_detail = Column(String)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    phone = Column(String, nullable=True)
    rating = Column(Float, default=0.0)
    review_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Customer(Base):
    __tablename__ = "customers"
    id = Column(String, primary_key=True, index=True)
    partner_code = Column(String, index=True)
    name = Column(String, nullable=True)
    email = Column(String, nullable=True, index=True)
    phone = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    vehicles = relationship(
        "Vehicle",
        back_populates="customer",
        cascade="all, delete-orphan"
    )


class Vehicle(Base):
    __tablename__ = "vehicles"
    id = Column(String, primary_key=True, index=True)
    customer_id = Column(
        String,
        ForeignKey("customers.id"),
        nullable=False,
        index=True
    )
    plate_number = Column(String, nullable=False)
    brand = Column(String)
    model = Column(String)
    year = Column(Integer)
    usage = Column(String)
    current_odd = Column(Integer)
    last_change_odd = Column(Integer)
    last_change_month = Column(String)
    last_oil_type = Column(String)
    paved_ratio = Column(Integer)
    unpaved_ratio = Column(Integer)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())

    customer = relationship("Customer", back_populates="vehicles")


class Reservation(Base):
    __tablename__ = "reservations"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    customer_code = Column(String, index=True)
    partner_code = Column(String, index=True)
    plate_number = Column(String(20), nullable=True) 
    reading_id = Column(String, nullable=True)
    reservation_date = Column(Date)
    reservation_time = Column(Time)
    is_approved = Column(Boolean, nullable=True) 
    note = Column(Text, nullable=True)          
    feedback = Column(Text, nullable=True)
    stars = Column(Float, nullable=True)
    reservation_candidate = Column(Text, nullable=True) 
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Analysis(Base):
    __tablename__ = "analysis_results"
    
    id = Column(Integer, primary_key=True, index=True)
    reading_id = Column(String, index=True)
    scores = Column(JSON)
    reference_scores = Column(JSON)
    explanation = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)) 
    plate_number = Column(String(255), index=True)
    
    analysis_stars = Column(Float, nullable=True)   # 별점
    analysis_feedback = Column(Text, nullable=True) # 리뷰 문구


class UserJourneyLog(Base):
    __tablename__ = "user_journey_logs"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(String, index=True)
    page_name = Column(String)
    action_type = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


if engine:
    Base.metadata.create_all(bind=engine)

# ===============================
# 3. FastAPI 설정 및 CORS 추가
# ===============================
app = FastAPI()

# ✅ 플러터 앱과의 통신을 위한 CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

auth_router = APIRouter(prefix="/auth", tags=["Auth"])
admin_router = APIRouter(prefix="/admin/api", tags=["Admin"])
customer_router = APIRouter(tags=["Customer"]) 

def get_db():
    if not SessionLocal:
        raise HTTPException(500, "DB 연결이 설정되지 않았습니다.")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_coords(address: str):
    if not address: return None, None
    url = f"https://dapi.kakao.com/v2/local/search/address.json?query={address}"
    headers = {"Authorization": "KakaoAK 1fdde3c94990fbc44311f128a1d8524f"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            docs = res.json().get('documents')
            if docs:
                return float(docs[0]['y']), float(docs[0]['x'])
    except Exception as e:
        print(f"좌표 변환 실패: {e}")
    return None, None

# ===============================
# 4. 로그인 API
# ===============================
@auth_router.post("/login")
async def login(data: dict, db: Session = Depends(get_db)):
    email = data.get("email")
    if not email:
        raise HTTPException(400, "email 정보가 누락되었습니다.")

    user = db.query(Customer).filter(
        (Customer.email == email) | (Customer.id == email)
    ).first()

    if not user:
        raise HTTPException(404, "등록되지 않은 사용자입니다.")

    return {
        "status": "success",
        "access_token": f"LOCAL_TOKEN_{user.id}",
        "customer_id": user.id
    }

# ===============================
# 5. 회원가입 API
# ===============================
@auth_router.post("/signup")
async def signup(data: dict, db: Session = Depends(get_db)):
    acc_type = data.get("account_type", "P")

    last_user = (
        db.query(Customer)
        .filter(Customer.id.like(f"{acc_type}%"))
        .order_by(Customer.id.desc())
        .first()
    )

    next_num = int(last_user.id[1:]) + 1 if last_user else 1
    new_id = f"{acc_type}{next_num:03d}"

    new_customer = Customer(
        id=new_id,
        partner_code=data.get("partner_code"),
        name=data.get("name"),
        email=data.get("email"),
        phone=data.get("phone"),
        created_at=datetime.now(timezone.utc)
    )

    db.add(new_customer)
    db.commit()
    return {"status": "success", "customer_id": new_id}

@app.get("/partners", tags=["Customer"])
async def get_partners(db: Session = Depends(get_db)):
    partners = db.query(Partner).all()
    updated = False
    for p in partners:
        if p.lat is None or p.lng is None or p.lat == 0:
            lat, lng = get_coords(p.address)
            if lat and lng:
                p.lat, p.lng = lat, lng
                updated = True
    if updated:
        db.commit()
        for p in partners: db.refresh(p)
    return partners

# ===============================
# 6. 차량 기본 등록
# ===============================
@customer_router.post("/register-vehicle")
async def register_vehicle(data: dict, db: Session = Depends(get_db)):
    customer_id = data.get("customer_id")
    plate_number = data.get("plate_number")

    if not customer_id or not plate_number:
        raise HTTPException(400, "필수 정보 누락")

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(400, "존재하지 않는 고객")

    vehicle_id = f"V-{plate_number}"

    if db.query(Vehicle).filter(Vehicle.id == vehicle_id).first():
        return {"status": "success", "vehicle_id": vehicle_id}

    vehicle = Vehicle(
        id=vehicle_id,
        customer_id=customer_id,
        plate_number=plate_number,
        brand=data.get("brand"),
        model=data.get("model"),
        year=data.get("year"),
        usage=data.get("usage"),
        current_odd=data.get("current_odd"),
        created_at=datetime.now(timezone.utc)
    )

    db.add(vehicle)
    db.commit()
    return {"status": "success", "vehicle_id": vehicle_id}

# ===============================
# 7. 차량 상세 설정
# ===============================
@customer_router.post("/setup/vehicle")
async def setup_vehicle(data: dict, db: Session = Depends(get_db)):
    v_id = data.get("vehicle_id")
    if not v_id:
        raise HTTPException(400, "vehicle_id 누락")

    clean_v_id = v_id.split("#")[0]
    if not clean_v_id.startswith("V-"):
        clean_v_id = f"V-{clean_v_id}"

    vehicle = db.query(Vehicle).filter(Vehicle.id == clean_v_id).first()
    if not vehicle:
        raise HTTPException(404, "차량 없음")

    for key, value in data.items():
        if hasattr(vehicle, key) and key not in ["id", "vehicle_id"]:
            setattr(vehicle, key, value)

    db.commit()
    return {"status": "success", "vehicle_id": clean_v_id}

# ===============================
# 8. 차량 단일 조회
# ===============================
@customer_router.get("/vehicle/{vehicle_id}")
async def get_vehicle(vehicle_id: str, db: Session = Depends(get_db)):
    clean_id = urllib.parse.unquote(vehicle_id).split("?")[0]
    if not clean_id.startswith("V-"):
        clean_id = f"V-{clean_id}"

    vehicle = db.query(Vehicle).filter(Vehicle.id == clean_id).first()
    if not vehicle:
        raise HTTPException(404, "차량을 찾을 수 없습니다.")

    return vehicle

# ===============================
# 9. 고객별 차량 목록 조회
# ===============================
@customer_router.get("/vehicles")
@customer_router.get("/vehicles/{customer_id}")
async def get_vehicles(customer_id: str = None, db: Session = Depends(get_db)):
    if customer_id:
        return db.query(Vehicle).filter(
            Vehicle.customer_id == customer_id
        ).all()

    return db.query(Vehicle).all()

# ===============================
# 10. 분석 데이터 조회 API
# ===============================
@customer_router.get("/analysis/latest/{vehicle_id}")
async def get_latest_analysis(vehicle_id: str, db: Session = Depends(get_db)):
    decoded_id = urllib.parse.unquote(vehicle_id).split("?")[0].strip()
    clean_plate_number = decoded_id.replace("V-", "").strip()
    
    target_no_space = clean_plate_number.replace(" ", "")
    
    analysis = (
        db.query(Analysis)
        .filter(func.replace(Analysis.plate_number, ' ', '') == target_no_space)
        .order_by(Analysis.created_at.desc())
        .first()
    )
    
    if not analysis:
        analysis = (
            db.query(Analysis)
            .filter(func.replace(Analysis.reading_id, ' ', '') == decoded_id.replace(" ", ""))
            .order_by(Analysis.created_at.desc())
            .first()
        )
    
    if not analysis:
        raise HTTPException(404, f"[{clean_plate_number}] 차량의 분석 데이터를 찾을 수 없습니다.")
        
    return analysis

@customer_router.get("/analysis/{analysis_id}")
async def get_analysis_by_id(analysis_id: int, db: Session = Depends(get_db)):
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(404, f"ID {analysis_id}에 해당하는 결과가 없습니다.")
    return analysis

# ===============================
# 10-1. 분석 결과 리뷰 업데이트 API
# ===============================
@customer_router.patch("/analysis/{reading_id}/review")
async def update_analysis_review(reading_id: str, data: dict, db: Session = Depends(get_db)):
    analysis = db.query(Analysis).filter(Analysis.reading_id == reading_id).first()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="해당 분석 데이터를 찾을 수 없습니다.")

    try:
        analysis.analysis_stars = float(data.get("analysis_stars", 0.0))
        analysis.analysis_feedback = data.get("analysis_feedback", "")
        
        db.commit()
        return {"status": "success", "message": "분석 리뷰가 성공적으로 등록되었습니다."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"리뷰 등록 중 오류 발생: {str(e)}")

# ===============================
# 11. 예약 개수 조회 API
# ===============================
@customer_router.get("/reserve/count")
async def get_reservation_count(
    customer_code: str, 
    partner_code: str, 
    db: Session = Depends(get_db)
):
    count = db.query(Reservation).filter(
        Reservation.customer_code == customer_code,
        Reservation.partner_code == partner_code
    ).count()
    
    return {"status": "success", "count": count}

# ===============================
# 12. 예약 생성
# ===============================
@customer_router.post("/reserve")
async def create_reservation(data: dict, db: Session = Depends(get_db)):
    try:
        customer_code = data.get("customer_code")
        partner_code = data.get("partner_code") 
        plate_number = data.get("plate_number") 
        reading_id = data.get("reading_id")
        
        if not customer_code or not partner_code or not plate_number:
            raise HTTPException(400, "필수 정보 누락")

        if reading_id:
            existing = db.query(Reservation).filter(Reservation.reading_id == reading_id).first()
            if existing:
                return {"status": "success", "reservation_id": existing.id, "note": "중복 예약"}

        r_time_str = data["reservation_time"]
        r_time_obj = datetime.strptime(r_time_str.split(':')[0] + ":" + r_time_str.split(':')[1], "%H:%M").time()

        reservation = Reservation(
            customer_code=customer_code,
            partner_code=partner_code,
            plate_number=plate_number, 
            reading_id=reading_id,
            reservation_date=datetime.strptime(data["reservation_date"], "%Y-%m-%d").date(),
            reservation_time=r_time_obj,
            is_approved=data.get("is_approved"),
            note=data.get("note"),
            feedback=data.get("feedback", ""),
            stars=data.get("stars", 0.0),
            reservation_candidate=data.get("reservation_candidate"),
            created_at=datetime.now(timezone.utc)
        )

        db.add(reservation)
        db.commit()
        db.refresh(reservation)
        return {"status": "success", "reservation_id": reservation.id}

    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))

# ===============================
# 13. 예약 리스트 조회
# ===============================
@customer_router.get("/reservations/{customer_id}")
async def get_reservations(customer_id: str, db: Session = Depends(get_db)):
    results = (
        db.query(Reservation, Partner.garage_name, Analysis.analysis_stars, Analysis.analysis_feedback)
        .outerjoin(Partner, Reservation.partner_code == Partner.garage_code)
        .outerjoin(Analysis, Reservation.reading_id == Analysis.reading_id)
        .filter(Reservation.customer_code == customer_id)
        .order_by(Reservation.created_at.desc())
        .all()
    )

    formatted_results = []
    for r, garage_name, a_stars, a_feedback in results:
        formatted_results.append({
            "id": r.id,
            "customer_code": r.customer_code,
            "partner_code": r.partner_code,
            "garage_name": garage_name if garage_name else "미지정 정비소",
            "plate_number": r.plate_number,
            "reading_id": r.reading_id,
            "reservation_date": r.reservation_date.isoformat() if r.reservation_date else None,
            "reservation_time": r.reservation_time.isoformat() if r.reservation_time else None,
            "is_approved": r.is_approved,
            "note": r.note,
            "feedback": r.feedback,
            "stars": r.stars,
            "analysis_stars": a_stars,
            "analysis_feedback": a_feedback,
            "reservation_candidate": r.reservation_candidate,
            "created_at": r.created_at.isoformat() if r.created_at else None
        })
    return formatted_results

# ===============================
# 14. 리뷰 등록 및 평점 업데이트
# ===============================
@customer_router.patch("/reservations/{reservation_id}/review")
async def update_review(reservation_id: int, data: dict, db: Session = Depends(get_db)):
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="예약 없음")

    try:
        reservation.stars = float(data.get("stars", 0.0))
        reservation.feedback = data.get("feedback", "")
        db.flush() 

        partner = db.query(Partner).filter(Partner.garage_code == reservation.partner_code).first()
        if partner:
            avg_rating = db.query(func.avg(Reservation.stars)).filter(
                Reservation.partner_code == reservation.partner_code,
                Reservation.stars.isnot(None)
            ).scalar()
            partner.rating = round(float(avg_rating), 1) if avg_rating else reservation.stars

        db.commit()
        return {"status": "success"}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))

# ===============================
# 15. 파트너 상세 및 리뷰 조회
# ===============================
@app.get("/partners/{garage_code}", tags=["Customer"])
async def get_partner_detail(garage_code: str, db: Session = Depends(get_db)):
    partner = db.query(Partner).filter(Partner.garage_code == garage_code).first()
    return partner

@app.get("/partners/{garage_code}/reviews", tags=["Customer"])
async def get_partner_reviews(garage_code: str, db: Session = Depends(get_db)):
    return db.query(Reservation).filter(
        Reservation.partner_code == garage_code,
        Reservation.feedback.isnot(None),
        Reservation.feedback != ""
    ).all()

# ===============================
# 16. 사용자 여정 로그
# ===============================
@customer_router.post("/userjourneylog", tags=["Customer"])
async def create_user_journey_log(data: dict, db: Session = Depends(get_db)):
    try:
        new_log = UserJourneyLog(
            user_id=data.get("user_id"),
            page_name=data.get("page_name"),
            action_type=data.get("action_type"),
            created_at=datetime.now(timezone.utc)
        )
        db.add(new_log)
        db.commit()
        return {"status": "success"}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, "로그 저장 실패")

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(customer_router)

# ===============================
# 17. 서버 실행 블록 (수정 완료)
# ===============================
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)