import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY                     = os.environ.get('SECRET_KEY') 
    SQLALCHEMY_DATABASE_URI        = os.environ.get('DATABASE_URL') or 'sqlite:///planair.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY        = True
    SESSION_COOKIE_SAMESITE        = 'Lax'
    PERMANENT_SESSION_LIFETIME     = 86400
    SIGNUP_PROMO_CODE              = os.environ.get('SIGNUP_PROMO_CODE') or 'PLANAIR2026'

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG                = False
    SESSION_COOKIE_SECURE = True

    @classmethod
    def init_app(cls, app):
        uri = os.environ.get('DATABASE_URL', '')
        if uri.startswith('postgres://'):
            os.environ['DATABASE_URL'] = uri.replace('postgres://', 'postgresql://', 1)
            app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']