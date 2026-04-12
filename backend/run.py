import os
from app import create_app
from app.config import DevelopmentConfig, ProductionConfig

config = ProductionConfig if os.environ.get('RENDER') else DevelopmentConfig
app = create_app(config)

if __name__ == '__main__':
    app.run()