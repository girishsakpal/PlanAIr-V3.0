import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY              = os.environ.get('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY  = True
    SESSION_COOKIE_SAMESITE  = 'Lax'
    PERMANENT_SESSION_LIFETIME = 86400
    SIGNUP_PROMO_CODE        = os.environ.get('SIGNUP_PROMO_CODE')

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False