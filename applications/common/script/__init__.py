import os

import click

from applications.common.script.initdb import init_db
from applications.common.script.newmodular.new import NewViewModular
from applications.studio.bootstrap import initialize_studio


def init_script(app):
    @app.cli.command()
    def init():
        """Initialize the legacy Pear Admin schema from test/pear.sql."""
        init_db()

    @app.cli.command("studio-init")
    def studio_init():
        """Initialize Commerce Studio tables, menus, admin and ToAPIs templates."""
        initialize_studio()
        click.echo("Commerce Studio 初始化完成，默认账号：admin / 123456")

    @app.cli.command("new")
    @click.option("--type", prompt="请输入类型", help="新增的类型")
    @click.option("--name", prompt="请输入新增的名称")
    def new(type, name):
        if type != "view":
            click.echo("目前只支持 view 类型")
            return
        if name.count("/") > 1:
            click.echo("目前只支持二级目录")
            return
        if os.path.exists(f"applications/view/{name}.py"):
            click.echo(f"视图模块 {name}.py 已经存在")
            return
        NewViewModular(name=name).new_view()
