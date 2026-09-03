import datetime
from applications.extensions import db

class AdminLog(db.Model):
    __tablename__ = 'admin_admin_log'
    id = db.Column(db.Integer, primary_key=True)
    method = db.Column(db.String(10))
    uid = db.Column(db.Integer)
    dept_id = db.Column(db.Integer, nullable=True, comment='操作人部门快照')
    url = db.Column(db.String(255))
    desc = db.Column(db.Text)
    ip = db.Column(db.String(255))
    success = db.Column(db.Integer)
    user_agent = db.Column(db.Text)
    create_time = db.Column(db.DateTime, default=datetime.datetime.now)
    expires_at = db.Column(
        db.DateTime,
        nullable=True,
        comment='日志保留截止时间',
    )
