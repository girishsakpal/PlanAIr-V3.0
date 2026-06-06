import os
from dotenv import load_dotenv

load_dotenv()

def _fix_db_url(url: str) -> str:
    """SQLAlchemy requires 'postgresql://' but Supabase/Heroku give 'postgres://'."""
    if url and url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql://', 1)
    return url

class Config:
    SECRET_KEY                     = os.environ.get('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI        = _fix_db_url(os.environ.get('DATABASE_URL', '')) or 'sqlite:///planair.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY        = True
    SESSION_COOKIE_SAMESITE        = 'Lax'
    PERMANENT_SESSION_LIFETIME     = 86400
    SIGNUP_PROMO_CODE              = os.environ.get('SIGNUP_PROMO_CODE') or 'PLANAIR2026'

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG                 = False
    SESSION_COOKIE_SECURE = True
