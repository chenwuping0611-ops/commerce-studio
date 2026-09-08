import os

project_root = os.path.dirname(os.path.abspath(__file__))
is_production = os.getenv("FLASK_CONFIG", "").lower() == "production"
if is_production:
    configured_log_dir = os.getenv("PEAR_AI_LOG_DIR") or "/var/log/pear-ai"
else:
    configured_log_dir = os.getenv("LOG_DIR") or os.path.join(project_root, "logs")
os.makedirs(configured_log_dir, exist_ok=True)

bind = os.getenv("GUNICORN_BIND", "127.0.0.1:8000")
backlog = 512
chdir = project_root
# Interface AI Responses requests may legitimately take up to 600 seconds.
# Keep Gunicorn alive longer than the provider timeout so Nginx never turns a
# valid long-running JSON response into an HTML 502/504 page.
timeout = int(os.getenv("GUNICORN_TIMEOUT") or 900)
# A long synchronous model request must not block history/options requests in
# the same worker. gthread keeps the existing single-process deployment while
# allowing the configured thread pool to serve those short requests.
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "gthread")

workers = max(1, int(os.getenv("GUNICORN_WORKERS") or 1))
threads = max(1, int(os.getenv("GUNICORN_THREADS") or 4))
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(t)s %(p)s %(h)s "%(r)s" %(s)s %(L)s %(b)s %(f)s" "%(a)s"'

accesslog = os.path.join(configured_log_dir, "gunicorn-access.log")
errorlog = os.path.join(configured_log_dir, "gunicorn-error.log")
capture_output = True
disable_redirect_access_to_syslog = True
