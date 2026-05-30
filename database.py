import os
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# ✅ 공통 선언 Base (main.py 연동용 고정)
Base = declarative_base()
Base.metadata.clear() 

# 전역 변수 유지
engine = None
_SessionLocal = None

def _initialize_db():
    """환경변수를 읽어 엔진과 세션을 안전하게 생성하는 내부 함수"""
    global engine, _SessionLocal
    
    # 이미 초기화가 완료되었다면 기존 세션 팩토리를 그대로 반환합니다.
    if _SessionLocal is not None:
        return _SessionLocal

    # 시스템 세팅에 등록된 환경변수 즉시 추출
    DB_USER = os.getenv("DB_USER")
    DB_PW = os.getenv("DB_PW")
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME")

    # 🚨 어떤 값이 누락되었는지 터미널에 명확하게 대괄호로 찍어 시각화합니다.
    print("=" * 60)
    print("🔍 [database.py] 현재 파이썬 인스턴스가 획득한 DB 설정 값:")
    print(f" - USER: [{DB_USER}]")
    print(f" - PW  : [{DB_PW}]")
    print(f" - HOST: [{DB_HOST}]")
    print(f" - PORT: [{DB_PORT}]")
    print(f" - NAME: [{DB_NAME}]")
    print("=" * 60)

    # 필수값 검증 단계
    if not all([DB_USER, DB_PW, DB_HOST, DB_NAME]):
        print("🚨 [위험] 필수 DB 환경변수 중 일부가 완전히 유실되어 있습니다. .env 파일 내부를 점검하십시오.")
        return None

    try:
        DATABASE_URL = f"postgresql://{DB_USER}:{DB_PW}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        
        # 전역 변수 engine에 커넥션 풀을 직접 할당
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        
        print("✅ [성공] 데이터베이스 엔진 및 세션 메이커가 정상적으로 빌드되었습니다.")
        return _SessionLocal
    except Exception as e:
        print(f"🚨 [연결 예외 발생]: {e}")
        return None

# ✅ 공통 의존성 주입 함수
def get_db():
    session_factory = _initialize_db()
    
    if not session_factory:
        raise HTTPException(
            status_code=500, 
            detail="DB 연결이 설정되지 않았습니다. 백엔드 터미널의 대괄호 [...] 출력값을 확인하여 .env 오탈자를 잡으십시오."
        )
        
    db = session_factory()
    try:
        yield db
    finally:
        db.close()