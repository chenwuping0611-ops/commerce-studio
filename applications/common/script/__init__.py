import os

import click

from applications.common.script.initdb import initialize_full_database
from applications.common.script.newmodular.new import NewViewModular
from applications.studio.bootstrap import initialize_studio
from applications.amazon_ai.bootstrap import initialize_amazon_ai


def init_script(app):
    @app.cli.command()
    @click.option(
        "--fresh",
        is_flag=True,
        help="删除并重建当前 MYSQL_DATABASE，清除全部历史数据。",
    )
    @click.option(
        "--yes",
        is_flag=True,
        help="确认执行 --fresh，适合部署脚本和无人值守环境。",
    )
    @click.option(
        "--seed-storage/--skip-storage",
        default=False,
        help="是否把内置 Skill 文件同步到 GoFastDFS，默认跳过外部存储。",
    )
    def init(fresh, yes, seed_storage):
        """Initialize the complete current database schema and base RBAC."""

        if fresh and not yes:
            click.confirm(
                "这会删除 MYSQL_DATABASE 中的全部数据，是否继续？",
                abort=True,
            )
        initialize_full_database(
            fresh=fresh,
            seed_storage=seed_storage,
        )
        if fresh:
            click.echo(
                "全新数据库初始化完成：旧数据已清除，仅创建 admin、角色、"
                "权限、模型模板和完整业务表。"
            )
        else:
            click.echo(
                "数据库初始化完成：已应用完整迁移并补齐基础角色、权限和模型模板。"
            )
        click.echo(
            "默认账号：admin；密码来自 ADMIN_PASSWORD（未设置时为 123456）；"
            "所有 API Key 均为空。"
        )

    @app.cli.command("studio-init")
    @click.option(
        "--seed-storage/--skip-storage",
        default=True,
        help="是否把内置 Skill 文件同步到 GoFastDFS。",
    )
    def studio_init(seed_storage):
        """Initialize Commerce Studio provider and model templates."""
        initialize_studio(
            seed_credentials=False,
            seed_storage=seed_storage,
        )
        click.echo("Commerce Studio 初始化完成，API Key 不会由命令自动写入。")

    @app.cli.command("amazon-ai-init")
    @click.option(
        "--seed-storage/--skip-storage",
        default=True,
        help="是否把 Amazon AI 内置 Skill 文件同步到 GoFastDFS。",
    )
    def amazon_ai_init(seed_storage):
        """Initialize only the independent Amazon AI menu and permissions."""

        initialize_amazon_ai(seed_storage=seed_storage)
        click.echo("Amazon AI 工作台菜单和权限初始化完成")

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
