import os

bind = f"0.0.0.0:{os.getenv('PORT', '8080')}"
workers = 2
threads = 2
worker_class = "gthread"
preload_app = True
accesslog = "-"
errorlog = "-"
loglevel = "info"
