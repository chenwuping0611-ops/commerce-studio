import datetime
from applications.extensions import db


class Role(db.Model):
    __tablename__ = 'admin_role'
    id = db.Column(db.Integer, primary_key=True, comment='角色ID')
    name = db.Column(db.String(255), comment='角色名称')
    code = db.Column(db.String(255), comment='角色标识')
    enable = db.Column(db.Integer, comment='是否启用')
    remark = db.Column(db.String(255), comment='备注')
    details = db.Column(db.String(255), comment='详情')
    sort = db.Column(db.Integer, comment='排序')
    dept_id = db.Column(db.Integer, nullable=True, comment='部门ID，空值表示系统内置角色')
    created_by = db.Column(db.Integer, nullable=True, comment='创建人')
    create_time = db.Column(db.DateTime, default=datetime.datetime.now, comment='创建时间')
    update_time = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now, comment='更新时间')
    power = db.relationship('Power', secondary="admin_role_power", backref=db.backref('role'))
